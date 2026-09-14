"""
Unit tests for OmniSight-NVR 4G Cloud Relay Manager & API Endpoints
"""

import unittest
import json
import urllib.request
import threading
import time
from http.server import ThreadingHTTPServer

from backend.cloud_relay import CloudRelayManager
from backend.server import OmniSightHandler, cloud_relay_manager, config_manager


class TestCloudRelay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8899
        cloud_relay_manager.port = cls.port
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), OmniSightHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

        # Create auth session for protected endpoints
        auth_session = config_manager.authenticate_user("admin", "admin123")
        cls.token = auth_session["token"]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_manager_properties(self):
        crm = CloudRelayManager(8080)
        status = crm.get_status()
        self.assertIn("enabled", status)
        self.assertIn("status", status)
        self.assertIn("local_ip", status)
        self.assertIn("local_url", status)

    def test_get_cloud_relay_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/cloud-relay"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", data)
            self.assertIn("local_url", data)

    def test_toggle_cloud_relay_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/cloud-relay/toggle"
        payload = json.dumps({"enable": False}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data["enabled"])


if __name__ == "__main__":
    unittest.main()
