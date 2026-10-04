"""
Regression tests for "claimed cameras that don't actually work":

  1. A real RTSP/RTMP/HLS URL must never be silently downgraded to the simulator
     just because the legacy ``is_simulated`` flag is still set on the camera.
  2. Editing a camera (new credentials / IP / source URL) must restart its live
     ingestion worker instead of leaving the stale, broken session running.
  3. User-entered camera fields are trimmed on save/load, so a username such as
     "admin " cannot silently break every camera authentication attempt.
  4. The API reports the *real* per-camera state (online / reconnecting / error)
     instead of every camera claiming to be online forever.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.stream_proxy as stream_proxy
from backend.config_manager import ConfigManager
from backend.stream_proxy import CameraStreamSession, StreamManager


def _temp_config(cameras):
    tmpdir = tempfile.mkdtemp(prefix="omnisight-test-")
    path = os.path.join(tmpdir, "cameras.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": "1.0.0", "cameras": cameras, "groups": ["All"], "users": []}, handle)
    return path


class TestCameraSourceSelection(unittest.TestCase):

    def test_real_rtsp_url_beats_stale_simulated_flag(self):
        """The repo's GatoCam/HIKVISION entries: real URL + is_simulated=true."""
        camera = {
            "id": "cam-gatocam-01", "vendor": "gatocam", "ip": "192.168.1.10",
            "stream_url": "rtsp://admin:@192.168.1.10:554/live/ch0",
            "sub_stream_url": "rtsp://admin:@192.168.1.10:554/live/ch1",
            "snapshot_url": "http://192.168.1.10/snapshot.jpg",
            "is_simulated": True, "legacy_polling": True,
        }
        with unittest.mock.patch.object(stream_proxy, "FFMPEG_BIN", "/usr/bin/ffmpeg"):
            self.assertEqual(CameraStreamSession(camera).classify_source(), "ffmpeg")

    def test_rtsp_without_ffmpeg_degrades_to_snapshot_not_simulation(self):
        """On hosts without FFmpeg an RTSP camera still falls back to its snapshot CGI."""
        camera = {
            "id": "cam-hik", "vendor": "hikvision", "ip": "192.168.1.13",
            "stream_url": "rtsp://admin:pass@192.168.1.13:554/Streaming/Channels/101",
            "snapshot_url": "http://192.168.1.13/ISAPI/Streaming/channels/101/picture",
        }
        session = CameraStreamSession(camera)
        calls = []
        with unittest.mock.patch.object(stream_proxy, "FFMPEG_BIN", None), \
             unittest.mock.patch.object(CameraStreamSession, "_http_snapshot_polling_loop",
                                        lambda self: calls.append("snapshot")), \
             unittest.mock.patch.object(CameraStreamSession, "_simulation_loop",
                                        lambda self: calls.append("simulation")):
            session._worker_loop()
        self.assertEqual(calls, ["snapshot"], "must not silently fake an unreachable real camera")

    def test_pure_simulator_and_special_sources_still_route_correctly(self):
        self.assertEqual(
            CameraStreamSession({"id": "s", "vendor": "simulated", "stream_url": "sim://gate"}).classify_source(),
            "simulation",
        )
        self.assertEqual(
            CameraStreamSession({"id": "w", "vendor": "usb_webcam", "stream_url": "webcam://0"}).classify_source(),
            "webcam",
        )
        self.assertEqual(
            CameraStreamSession({"id": "n", "vendor": "browser_node", "stream_url": "node://phone"}).classify_source(),
            "browser_node",
        )


class TestSessionLifecycle(unittest.TestCase):

    def test_editing_a_camera_restarts_its_stream_session(self):
        path = _temp_config([{
            "id": "cam-x", "name": "Cam X", "vendor": "hikvision", "ip": "10.0.0.5",
            "stream_url": "rtsp://admin:WRONGPASS@10.0.0.5:554/Streaming/Channels/101",
            "is_simulated": False,
        }])
        manager = ConfigManager(path)
        streams = StreamManager(manager)

        old_session = streams.get_session("cam-x")
        self.assertIn("WRONGPASS", old_session.stream_url)

        manager.update_camera("cam-x", {
            "password": "CORRECT",
            "stream_url": "rtsp://admin:CORRECT@10.0.0.5:554/Streaming/Channels/101",
        })
        streams.refresh_cameras()  # what PUT /api/cameras/<id> triggers

        new_session = streams.get_session("cam-x")
        self.assertIsNot(new_session, old_session, "edited camera must get a fresh worker")
        self.assertIn("CORRECT", new_session.stream_url)

        for session in streams.sessions.values():
            session.stop()

    def test_live_status_is_reported_per_camera(self):
        session = CameraStreamSession({"id": "cam-status", "vendor": "simulated", "stream_url": "sim://x"})
        status = session.get_status()
        self.assertEqual(status["camera_id"], "cam-status")
        self.assertIn("online", status)
        self.assertIn("source_kind", status)
        self.assertFalse(status["online"], "a session that never delivered a frame is not online")


class TestCredentialNormalization(unittest.TestCase):

    def test_trailing_whitespace_in_username_is_trimmed(self):
        path = _temp_config([{
            "id": "cam-ws", "name": " HIKVISION (192.168.1.13) ", "vendor": "hikvision",
            "ip": " 192.168.1.13 ", "username": "admin ", "password": "Hik@1234",
            "stream_url": " rtsp://192.168.1.13:554/Streaming/Channels/101 ",
        }])
        manager = ConfigManager(path)
        cam = manager.get_camera("cam-ws")

        self.assertEqual(cam["username"], "admin")
        self.assertEqual(cam["ip"], "192.168.1.13")
        self.assertEqual(cam["name"], "HIKVISION (192.168.1.13)")
        self.assertEqual(cam["stream_url"], "rtsp://192.168.1.13:554/Streaming/Channels/101")
        # Passwords are intentionally preserved verbatim.
        self.assertEqual(cam["password"], "Hik@1234")

    def test_add_and_update_normalize_fields(self):
        path = _temp_config([])
        manager = ConfigManager(path)
        added = manager.add_camera({"name": "  Front Door ", "vendor": "dahua", "username": " admin  ",
                                    "ip": "10.0.0.9 ", "port": "554", "stream_url": ""})
        self.assertEqual(added["name"], "Front Door")
        self.assertEqual(added["username"], "admin")
        self.assertEqual(added["port"], 554)

        updated = manager.update_camera(added["id"], {"username": " operator ", "channel": "2"})
        self.assertEqual(updated["username"], "operator")
        self.assertEqual(updated["channel"], 2)


class TestMultipartSnapshotReader(unittest.TestCase):

    class _EndlessMultipartResponse:
        """Simulates a multipart/x-mixed-replace MJPEG feed that never ends."""

        def __init__(self):
            self.frame = b"\xff\xd8" + b"\x00" * 300 + b"\xff\xd9"
            self.calls = 0

        def read1(self, _n):
            self.calls += 1
            if self.calls > 50:
                raise AssertionError("reader kept going after a complete JPEG frame was available")
            return self.frame + b"PART"

    def test_reader_returns_after_first_complete_jpeg(self):
        response = self._EndlessMultipartResponse()
        frame = CameraStreamSession._read_single_jpeg(response)
        self.assertTrue(frame.startswith(b"\xff\xd8"))
        self.assertTrue(frame.endswith(b"\xff\xd9"))
        self.assertLess(response.calls, 10, "must not block on an endless MJPEG stream")


class TestLiveStatusAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import backend.server as server_mod
        from backend.server import OmniSightHandler

        cls.server_mod = server_mod
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OmniSightHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        cls.cam_id = "cam-reliability-test"
        server_mod.config_manager.add_camera({
            "id": cls.cam_id, "name": "Reliability Test Cam", "vendor": "simulated",
            "stream_url": "sim://reliability", "is_simulated": True,
        })
        server_mod.stream_manager.refresh_cameras()
        auth = server_mod.config_manager.authenticate_user("admin", "admin123")
        cls.token = auth["token"]

    @classmethod
    def tearDownClass(cls):
        cls.server_mod.config_manager.delete_camera(cls.cam_id)
        cls.server_mod.stream_manager.refresh_cameras()
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        return urllib.request.urlopen(req, timeout=10)

    def test_camera_list_exposes_live_status(self):
        with self._get("/api/cameras") as resp:
            data = json.loads(resp.read().decode())
        match = next(c for c in data["cameras"] if c["id"] == self.cam_id)
        self.assertIn("live_status", match)
        self.assertIn("status", match["live_status"])
        self.assertEqual(match["live_status"]["source_kind"], "simulation")

    def test_single_camera_status_endpoint(self):
        with self._get(f"/api/cameras/{self.cam_id}/status") as resp:
            self.assertEqual(resp.status, 200)
            status = json.loads(resp.read().decode())
        self.assertIn(status["status"], {"idle", "connecting", "streaming", "reconnecting", "error"})
        self.assertIn("last_frame_age", status)

    def test_snapshot_reports_real_online_state_in_headers(self):
        with self._get(f"/api/cameras/{self.cam_id}/snapshot") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(resp.headers.get("X-Camera-Online"), {"true", "false"})
            self.assertTrue(resp.headers.get("X-Camera-Status"))


if __name__ == "__main__":
    unittest.main()
