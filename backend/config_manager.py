"""
OmniSight-NVR - Configuration and State Manager
Handles persistence for cameras, groups, layouts, system settings,
and user authentication & sessions.
"""

import os
import json
import uuid
import secrets
import hashlib
import time
import copy
import threading
from typing import Dict, Any, List, Optional, Tuple

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "cameras.json")

DEFAULT_CAMERAS = [
    {
        "id": "cam-hikvision-01",
        "name": "Hikvision DS-2CD Gate",
        "vendor": "hikvision",
        "group": "Perimeter",
        "ip": "192.168.1.101",
        "port": 554,
        "username": "admin",
        "password": "",
        "stream_url": "sim://hikvision_gate",
        "sub_stream_url": "sim://hikvision_gate_sub",
        "channel": 1,
        "is_simulated": True,
        "status": "online",
        "fps": 25,
        "resolution": "1920x1080",
        "ptz": True,
        "notes": "Hikvision 4MP ColorVu Bullet overlooking main entrance."
    },
    {
        "id": "cam-xiongmai-02",
        "name": "Xiongmai XM530 Backyard",
        "vendor": "xiongmai",
        "group": "Backyard",
        "ip": "192.168.1.102",
        "port": 554,
        "username": "admin",
        "password": "",
        "stream_url": "sim://xm_backyard",
        "sub_stream_url": "sim://xm_backyard_sub",
        "channel": 0,
        "is_simulated": True,
        "status": "online",
        "fps": 20,
        "resolution": "1280x720",
        "ptz": False,
        "notes": "Generic Chinese dome camera running Xiongmai HiSilicon firmware."
    },
    {
        "id": "cam-dahua-03",
        "name": "Dahua WizSense Driveway",
        "vendor": "dahua",
        "group": "Driveway",
        "ip": "192.168.1.103",
        "port": 554,
        "username": "admin",
        "password": "admin",
        "stream_url": "sim://dahua_driveway",
        "sub_stream_url": "sim://dahua_driveway_sub",
        "channel": 1,
        "is_simulated": True,
        "status": "online",
        "fps": 30,
        "resolution": "2560x1440",
        "ptz": True,
        "notes": "Dahua WizSense PTZ camera with active deterrence."
    },
    {
        "id": "cam-tapo-04",
        "name": "Tapo C200 Living Room",
        "vendor": "tapo",
        "group": "Indoor",
        "ip": "192.168.1.104",
        "port": 554,
        "username": "admin",
        "password": "",
        "stream_url": "sim://tapo_interior",
        "sub_stream_url": "sim://tapo_interior_sub",
        "channel": 1,
        "is_simulated": True,
        "status": "online",
        "fps": 25,
        "resolution": "1920x1080",
        "ptz": True,
        "notes": "TP-Link Tapo indoor pan/tilt surveillance."
    }
]

DEFAULT_CONFIG = {
    "version": "1.0.0",
    "system_name": "OmniSight-NVR Hub",
    "theme": "dark_gothic",
    "grid_layout": "2x2",
    "cameras": DEFAULT_CAMERAS,
    "groups": ["All", "Perimeter", "Backyard", "Driveway", "Indoor", "Warehouse"],
    "users": [],
    "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
    "recordings_path": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "recordings")),
    "snapshots_path": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))
}

SESSION_TTL_SECONDS = 86400  # 24 hours


class ConfigManager:
    """Thread-safe configuration & security manager."""

    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}  # token -> session_info
        self._load()

    def _hash_password(self, password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
        if salt is None:
            salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return key.hex(), salt.hex()

    def _verify_password(self, password: str, hash_hex: str, salt_hex: str) -> bool:
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return secrets.compare_digest(key.hex(), hash_hex)

    def _load(self):
        with self._lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                except Exception as e:
                    print(f"[ConfigManager] Error reading config, initializing default: {e}")
                    self.data = copy.deepcopy(DEFAULT_CONFIG)
            else:
                self.data = copy.deepcopy(DEFAULT_CONFIG)

            # Ensure users list exists and has default admin account
            users = self.data.get("users", [])
            if not users:
                hash_hex, salt_hex = self._hash_password("admin123")
                self.data["users"] = [{
                    "username": "admin",
                    "password_hash": hash_hex,
                    "salt": salt_hex,
                    "created_at": int(time.time())
                }]

            self._save()

    def _save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)

    # --- Authentication & Session Methods ---

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            users = self.data.get("users", [])
            user = next((u for u in users if u.get("username").lower() == username.lower()), None)
            if not user:
                return None

            if not self._verify_password(password, user["password_hash"], user["salt"]):
                return None

            token = secrets.token_hex(32)
            expires_at = time.time() + SESSION_TTL_SECONDS
            session_info = {
                "token": token,
                "username": user["username"],
                "expires_at": expires_at
            }
            self._sessions[token] = session_info
            return session_info

    def validate_session(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if time.time() > session["expires_at"]:
                del self._sessions[token]
                return None
            return session

    def logout_session(self, token: str) -> bool:
        with self._lock:
            if token in self._sessions:
                del self._sessions[token]
                return True
            return False

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        with self._lock:
            users = self.data.get("users", [])
            user = next((u for u in users if u.get("username").lower() == username.lower()), None)
            if not user:
                return False

            if not self._verify_password(old_password, user["password_hash"], user["salt"]):
                return False

            new_hash_hex, new_salt_hex = self._hash_password(new_password)
            user["password_hash"] = new_hash_hex
            user["salt"] = new_salt_hex
            self._save()
            return True

    def get_google_client_id(self) -> str:
        with self._lock:
            return self.data.get("google_client_id") or os.environ.get("GOOGLE_CLIENT_ID", "")

    def set_google_client_id(self, client_id: str):
        with self._lock:
            self.data["google_client_id"] = client_id.strip()
            self._save()

    def authenticate_google_user(self, email: str, name: str = "", picture: str = "") -> Dict[str, Any]:
        with self._lock:
            users = self.data.setdefault("users", [])
            email_lower = email.strip().lower()
            user = next((u for u in users if u.get("email", "").lower() == email_lower), None)
            
            if not user:
                username_candidate = email_lower.split("@")[0]
                user = next((u for u in users if u.get("username", "").lower() == username_candidate), None)

            if not user:
                user = {
                    "username": email_lower.split("@")[0],
                    "email": email_lower,
                    "name": name or email_lower.split("@")[0],
                    "picture": picture,
                    "auth_type": "google",
                    "created_at": int(time.time())
                }
                users.append(user)
            else:
                user["email"] = email_lower
                if name:
                    user["name"] = name
                if picture:
                    user["picture"] = picture

            self._save()

            token = secrets.token_hex(32)
            expires_at = time.time() + SESSION_TTL_SECONDS
            session_info = {
                "token": token,
                "username": user.get("username", email_lower.split("@")[0]),
                "email": email_lower,
                "name": user.get("name", ""),
                "picture": user.get("picture", ""),
                "auth_type": "google",
                "expires_at": expires_at
            }
            self._sessions[token] = session_info
            return session_info

    # --- Camera & Layout Methods ---

    def get_all_cameras(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.data.get("cameras", []))

    def get_camera(self, camera_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for cam in self.data.get("cameras", []):
                if cam.get("id") == camera_id:
                    return cam
            return None

    def add_camera(self, cam_data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if "id" not in cam_data or not cam_data["id"]:
                cam_data["id"] = f"cam-{uuid.uuid4().hex[:8]}"
            
            cam_data.setdefault("status", "online")
            cam_data.setdefault("fps", 25)
            cam_data.setdefault("resolution", "1920x1080")
            cam_data.setdefault("ptz", False)
            cam_data.setdefault("group", "Default")

            groups = self.data.setdefault("groups", ["All"])
            if cam_data["group"] not in groups and cam_data["group"] != "All":
                groups.append(cam_data["group"])

            self.data.setdefault("cameras", []).append(cam_data)
            self._save()
            return cam_data

    def update_camera(self, camera_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            for i, cam in enumerate(self.data.get("cameras", [])):
                if cam.get("id") == camera_id:
                    cam.update(updates)
                    self.data["cameras"][i] = cam
                    self._save()
                    return cam
            return None

    def delete_camera(self, camera_id: str) -> bool:
        with self._lock:
            cameras = self.data.get("cameras", [])
            initial_len = len(cameras)
            self.data["cameras"] = [c for c in cameras if c.get("id") != camera_id]
            if len(self.data["cameras"]) != initial_len:
                self._save()
                return True
            return False

    def get_layout(self) -> str:
        with self._lock:
            return self.data.get("grid_layout", "2x2")

    def set_layout(self, layout: str):
        with self._lock:
            self.data["grid_layout"] = layout
            self._save()

    def get_groups(self) -> List[str]:
        with self._lock:
            return list(self.data.get("groups", ["All"]))

    def get_full_config(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.data)
