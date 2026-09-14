import unittest
import os
import sys
import tempfile
import json
import urllib.request
import urllib.error
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config_manager import ConfigManager
import backend.server as server_mod


class TestServerAuthEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.config_path = os.path.join(cls.tmp_dir.name, "test_cameras.json")
        server_mod.config_manager = ConfigManager(config_path=cls.config_path)
        cls.port = 8898
        cls.server = server_mod.ThreadingHTTPServer(("127.0.0.1", cls.port), server_mod.OmniSightHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp_dir.cleanup()

    def test_unauthenticated_api_access(self):
        url = f"http://127.0.0.1:{self.port}/api/cameras"
        req = urllib.request.Request(url)
        try:
            urllib.request.urlopen(req)
            self.fail("Should have raised HTTPError 401")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_login_and_authenticated_api_access(self):
        login_url = f"http://127.0.0.1:{self.port}/api/auth/login"
        data = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
        req = urllib.request.Request(login_url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res_data["status"], "ok")
            token = res_data["token"]

        # Access protected endpoint with Bearer token
        cam_url = f"http://127.0.0.1:{self.port}/api/cameras"
        auth_req = urllib.request.Request(cam_url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(auth_req) as resp:
            self.assertEqual(resp.status, 200)
            cams_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("cameras", cams_data)


if __name__ == "__main__":
    unittest.main()
