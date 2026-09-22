import os
import unittest
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import NotFound

from clipforge import quota


class QuotaTests(unittest.TestCase):
    def test_no_bucket_allows_everything(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(quota.check_and_increment(), (True, 0))

    def _client(self, existing=None, error=None):
        client = MagicMock()
        blob = MagicMock()
        client.bucket.return_value.blob.return_value = blob
        if error is not None:
            blob.download_as_bytes.side_effect = error
        elif existing is None:
            blob.download_as_bytes.side_effect = NotFound("no such object")
        else:
            blob.download_as_bytes.return_value = str(existing).encode()
        return client, blob

    def test_first_run_of_day_increments_from_zero(self):
        client, blob = self._client(existing=None)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 1))
        client.bucket.assert_called_once_with("demo-bkt")
        blob.upload_from_string.assert_called_once_with("1")
        blob_name = client.bucket.return_value.blob.call_args.args[0]
        self.assertTrue(blob_name.startswith("demo-runs/"))

    def test_under_limit_increments(self):
        client, blob = self._client(existing=7)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 8))
        blob.upload_from_string.assert_called_once_with("8")

    def test_at_limit_blocks(self):
        client, blob = self._client(existing=quota.DAILY_LIMIT)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (False, quota.DAILY_LIMIT))
        blob.upload_from_string.assert_not_called()

    def test_quota_store_outage_fails_open(self):
        client, blob = self._client(error=RuntimeError("gcs unreachable"))
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 0))

    def test_per_ip_limit_blocks_before_global_limit(self):
        client, blob = self._client(existing=quota.PER_IP_DAILY_LIMIT)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment(client_ip="1.2.3.4")
        self.assertEqual((allowed, used), (False, quota.PER_IP_DAILY_LIMIT))

    def test_per_ip_counter_uses_separate_blob_from_global(self):
        client, blob = self._client(existing=0)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            quota.check_and_increment(client_ip="1.2.3.4")
        blob_names = [call.args[0] for call in client.bucket.return_value.blob.call_args_list]
        self.assertTrue(any("ip-1.2.3.4" in name for name in blob_names))
        self.assertTrue(
            any(name.startswith("demo-runs/") and "ip-" not in name for name in blob_names)
        )

    def test_no_client_ip_only_checks_global_limit(self):
        client, blob = self._client(existing=0)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("google.cloud.storage.Client", return_value=client),
        ):
            allowed, used = quota.check_and_increment(client_ip=None)
        self.assertEqual((allowed, used), (True, 1))
        client.bucket.return_value.blob.assert_called_once()


if __name__ == "__main__":
    unittest.main()
