"""
Tests for Hub deep-linking via query parameters and multi-camera matrix defaults.
"""

import os
import re
import unittest
from backend.config_manager import DEFAULT_CAMERAS, ConfigManager
from backend.cloud_relay import CloudRelayManager

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(REPO_ROOT, "static", "js", "app.js")


class TestHubDeeplinkAndMulticam(unittest.TestCase):
    def test_default_cameras_multicam_matrix(self):
        """Ensure DEFAULT_CAMERAS provides a robust multi-camera matrix (> 4 cameras)."""
        self.assertGreaterEqual(len(DEFAULT_CAMERAS), 6)
        vendors = {c["vendor"] for c in DEFAULT_CAMERAS}
        self.assertIn("hikvision", vendors)
        self.assertIn("xiongmai", vendors)
        self.assertIn("dahua", vendors)
        self.assertIn("tapo", vendors)
        self.assertIn("gatocam", vendors)
        self.assertIn("usb_webcam", vendors)

    def test_client_fallback_cameras_multicam(self):
        """Ensure DEFAULT_CLIENT_CAMERAS in app.js provides multiple simulated streams for standalone mode."""
        with open(APP_JS, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"const DEFAULT_CLIENT_CAMERAS = \[([\s\S]*?)\];", content)
        self.assertIsNotNone(match, "DEFAULT_CLIENT_CAMERAS array must be defined in app.js")
        
        # Check that we have at least 6 camera definitions
        id_matches = re.findall(r'id:\s*"([^"]+)"', match.group(1))
        self.assertGreaterEqual(len(id_matches), 6)

        # Check that ?hub= query param handling is present
        self.assertIn('urlParams.get("hub")', content)
        self.assertIn('localStorage.setItem("omnisight_hub_url"', content)

    def test_cloud_relay_hosted_link(self):
        """Verify CloudRelayManager produces the correct deep-link URL for GitHub Pages."""
        crm = CloudRelayManager(port=8080)
        crm.cloud_url = "https://quick-tunnel-123.trycloudflare.com"
        crm.status = "connected"
        status = crm.get_status()
        self.assertEqual(
            status["hosted_url"],
            "https://mikoyae-ai.github.io/OmniSight-NVR/?hub=https://quick-tunnel-123.trycloudflare.com"
        )


if __name__ == "__main__":
    unittest.main()
