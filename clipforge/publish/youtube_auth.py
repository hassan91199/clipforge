"""Google OAuth helper for the single hardcoded YouTube channel this demo posts to.

Uses google-auth-oauthlib's InstalledAppFlow (Desktop app client type - see
CF-1 in .docs/clickup_tasks.txt for why) instead of CloakMotion's
LinkedAccount/token-per-user DB model: there's exactly one channel here, so
the token just gets cached to a local file.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from clipforge.config import Config

# Matches CloakMotion's config/google.php scopes.youtube list.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

TOKEN_PATH = Path(".clipforge_youtube_token.json")


def get_credentials(config: Config, token_path: Path = TOKEN_PATH) -> Credentials:
    """Return valid credentials, refreshing or running the consent flow as needed."""
    config.require("google_client_id", "google_client_secret")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": config.google_client_id,
                    "client_secret": config.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds
