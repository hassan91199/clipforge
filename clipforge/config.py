"""Environment-backed config for ClipForge.

Deliberately flat env vars instead of CloakMotion's DB-backed ApiKeyManager
(TinyMongo) — this demo has one operator and one YouTube channel, so there's
no per-tenant key storage to manage.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    openai_api_key: str
    replicate_api_token: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    def require(self, *names: str) -> None:
        missing = [name for name in names if not getattr(self, name)]
        if missing:
            raise RuntimeError(f"Missing required config: {', '.join(missing)} (check .env)")


def load_config() -> Config:
    return Config(
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        replicate_api_token=os.environ.get("REPLICATE_API_TOKEN", ""),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        google_redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", ""),
    )


def demo_config(openai_api_key: str, replicate_api_token: str) -> Config:
    """Public-demo config: visitor-supplied keys; Google/publish excluded.

    The demo never takes public writes to a YouTube channel, and visitors
    would each need their own OAuth client, so the publish path is not part
    of the public demo.
    """
    return Config(
        openai_api_key=openai_api_key,
        replicate_api_token=replicate_api_token,
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="",
    )
