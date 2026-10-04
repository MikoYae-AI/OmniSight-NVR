"""
Tests for Hikvision cameras that ask for the WebComponents.exe ActiveX plugin in IE.

Hikvision's own web UI tells you to install WebComponents.exe (an Internet Explorer
ActiveX control). Nothing in OmniSight should need it:

  * ISAPI still-image endpoint  -> /ISAPI/Streaming/channels/101/picture
  * ISAPI continuous MJPEG      -> /ISAPI/Streaming/channels/101/httpPreview
  * PSIA (older firmware)       -> /PSIA/Streaming/channels/101/picture
  * Legacy streaming path       -> /Streaming/Channels/101/picture

All of them are plain HTTP with Digest authentication, which is why the plugin is
never required. These tests verify discovery, Digest auth, real frame delivery and
the RTSP -> plugin-free fallback using a camera that only answers Digest requests.
"""

import hashlib
import io
import os
import re
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from backend.stream_proxy import CameraStreamSession, VENDOR_MJPEG_CANDIDATES, VENDOR_SNAPSHOT_CANDIDATES
from backend.vendor_presets import VENDOR_PRESETS

HIK_USER, HIK_PASSWORD = "admin", "Hik@1234"
HIK_REALM = "IP Camera(Camera 01)"
HIK_NONCE = "dcd98b7102dd2f0e8b11d0f600bfb0c093"


def _jpeg(frame_number=0):
    img = Image.new("RGB", (160, 90), (10, 25, 40))
    ImageDraw.Draw(img).text((5, 5), f"HIK frame {frame_number}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return buf.getvalue()


def _digest_ok(header: str) -> bool:
    """Validates an RFC 2617 Digest response, echoing what Hikvision firmware enforces."""
    if not header or not header.startswith("Digest "):
        return False
    values = {k: (v1 or v2).strip() for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,]+))', header)}

    def md5(text):
        return hashlib.md5(text.encode()).hexdigest()

    ha1 = md5(f"{HIK_USER}:{HIK_REALM}:{HIK_PASSWORD}")
    ha2 = md5(f"GET:{values.get('uri', '')}")
    if values.get("qop"):
        expected = md5(
            f"{ha1}:{values.get('nonce','')}:{values.get('nc','')}:"
            f"{values.get('cnonce','')}:{values['qop']}:{ha2}"
        )
    else:
        expected = md5(f"{ha1}:{values.get('nonce','')}:{ha2}")
    return values.get("username") == HIK_USER and values.get("response") == expected


class FakeHikvisionCamera(BaseHTTPRequestHandler):
    """Only ISAPI / PSIA endpoints answer - everything else 404s, as on real R6 firmware."""

    protocol_version = "HTTP/1.1"
    frame_counter = 0
    requested_paths = []

    def log_message(self, *args):
        pass

    def _challenge(self):
        body = b"<html><body>Please install WebComponents.exe to view this camera.</body></html>"
        self.send_response(401)
        self.send_header("WWW-Authenticate", f'Digest qop="auth", realm="{HIK_REALM}", nonce="{HIK_NONCE}"')
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeHikvisionCamera.requested_paths.append(self.path)
        if not _digest_ok(self.headers.get("Authorization", "")):
            self._challenge()
            return

        path = self.path.split("?")[0]
        if path in (
            "/ISAPI/Streaming/channels/101/picture",
            "/PSIA/Streaming/channels/101/picture",
        ):
            FakeHikvisionCamera.frame_counter += 1
            data = _jpeg(FakeHikvisionCamera.frame_counter)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/ISAPI/Streaming/channels/101/httpPreview":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=boundarydonotcross")
            self.end_headers()
            for n in range(300):
                data = _jpeg(n)
                try:
                    self.wfile.write(
                        b"--boundarydonotcross\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"
                    )
                    self.wfile.flush()
                except Exception:
                    break
                time.sleep(0.05)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


class HikvisionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeHikvisionCamera.requested_paths = []
        cls.camera_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHikvisionCamera)
        cls.camera_port = cls.camera_server.server_address[1]
        threading.Thread(target=cls.camera_server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.camera_server.shutdown()
        cls.camera_server.server_close()

    def hik_camera(self, **overrides):
        """Mirrors the live config: RTSP URL + ISAPI snapshot URL, like the user's DS-2CD."""
        camera = {
            "id": "hik-test",
            "name": "Hikvision DS-2CD2420F-IW",
            "vendor": "hikvision",
            "ip": "127.0.0.1",
            "port": self.camera_port,
            "username": HIK_USER,
            "password": HIK_PASSWORD,
            "channel": 1,
            "stream_url": f"rtsp://{HIK_USER}:{HIK_PASSWORD}@127.0.0.1:554/Streaming/Channels/101",
            "is_simulated": False,
        }
        camera.update(overrides)
        return camera


class TestHikvisionEndpoints(HikvisionTestCase):

    def test_plugin_free_endpoints_are_configured(self):
        self.assertIn("/ISAPI/Streaming/channels/{channel}01/picture", VENDOR_SNAPSHOT_CANDIDATES["hikvision"])
        self.assertIn("/PSIA/Streaming/channels/{channel}01/picture", VENDOR_SNAPSHOT_CANDIDATES["hikvision"])
        self.assertIn("/ISAPI/Streaming/channels/{channel}01/httpPreview", VENDOR_MJPEG_CANDIDATES["hikvision"])

    def test_mjpeg_candidate_urls_target_http_not_rtsp(self):
        session = CameraStreamSession(self.hik_camera(port=554))
        urls = session._mjpeg_candidates()
        self.assertTrue(urls, "Hikvision must offer a plugin-free MJPEG endpoint")
        self.assertIn("/ISAPI/Streaming/channels/101/httpPreview", urls[0])
        self.assertTrue(all(u.startswith("http://") for u in urls), urls)

    def test_rtsp_camera_still_has_plugin_free_fallback(self):
        """A Hikvision camera configured for RTSP must remain ingestible without FFmpeg."""
        session = CameraStreamSession(self.hik_camera())
        self.assertEqual(session.classify_source(), "ffmpeg")
        self.assertTrue(session._snapshot_capable())

    def test_preset_documents_that_no_plugin_is_needed(self):
        quirks = " ".join(VENDOR_PRESETS["hikvision"].get("quirks", [])).lower()
        self.assertIn("webcomponents", quirks)
        self.assertIn("httpPreview".lower(), quirks.replace("httpPreview", "httpPreview".lower()))


class TestHikvisionSnapshotFallback(HikvisionTestCase):

    def test_discovers_isapi_snapshot_endpoint_with_digest_auth(self):
        session = CameraStreamSession(self.hik_camera())
        found = session.discover_snapshot_endpoint(timeout=2.0)
        self.assertIsNotNone(found, "ISAPI snapshot endpoint was not discovered")
        self.assertIn("/ISAPI/Streaming/channels/101/picture", found)
        # Digest auth is mandatory on this camera; discovery must not bypass it
        self.assertTrue(session._working_snapshot_url)

    def test_plugin_free_polling_delivers_real_frames(self):
        session = CameraStreamSession(self.hik_camera(legacy_polling=True))
        session.start()
        try:
            deadline = time.time() + 20
            while time.time() < deadline and not session.get_status()["online"]:
                time.sleep(0.25)
            status = session.get_status()
            self.assertTrue(status["online"], status)
            # A continuous MJPEG endpoint is preferred over single-frame polling
            self.assertIn(status["source_kind"], {"mjpeg", "snapshot"})
            frame = session.get_latest_frame()
            self.assertTrue(frame.startswith(b"\xff\xd8"))
            self.assertNotIn(b"NO IE PLUGIN", frame[:500], "frame is a HUD placeholder, not camera video")
        finally:
            session.stop()


class TestHikvisionMjpeg(HikvisionTestCase):

    def test_mjpeg_endpoint_streams_at_framerate(self):
        """httpPreview is the thing WebComponents.exe consumed - we read it directly."""
        session = CameraStreamSession(self.hik_camera(legacy_polling=True))
        session.start()
        try:
            deadline = time.time() + 20
            while time.time() < deadline and not session.get_status()["online"]:
                time.sleep(0.25)
            self.assertEqual(session.get_status()["source_kind"], "mjpeg")
            self.assertIn("/ISAPI/Streaming/channels/101/httpPreview", session._working_mjpeg_url)

            distinct = set()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                distinct.add(hash(session.get_latest_frame()))
                time.sleep(0.02)
            self.assertGreater(len(distinct), 5, "stream is not delivering successive frames")
        finally:
            session.stop()

    def test_worker_prefers_mjpeg_when_rtsp_is_unavailable(self):
        """With no FFmpeg the camera still becomes live video via ISAPI MJPEG."""
        import backend.stream_proxy as stream_proxy

        session = CameraStreamSession(self.hik_camera())
        original = stream_proxy.FFMPEG_BIN
        stream_proxy.FFMPEG_BIN = None
        try:
            session.start()
            deadline = time.time() + 25
            while time.time() < deadline and not session.get_status()["online"]:
                time.sleep(0.25)
            status = session.get_status()
            self.assertTrue(status["online"], f"never went live: {status}")
            self.assertEqual(status["source_kind"], "mjpeg")
        finally:
            session.stop()
            stream_proxy.FFMPEG_BIN = original

    def test_wrong_password_does_not_claim_success(self):
        """Digest auth must actually be validated - never fall through to a success state."""
        session = CameraStreamSession(self.hik_camera(password="not-the-password"))
        session.start()
        try:
            time.sleep(6)
            status = session.get_status()
            self.assertFalse(status["online"], f"camera claimed online with bad credentials: {status}")
            self.assertNotEqual(status["status"], "streaming")
        finally:
            session.stop()


if __name__ == "__main__":
    unittest.main()
