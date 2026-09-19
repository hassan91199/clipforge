# ClipForge

Prompt-driven YouTube Shorts pipeline: text prompt → GPT-4o script → TTS voiceover → Whisper-timed captions → GPT-4o scene prompts → Replicate FLUX images → ffmpeg-rendered vertical video with burned-in captions.

## Setup

```bash
cp .env.example .env   # fill in API keys
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Machine-level dependency: `ffmpeg` with the `drawtext` filter (verify: `ffmpeg -h filter=drawtext`). Running via Docker avoids this entirely.

## Docker (recommended)

The image carries Python deps (Streamlit included) + ffmpeg (with drawtext
asserted at build time); no host installs needed. Three entrypoint modes:

```bash
docker build -t clipforge .
docker run --rm clipforge        # test    - run the test suite (default CMD)
docker run --rm ... clipforge run <cli args>   # run     - the CLI pipeline
docker run --rm -p 8501:8501 ... clipforge ui  # ui      - the Streamlit front-end
```

Secrets stay on the host: `.env` is passed with `--env-file` at runtime and is excluded from the image by `.dockerignore`.

## Full pipeline

```bash
python -m clipforge "Why the sky is blue, for curious kids"   # render + schedule upload +24h
python -m clipforge "..." --no-upload                          # render only
python -m clipforge "..." --publish-now                        # publish immediately, not scheduled
```

Run artifacts land in `./runs/run-<timestamp>/`: script.json, voiceover.mp3, captions.json (+.srt), images/, short.mp4, publish.json.

Via Docker:

```bash
docker run --rm --env-file .env -v "$PWD/runs:/app/runs" clipforge \
    run "Why the sky is blue, for curious kids" --no-upload
```

## Web UI

Same pipeline behind a browser page, with a live timing row per stage and the
total elapsed time at the end:

```bash
.venv/bin/streamlit run clipforge/ui.py
```

Controls: prompt box, scene-image count, target length, and a
"Also schedule on YouTube" checkbox (off by default — uploads only happen when
explicitly ticked). The finished short plays in the page; run artifacts land in
the same `runs/run-<timestamp>/` layout as the CLI.

Via Docker — UI at http://localhost:8501:

```bash
docker run --rm -p 8501:8501 --env-file .env \
    -v "$PWD/runs:/app/runs" clipforge ui
```

To let the upload checkbox work, mount the cached OAuth token too (consent
first via the CLI, since the container has no browser):

```bash
docker run --rm -p 8501:8501 --env-file .env \
    -v "$PWD/runs:/app/runs" \
    -v "$PWD/.clipforge_youtube_token.json:/app/.clipforge_youtube_token.json" \
    clipforge ui
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests   # local venv
docker run --rm clipforge                        # container
```
