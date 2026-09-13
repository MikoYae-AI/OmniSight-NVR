"""
OmniSight-NVR - Snapshot and Video Recording Manager
Handles saving stills, managing disk retention, and recording triggers.
"""

import os
import time
import glob
from typing import List, Dict, Any, Optional

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")

os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
os.makedirs(RECORDINGS_DIR, exist_ok=True)


class RecorderManager:
    """Manages captured surveillance artifacts."""

    def __init__(self, stream_manager):
        self.stream_manager = stream_manager
        self.active_recordings: Dict[str, Dict[str, Any]] = {}

    def capture_snapshot(self, camera_id: str, camera_name: str = "") -> Optional[Dict[str, Any]]:
        """Takes a high-res snapshot of the given camera feed and stores it on disk."""
        session = self.stream_manager.get_session(camera_id)
        if not session:
            return None

        jpeg_data = session.get_latest_frame()
        timestamp = int(time.time())
        timestr = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
        filename = f"snap_{camera_id}_{timestr}.jpg"
        filepath = os.path.join(SNAPSHOTS_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(jpeg_data)

        return {
            "id": f"snap-{timestamp}",
            "camera_id": camera_id,
            "camera_name": camera_name or session.camera_info.get("name", "Camera"),
            "filename": filename,
            "path": filepath,
            "url": f"/api/snapshots/{filename}",
            "timestamp": timestamp,
            "size_bytes": len(jpeg_data),
            "date_formatted": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        }

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Returns sorted list of all captured snapshots."""
        items = []
        files = glob.glob(os.path.join(SNAPSHOTS_DIR, "*.jpg"))
        for f in sorted(files, key=os.path.getmtime, reverse=True):
            fname = os.path.basename(f)
            stat = os.stat(f)
            # parse camera_id from snap_cam-id_timestamp.jpg
            parts = fname.replace(".jpg", "").split("_")
            cam_id = parts[1] if len(parts) >= 2 else "unknown"
            items.append({
                "filename": fname,
                "camera_id": cam_id,
                "url": f"/api/snapshots/{fname}",
                "timestamp": int(stat.st_mtime),
                "size_bytes": stat.st_size,
                "date_formatted": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            })
        return items

    def delete_snapshot(self, filename: str) -> bool:
        """Deletes a snapshot file."""
        filepath = os.path.join(SNAPSHOTS_DIR, os.path.basename(filename))
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                return True
            except Exception:
                return False
        return False
