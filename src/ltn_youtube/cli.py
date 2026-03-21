"""YouTube subcommand for lazy-take-notes — transcribe YouTube videos."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import click
from lazy_take_notes.plugin_api import run_transcribe

from ltn_youtube.youtube_source import download_audio, fetch_subtitles, is_youtube_url


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
        run_transcribe(ctx, subtitle_segments=segments, audio_path=None, label=resolved_label)
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
        run_transcribe(ctx, subtitle_segments=None, audio_path=audio_path, label=resolved_label)
