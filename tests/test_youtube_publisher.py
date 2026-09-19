import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from googleapiclient.errors import HttpError

from clipforge.publish.youtube_publisher import (
    CHUNK_SIZE,
    format_publish_at,
    publish_video,
)


class FakeProgress:
    def __init__(self, fraction):
        self._fraction = fraction

    def progress(self):
        return self._fraction


class FakeRequest:
    def __init__(self, chunks, response):
        self._chunks = chunks
        self._response = response

    def next_chunk(self):
        if self._chunks:
            return FakeProgress(self._chunks.pop(0)), None
        return None, self._response


class FakeVideos:
    def __init__(self, call_log, response, chunks):
        self._call_log = call_log
        self._response = response
        self._chunks = chunks

    def insert(self, part, body, media_body):
        self._call_log.append(
            {
                "part": part,
                "body": body,
                "media_body": media_body,
            }
        )
        return FakeRequest(list(self._chunks), self._response)


class FakeYoutube:
    def __init__(self, call_log=None, response=None, chunks=(0.5,)):
        self.call_log = call_log if call_log is not None else []
        self._response = response or {"id": "vid123", "status": {"privacyStatus": "private"}}
        self._chunks = chunks

    def videos(self):
        return FakeVideos(self.call_log, self._response, self._chunks)


def _video_file(tmp_dir, size_bytes=2048):
    path = Path(tmp_dir) / "short.mp4"
    path.write_bytes(b"\x00" * size_bytes)
    return path


class FormatPublishAtTests(unittest.TestCase):
    def test_naive_datetime_treated_as_utc(self):
        self.assertEqual(format_publish_at(datetime(2026, 9, 21, 15, 30)), "2026-09-21T15:30:00Z")

    def test_aware_datetime_converted_to_utc(self):
        dt = datetime(2026, 9, 21, 18, 30, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(format_publish_at(dt), "2026-09-21T15:30:00Z")


class PublishVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = _video_file(self.tmp.name)
        self.call_log = []
        self.youtube = FakeYoutube(call_log=self.call_log)

    def _publish(self, **kwargs):
        defaults = {
            "video_path": self.video,
            "title": "Test title",
            "description": "Test description",
            "youtube": self.youtube,
        }
        defaults.update(kwargs)
        return publish_video(**defaults)

    def test_upload_without_publish_at_is_public_immediately(self):
        response = self._publish()
        self.assertEqual(response["id"], "vid123")
        body = self.call_log[0]["body"]
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertNotIn("publishAt", body["status"])
        self.assertEqual(body["snippet"]["categoryId"], "22")
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])

    def test_scheduled_upload_is_private_with_utc_publish_at(self):
        publish_at = datetime(2026, 9, 21, 15, 30)
        self._publish(publish_at=publish_at)
        body = self.call_log[0]["body"]
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(body["status"]["publishAt"], "2026-09-21T15:30:00Z")

    def test_upload_sends_resumable_media_with_chunk_size(self):
        self._publish()
        media = self.call_log[0]["media_body"]
        self.assertEqual(media._chunksize, CHUNK_SIZE)
        self.assertTrue(media.resumable)

    def test_chunk_loop_drains_all_chunks_before_response(self):
        self._publish()
        self.assertEqual(len(self.call_log), 1)

    def test_missing_video_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self._publish(video_path=Path(self.tmp.name) / "missing.mp4")

    def test_empty_title_raises(self):
        with self.assertRaises(ValueError):
            self._publish(title="   ")

    def test_title_over_100_chars_raises(self):
        with self.assertRaises(ValueError):
            self._publish(title="x" * 101)

    def test_description_over_5000_chars_raises(self):
        with self.assertRaises(ValueError):
            self._publish(description="x" * 5001)

    def test_response_without_id_raises(self):
        youtube = FakeYoutube(response={"kind": "youtube#video"})
        with self.assertRaises(RuntimeError):
            publish_video(
                video_path=self.video,
                title="Test",
                description="Test",
                youtube=youtube,
            )


class ChunkSizeTests(unittest.TestCase):
    def test_chunk_size_is_1mb_like_cloakmotion(self):
        self.assertEqual(CHUNK_SIZE, 1 * 1024 * 1024)


class PublishProgressTests(unittest.TestCase):
    def test_progress_prints_during_upload(self):
        import contextlib
        import io

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        video = _video_file(tmp.name)
        youtube = FakeYoutube(chunks=(0.25, 0.75))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            publish_video(video_path=video, title="T", description="D", youtube=youtube)
        self.assertIn("uploaded 25%", buffer.getvalue())
        self.assertIn("uploaded 75%", buffer.getvalue())


class HttpErrorTests(unittest.TestCase):
    def test_http_error_propagates(self):
        class FailRequest:
            def next_chunk(self):
                resp = type("Resp", (), {"status": 403, "reason": "quotaExceeded"})()
                raise HttpError(resp, b'{"error": {"message": "quota exceeded"}}')

        class FailInsert:
            def insert(self, part, body, media_body):
                return FailRequest()

        class FailVideos:
            def insert(self, part, body, media_body):
                return FailInsert().insert(part, body, media_body)

        class FailYoutube:
            def videos(self):
                return FailVideos()

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        video = _video_file(tmp.name)
        with self.assertRaises(HttpError):
            publish_video(video_path=video, title="T", description="D", youtube=FailYoutube())


if __name__ == "__main__":
    unittest.main()
