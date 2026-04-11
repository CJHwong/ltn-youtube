"""Tests for YouTube plugin CLI command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from lazy_take_notes.plugin_api import TranscriptSegment

from ltn_youtube.cli import youtube_command

_CLI = 'ltn_youtube.cli'

_STUB_SEGMENTS = [
    TranscriptSegment(text='Hello from subtitles', wall_start=1.0, wall_end=3.0),
]


def _run(args, **patch_kwargs):
    """Invoke youtube_command with mix_stderr so stderr assertions work on result.output."""
    runner = CliRunner()
    return runner.invoke(
        youtube_command,
        args,
        obj={'config_path': None, 'output_dir': None},
        **patch_kwargs,
    )


class TestYoutubeCommand:
    def test_non_youtube_url_exits_1(self):
        result = _run(['https://vimeo.com/12345'])
        assert result.exit_code == 1
        assert 'does not look like a YouTube URL' in result.output

    def test_subtitles_found_skips_audio_and_exits_0(self):
        """When subtitles are found, run_transcribe receives subtitle_segments."""
        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=(_STUB_SEGMENTS, 'Test Video')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            result = _run(['https://www.youtube.com/watch?v=test123'])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs['subtitle_segments'] is not None
        assert len(call_kwargs['subtitle_segments']) == 1
        assert call_kwargs['audio_path'] is None
        assert call_kwargs['label'] == 'Test Video'

    def test_subtitles_path_passes_source_url_and_title(self):
        """source_url and source_title are forwarded when subtitles are found."""
        url = 'https://www.youtube.com/watch?v=test123'
        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=(_STUB_SEGMENTS, 'Test Video')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            _run([url])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs['source_url'] == url
        assert call_kwargs['source_title'] == 'Test Video'

    def test_audio_fallback_when_no_subtitles(self, tmp_path):
        """When no subtitles, run_transcribe receives audio_path."""
        audio_file = tmp_path / 'audio.wav'
        audio_file.touch()

        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=None),
            patch(f'{_CLI}.download_audio', return_value=(audio_file, 'Test Video')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            result = _run(['https://www.youtube.com/watch?v=test123'])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs['audio_path'] == audio_file
        assert call_kwargs['subtitle_segments'] is None

    def test_audio_fallback_passes_source_url_and_title(self, tmp_path):
        """source_url and source_title are forwarded in the audio fallback path."""
        audio_file = tmp_path / 'audio.wav'
        audio_file.touch()
        url = 'https://www.youtube.com/watch?v=test123'

        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=None),
            patch(f'{_CLI}.download_audio', return_value=(audio_file, 'Fallback Title')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            result = _run([url])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs['source_url'] == url
        assert call_kwargs['source_title'] == 'Fallback Title'

    def test_unexpected_fetch_subtitles_exception_exits_1(self):
        """Uncaught exception from fetch_subtitles exits cleanly with error message."""
        with patch(f'{_CLI}.fetch_subtitles', side_effect=RuntimeError('network error')):
            result = _run(['https://www.youtube.com/watch?v=test123'])

        assert result.exit_code == 1
        assert 'network error' in result.output

    def test_download_audio_exception_exits_1(self, tmp_path):
        """RuntimeError from download_audio in the fallback path exits cleanly."""
        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=None),
            patch(f'{_CLI}.download_audio', side_effect=RuntimeError('403 Forbidden')),
        ):
            result = _run(['https://www.youtube.com/watch?v=test123'])

        assert result.exit_code == 1
        assert '403 Forbidden' in result.output

    def test_label_defaults_to_video_title(self):
        """When no --label, video title is used as session label."""
        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=(_STUB_SEGMENTS, 'My Video Title')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            result = _run(['https://www.youtube.com/watch?v=test123'])

        assert result.exit_code == 0
        assert mock_run.call_args[1]['label'] == 'My Video Title'

    def test_label_flag_overrides_video_title(self):
        """Explicit --label takes precedence over video title."""
        with (
            patch(f'{_CLI}.fetch_subtitles', return_value=(_STUB_SEGMENTS, 'Video Title')),
            patch(f'{_CLI}.run_transcribe') as mock_run,
        ):
            result = _run(['https://www.youtube.com/watch?v=test123', '--label', 'my-custom-label'])

        assert result.exit_code == 0
        assert mock_run.call_args[1]['label'] == 'my-custom-label'
