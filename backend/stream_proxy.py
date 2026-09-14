"""
OmniSight-NVR - Universal Stream Proxy & Procedural CCTV Engine
Handles RTSP ingestion (via ffmpeg when available), HTTP/MJPEG streams,
and procedural CCTV frame synthesis for Hikvision, Dahua, Xiongmai, and generic cameras.
"""

import os
import io
import time
import math
import shutil
import random
import threading
import subprocess
from typing import Dict, Any, Optional, Iterator
from PIL import Image, ImageDraw, ImageFont

FFMPEG_BIN = shutil.which("ffmpeg")


class CameraStreamSession:
    """Manages stream ingestion and client distribution for a single camera."""

    def __init__(self, camera_info: Dict[str, Any]):
        self.camera_info = camera_info
        self.camera_id = camera_info["id"]
        self.stream_url = camera_info.get("stream_url", "")
        self.is_simulated = camera_info.get("is_simulated", False) or self.stream_url.startswith("sim://")
        
        self.active_subscribers = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_jpeg: Optional[bytes] = None
        self._last_frame_time = 0.0
        
        # PTZ State
        self.pan = 0.0     # -180 to 180 degrees
        self.tilt = 0.0    # -90 to 90 degrees
        self.zoom = 1.0    # 1.0x to 10.0x
        
        # Motion State
        self.motion_detected = False
        self.motion_box = None
        self.motion_timer = 0

    def adjust_ptz(self, action: str, step: float = 5.0):
        with self._lock:
            if action == "left":
                self.pan = max(-180.0, self.pan - step)
            elif action == "right":
                self.pan = min(180.0, self.pan + step)
            elif action == "up":
                self.tilt = min(90.0, self.tilt + step)
            elif action == "down":
                self.tilt = max(-90.0, self.tilt - step)
            elif action == "zoom_in":
                self.zoom = min(10.0, round(self.zoom + 0.5, 1))
            elif action == "zoom_out":
                self.zoom = max(1.0, round(self.zoom - 0.5, 1))
            elif action == "home":
                self.pan = 0.0
                self.tilt = 0.0
                self.zoom = 1.0

    def start(self):
        with self._lock:
            if not self._running:
                self._running = True
                self._thread = threading.Thread(target=self._worker_loop, daemon=True, name=f"Stream-{self.camera_id}")
                self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False

    def get_latest_frame(self) -> bytes:
        with self._lock:
            if self._latest_jpeg:
                return self._latest_jpeg
        # Fallback frame if none exists yet
        return self._generate_simulated_frame(0)

    def _worker_loop(self):
        """Dispatches either real RTSP/HTTP or the procedural simulation engine."""
        if not self.is_simulated and FFMPEG_BIN and self.stream_url.startswith("rtsp://"):
            self._ffmpeg_rtsp_loop()
        elif not self.is_simulated and (self.camera_info.get("snapshot_url") or self.camera_info.get("legacy_polling") or self.camera_info.get("ip")):
            self._http_snapshot_polling_loop()
        else:
            self._simulation_loop()

    def _http_snapshot_polling_loop(self):
        """Polls camera HTTP snapshot endpoint with Digest/Basic auth support."""
        ip = self.camera_info.get("ip", "")
        username = self.camera_info.get("username", "admin")
        password = self.camera_info.get("password", "")
        snapshot_url = self.camera_info.get("snapshot_url")
        if not snapshot_url and ip:
            vendor = self.camera_info.get("vendor", "hikvision")
            if vendor in ("hikvision", "hikvision_dvr"):
                snapshot_url = f"http://{ip}/ISAPI/Streaming/channels/101/picture"
            elif vendor == "dahua":
                snapshot_url = f"http://{ip}/cgi-bin/snapshot.cgi?channel=1"
            else:
                snapshot_url = f"http://{ip}/snapshot.jpg"

        if not snapshot_url:
            self._simulation_loop()
            return

        import urllib.request
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        if username and password:
            password_mgr.add_password(None, snapshot_url, username, password)
            password_mgr.add_password(None, f"http://{ip}/", username, password)

        auth_handler = urllib.request.HTTPDigestAuthHandler(password_mgr)
        basic_handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
        opener = urllib.request.build_opener(auth_handler, basic_handler)

        target_fps = max(2, min(15, self.camera_info.get("fps", 10)))
        interval = 1.0 / target_fps
        consecutive_fails = 0

        while self._running:
            t0 = time.time()
            try:
                req = urllib.request.Request(f"{snapshot_url}?t={int(t0 * 1000)}", headers={"User-Agent": "OmniSight/1.0"})
                with opener.open(req, timeout=2.0) as resp:
                    jpeg_bytes = resp.read()
                    if jpeg_bytes and len(jpeg_bytes) > 500:
                        with self._lock:
                            self._latest_jpeg = jpeg_bytes
                            self._last_frame_time = time.time()
                        consecutive_fails = 0
            except Exception as e:
                consecutive_fails += 1
                if consecutive_fails >= 3:
                    # Draw a informative status frame
                    err_text = f"HIKVISION DS-2CD @ {ip}\nAWAITING PASSWORD IN SETTINGS" if not password else f"CONNECTING TO {ip}...\nCHECK PASSWORD / NETWORK"
                    with self._lock:
                        self._latest_jpeg = self._draw_connecting_frame(err_text)
                    time.sleep(1.0)

            elapsed = time.time() - t0
            sleep_time = max(0.05, interval - elapsed)
            time.sleep(sleep_time)

    def _draw_connecting_frame(self, message: str) -> bytes:
        width = 854
        height = 480
        img = Image.new("RGB", (width, height), color=(18, 18, 20))
        draw = ImageDraw.Draw(img)
        # Center status message
        lines = message.split("\n")
        y = height // 2 - (len(lines) * 12)
        for line in lines:
            draw.text((width // 2 - len(line) * 4, y), line, fill=(255, 159, 10))
            y += 24
        draw.text((20, 20), self.camera_info.get("name", "Camera").upper(), fill=(255, 255, 255))
        draw.text((20, height - 30), "OMNISIGHT // STANDALONE PROXY", fill=(100, 110, 130))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    def _simulation_loop(self):
        """Generates procedural surveillance frames with vendor-authentic OSDs."""
        frame_interval = 1.0 / max(10, self.camera_info.get("fps", 25))
        frame_count = 0

        while self._running:
            t0 = time.time()
            frame_count += 1
            jpeg_bytes = self._generate_simulated_frame(frame_count)
            
            with self._lock:
                self._latest_jpeg = jpeg_bytes
                self._last_frame_time = time.time()

            elapsed = time.time() - t0
            sleep_time = max(0.01, frame_interval - elapsed)
            time.sleep(sleep_time)

    def _generate_simulated_frame(self, frame_idx: int) -> bytes:
        """Draws realistic dark surveillance visuals with dynamic overlays."""
        width = 854
        height = 480
        vendor = self.camera_info.get("vendor", "hikvision")
        cam_name = self.camera_info.get("name", "Surveillance Cam")
        
        # Base scene background: deep gothic security canvas
        img = Image.new("RGB", (width, height), color=(12, 14, 18))
        draw = ImageDraw.Draw(img)

        # Draw procedural grid / architectural scene based on vendor / camera group
        t = time.time()
        # Simulated panning offset
        offset_x = int(self.pan * 2)
        offset_y = int(self.tilt * 2)

        # Perspective ground grid
        horizon = height // 2 + offset_y
        draw.line([(0, horizon), (width, horizon)], fill=(30, 36, 46), width=2)
        
        # Grid rays
        for i in range(-5, 15):
            gx = width // 2 + (i * 90) + offset_x
            draw.line([(gx, horizon), (gx * 1.5 - (width * 0.25), height)], fill=(20, 26, 35), width=1)

        # Draw architectural silhouettes (buildings / perimeter fence)
        fence_y = horizon + 30
        for fx in range(-100, width + 100, 40):
            fx_adj = fx + (offset_x % 40)
            draw.line([(fx_adj, fence_y - 25), (fx_adj, fence_y + 40)], fill=(35, 42, 54), width=2)
            draw.line([(fx_adj - 20, fence_y - 15), (fx_adj + 20, fence_y - 15)], fill=(28, 34, 45), width=1)

        # Draw moving target (vehicle / pedestrian / security patrol / feline)
        # Periodically trigger motion box
        cycle = (t * 0.4) % (math.pi * 2)
        target_x = int(width / 2 + math.sin(cycle) * 260 + offset_x)
        target_y = int(horizon + 40 + math.cos(cycle * 0.5) * 20)

        # Target bounding box (AI Detection)
        box_w, box_h = 70, 90
        x1, y1 = target_x - box_w // 2, target_y - box_h // 2
        x2, y2 = x1 + box_w, y1 + box_h

        # Vendor specific HUD colors & styling
        if vendor == "hikvision":
            osd_color = (255, 255, 255) # Classic crisp white Hikvision font
            accent_color = (220, 53, 69) # Red alarm
            ai_color = (255, 193, 7)    # AcuSense Target Gold
            vendor_tag = "HIKVISION DS-2CD • AcuSense AI"
        elif vendor == "dahua":
            osd_color = (240, 240, 240)
            accent_color = (255, 69, 0)
            ai_color = (0, 230, 118)     # Dahua WizSense Green Box
            vendor_tag = "DAHUA WizSense IPC • SMD 4.0"
        elif vendor == "xiongmai":
            osd_color = (0, 255, 0)      # Classic retro green Chinese OSD
            accent_color = (255, 0, 0)
            ai_color = (0, 255, 0)
            vendor_tag = "XM NetSurveillance • HiSilicon H.265+"
        elif vendor == "tapo":
            osd_color = (255, 255, 255)
            accent_color = (0, 150, 255)
            ai_color = (0, 200, 255)
            vendor_tag = "TP-LINK TAPO • Smart AI Tracking"
        else:
            osd_color = (220, 220, 220)
            accent_color = (180, 80, 255)
            ai_color = (180, 80, 255)
            vendor_tag = "OMNISIGHT UNIVERSAL NVR • Protocol Stream"

        # Draw AI motion detection box on target
        draw.rectangle([x1, y1, x2, y2], outline=ai_color, width=2)
        # Target label
        draw.rectangle([x1, y1 - 18, x1 + 65, y1], fill=(15, 18, 24))
        draw.text((x1 + 4, y1 - 16), "OBJECT 98%", fill=ai_color)

        # Crosshairs in center
        cx, cy = width // 2, height // 2
        draw.line([(cx - 15, cy), (cx + 15, cy)], fill=(60, 70, 90), width=1)
        draw.line([(cx, cy - 15), (cx, cy + 15)], fill=(60, 70, 90), width=1)
        draw.arc([cx - 30, cy - 30, cx + 30, cy + 30], start=0, end=360, fill=(40, 48, 62), width=1)

        # Top-Left OSD: Camera Name & Vendor tag
        draw.text((20, 15), cam_name.upper(), fill=osd_color)
        draw.text((20, 32), vendor_tag, fill=(140, 150, 170))
        
        # Real-time Bitrate & Resolution
        kbps = 2048 + int(math.sin(t * 2) * 280)
        draw.text((20, 50), f"{self.camera_info.get('resolution', '1920x1080')}  {self.camera_info.get('fps', 25)} FPS  {kbps} kbps", fill=(100, 120, 140))

        # Top-Right OSD: Dynamic Timestamp & REC Indicator
        time_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(t))
        millis = int((t % 1) * 1000)
        full_time_str = f"{time_str}.{millis:03d}"
        
        # Blinking REC dot
        if int(t * 2) % 2 == 0:
            draw.ellipse([width - 240, 18, width - 228, 30], fill=(230, 40, 40))
            draw.text((width - 222, 16), "REC", fill=(230, 40, 40))

        draw.text((width - 175, 16), full_time_str, fill=osd_color)

        # Bottom-Left OSD: PTZ telemetry
        ptz_str = f"PAN: {self.pan:+06.1f}°  TILT: {self.tilt:+05.1f}°  ZOOM: {self.zoom:.1f}x"
        draw.text((20, height - 35), ptz_str, fill=(140, 150, 170))

        # Bottom-Right OSD: OmniSight Brand watermark
        draw.text((width - 160, height - 35), "OMNISIGHT // SECURE", fill=(70, 80, 100))

        # Scanline effect (subtle gothic monitor overlay)
        for sl in range(0, height, 4):
            draw.line([(0, sl), (width, sl)], fill=(0, 0, 0, 30))

        # Encode to JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    def _ffmpeg_rtsp_loop(self):
        """Ingests live RTSP feed from physical cameras using ffmpeg."""
        cmd = [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", self.stream_url,
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "4",
            "-r", str(self.camera_info.get("fps", 20)),
            "-"
        ]
        
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10**6)
            buffer = bytearray()
            
            while self._running:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                
                # Look for JPEG SOI and EOI markers
                a = buffer.find(b'\xff\xd8')
                b = buffer.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    jpeg_bytes = bytes(buffer[a:b+2])
                    buffer = buffer[b+2:]
                    with self._lock:
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.time()
            
            proc.terminate()
        except Exception as e:
            print(f"[StreamProxy] Error in ffmpeg RTSP loop for {self.camera_id}: {e}")
            # Fallback to simulation
            self._simulation_loop()


class StreamManager:
    """Manages collection of active camera stream sessions."""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.sessions: Dict[str, CameraStreamSession] = {}
        self._lock = threading.Lock()
        self._sync_sessions()

    def _sync_sessions(self):
        with self._lock:
            cameras = self.config_manager.get_all_cameras()
            existing_ids = set(self.sessions.keys())
            current_ids = {c["id"] for c in cameras}

            # Remove obsolete sessions
            for cid in existing_ids - current_ids:
                self.sessions[cid].stop()
                del self.sessions[cid]

            # Add new sessions
            for c in cameras:
                cid = c["id"]
                if cid not in self.sessions:
                    session = CameraStreamSession(c)
                    session.start()
                    self.sessions[cid] = session

    def get_session(self, camera_id: str) -> Optional[CameraStreamSession]:
        with self._lock:
            if camera_id in self.sessions:
                return self.sessions[camera_id]
            cam = self.config_manager.get_camera(camera_id)
            if cam:
                session = CameraStreamSession(cam)
                session.start()
                self.sessions[camera_id] = session
                return session
            return None

    def refresh_cameras(self):
        self._sync_sessions()
