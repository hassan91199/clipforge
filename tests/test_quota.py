import os
import unittest
from unittest.mock import MagicMock, patch

from clipforge import quota


class QuotaTests(unittest.TestCase):
    def test_no_bucket_allows_everything(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(quota.check_and_increment(), (True, 0))

    def _client(self, existing=None, error=None):
        client = MagicMock()
        client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        if error is not None:
            client.get_object.side_effect = error
        elif existing is None:
            client.get_object.side_effect = client.exceptions.NoSuchKey()
        else:
            body = MagicMock()
            body.read.return_value = str(existing).encode()
            client.get_object.return_value = {"Body": body}
        return client

    def test_first_run_of_day_increments_from_zero(self):
        client = self._client(existing=None)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 1))
        client.put_object.assert_called_once()
        kwargs = client.put_object.call_args.kwargs
        self.assertEqual(kwargs["Bucket"], "demo-bkt")
        self.assertEqual(kwargs["Body"], b"1")
        self.assertTrue(kwargs["Key"].startswith("demo-runs/"))

    def test_under_limit_increments(self):
        client = self._client(existing=7)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 8))
        client.put_object.assert_called_once_with(
            Bucket="demo-bkt", Key=client.put_object.call_args.kwargs["Key"], Body=b"8"
        )

    def test_at_limit_blocks(self):
        client = self._client(existing=quota.DAILY_LIMIT)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (False, quota.DAILY_LIMIT))
        client.put_object.assert_not_called()

    def test_quota_store_outage_fails_open(self):
        client = self._client(error=RuntimeError("s3 unreachable"))
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 0))

    def test_per_ip_limit_blocks_before_global_limit(self):
        client = self._client(existing=quota.PER_IP_DAILY_LIMIT)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment(client_ip="1.2.3.4")
        self.assertEqual((allowed, used), (False, quota.PER_IP_DAILY_LIMIT))

    def test_per_ip_counter_uses_separate_key_from_global(self):
        client = self._client(existing=0)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            quota.check_and_increment(client_ip="1.2.3.4")
        keys = [call.kwargs["Key"] for call in client.get_object.call_args_list]
        self.assertTrue(any("ip-1.2.3.4" in key for key in keys))
        self.assertTrue(any(key.startswith("demo-runs/") and "ip-" not in key for key in keys))

    def test_no_client_ip_only_checks_global_limit(self):
        client = self._client(existing=0)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment(client_ip=None)
        self.assertEqual((allowed, used), (True, 1))
        client.get_object.assert_called_once()

    def test_uses_s3_client_for_configured_bucket(self):
        client = self._client(existing=0)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client) as boto_client,
        ):
            quota.check_and_increment()
        boto_client.assert_called_once_with("s3")
        self.assertEqual(client.get_object.call_args.kwargs["Bucket"], "demo-bkt")


if __name__ == "__main__":
    unittest.main()
