"""YouTube source — download subtitles or audio via yt-dlp."""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from lazy_take_notes.plugin_api import TranscriptSegment

log = logging.getLogger('ltn.youtube')

_SUBTITLE_FETCH_TIMEOUT = 15

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

    Single-phase approach: extract video info (which includes subtitle track
    URLs), pick the best track, fetch the json3 data directly, and parse it
    into segments. No temp files, no second yt-dlp invocation.

    Track selection priority:
    1. Manual subs in the video's own language
    2. Manual subs in the preferred language list
    3. Auto subs in the video's own language
    4. Auto subs in the preferred language list
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

    track = _pick_subtitle_track(manual_subs, auto_subs, video_lang)

    if track is None:
        return None

    # Find json3 format entry in the track
    json3_url = next((fmt.get('url') for fmt in track if fmt.get('ext') == 'json3' and fmt.get('url')), None)
    if json3_url is None:
        return None

    try:
        with urllib.request.urlopen(json3_url, timeout=_SUBTITLE_FETCH_TIMEOUT) as resp:  # noqa: S310 -- URL comes from yt-dlp info dict, not user input
            data = json.load(resp)
    except Exception:
        log.warning('Failed to fetch json3 subtitles from %s', json3_url[:80], exc_info=True)
        return None

    segments = parse_json3_events(data.get('events', []))
    if not segments:
        return None

    return segments, title


def _pick_subtitle_track(
    manual_subs: dict[str, list],
    auto_subs: dict[str, list],
    video_lang: str,
) -> list | None:
    """Pick the best subtitle track.

    Priority:
    1. Manual subs in the video's own language
    2. First available manual sub track (any language)
    3. Auto subs in the video's own language
    4. First available auto sub track (any language)

    Manual subs always beat auto subs — they're human-authored and higher
    quality. Within manual or auto, the video's own language is preferred
    because it matches what's actually being spoken.
    """

    def _first_track(subs: dict[str, list]) -> list | None:
        return next(iter(subs.values()), None) if subs else None

    # Manual subs: video language first, then any
    if video_lang and video_lang in manual_subs:
        return manual_subs[video_lang]
    if manual_subs:
        return _first_track(manual_subs)

    # Auto subs: video language first, then any
    if video_lang and video_lang in auto_subs:
        return auto_subs[video_lang]
    return _first_track(auto_subs)


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
