"""FastAPI backend exposing run_pipeline over REST + SSE (CF-20).

Backs the Next.js frontend (CF-21) the way clipforge/ui.py backs Streamlit
today: BYO-keys demo mode, the same quota gate, and the same on_event
contract from clipforge.cli.run_pipeline. The pipeline itself is synchronous
and I/O-bound, so each request runs it on a worker thread and streams its
events out over SSE as they arrive - the split-architecture equivalent of
Streamlit's websocket auto-refresh.
"""

import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from clipforge.cli import run_pipeline
from clipforge.config import demo_config
from clipforge.quota import check_and_increment

# A run's video is served back from the same container that rendered it -
# Cloud Run session affinity (CF-17) pins a browser session to one instance,
# the same trick that makes the Streamlit demo's fetch work.
RUNS_DIR = Path("runs")

app = FastAPI(title="ClipForge API")

_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin] if _frontend_origin else ["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str
    openai_api_key: str
    replicate_api_token: str
    num_images: int | None = None
    video_duration: str = "30"


def client_ip(request: Request) -> str | None:
    """Best-effort caller IP - X-Forwarded-For first hop, else the socket peer."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _stream_run(config, prompt: str, num_images: int | None, video_duration: str) -> Iterator[str]:
    run_id = uuid.uuid4().hex
    output_dir = RUNS_DIR / run_id
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            run_pipeline(
                config,
                prompt,
                output_dir,
                num_images=num_images,
                video_duration=video_duration,
                upload=False,
                on_event=events.put,
            )
            events.put({"event": "result", "video_url": f"/api/runs/{run_id}/video"})
        except Exception as error:
            events.put({"event": "error", "message": str(error)})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        event = events.get()
        if event is None:
            return
        yield _sse(event)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/generate")
def generate(payload: GenerateRequest, request: Request) -> StreamingResponse:
    allowed, used = check_and_increment(client_ip=client_ip(request))
    if not allowed:

        def _blocked() -> Iterator[str]:
            yield _sse(
                {"event": "error", "message": f"Daily demo limit reached ({used} runs today)"}
            )

        return StreamingResponse(_blocked(), media_type="text/event-stream")

    config = demo_config(payload.openai_api_key, payload.replicate_api_token)
    stream = _stream_run(config, payload.prompt, payload.num_images, payload.video_duration)
    return StreamingResponse(stream, media_type="text/event-stream")


@app.get("/api/runs/{run_id}/video")
def get_video(run_id: str) -> FileResponse:
    video_path = RUNS_DIR / run_id / "short.mp4"
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="run not found")
    return FileResponse(video_path, media_type="video/mp4")
