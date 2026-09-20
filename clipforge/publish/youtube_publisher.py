"""Uploads a rendered video to the single demo YouTube channel.

Adapted from CloakMotion's app/Services/YouTube/YouTubePublisher.php with two
changes:

- Scheduled publish: YouTubePublisher.php posts immediately as public. Here
  `publish_at` instead sets status.privacyStatus=private + status.publishAt
  (RFC 3339 UTC), so the video goes live on its own later. publishAt only
  takes effect on private videos - YouTube rejects the combination of
  publishAt with any other privacy status.
- No LinkedAccount model: credentials come from youtube_auth's single cached
  token file (CF-1), and the caller can inject a prebuilt youtube service for
  testing instead of hitting the network.
"""

from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from clipforge.config import Config
from clipforge.publish.youtube_auth import get_credentials

# Same category CloakMotion hardcodes: People & Blogs.
CATEGORY_ID = "22"

# Mirrors CloakMotion's 1MB chunk size for resumable uploads.
CHUNK_SIZE = 1 * 1024 * 1024

TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 5000


def format_publish_at(publish_at: datetime) -> str:
    """RFC 3339 UTC string, as videos.insert's publishAt expects."""
    if publish_at.tzinfo is None:
        publish_at = publish_at.replace(tzinfo=timezone.utc)
    return publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish_video(
    video_path: Path,
    title: str,
    description: str,
    publish_at: datetime | None = None,
    config: Config | None = None,
    youtube=None,
) -> dict:
    """Resumable-upload video_path and return the videos.insert response.

    With publish_at, the upload lands as a private video scheduled to go
    public at that time; without it, the video publishes immediately.
    Pass `youtube` (a googleapiclient youtube resource) to bypass auth and
    network entirely - used by tests; config is only needed in that case.
    """
    title = title.strip()
    description = description.strip()
    if not title:
        raise ValueError("Title is empty")
    if len(title) > TITLE_MAX_CHARS:
        raise ValueError(
            f"Title exceeds YouTube's {TITLE_MAX_CHARS}-char limit ({len(title)} chars)"
        )
    if len(description) > DESCRIPTION_MAX_CHARS:
        raise ValueError(
            f"Description exceeds YouTube's {DESCRIPTION_MAX_CHARS}-char limit "
            f"({len(description)} chars)"
        )
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if youtube is None:
        if config is None:
            raise ValueError("config is required unless a youtube service is injected")
        creds = get_credentials(config)
        youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private" if publish_at else "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = format_publish_at(publish_at)

    media = MediaFileUpload(video_path, mimetype="video/*", chunksize=CHUNK_SIZE, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"  uploaded {int(progress.progress() * 100)}%", flush=True)

    if not response.get("id"):
        raise RuntimeError(f"YouTube upload returned no video id: {response}")
    return response
