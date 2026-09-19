import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError

from clipforge.config import Config
from clipforge.publish.youtube_auth import SCOPES, get_credentials


def _config():
    return Config(
        openai_api_key="",
        replicate_api_token="",
        google_client_id="id123",
        google_client_secret="secret123",
        google_redirect_uri="",
    )


class FakeCreds:
    def __init__(self, valid=False, expired=False, has_refresh=True):
        self.valid = valid
        self.expired = expired
        self.refresh_token = "refresh-token" if has_refresh else None
        self.to_json = MagicMock(return_value=json.dumps({"fake": "creds"}))

    def refresh(self, request):
        if self.expired and self.refresh_token:
            raise RefreshError("invalid_grant: Token has been expired or revoked.")
        raise AssertionError("refresh should not be called in this test")


def _write_token(path, content):
    path.write_text(content)


class GetCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token_path = Path(self.tmp.name) / "token.json"
        self.config = _config()

    def test_missing_token_file_runs_consent_flow_and_saves_token(self):
        with patch("clipforge.publish.youtube_auth.Credentials") as _, patch(
            "clipforge.publish.youtube_auth.InstalledAppFlow"
        ) as flow_cls:
            flow_cls.from_client_config.return_value.run_local_server.return_value = FakeCreds(valid=True)
            creds = get_credentials(self.config, self.token_path)
        self.assertTrue(creds.valid)
        flow_cls.from_client_config.assert_called_once()
        self.assertIn(SCOPES[0], str(flow_cls.from_client_config.call_args))
        self.assertEqual(json.loads(self.token_path.read_text()), {"fake": "creds"})

    def test_valid_cached_token_is_returned_without_network_or_consent(self):
        _write_token(self.token_path, json.dumps({"cached": True}))
        with patch("clipforge.publish.youtube_auth.Credentials") as creds_cls, patch(
            "clipforge.publish.youtube_auth.InstalledAppFlow"
        ) as flow_cls:
            creds_cls.from_authorized_user_file.return_value = FakeCreds(valid=True)
            get_credentials(self.config, self.token_path)
        flow_cls.from_client_config.assert_not_called()
        creds_cls.from_authorized_user_file.assert_called_once_with(str(self.token_path), SCOPES)

    def test_expired_token_refreshes_instead_of_reconsenting(self):
        _write_token(self.token_path, json.dumps({"cached": True}))
        refreshed = FakeCreds(valid=True)
        with patch("clipforge.publish.youtube_auth.Credentials") as creds_cls, patch(
            "clipforge.publish.youtube_auth.InstalledAppFlow"
        ) as flow_cls, patch("clipforge.publish.youtube_auth.Request"):
            cached = FakeCreds(valid=False, expired=True)
            cached.refresh = MagicMock()  # succeeds silently
            creds_cls.from_authorized_user_file.return_value = cached

            def refresh_side_effect(request):
                cached.valid = True

            cached.refresh.side_effect = refresh_side_effect
            creds = get_credentials(self.config, self.token_path)
        flow_cls.from_client_config.assert_not_called()
        cached.refresh.assert_called_once()
        self.assertTrue(creds.valid)

    def test_revoked_refresh_token_falls_back_to_consent_flow(self):
        _write_token(self.token_path, json.dumps({"cached": True}))
        with patch("clipforge.publish.youtube_auth.Credentials") as creds_cls, patch(
            "clipforge.publish.youtube_auth.InstalledAppFlow"
        ) as flow_cls, patch("clipforge.publish.youtube_auth.Request"):
            stale = FakeCreds(valid=False, expired=True)
            creds_cls.from_authorized_user_file.return_value = stale
            fresh = FakeCreds(valid=True)
            flow_cls.from_client_config.return_value.run_local_server.return_value = fresh

            creds = get_credentials(self.config, self.token_path)
        flow_cls.from_client_config.assert_called_once()
        self.assertTrue(creds.valid)
        self.assertEqual(json.loads(self.token_path.read_text()), {"fake": "creds"})

    def test_corrupt_token_file_falls_back_to_consent_flow(self):
        _write_token(self.token_path, "not json at all")
        with patch("clipforge.publish.youtube_auth.Credentials") as creds_cls, patch(
            "clipforge.publish.youtube_auth.InstalledAppFlow"
        ) as flow_cls:
            creds_cls.from_authorized_user_file.side_effect = ValueError("bad file")
            fresh = FakeCreds(valid=True)
            flow_cls.from_client_config.return_value.run_local_server.return_value = fresh

            creds = get_credentials(self.config, self.token_path)
        flow_cls.from_client_config.assert_called_once()
        self.assertTrue(creds.valid)


if __name__ == "__main__":
    unittest.main()
