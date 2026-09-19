"""Google OAuth helper for the single hardcoded YouTube channel this demo posts to.

Uses google-auth-oauthlib's InstalledAppFlow (Desktop app client type - see
CF-1 in .docs/clickup_tasks.txt for why) instead of CloakMotion's
LinkedAccount/token-per-user DB model: there's exactly one channel here, so
the token just gets cached to a local file.
"""

from pathlib import Path

from google.auth.exceptions import RefreshError
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
    """Return valid credentials, refreshing or running the consent flow as needed.

    A cached token can be unrecoverable - Google expires refresh tokens after
    7 days while the OAuth app is in Testing mode - so refresh failures fall
    back to a fresh consent flow instead of crashing with invalid_grant.
    """
    config.require("google_client_id", "google_client_secret")

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, RefreshError):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None
        if creds is None:
            creds = run_consent_flow(config)

    token_path.write_text(creds.to_json())
    return creds


def run_consent_flow(config: Config) -> Credentials:
    """Interactive browser consent; opens a local server and waits."""
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
    return flow.run_local_server(port=0)
