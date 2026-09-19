# ClipForge

Prompt-driven YouTube Shorts pipeline: text prompt → GPT-4o script → TTS voiceover → Whisper-timed captions → GPT-4o scene prompts → Replicate FLUX images → ffmpeg-rendered vertical video with burned-in captions.

## Setup

```bash
cp .env.example .env   # fill in API keys
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Machine-level dependency: `ffmpeg` with the `drawtext` filter (verify: `ffmpeg -h filter=drawtext`). Running via Docker avoids this entirely.

## Docker (recommended)

The image carries Python deps + ffmpeg (with drawtext asserted at build time); no host installs needed.

```bash
docker build -t clipforge .
docker run --rm clipforge                          # run the test suite (default CMD)
docker run --rm --env-file .env clipforge \
    python -m clipforge.pipeline.render_video ...  # override for pipeline runs
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
    python -m clipforge "Why the sky is blue, for curious kids" --no-upload
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests   # local venv
docker run --rm clipforge                        # container
```
