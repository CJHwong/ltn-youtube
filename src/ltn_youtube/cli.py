"""YouTube subcommand for lazy-take-notes — transcribe YouTube videos."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import click
from lazy_take_notes.plugin_api import SessionArtifacts, run_transcribe

from ltn_youtube.youtube_source import download_audio, fetch_subtitles, is_youtube_url

_TIMESTAMP = re.compile(r'\[(\d{2,}):([0-5]\d):([0-5]\d)\](?!\()')


def _timestamp_link(match: re.Match[str], source_url: str) -> str:
    hours, minutes, seconds = map(int, match.groups())
    parts = urlsplit(source_url)
    query = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name != 't']
    query.append(('t', str(hours * 3600 + minutes * 60 + seconds)))
    target = urlunsplit(parts._replace(query=urlencode(query)))
    return f'{match.group(0)}({target})'


def _annotate_notes(artifacts: SessionArtifacts | None, source_url: str, source_title: str) -> None:
    if artifacts is None or artifacts.notes_path is None:
        return
    try:
        notes = artifacts.notes_path.read_text(encoding='utf-8')
        linked_notes, count = _TIMESTAMP.subn(lambda match: _timestamp_link(match, source_url), notes)
        title = source_title.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        header = f'{source_url}\n# [{title or "YouTube video"}]({source_url})\n\n'
        artifacts.notes_path.write_text(header + linked_notes, encoding='utf-8')
    except (OSError, UnicodeError) as error:
        click.echo(f'Warning: could not add YouTube source metadata: {error}', err=True)
        return
    if count == 0:
        click.echo('Warning: no timestamps found in generated notes.', err=True)


@click.command('youtube')
@click.argument('url')
@click.option(
    '-l',
    '--label',
    default=None,
    help='Session label (defaults to video title).',
)
@click.pass_context
def youtube_command(ctx, url, label):
    """Transcribe a YouTube video (subtitles preferred, audio fallback)."""
    if not is_youtube_url(url):
        click.echo(f'Error: {url!r} does not look like a YouTube URL.', err=True)
        sys.exit(1)

    # Try subtitles first — no temp dir needed
    click.echo('Checking for YouTube subtitles...', err=True)
    try:
        subtitle_result = fetch_subtitles(url)
    except Exception as exc:  # noqa: BLE001 -- yt-dlp raises various exception types
        click.echo(f'Error: {exc}', err=True)
        sys.exit(1)

    if subtitle_result is not None:
        segments, video_title = subtitle_result
        click.echo(f'Found subtitles ({len(segments)} segments), skipping audio download.', err=True)
        resolved_label = label if label is not None else (video_title or None)
        artifacts = run_transcribe(
            ctx,
            subtitle_segments=segments,
            audio_path=None,
            label=resolved_label,
        )
        _annotate_notes(artifacts, url, video_title)
        return

    # Audio fallback
    click.echo('No subtitles found. Downloading audio...', err=True)
    with tempfile.TemporaryDirectory(prefix='ltn_yt_') as tmp_dir:
        try:
            audio_path, video_title = download_audio(url, Path(tmp_dir))
        except Exception as exc:  # noqa: BLE001 -- yt-dlp raises various exception types
            click.echo(f'Error: {exc}', err=True)
            sys.exit(1)

        click.echo(f'Audio downloaded: {audio_path.name}', err=True)
        resolved_label = label if label is not None else (video_title or None)
        artifacts = run_transcribe(
            ctx,
            subtitle_segments=None,
            audio_path=audio_path,
            label=resolved_label,
        )
        _annotate_notes(artifacts, url, video_title)
