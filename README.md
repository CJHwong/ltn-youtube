# ltn-youtube

YouTube transcription plugin for [lazy-take-notes](https://github.com/CJHwong/lazy-take-notes).

Transcribe YouTube videos using existing subtitles (preferred) or audio download with whisper (fallback). All digest, quick actions, and TUI features from lazy-take-notes work out of the box.

## Usage

```bash
uvx --from "lazy-take-notes @ git+https://github.com/CJHwong/lazy-take-notes.git" \
    --with "ltn-youtube @ git+https://github.com/CJHwong/ltn-youtube.git" \
    lazy-take-notes youtube "https://www.youtube.com/watch?v=VIDEO_ID"

# With a custom session label
uvx --from "lazy-take-notes @ git+https://github.com/CJHwong/lazy-take-notes.git" \
    --with "ltn-youtube @ git+https://github.com/CJHwong/ltn-youtube.git" \
    lazy-take-notes youtube "https://youtu.be/VIDEO_ID" --label "my-notes"
```

If you have `take-note` installed via [lazy-take-notes setup](https://github.com/CJHwong/lazy-take-notes), you can add the plugin permanently by updating the wrapper script:

```bash
# Replace the existing take-note wrapper to include the youtube plugin
cat > "$(brew --prefix)/bin/take-note" << 'EOF'
#!/bin/bash
exec uvx --from "git+https://github.com/CJHwong/lazy-take-notes.git" \
    --with "ltn-youtube @ git+https://github.com/CJHwong/ltn-youtube.git" \
    lazy-take-notes "$@"
EOF
chmod +x "$(brew --prefix)/bin/take-note"
```

Then use directly:

```bash
take-note youtube "https://www.youtube.com/watch?v=VIDEO_ID"
```

## How it works

1. Checks for YouTube subtitles — picks the best track automatically (manual preferred over auto-generated, video's own language preferred)
2. If subtitles found — parses json3 and replays segments into the TUI (no whisper inference needed)
3. If no subtitles — downloads audio via yt-dlp and transcribes with whisper
4. Opens the standard lazy-take-notes TUI with template picker, digest, and quick actions

## Development

```bash
git clone https://github.com/CJHwong/ltn-youtube.git
cd ltn-youtube
uv sync

# Run from local source (always picks up uncommitted changes)
uv run lazy-take-notes youtube "https://www.youtube.com/watch?v=VIDEO_ID"

# Run tests
uv run pytest tests/ -v
```

## Acknowledgements

Special thanks to [@Sean-fn](https://github.com/Sean-fn) for the original YouTube transcription idea and implementation in [lazy-take-notes#12](https://github.com/CJHwong/lazy-take-notes/pull/12), which inspired this plugin.

## License

MIT
