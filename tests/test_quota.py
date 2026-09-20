import io
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
        # quota.py catches s3.exceptions.NoSuchKey off the live client; give
        # the mock a real exception class so the except clause is exercisable.
        client.exceptions.NoSuchKey = KeyError
        if error is not None:
            client.get_object.side_effect = error
        elif existing is None:
            client.get_object.side_effect = KeyError("NoSuchKey")
        else:
            client.get_object.return_value = {"Body": io.BytesIO(str(existing).encode())}
        return client

    def test_first_run_of_day_increments_from_zero(self):
        client = self._client(existing=None)
        with (
            patch.dict(os.environ, {"DEMO_BUCKET": "demo-bkt"}),
            patch("boto3.client", return_value=client),
        ):
            allowed, used = quota.check_and_increment()
        self.assertEqual((allowed, used), (True, 1))
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
        self.assertEqual(client.put_object.call_args.kwargs["Body"], b"8")

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


if __name__ == "__main__":
    unittest.main()
