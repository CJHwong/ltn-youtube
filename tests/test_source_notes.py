"""Source metadata stays in the YouTube plugin."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from lazy_take_notes.plugin_api import SessionArtifacts, TranscriptSegment

from ltn_youtube.cli import youtube_command


@pytest.mark.parametrize('use_subtitles', [True, False])
def test_generated_notes_include_source_and_timestamp_links(tmp_path, use_subtitles):
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text('## [01:02:03] Topic\nBody\n', encoding='utf-8')
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    segments = [TranscriptSegment(text='hello', wall_start=0.0, wall_end=1.0)]
    subtitle_result = (segments, 'Video title') if use_subtitles else None
    audio_path = tmp_path / 'audio.wav'
    audio_path.touch()
    address = 'https://www.youtube.com/watch?v=test123'
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=subtitle_result),
        patch('ltn_youtube.cli.download_audio', return_value=(audio_path, 'Video title')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts) as transcribe,
    ):
        result = CliRunner().invoke(youtube_command, [address], obj={'config_path': None, 'output_dir': None})

    assert result.exit_code == 0, result.output
    transcribe.assert_called_once()
    assert 'source_url' not in transcribe.call_args.kwargs
    assert notes_path.read_text(encoding='utf-8') == (
        f'{address}\n# [Video title]({address})\n\n## [01:02:03]({address}&t=3723) Topic\nBody\n'
    )


def test_short_link_keeps_fragment_after_timestamp(tmp_path):
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text('[00:00:09]\n', encoding='utf-8')
    address = 'https://youtu.be/test123#chapter'
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, [address], obj={})

    assert result.exit_code == 0, result.output
    assert '[00:00:09](https://youtu.be/test123?t=9#chapter)' in notes_path.read_text(encoding='utf-8')


def test_missing_timestamps_still_adds_source_and_warns(tmp_path):
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text('Notes without timestamps\n', encoding='utf-8')
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, ['https://youtu.be/test123'], obj={})

    assert result.exit_code == 0, result.output
    assert '# [Video](https://youtu.be/test123)' in notes_path.read_text(encoding='utf-8')
    assert 'no timestamps' in result.output.lower()


def test_cancelled_transcription_does_not_write_notes(tmp_path):
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=None) as transcribe,
    ):
        result = CliRunner().invoke(youtube_command, ['https://youtu.be/test123'], obj={})

    assert result.exit_code == 0, result.output
    transcribe.assert_called_once()
    assert list(tmp_path.iterdir()) == []


def test_existing_timestamp_parameter_is_replaced(tmp_path):
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text('[00:00:09]\n', encoding='utf-8')
    address = 'https://youtu.be/test123?t=600#chapter'
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, [address], obj={})

    assert result.exit_code == 0, result.output
    assert '[00:00:09](https://youtu.be/test123?t=9#chapter)' in notes_path.read_text(encoding='utf-8')


def test_existing_timestamp_links_are_not_wrapped_again(tmp_path):
    notes_path = tmp_path / 'notes.md'
    original = '[00:00:09](https://youtu.be/other?t=9)\n'
    notes_path.write_text(original, encoding='utf-8')
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, ['https://youtu.be/test123'], obj={})

    assert result.exit_code == 0, result.output
    assert notes_path.read_text(encoding='utf-8').endswith(original)


def test_missing_notes_warns_without_failing_transcription(tmp_path):
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=tmp_path / 'missing.md')
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, ['https://youtu.be/test123'], obj={})

    assert result.exit_code == 0, result.output
    assert 'could not add YouTube source metadata' in result.output


def test_source_title_brackets_remain_literal(tmp_path):
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text('[00:00:09]\n', encoding='utf-8')
    artifacts = SessionArtifacts(session_dir=tmp_path, notes_path=notes_path)
    with (
        patch('ltn_youtube.cli.fetch_subtitles', return_value=([], 'Video [part 1]')),
        patch('ltn_youtube.cli.run_transcribe', autospec=True, return_value=artifacts),
    ):
        result = CliRunner().invoke(youtube_command, ['https://youtu.be/test123'], obj={})

    assert result.exit_code == 0, result.output
    assert r'# [Video \[part 1\]](https://youtu.be/test123)' in notes_path.read_text(encoding='utf-8')
