"""
Tests for Universal Camera Prober, Preset Database, System Webcams, and Browser Node Ingestion
"""

import unittest
from backend.vendor_presets import VENDOR_PRESETS, build_stream_url, detect_vendor_by_ports
from backend.discovery import probe_camera_connection, list_system_webcams
from backend.config_manager import ConfigManager
from backend.stream_proxy import StreamManager, CameraStreamSession


class TestUniversalCameraEngine(unittest.TestCase):

    def test_vendor_presets_catalog(self):
        """Verify presence of key commercial, consumer, DVR, and DIY camera brands."""
        required_brands = [
            "hikvision", "dahua", "amcrest", "uniview", "axis", "hanwha", "bosch",
            "sony", "panasonic", "vivotek", "foscam", "reolink", "tapo", "kasa",
            "wyze", "eufy", "tuya", "yoosee", "v380", "v360", "srihome", "dlink",
            "unifi", "milesight", "mobotix", "xiongmai", "gatocam", "hikvision_dvr",
            "xiongmai_dvr", "zosi_dvr", "esp32_cam", "raspberry_pi", "ip_webcam",
            "usb_webcam", "browser_node", "generic_onvif", "generic_rtsp", "simulated",
            "icsee", "ezviz", "imou"
        ]
        for brand in required_brands:
            self.assertIn(brand, VENDOR_PRESETS, f"Brand {brand} must be in VENDOR_PRESETS")
            preset = VENDOR_PRESETS[brand]
            self.assertTrue(preset.get("name"), f"Preset {brand} must have a name")

    def test_build_stream_url_patterns(self):
        """Verify URL generation for diverse camera vendors."""
        # Amcrest (Dahua syntax)
        amc_url = build_stream_url("amcrest", "192.168.1.50", 554, "admin", "secret", channel=1)
        self.assertEqual(amc_url, "rtsp://admin:secret@192.168.1.50:554/cam/realmonitor?channel=1&subtype=0")

        # Uniview
        unv_url = build_stream_url("uniview", "192.168.1.60", 554, "admin", "123456", channel=2)
        self.assertEqual(unv_url, "rtsp://admin:123456@192.168.1.60:554/unicast/c2/s0/live")

        # Axis
        axis_url = build_stream_url("axis", "192.168.1.70", 554, "root", "pass")
        self.assertIn("/axis-media/media.amp?videocodec=h264", axis_url)

        # Tapo
        tapo_url = build_stream_url("tapo", "192.168.1.80", 554, "user", "pass")
        self.assertEqual(tapo_url, "rtsp://user:pass@192.168.1.80:554/stream1")

        # Reolink (padded channel)
        reo_url = build_stream_url("reolink", "192.168.1.90", 554, "admin", "pass", channel=1)
        self.assertEqual(reo_url, "rtsp://admin:pass@192.168.1.90:554/h264Preview_01_main")

        # ESP32-CAM HTTP MJPEG
        esp_url = build_stream_url("esp32_cam", "192.168.1.100", 81)
        self.assertEqual(esp_url, "http://192.168.1.100:81/stream")

        # USB Webcam
        usb_url = build_stream_url("usb_webcam", "0", custom_path="Integrated Camera")
        self.assertEqual(usb_url, "webcam://Integrated Camera")

        # Browser Node
        node_url = build_stream_url("browser_node", "node-1", custom_path="node-1")
        self.assertEqual(node_url, "node://node-1")

    def test_detect_vendor_by_signature_ports(self):
        """Verify signature port detection."""
        self.assertEqual(detect_vendor_by_ports([37777, 80])["preset_id"], "dahua")
        self.assertEqual(detect_vendor_by_ports([34567, 554])["preset_id"], "xiongmai")
        self.assertEqual(detect_vendor_by_ports([8000, 554])["preset_id"], "hikvision")
        self.assertEqual(detect_vendor_by_ports([2020])["preset_id"], "tapo")
        self.assertEqual(detect_vendor_by_ports([7447])["preset_id"], "unifi")
        self.assertEqual(detect_vendor_by_ports([4747])["preset_id"], "ip_webcam")

    def test_probe_simulated_shortcut(self):
        """Verify simulator prober shortcut."""
        res = probe_camera_connection("127.0.0.1", vendor_hint="simulated")
        self.assertTrue(res["success"])
        self.assertEqual(res["detected_vendor"], "simulated")
        self.assertTrue(res["stream_url"].startswith("sim://"))

    def test_list_system_webcams(self):
        """Verify enumeration of host webcams."""
        cams = list_system_webcams()
        self.assertIsInstance(cams, list)
        self.assertTrue(len(cams) >= 1)
        self.assertTrue("stream_url" in cams[0])

    def test_browser_node_push_frame(self):
        """Verify browser camera node frame pushing."""
        cam_info = {
            "id": "cam-browser-node",
            "name": "Phone Camera Node",
            "vendor": "browser_node",
            "stream_url": "node://cam-browser-node",
            "is_simulated": False
        }
        session = CameraStreamSession(cam_info)
        session.start()
        try:
            # Generate dummy JPEG bytes
            dummy_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"
            pushed = session.push_frame(dummy_jpeg)
            self.assertTrue(pushed)
            latest = session.get_latest_frame()
            self.assertEqual(latest, dummy_jpeg)
            self.assertEqual(session.connection_status, "streaming")
        finally:
            session.stop()

    def test_ptz_hardware_dispatch(self):
        """Verify PTZ hardware protocol dispatching doesn't crash on invalid/offline endpoints."""
        cam_info = {
            "id": "cam-test-ptz",
            "name": "PTZ Test Cam",
            "vendor": "hikvision",
            "ip": "127.0.0.1",
            "stream_url": "sim://test",
            "is_simulated": True
        }
        session = CameraStreamSession(cam_info)
        # Testing simulated adjusts
        session.adjust_ptz("left")
        self.assertLess(session.pan, 0)
        session.adjust_ptz("up")
        self.assertGreater(session.tilt, 0)
        session.adjust_ptz("home")
        self.assertEqual(session.pan, 0.0)
        self.assertEqual(session.tilt, 0.0)

        # Dispatch hardware PTZ (mock offline target should fail silently)
        session.camera_info["vendor"] = "dahua"
        session._dispatch_hardware_ptz("left")
        session.camera_info["vendor"] = "hikvision"
        session._dispatch_hardware_ptz("right")
        session.camera_info["vendor"] = "axis"
        session._dispatch_hardware_ptz("zoom_in")
        session.camera_info["vendor"] = "foscam"
        session._dispatch_hardware_ptz("up")


class TestUniversalEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        import backend.server as server_mod
        from backend.server import OmniSightHandler

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OmniSightHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

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

    def test_api_system_webcams(self):
        """Verify GET /api/system/webcams returns webcam list."""
        import urllib.request
        import json

        url = f"http://127.0.0.1:{self.port}/api/system/webcams"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.auth_token}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIsInstance(data, list)
            self.assertTrue(len(data) >= 1)

    def test_api_cameras_probe(self):
        """Verify POST /api/cameras/probe with simulated vendor hint."""
        import urllib.request
        import json

        url = f"http://127.0.0.1:{self.port}/api/cameras/probe"
        payload = json.dumps({"ip": "127.0.0.1", "vendor": "simulated"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=self.headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("detected_vendor"), "simulated")
            self.assertTrue(data.get("stream_url", "").startswith("sim://"))

    def test_api_cameras_ingest(self):
        """Verify POST /api/cameras/<id>/ingest frame ingestion."""
        import urllib.request
        import json
        import base64
        import backend.server as server_mod

        # Register camera first
        cam_payload = {
            "id": "node-test-ingest",
            "name": "Node Ingest Test",
            "vendor": "browser_node",
            "stream_url": "node://node-test-ingest",
            "is_simulated": False
        }
        server_mod.config_manager.add_camera(cam_payload)
        server_mod.stream_manager.refresh_cameras()

        try:
            url = f"http://127.0.0.1:{self.port}/api/cameras/node-test-ingest/ingest"
            dummy_b64 = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9").decode()
            body = json.dumps({"frame_base64": dummy_b64}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=self.headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertEqual(data.get("status"), "ok")
                self.assertGreater(data.get("bytes", 0), 100)
        finally:
            server_mod.config_manager.delete_camera("node-test-ingest")
            server_mod.stream_manager.refresh_cameras()

    def test_v360_qianniao_cfeo_preset(self):
        """Verify V360 Pro preset tailored for Shenzhen Qianniao Xiangyun Technology / CFEO models."""
        from backend.vendor_presets import VENDOR_PRESETS, build_stream_url, detect_vendor_by_ports
        v360 = VENDOR_PRESETS.get("v360")
        self.assertIsNotNone(v360)
        self.assertIn("Qianniao Xiangyun", v360["name"])
        self.assertEqual(v360["brand"], "Shenzhen Qianniao Xiangyun Technology")
        self.assertEqual(v360["default_credentials"]["username"], "admin")
        self.assertEqual(v360["default_credentials"]["password"], "")
        
        # Test RTSP URL generation on port 554
        url_main = build_stream_url("v360", "192.168.1.99", 554, "admin", "", channel=1, stream_type="main")
        self.assertEqual(url_main, "rtsp://admin@192.168.1.99:554/live/ch0")

        # Test RTSP URL generation on port 8554 (/profile0)
        url_alt = build_stream_url("v360", "192.168.1.99", 8554, "admin", "", channel=1, stream_type="alt8554")
        self.assertEqual(url_alt, "rtsp://admin@192.168.1.99:8554/profile0")

        # Signature port tests
        det_6688 = detect_vendor_by_ports([6688])
        self.assertEqual(det_6688["preset_id"], "v360")
        det_8554 = detect_vendor_by_ports([8554])
        self.assertEqual(det_8554["preset_id"], "v360")

    def test_dual_html_synchronization(self):
        """Verify root index.html and static/index.html are strictly bit-for-bit identical."""
        with open("index.html", "rb") as f1, open("static/index.html", "rb") as f2:
            self.assertEqual(f1.read(), f2.read(), "index.html and static/index.html must be identical!")


if __name__ == "__main__":
    unittest.main()

