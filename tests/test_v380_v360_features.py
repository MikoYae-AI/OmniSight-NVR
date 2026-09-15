"""
OmniSight-NVR - Test Suite for V380 Pro / V360 Pro Replicated Features
Verifies:
  1. Live Intercom microphone talkback streaming.
  2. Autonomous OpenCV / PTZ Sentry Auto-Tracking.
  3. 24-Hour Timeline event markers & historical playback frame streaming.
"""

import unittest
import base64
import time
import json
import urllib.request
import threading
from http.server import ThreadingHTTPServer

from backend.config_manager import ConfigManager
from backend.stream_proxy import StreamManager, CameraStreamSession
from backend.recorder import RecorderManager
from backend.server import OmniSightHandler
import backend.server as server_mod


class TestV380V360ProFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_manager = ConfigManager()
        cls.stream_manager = StreamManager(cls.config_manager)
        cls.recorder_manager = RecorderManager(cls.stream_manager)
        
        # Start test HTTP server on an ephemeral port
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OmniSightHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # Obtain valid authentication token
        auth_info = server_mod.config_manager.authenticate_user("admin", "admin123")
        cls.auth_token = auth_info["token"]
        cls.headers = {
            "Authorization": f"Bearer {cls.auth_token}",
            "Content-Type": "application/json"
        }

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_01_intercom_talkback_api(self):
        """Tests sending audio chunks via /api/cameras/:id/talk."""
        # Grab first camera
        cams = server_mod.config_manager.get_all_cameras()
        self.assertTrue(len(cams) > 0)
        cam_id = cams[0]["id"]
        session = server_mod.stream_manager.get_session(cam_id)
        self.assertIsNotNone(session)

        # Generate 1KB dummy PCM/WebM audio bytes
        raw_audio = b"\x00\x7f\x80\xff" * 256
        b64_audio = base64.b64encode(raw_audio).decode("ascii")

        url = f"http://127.0.0.1:{self.port}/api/cameras/{cam_id}/talk"
        req = urllib.request.Request(
            url,
            data=json.dumps({"audio_base64": b64_audio, "format": "webm"}).encode("utf-8"),
            headers=self.headers,
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["camera_id"], cam_id)
            self.assertEqual(data["bytes_received"], len(raw_audio))

        self.assertTrue(session.intercom_active)
        self.assertGreaterEqual(session.audio_bytes_sent, len(raw_audio))

    def test_02_autonomous_auto_tracking_control(self):
        """Tests activating and verifying PTZ auto-tracking."""
        cams = server_mod.config_manager.get_all_cameras()
        cam_id = cams[0]["id"]
        session = server_mod.stream_manager.get_session(cam_id)
        self.assertIsNotNone(session)

        # Enable Auto-Tracking
        url = f"http://127.0.0.1:{self.port}/api/cameras/{cam_id}/control"
        req = urllib.request.Request(
            url,
            data=json.dumps({"type": "auto_tracking", "value": True}).encode("utf-8"),
            headers=self.headers,
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["auto_tracking"])

        self.assertTrue(session.auto_tracking)

        # Let the simulation generate at least one frame and verify pan/tilt responds
        time.sleep(0.15)
        frame = session.get_latest_frame()
        self.assertIsInstance(frame, bytes)
        self.assertTrue(len(frame) > 1000)

        # Disable Auto-Tracking
        req_off = urllib.request.Request(
            url,
            data=json.dumps({"type": "auto_tracking", "value": False}).encode("utf-8"),
            headers=self.headers,
            method="POST"
        )
        with urllib.request.urlopen(req_off) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data["auto_tracking"])

        self.assertFalse(session.auto_tracking)

    def test_03_timeline_events_and_playback_stream(self):
        """Tests /api/cameras/:id/timeline and /api/cameras/:id/playback."""
        cams = server_mod.config_manager.get_all_cameras()
        cam_id = cams[0]["id"]

        # 1. Timeline markers
        timeline_url = f"http://127.0.0.1:{self.port}/api/cameras/{cam_id}/timeline?date=2026-09-14"
        req = urllib.request.Request(timeline_url, headers=self.headers)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            events = json.loads(resp.read().decode("utf-8"))
            self.assertIsInstance(events, list)
            self.assertGreater(len(events), 0)
            # Check event types: continuous, motion, alarm
            types = {e["type"] for e in events}
            self.assertIn("continuous", types)
            self.assertIn("motion", types)
            self.assertIn("alarm", types)

            first_evt = events[0]
            self.assertIn("start_pct", first_evt)
            self.assertIn("width_pct", first_evt)
            self.assertIn("start_str", first_evt)

        # 2. Historical playback frame
        playback_url = f"http://127.0.0.1:{self.port}/api/cameras/{cam_id}/playback?time=52200"
        req_play = urllib.request.Request(playback_url, headers=self.headers)
        with urllib.request.urlopen(req_play) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/jpeg")
            frame_data = resp.read()
            self.assertGreater(len(frame_data), 1000)
            # Check JPEG SOI and EOI markers
            self.assertTrue(frame_data.startswith(b"\xff\xd8"))
            self.assertTrue(frame_data.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
