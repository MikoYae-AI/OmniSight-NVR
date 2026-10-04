"""
Tests for cameras that only ever worked in Internet Explorer / ActiveX.

These cameras expose no usable RTSP path (video was produced by the vendor's
ActiveX control), so OmniSight must:

  1. Never fabricate an RTSP URL for them.
  2. Find their raw JPEG endpoint automatically, including endpoints that only
     answer when the ActiveX plugin's query string is present.
  3. Authenticate against that endpoint (Basic and Digest) and stream real frames.
  4. Report the verified snapshot endpoint from the prober instead of a guessed
     RTSP URL, even when port 554 happens to be open.
"""

import base64
import io
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import backend.discovery as discovery
from backend.stream_proxy import LEGACY_SNAPSHOT_CANDIDATES, CameraStreamSession, format_snapshot_url
from backend.vendor_presets import VENDOR_PRESETS, build_stream_url


def _jpeg_bytes(text="IE-ONLY"):
    img = Image.new("RGB", (160, 90), (20, 30, 50))
    from PIL import ImageDraw
    ImageDraw.Draw(img).text((5, 5), text, fill=(255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return buf.getvalue()


class FakeLegacyCamera(BaseHTTPRequestHandler):
    """ActiveX-era camera: video only at /webcapture.jpg?command=snap&channel=N, Basic auth."""

    valid_auth = base64.b64encode(b"admin:12345").decode()
    hits = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeLegacyCamera.hits.append(self.path)
        if self.headers.get("Authorization") != f"Basic {self.valid_auth}":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="camera"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path.split("?")[0] == "/webcapture.jpg" and "command=snap" in self.path:
            data = _jpeg_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


class LegacyCameraServerMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeLegacyCamera.hits = []
        cls.camera_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLegacyCamera)
        cls.camera_port = cls.camera_server.server_address[1]
        cls.camera_thread = threading.Thread(target=cls.camera_server.serve_forever, daemon=True)
        cls.camera_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.camera_server.shutdown()
        cls.camera_server.server_close()

    def legacy_camera_info(self, **overrides):
        camera = {
            "id": "legacy-ie-cam",
            "name": "Legacy IE Camera",
            "vendor": "legacy_activex",
            "ip": "127.0.0.1",
            "port": self.camera_port,
            "username": "admin",
            "password": "12345",
            "channel": 1,
            "stream_url": "rtsp://admin:12345@127.0.0.1:554/live/ch0",
            "is_simulated": False,
        }
        camera.update(overrides)
        return camera


class TestLegacyPreset(LegacyCameraServerMixin):

    def test_preset_is_snapshot_first(self):
        preset = VENDOR_PRESETS["legacy_activex"]
        self.assertTrue(preset.get("snapshot_first"), "legacy ActiveX cameras must not rely on RTSP")
        self.assertEqual(preset.get("default_channel"), 1)

    def test_build_stream_url_returns_snapshot_not_rtsp(self):
        url = build_stream_url("legacy_activex", "192.168.1.60", 554, "admin", "12345", channel=1)
        self.assertTrue(url.startswith("http://"), f"expected an HTTP snapshot URL, got {url}")
        self.assertIn("command=snap", url)
        self.assertIn("channel=1", url)
        self.assertNotIn(":554", url, "RTSP port must not leak into the HTTP snapshot URL")

    def test_snapshot_url_formatting_helper(self):
        url = format_snapshot_url(
            "/webcapture.jpg?command=snap&channel={channel}", "10.0.0.4", 80, 3, "admin", "p@ss word"
        )
        self.assertEqual(url, "http://10.0.0.4:80/webcapture.jpg?command=snap&channel=3")
        self.assertIn("p%40ss%20word", format_snapshot_url("/x?u={username}&p={password}", "10.0.0.4", 80, 1, "admin", "p@ss word"))


class TestLegacyRouting(LegacyCameraServerMixin):

    def test_never_routed_to_ffmpeg_rtsp(self):
        session = CameraStreamSession(self.legacy_camera_info())
        self.assertEqual(session.classify_source(), "snapshot")
        self.assertTrue(session.is_legacy_ie_camera())
        self.assertTrue(session._snapshot_capable())

    def test_legacy_endpoint_is_tried_before_generic_ones(self):
        session = CameraStreamSession(self.legacy_camera_info())
        candidates = session._snapshot_url_candidates()
        self.assertIn("/webcapture.jpg?command=snap&channel=1", candidates[0])
        self.assertGreater(len(candidates), len(LEGACY_SNAPSHOT_CANDIDATES) - 1)

    def test_rtsp_port_maps_to_http_port_for_polling(self):
        session = CameraStreamSession(self.legacy_camera_info(port=554))
        self.assertEqual(session._snapshot_port(), 80)


class TestSnapshotDiscovery(LegacyCameraServerMixin):

    def test_discovers_endpoint_that_requires_the_activex_query_string(self):
        """The bare path 404s; only ?command=snap&channel=N works - discovery must find it."""
        session = CameraStreamSession(self.legacy_camera_info())
        found = session.discover_snapshot_endpoint(timeout=1.5)
        self.assertIsNotNone(found, "discovery failed to locate the ActiveX-era snapshot endpoint")
        self.assertIn("command=snap", found)
        self.assertIn(f":{self.camera_port}", found)

    def test_discovers_endpoint_through_basic_auth(self):
        session = CameraStreamSession(self.legacy_camera_info(password="wrong-password"))
        self.assertIsNone(
            session.discover_snapshot_endpoint(timeout=1.0),
            "must not report success when the camera rejects our credentials",
        )

    def test_polling_loop_streams_real_frames(self):
        session = CameraStreamSession(self.legacy_camera_info())
        session.start()
        try:
            deadline = time.time() + 15
            while time.time() < deadline and not session.get_status()["online"]:
                time.sleep(0.25)
            status = session.get_status()
            self.assertTrue(status["online"], f"legacy camera never went online: {status}")
            self.assertEqual(status["source_kind"], "snapshot")
            frame = session.get_latest_frame()
            self.assertTrue(frame.startswith(b"\xff\xd8"), "latest frame is not a JPEG")
        finally:
            session.stop()

    def test_working_endpoint_is_remembered_and_reused(self):
        session = CameraStreamSession(self.legacy_camera_info())
        session.start()
        try:
            deadline = time.time() + 15
            while time.time() < deadline and not session._working_snapshot_url:
                time.sleep(0.25)
            self.assertTrue(session._working_snapshot_url)
            remembered = session._working_snapshot_url
            # A fresh candidate list for the same camera offers the known-good URL first
            self.assertEqual(session._snapshot_url_candidates()[0], remembered)
        finally:
            session.stop()


class TestProberPrefersVerifiedSnapshot(LegacyCameraServerMixin):

    def test_prober_reports_verified_snapshot_over_guessed_rtsp(self):
        result = discovery.probe_camera_connection(
            ip="127.0.0.1",
            port=self.camera_port,
            username="admin",
            password="12345",
            vendor_hint="legacy_activex",
        )
        self.assertTrue(result["success"], result)
        self.assertTrue(result["reachable"])
        self.assertTrue(
            result["stream_url"].startswith("http://"),
            f"prober must not recommend a fabricated RTSP URL: {result['stream_url']}",
        )
        self.assertIn("command=snap", result["stream_url"])
        self.assertIn("snapshot", result["summary"].lower())


if __name__ == "__main__":
    unittest.main()
