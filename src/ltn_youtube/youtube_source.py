"""YouTube source — download subtitles or audio via yt-dlp."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from lazy_take_notes.plugin_api import TranscriptSegment

log = logging.getLogger('ltn.youtube')

_YOUTUBE_HOSTS = frozenset(
    {
        'youtube.com',
        'www.youtube.com',
        'm.youtube.com',
        'youtu.be',
        'music.youtube.com',
        'youtube-nocookie.com',
    }
)


def is_youtube_url(value: str) -> bool:
    """Check if value looks like a YouTube URL."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    return (parsed.hostname or '') in _YOUTUBE_HOSTS


def fetch_subtitles(url: str) -> tuple[list[TranscriptSegment], str] | None:
    """Fetch YouTube subtitles as TranscriptSegments. Returns (segments, title) or None.

    Two-phase approach:
    1. extract_info(download=False) to get video metadata and pick the best
       subtitle track via _pick_subtitle_track.
    2. Use yt-dlp's native subtitle download to fetch the json3 file to a
       temp directory, then parse it.

    Track selection priority:
    1. Manual subs in the video's own language
    2. Manual subs in any language
    3. Auto subs in the video's own language
    4. Auto subs in any language
    """
    import yt_dlp  # noqa: PLC0415 -- deferred: yt-dlp is heavy

    try:
        with yt_dlp.YoutubeDL(_quiet_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError:
        log.debug('Failed to extract video info', exc_info=True)
        return None

    title = info.get('title', '')
    manual_subs = info.get('subtitles') or {}
    auto_subs = info.get('automatic_captions') or {}
    video_lang = info.get('language') or ''

    picked = _pick_subtitle_track(manual_subs, auto_subs, video_lang)
    if picked is None:
        return None

    lang_code, is_manual = picked

    with tempfile.TemporaryDirectory() as tmp_dir:
        sub_opts = {
            **_quiet_opts(),
            'skip_download': True,
            'writesubtitles': is_manual,
            'writeautomaticsubs': not is_manual,
            'subtitleslangs': [lang_code],
            'subtitlesformat': 'json3',
            'outtmpl': str(Path(tmp_dir) / '%(id)s.%(ext)s'),
        }

        try:
            with yt_dlp.YoutubeDL(sub_opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError:
            log.warning('Failed to download subtitles for %s', url, exc_info=True)
            return None

        json3_file = next(Path(tmp_dir).glob('*.json3'), None)
        if json3_file is None:
            return None

        with open(json3_file) as fh:
            data = json.load(fh)

        segments = parse_json3_events(data.get('events', []))
        if not segments:
            return None

    return segments, title


def _pick_subtitle_track(
    manual_subs: dict[str, list],
    auto_subs: dict[str, list],
    video_lang: str,
) -> tuple[str, bool] | None:
    """Pick the best subtitle track, returning (language_code, is_manual).

    Priority:
    1. Manual subs in the video's own language
    2. First available manual sub track (any language)
    3. Auto subs in the video's own language
    4. First available auto sub track (any language)

    Manual subs always beat auto subs — they're human-authored and higher
    quality. Within manual or auto, the video's own language is preferred
    because it matches what's actually being spoken.
    """

    def _first_lang(subs: dict[str, list]) -> str | None:
        return next(iter(subs), None) if subs else None

    # Manual subs: video language first, then any
    if video_lang and video_lang in manual_subs:
        return (video_lang, True)
    first_manual = _first_lang(manual_subs)
    if first_manual is not None:
        return (first_manual, True)

    # Auto subs: video language first, then any
    if video_lang and video_lang in auto_subs:
        return (video_lang, False)
    first_auto = _first_lang(auto_subs)
    if first_auto is not None:
        return (first_auto, False)

    return None


def parse_json3_events(events: list[dict]) -> list[TranscriptSegment]:
    """Parse YouTube json3 subtitle events into TranscriptSegments."""
    segments: list[TranscriptSegment] = []
    for event in events:
        segs = event.get('segs')
        if not segs:
            continue
        text = ''.join(seg.get('utf8', '') for seg in segs).strip()
        if not text:
            continue
        start_ms = event.get('tStartMs', 0)
        duration_ms = event.get('dDurationMs', 0)
        segments.append(
            TranscriptSegment(
                text=text,
                wall_start=start_ms / 1000,
                wall_end=(start_ms + duration_ms) / 1000,
            )
        )
    return segments


def download_audio(url: str, dest_dir: Path) -> tuple[Path, str]:
    """Download YouTube audio as WAV. Returns (audio_path, video_title).

    Raises RuntimeError if download fails.
    """
    import yt_dlp  # noqa: PLC0415 -- deferred: yt-dlp is heavy

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_quiet_opts(),
        'format': 'bestaudio/best',
        'outtmpl': str(dest_dir / '%(id)s.%(ext)s'),
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        msg = f'Failed to download YouTube audio: {exc}'
        raise RuntimeError(msg) from exc

    title = info.get('title', '')
    video_id = info.get('id') or ''
    if not video_id:
        msg = 'yt-dlp returned no video ID; cannot locate output file'
        raise RuntimeError(msg)

    audio_path = dest_dir / f'{video_id}.wav'
    if not audio_path.exists():
        msg = f'yt-dlp did not produce {audio_path.name}'
        raise RuntimeError(msg)

    return audio_path, title


class _StderrLogger:
    """Silence yt-dlp's internal chatter.

    We set quiet=True and no_warnings=True in opts, but yt-dlp still calls
    the logger directly for some messages. Route everything to debug so it
    only appears when the user explicitly enables verbose logging.
    """

    def debug(self, msg: str) -> None:
        log.debug('yt-dlp: %s', msg)

    def info(self, msg: str) -> None:
        log.debug('yt-dlp: %s', msg)

    def warning(self, msg: str) -> None:
        log.debug('yt-dlp: %s', msg)

    def error(self, msg: str) -> None:
        log.error('yt-dlp: %s', msg)


_STDERR_LOGGER = _StderrLogger()


def _quiet_opts() -> dict:
    """Base yt-dlp options: suppress stdout noise, route to stderr logger."""
    return {
        'quiet': True,
        'no_warnings': True,
        'logger': _STDERR_LOGGER,
    }
