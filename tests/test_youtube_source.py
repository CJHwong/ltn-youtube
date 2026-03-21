"""Tests for YouTube source — URL detection, subtitle parsing, and download gateway."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ltn_youtube.youtube_source import download_audio, fetch_subtitles, is_youtube_url, parse_json3_events


def _make_mock_ydl(extract_return=None, extract_side_effect=None):
    """Build a MagicMock that behaves as a yt_dlp.YoutubeDL context manager."""
    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    if extract_side_effect is not None:
        mock_ydl.extract_info.side_effect = extract_side_effect
    elif extract_return is not None:
        mock_ydl.extract_info.return_value = extract_return
    return mock_ydl


class TestIsYoutubeUrl:
    def test_standard_youtube_url(self):
        assert is_youtube_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_short_youtube_url(self):
        assert is_youtube_url('https://youtu.be/dQw4w9WgXcQ') is True

    def test_mobile_youtube_url(self):
        assert is_youtube_url('https://m.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_nocookie_youtube_url(self):
        assert is_youtube_url('https://youtube-nocookie.com/embed/dQw4w9WgXcQ') is True

    def test_music_youtube_url(self):
        assert is_youtube_url('https://music.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_non_youtube_url_rejected(self):
        assert is_youtube_url('https://vimeo.com/12345') is False

    def test_generic_http_url_rejected(self):
        assert is_youtube_url('https://example.com/video.mp4') is False

    def test_local_file_path_rejected(self):
        assert is_youtube_url('/tmp/audio.wav') is False

    def test_empty_string_rejected(self):
        assert is_youtube_url('') is False

    def test_garbage_rejected(self):
        assert is_youtube_url('not a url at all') is False

    def test_spoofed_hostname_rejected(self):
        """evil-youtube.com must not match youtube.com."""
        assert is_youtube_url('https://evil-youtube.com/watch?v=abc') is False

    def test_subdomain_spoof_rejected(self):
        assert is_youtube_url('https://notyoutube.com/watch?v=abc') is False


class TestParseJson3Events:
    def test_basic_events(self):
        events = [
            {'tStartMs': 1000, 'dDurationMs': 2500, 'segs': [{'utf8': 'Hello world'}]},
            {'tStartMs': 4000, 'dDurationMs': 2000, 'segs': [{'utf8': 'Second line'}]},
        ]
        segments = parse_json3_events(events)
        assert len(segments) == 2
        assert segments[0].text == 'Hello world'
        assert segments[0].wall_start == 1.0
        assert segments[0].wall_end == 3.5
        assert segments[1].text == 'Second line'
        assert segments[1].wall_start == 4.0
        assert segments[1].wall_end == 6.0

    def test_multi_seg_event_concatenated(self):
        events = [
            {'tStartMs': 0, 'dDurationMs': 3000, 'segs': [{'utf8': 'Hello '}, {'utf8': 'world'}]},
        ]
        segments = parse_json3_events(events)
        assert len(segments) == 1
        assert segments[0].text == 'Hello world'

    def test_empty_segs_skipped(self):
        events = [
            {'tStartMs': 0, 'dDurationMs': 1000},
            {'tStartMs': 1000, 'dDurationMs': 2000, 'segs': [{'utf8': 'Real text'}]},
        ]
        segments = parse_json3_events(events)
        assert len(segments) == 1
        assert segments[0].text == 'Real text'

    def test_whitespace_only_segs_skipped(self):
        events = [
            {'tStartMs': 0, 'dDurationMs': 1000, 'segs': [{'utf8': '  \n  '}]},
            {'tStartMs': 1000, 'dDurationMs': 2000, 'segs': [{'utf8': 'Actual text'}]},
        ]
        segments = parse_json3_events(events)
        assert len(segments) == 1
        assert segments[0].text == 'Actual text'

    def test_empty_events_returns_empty(self):
        assert parse_json3_events([]) == []


_FAKE_JSON3_BODY = b'{"events": [{"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Hello"}]}]}'

_INFO_WITH_MANUAL_SUBS = {
    'title': 'Test Video',
    'language': 'en',
    'subtitles': {
        'en': [{'ext': 'json3', 'url': 'https://example.com/subs.json3'}],
    },
    'automatic_captions': {},
}


class TestFetchSubtitles:
    def test_happy_path_returns_segments_and_title(self):
        """Full success path: extract info -> pick track -> fetch json3 -> parse."""
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_return=_INFO_WITH_MANUAL_SUBS)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _FAKE_JSON3_BODY
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            patch('ltn_youtube.youtube_source.urllib.request.urlopen', return_value=mock_resp),
        ):
            result = fetch_subtitles('https://www.youtube.com/watch?v=test')

        assert result is not None
        segments, title = result
        assert title == 'Test Video'
        assert len(segments) == 1
        assert segments[0].text == 'Hello'
        assert segments[0].wall_start == 1.0
        assert segments[0].wall_end == 3.0

    def test_manual_subs_preferred_over_auto(self):
        """Manual subtitles always beat auto-generated, regardless of language."""
        import yt_dlp

        info = {
            'title': 'Mixed',
            'language': 'en',
            'subtitles': {'ja': [{'ext': 'json3', 'url': 'https://example.com/manual.json3'}]},
            'automatic_captions': {'en': [{'ext': 'json3', 'url': 'https://example.com/auto.json3'}]},
        }
        mock_ydl = _make_mock_ydl(extract_return=info)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _FAKE_JSON3_BODY
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            patch('ltn_youtube.youtube_source.urllib.request.urlopen', return_value=mock_resp) as mock_urlopen,
        ):
            result = fetch_subtitles('https://www.youtube.com/watch?v=test')

        assert result is not None
        fetched_url = mock_urlopen.call_args[0][0]
        assert 'manual' in fetched_url

    def test_download_error_returns_none(self):
        """yt-dlp DownloadError (e.g. 429) should return None, not crash."""
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_side_effect=yt_dlp.utils.DownloadError('HTTP Error 429'))

        with patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl):
            result = fetch_subtitles('https://www.youtube.com/watch?v=test')

        assert result is None

    def test_no_subtitles_returns_none(self):
        """Video with no subtitle tracks returns None."""
        import yt_dlp

        info = {'title': 'Test Video', 'language': 'en', 'subtitles': {}, 'automatic_captions': {}}
        mock_ydl = _make_mock_ydl(extract_return=info)

        with patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl):
            result = fetch_subtitles('https://www.youtube.com/watch?v=test')

        assert result is None

    def test_json3_fetch_failure_returns_none(self):
        """Network error fetching json3 URL returns None instead of propagating."""
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_return=_INFO_WITH_MANUAL_SUBS)

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            patch('ltn_youtube.youtube_source.urllib.request.urlopen', side_effect=OSError('connection reset')),
        ):
            result = fetch_subtitles('https://www.youtube.com/watch?v=test')

        assert result is None


class TestDownloadAudio:
    def test_happy_path_returns_path_and_title(self, tmp_path: Path):
        import yt_dlp

        wav_file = tmp_path / 'abc123.wav'
        wav_file.touch()

        mock_ydl = _make_mock_ydl(extract_return={'title': 'My Song', 'id': 'abc123'})

        with patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl):
            audio_path, title = download_audio('https://www.youtube.com/watch?v=abc123', tmp_path)

        assert audio_path == wav_file
        assert title == 'My Song'

    def test_yt_dlp_exception_raises_runtime_error(self, tmp_path: Path):
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_side_effect=yt_dlp.utils.DownloadError('HTTP 403'))

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            pytest.raises(RuntimeError, match='Failed to download YouTube audio'),
        ):
            download_audio('https://www.youtube.com/watch?v=test', tmp_path)

    def test_missing_wav_raises_runtime_error(self, tmp_path: Path):
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_return={'title': 'My Song', 'id': 'abc123'})

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            pytest.raises(RuntimeError, match='abc123.wav'),
        ):
            download_audio('https://www.youtube.com/watch?v=abc123', tmp_path)

    def test_empty_video_id_raises_runtime_error(self, tmp_path: Path):
        import yt_dlp

        mock_ydl = _make_mock_ydl(extract_return={'title': 'No ID', 'id': ''})

        with (
            patch.object(yt_dlp, 'YoutubeDL', return_value=mock_ydl),
            pytest.raises(RuntimeError, match='no video ID'),
        ):
            download_audio('https://www.youtube.com/watch?v=test', tmp_path)
