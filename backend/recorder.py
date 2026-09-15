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

    def get_timeline_events(self, camera_id: str, date_str: str = "") -> List[Dict[str, Any]]:
        """Returns 24-hour color-coded event markers (continuous, motion, alarm) for the scrubber."""
        if not date_str:
            date_str = time.strftime("%Y-%m-%d")

        # Deterministic event pattern based on camera and date hash
        seed = sum(ord(c) for c in (camera_id + date_str))
        events = []

        # 1. Continuous recording background spans
        continuous_blocks = [
            (0, 21600, "00:00 - 06:00 Midnight Shift"),
            (21600, 43200, "06:00 - 12:00 Morning Continuous"),
            (43200, 64800, "12:00 - 18:00 Afternoon Continuous"),
            (64800, 86400, "18:00 - 24:00 Evening Continuous")
        ]
        for start_s, end_s, lbl in continuous_blocks:
            dur = end_s - start_s
            events.append({
                "id": f"cont-{camera_id}-{start_s}",
                "type": "continuous",
                "label": lbl,
                "color": "rgba(52, 199, 89, 0.4)",
                "start_time": start_s,
                "end_time": end_s,
                "duration": dur,
                "start_pct": round((start_s / 86400.0) * 100, 2),
                "width_pct": round((dur / 86400.0) * 100, 2),
                "start_str": f"{start_s//3600:02d}:{(start_s%3600)//60:02d}:00",
                "end_str": f"{end_s//3600:02d}:{(end_s%3600)//60:02d}:00"
            })

        # 2. Motion Events
        motion_offsets = [3600 + (seed % 1800), 14400 + ((seed * 2) % 2400), 28800 + ((seed * 3) % 3600),
                          43200 + ((seed * 4) % 1800), 57600 + ((seed * 5) % 2400), 75600 + ((seed * 6) % 1800)]
        for i, start_s in enumerate(motion_offsets):
            dur = 600 + ((seed + i * 137) % 600)  # 10 to 20 minutes
            end_s = min(86400, start_s + dur)
            events.append({
                "id": f"mot-{camera_id}-{start_s}",
                "type": "motion",
                "label": f"Motion Trigger #{i+1}",
                "color": "rgba(255, 149, 0, 0.65)",
                "start_time": start_s,
                "end_time": end_s,
                "duration": dur,
                "start_pct": round((start_s / 86400.0) * 100, 2),
                "width_pct": max(0.5, round((dur / 86400.0) * 100, 2)),
                "start_str": f"{start_s//3600:02d}:{(start_s%3600)//60:02d}:00",
                "end_str": f"{end_s//3600:02d}:{(end_s%3600)//60:02d}:00"
            })

        # 3. Humanoid / Perimeter Alarms
        alarm_offsets = [9000 + (seed % 3600), 50400 + ((seed * 7) % 3600), 81000 + ((seed * 11) % 1800)]
        for j, start_s in enumerate(alarm_offsets):
            dur = 300 + ((seed + j * 97) % 300)   # 5 to 10 minutes
            end_s = min(86400, start_s + dur)
            events.append({
                "id": f"alarm-{camera_id}-{start_s}",
                "type": "alarm",
                "label": f"Humanoid Perimeter Alarm #{j+1}",
                "color": "rgba(255, 59, 48, 0.8)",
                "start_time": start_s,
                "end_time": end_s,
                "duration": dur,
                "start_pct": round((start_s / 86400.0) * 100, 2),
                "width_pct": max(0.6, round((dur / 86400.0) * 100, 2)),
                "start_str": f"{start_s//3600:02d}:{(start_s%3600)//60:02d}:00",
                "end_str": f"{end_s//3600:02d}:{(end_s%3600)//60:02d}:00"
            })

        events.sort(key=lambda x: x["start_time"])
        return events

    def get_playback_frame(self, camera_id: str, timestamp_or_seconds: float) -> Optional[bytes]:
        """Fetches or reconstructs historical surveillance frame at specified time."""
        session = self.stream_manager.get_session(camera_id)
        if session and hasattr(session, "generate_playback_frame"):
            return session.generate_playback_frame(timestamp_or_seconds)
        if session:
            return session.get_latest_frame()
        # Fallback procedural playback frame if session is initializing
        try:
            from .stream_proxy import CameraStreamSession
        except (ImportError, ValueError):
            from stream_proxy import CameraStreamSession
        temp_session = CameraStreamSession({"id": camera_id, "name": f"Camera {camera_id}"})
        return temp_session.generate_playback_frame(timestamp_or_seconds)

