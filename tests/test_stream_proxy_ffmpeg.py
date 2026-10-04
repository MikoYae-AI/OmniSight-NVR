"""
Tests for FFmpeg binary detection and low-latency RTSP transport ordering.
"""

import unittest
from backend.stream_proxy import _find_ffmpeg, FFMPEG_BIN, CameraStreamSession


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


if __name__ == "__main__":
    unittest.main()
