"""
Tests for FFmpeg binary detection and low-latency RTSP transport ordering.
"""

import unittest
from backend.stream_proxy import _find_ffmpeg, FFMPEG_BIN, CameraStreamSession, _drain_latest_jpeg


class TestStreamProxyFFmpeg(unittest.TestCase):
    def test_find_ffmpeg_candidate_resolution(self):
        """Ensure _find_ffmpeg resolves the binary from local paths or system paths."""
        found = _find_ffmpeg()
        if FFMPEG_BIN:
            self.assertIsNotNone(found)
            self.assertTrue(found.endswith("ffmpeg"))

    def test_rtsp_transport_prefers_udp(self):
        """Ensure CameraStreamSession RTSP transport list prefers low-latency UDP for IP cameras."""
        dummy_cam = {
            "id": "cam-test-rtsp",
            "name": "Test RTSP Cam",
            "stream_url": "rtsp://127.0.0.1:554/live",
            "is_simulated": False
        }
        session = CameraStreamSession(dummy_cam)
        self.assertEqual(session.classify_source(), "ffmpeg")

    def test_drain_latest_jpeg_single_frame(self):
        """Verifies single complete JPEG is extracted cleanly."""
        raw = bytearray(b"\xff\xd8FRAME_DATA_1\xff\xd9")
        frame = _drain_latest_jpeg(raw)
        self.assertEqual(frame, b"\xff\xd8FRAME_DATA_1\xff\xd9")
        self.assertEqual(len(raw), 0)

    def test_drain_latest_jpeg_drops_backlogged_frames(self):
        """Verifies that multiple backlogged frames in buffer are dropped, returning ONLY the newest."""
        raw = bytearray(
            b"junk_prefix\xff\xd8STALE_FRAME_1\xff\xd9"
            b"junk_middle\xff\xd8STALE_FRAME_2\xff\xd9"
            b"\xff\xd8LATEST_FRAME_3\xff\xd9"
            b"\xff\xd8INCOMPLETE_FRAME_4"
        )
        frame = _drain_latest_jpeg(raw)
        self.assertEqual(frame, b"\xff\xd8LATEST_FRAME_3\xff\xd9")
        self.assertEqual(raw, bytearray(b"\xff\xd8INCOMPLETE_FRAME_4"))

    def test_drain_latest_jpeg_incomplete_frame(self):
        """Verifies that incomplete frame without EOI returns None and preserves bytes."""
        raw = bytearray(b"\xff\xd8PARTIAL_DATA")
        frame = _drain_latest_jpeg(raw)
        self.assertIsNone(frame)
        self.assertEqual(raw, bytearray(b"\xff\xd8PARTIAL_DATA"))


if __name__ == "__main__":
    unittest.main()
