"""
OmniSight-NVR - Configuration and State Manager
Handles persistence for cameras, groups, layouts, and system settings.
"""

import os
import json
import uuid
import threading
from typing import Dict, Any, List, Optional

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
    "recordings_path": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "recordings")),
    "snapshots_path": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))
}


class ConfigManager:
    """Thread-safe configuration manager."""
    
    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self):
        with self._lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                    return
                except Exception as e:
                    print(f"[ConfigManager] Error reading config, initializing default: {e}")
            
            # Write default config
            self.data = DEFAULT_CONFIG
            self._save()

    def _save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)

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

            # Check if group exists, if not append
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
