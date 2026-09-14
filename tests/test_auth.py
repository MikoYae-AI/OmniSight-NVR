import unittest
import os
import sys
import tempfile
import json
import time

# Ensure backend module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config_manager import ConfigManager


class TestAuthAndConfigManager(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp_dir.name, "test_cameras.json")
        self.config_mgr = ConfigManager(config_path=self.config_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_default_admin_created(self):
        session = self.config_mgr.authenticate_user("admin", "admin123")
        self.assertIsNotNone(session)
        self.assertEqual(session["username"], "admin")
        self.assertIn("token", session)

    def test_invalid_login(self):
        session = self.config_mgr.authenticate_user("admin", "wrongpassword")
        self.assertIsNone(session)

        session_nonexistent = self.config_mgr.authenticate_user("nonexistent", "admin123")
        self.assertIsNone(session_nonexistent)

    def test_session_validation_and_logout(self):
        session = self.config_mgr.authenticate_user("admin", "admin123")
        token = session["token"]

        validated = self.config_mgr.validate_session(token)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["username"], "admin")

        # Logout
        logged_out = self.config_mgr.logout_session(token)
        self.assertTrue(logged_out)

        # Validate after logout
        self.assertIsNone(self.config_mgr.validate_session(token))

    def test_change_password(self):
        # Change password
        changed = self.config_mgr.change_password("admin", "admin123", "newsecret456")
        self.assertTrue(changed)

        # Old password fails
        self.assertIsNone(self.config_mgr.authenticate_user("admin", "admin123"))

        # New password succeeds
        session = self.config_mgr.authenticate_user("admin", "newsecret456")
        self.assertIsNotNone(session)


if __name__ == "__main__":
    unittest.main()
