"""
OmniSight-NVR - Universal Stream Proxy & Procedural CCTV Engine
Handles RTSP/RTSPS/RTMP/HLS ingestion via FFmpeg with automatic transport fallbacks (TCP->UDP->HTTP),
resilient auto-reconnect, local USB/DirectShow webcam ingestion, browser camera node uploading,
HTTP/MJPEG snapshot polling, and procedural CCTV frame synthesis.
"""

import os
import io
import time
import math
import shutil
import random
import threading
import subprocess
import urllib.request
import urllib.parse
import re
from typing import Dict, Any, Optional, Iterator
from PIL import Image, ImageDraw, ImageFont

FFMPEG_BIN = shutil.which("ffmpeg")


class CameraStreamSession:
    """Manages stream ingestion, hardware PTZ, and client distribution for a single camera."""

    def __init__(self, camera_info: Dict[str, Any]):
        self.camera_info = camera_info
        self.camera_id = camera_info["id"]
        self.stream_url = camera_info.get("stream_url", "")
        self.is_simulated = (
            camera_info.get("is_simulated", False) or
            self.stream_url.startswith("sim://")
        )
        
        self.active_subscribers = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_jpeg: Optional[bytes] = None
        self._last_frame_time = 0.0
        self.connection_status = "idle"  # idle, connecting, streaming, reconnecting, error
        self.reconnect_count = 0
        
        # PTZ State (Virtual coordinates + Hardware Tracking)
        self.pan = 0.0     # -180 to 180 degrees
        self.tilt = 0.0    # -90 to 90 degrees
        self.zoom = 1.0    # 1.0x to 10.0x
        
        # Motion State
        self.motion_detected = False
        self.motion_box = None
        self.motion_timer = 0

        # Smart Camera Controls (Night Vision, Siren, Intercom, Auto-Tracking)
        self.night_vision = "auto"  # auto, color, ir, smart
        self.siren_active = False
        self.intercom_active = False
        self.auto_tracking = False
        self.audio_bytes_sent = 0
        self.last_audio_tx = 0.0
        self.presets = {
            1: {"pan": 0.0, "tilt": 0.0, "zoom": 1.0},
            2: {"pan": 45.0, "tilt": 15.0, "zoom": 1.5},
            3: {"pan": -45.0, "tilt": -10.0, "zoom": 2.0}
        }

    def push_frame(self, jpeg_bytes: bytes) -> bool:
        """Allows external sources (e.g. Browser Camera Node or local webcam) to push frames."""
        if not jpeg_bytes or len(jpeg_bytes) < 100:
            return False
        with self._lock:
            self._latest_jpeg = jpeg_bytes
            self._last_frame_time = time.time()
            self.connection_status = "streaming"
        return True

    def set_night_vision(self, mode: str):
        with self._lock:
            if mode in ("auto", "color", "ir", "smart"):
                self.night_vision = mode

    def trigger_siren(self, duration: float = 3.0):
        with self._lock:
            self.siren_active = True
        def _stop():
            time.sleep(duration)
            with self._lock:
                self.siren_active = False
        threading.Thread(target=_stop, daemon=True).start()

    def set_intercom(self, active: bool):
        with self._lock:
            self.intercom_active = bool(active)

    def set_auto_tracking(self, enabled: bool):
        with self._lock:
            self.auto_tracking = bool(enabled)

    def receive_audio_chunk(self, audio_data: bytes, audio_format: str = "webm") -> Dict[str, Any]:
        with self._lock:
            self.intercom_active = True
            self.last_audio_tx = time.time()
            self.audio_bytes_sent += len(audio_data)

        ip = self.camera_info.get("ip", "")
        if ip and not self.is_simulated:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(0.2)
                talkback_port = int(self.camera_info.get("talkback_port", 8800))
                sock.sendto(audio_data, (ip, talkback_port))
                sock.close()
            except Exception:
                pass

        return {
            "status": "ok",
            "camera_id": self.camera_id,
            "bytes_received": len(audio_data),
            "total_bytes_sent": self.audio_bytes_sent,
            "timestamp": time.time()
        }

    def save_preset(self, num: int):
        with self._lock:
            self.presets[int(num)] = {
                "pan": self.pan,
                "tilt": self.tilt,
                "zoom": self.zoom
            }

    def goto_preset(self, num: int):
        with self._lock:
            p = self.presets.get(int(num))
            if p:
                self.pan = p["pan"]
                self.tilt = p["tilt"]
                self.zoom = p["zoom"]

    def adjust_ptz(self, action: str, step: float = 5.0):
        """Updates internal PTZ telemetry and dispatches native hardware PTZ commands to physical camera."""
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
            elif action.startswith("preset_"):
                try:
                    num = int(action.split("_")[1])
                    p = self.presets.get(num)
                    if p:
                        self.pan = p["pan"]
                        self.tilt = p["tilt"]
                        self.zoom = p["zoom"]
                except (IndexError, ValueError):
                    pass
            elif action.startswith("save_"):
                try:
                    num = int(action.split("_")[1])
                    self.presets[num] = {"pan": self.pan, "tilt": self.tilt, "zoom": self.zoom}
                except (IndexError, ValueError):
                    pass

        # Dispatch native hardware command in background if camera has physical IP
        ip = self.camera_info.get("ip", "")
        if ip and not self.is_simulated and not ip.startswith("127."):
            threading.Thread(target=self._dispatch_hardware_ptz, args=(action,), daemon=True).start()

    def _dispatch_hardware_ptz(self, action: str):
        """Sends native vendor PTZ commands (Hikvision ISAPI, Dahua CGI, Axis VAPIX, etc.)."""
        ip = self.camera_info.get("ip", "")
        vendor = self.camera_info.get("vendor", "")
        channel = self.camera_info.get("channel", 1)
        username = self.camera_info.get("username", "admin")
        password = self.camera_info.get("password", "")

        try:
            # 1. Dahua & Amcrest PTZ CGI
            if vendor in ("dahua", "amcrest"):
                dahua_codes = {
                    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
                    "zoom_in": "ZoomTele", "zoom_out": "ZoomWide"
                }
                code = dahua_codes.get(action)
                if code:
                    url = f"http://{ip}/cgi-bin/ptz.cgi?action=start&channel={channel}&code={code}&arg1=0&arg2=5&arg3=0"
                    self._send_authenticated_http(url, username, password)
                    time.sleep(0.3)
                    stop_url = f"http://{ip}/cgi-bin/ptz.cgi?action=stop&channel={channel}&code={code}&arg1=0&arg2=5&arg3=0"
                    self._send_authenticated_http(stop_url, username, password)

            # 2. Hikvision ISAPI PTZ
            elif vendor in ("hikvision", "hikvision_dvr"):
                isapi_pan = 0
                isapi_tilt = 0
                if action == "left": isapi_pan = -60
                elif action == "right": isapi_pan = 60
                elif action == "up": isapi_tilt = 60
                elif action == "down": isapi_tilt = -60

                if isapi_pan != 0 or isapi_tilt != 0:
                    xml = f"""<PTZData><pan>{isapi_pan}</pan><tilt>{isapi_tilt}</tilt></PTZData>"""
                    url = f"http://{ip}/ISAPI/PTZCtrl/channels/{channel}/continuous"
                    self._send_authenticated_http(url, username, password, method="PUT", data=xml.encode("utf-8"), content_type="application/xml")
                    time.sleep(0.4)
                    stop_xml = """<PTZData><pan>0</pan><tilt>0</tilt></PTZData>"""
                    self._send_authenticated_http(url, username, password, method="PUT", data=stop_xml.encode("utf-8"), content_type="application/xml")

            # 3. Axis VAPIX PTZ
            elif vendor == "axis":
                axis_params = {
                    "left": "continuouspantiltmove=-50,0", "right": "continuouspantiltmove=50,0",
                    "up": "continuouspantiltmove=0,50", "down": "continuouspantiltmove=0,-50",
                    "zoom_in": "continuouszoommove=50", "zoom_out": "continuouszoommove=-50"
                }
                param = axis_params.get(action)
                if param:
                    url = f"http://{ip}/axis-cgi/com/ptz.cgi?{param}"
                    self._send_authenticated_http(url, username, password)
                    time.sleep(0.3)
                    self._send_authenticated_http(f"http://{ip}/axis-cgi/com/ptz.cgi?continuouspantiltmove=0,0&continuouszoommove=0", username, password)

            # 4. Foscam CGI
            elif vendor == "foscam":
                foscam_cmds = {
                    "left": "ptzMoveLeft", "right": "ptzMoveRight", "up": "ptzMoveUp", "down": "ptzMoveDown"
                }
                cmd = foscam_cmds.get(action)
                if cmd:
                    url = f"http://{ip}/cgi-bin/CGIProxy.fcgi?cmd={cmd}&usr={username}&pwd={password}"
                    self._send_authenticated_http(url, username, password)
                    time.sleep(0.3)
                    self._send_authenticated_http(f"http://{ip}/cgi-bin/CGIProxy.fcgi?cmd=ptzStopRun&usr={username}&pwd={password}", username, password)
        except Exception:
            pass

    def _send_authenticated_http(self, url: str, username: str, password: str, method: str = "GET", data: Optional[bytes] = None, content_type: str = "text/plain"):
        """Lightweight HTTP helper with Digest & Basic Auth for hardware camera controls."""
        try:
            pwd_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            pwd_mgr.add_password(None, url, username, password or "")
            auth_h = urllib.request.HTTPDigestAuthHandler(pwd_mgr)
            basic_h = urllib.request.HTTPBasicAuthHandler(pwd_mgr)
            opener = urllib.request.build_opener(auth_h, basic_h)
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "OmniSight/1.0", "Content-Type": content_type}, method=method)
            with opener.open(req, timeout=1.5):
                pass
        except Exception:
            pass

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
        return self._generate_simulated_frame(0)

    def _worker_loop(self):
        """Universal Dispatcher: FFmpeg (RTSP/RTMP/HLS), USB Webcam, Browser Node, HTTP Snapshot, or Simulator."""
        ip = self.camera_info.get("ip", "")
        vendor = self.camera_info.get("vendor", "")

        # 1. Local USB / DirectShow Webcam
        if self.stream_url.startswith("webcam://") or vendor == "usb_webcam":
            if FFMPEG_BIN:
                self._ffmpeg_webcam_loop()
            else:
                self._simulation_loop()
            return

        # 2. Browser Camera Node (Phone or Laptop streaming to NVR)
        if self.stream_url.startswith("node://") or vendor == "browser_node":
            self._browser_node_loop()
            return

        # 3. Live Stream Feeds (RTSP, RTSPS, RTMP, HLS .m3u8, or HTTP-FLV)
        is_stream_feed = any(self.stream_url.startswith(p) for p in ("rtsp://", "rtsps://", "rtmp://", "rtmps://")) or self.stream_url.endswith(".m3u8")
        if not self.is_simulated and FFMPEG_BIN and is_stream_feed:
            self._ffmpeg_universal_stream_loop()
            return

        # 4. HTTP Snapshot Polling (Direct camera picture polling with zero IE or ActiveX)
        if (not self.is_simulated or (ip and not self.stream_url.startswith("sim://"))) and (
            self.camera_info.get("snapshot_url") or self.camera_info.get("legacy_polling") or ip
        ):
            self._http_snapshot_polling_loop()
            return

        # 5. Fallback: Procedural Surveillance Simulation Engine
        self._simulation_loop()

    def _browser_node_loop(self):
        """Maintains state for a browser camera node; draws placeholder if waiting for frames."""
        self.connection_status = "connecting"
        while self._running:
            now = time.time()
            if self._latest_jpeg and (now - self._last_frame_time < 5.0):
                self.connection_status = "streaming"
                time.sleep(0.1)
            else:
                self.connection_status = "connecting"
                msg = f"BROWSER CAMERA NODE READY\nAWAITING STREAM FROM DEVICE\n{self.camera_info.get('name', 'Camera')}"
                with self._lock:
                    self._latest_jpeg = self._draw_connecting_frame(msg, status_color=(0, 200, 255))
                time.sleep(1.0)

    def _ffmpeg_webcam_loop(self):
        """Captures video from physical USB webcams via DirectShow (Windows) or V4L2 (Linux)."""
        device_arg = self.stream_url.replace("webcam://", "").strip() or "0"
        fps = str(self.camera_info.get("fps", 20))

        if os.name == "nt":
            # Windows DirectShow
            # If numeric, wrap in video="<num>" or default name
            if device_arg == "0":
                device_spec = "video=Integrated Camera"
            else:
                device_spec = f"video={device_arg}"
            input_args = ["-f", "dshow", "-i", device_spec]
        else:
            # Linux V4L2
            input_args = ["-f", "v4l2", "-i", device_arg if device_arg.startswith("/dev/") else f"/dev/video{device_arg}"]

        cmd = [
            FFMPEG_BIN,
            "-hide_banner",
            "-loglevel", "error",
            *input_args,
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "4",
            "-r", fps,
            "-"
        ]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**6)
            buffer = bytearray()
            while self._running:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                a = buffer.find(b'\xff\xd8')
                b = buffer.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    jpeg_bytes = bytes(buffer[a:b+2])
                    buffer = buffer[b+2:]
                    with self._lock:
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.time()
                        self.connection_status = "streaming"
            proc.terminate()
        except Exception:
            pass
        self._simulation_loop()

    def _ffmpeg_universal_stream_loop(self):
        """
        Universal Stream Ingestion Engine with Dynamic Transport Fallback & Resilient Auto-Reconnect.
        Tries TCP -> UDP -> HTTP tunneling. On disconnect, never permanently degrades to simulation;
        instead it draws a clean reconnecting overlay and restores the live feed automatically.
        """
        transports = ["tcp", "udp", "http"]
        current_transport_idx = 0
        backoff = 1.0

        while self._running:
            transport = transports[current_transport_idx % len(transports)]
            self.connection_status = "connecting"
            fps = str(self.camera_info.get("fps", 20))

            cmd = [
                FFMPEG_BIN,
                "-hide_banner",
                "-loglevel", "error",
                "-rtsp_transport", transport,
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-strict", "experimental",
                "-probesize", "1000000",
                "-analyzeduration", "1000000",
                "-i", self.stream_url,
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-q:v", "4",
                "-r", fps,
                "-"
            ]

            proc = None
            t_connect_start = time.time()
            frames_received = 0

            try:
                # Pass stderr=subprocess.DEVNULL to prevent pipe buffer deadlock!
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**6)
                buffer = bytearray()

                while self._running:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    buffer.extend(chunk)

                    # Guard against runaway memory growth on corrupt stream data
                    if len(buffer) > 2 * 1024 * 1024:
                        buffer = buffer[-512 * 1024:]

                    a = buffer.find(b'\xff\xd8')
                    b = buffer.find(b'\xff\xd9')
                    if a != -1 and b != -1 and b > a:
                        jpeg_bytes = bytes(buffer[a:b+2])
                        buffer = buffer[b+2:]
                        frames_received += 1
                        with self._lock:
                            self._latest_jpeg = jpeg_bytes
                            self._last_frame_time = time.time()
                            self.connection_status = "streaming"
                            self.reconnect_count = 0
                        backoff = 1.0

            except Exception:
                pass
            finally:
                if proc:
                    try:
                        proc.terminate()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass

            if not self._running:
                break

            # If stream failed very quickly without receiving frames, switch transport protocol
            session_duration = time.time() - t_connect_start
            if frames_received < 5:
                current_transport_idx += 1

            self.reconnect_count += 1
            self.connection_status = "reconnecting"

            # Display authentic reconnecting HUD overlay
            ip = self.camera_info.get("ip", "")
            cam_name = self.camera_info.get("name", "Camera")
            reconnect_msg = (
                f"{cam_name.upper()} @ {ip or 'STREAM'}\n"
                f"SIGNAL LOST • AUTO-RECONNECTING (TRY {self.reconnect_count})...\n"
                f"PROTOCOL: RTSP/{transport.upper()}"
            )
            with self._lock:
                self._latest_jpeg = self._draw_connecting_frame(reconnect_msg, status_color=(255, 159, 10))

            time.sleep(backoff)
            backoff = min(5.0, backoff * 1.5)

    def _http_snapshot_polling_loop(self):
        """Polls camera HTTP snapshot endpoint with Digest/Basic auth support and auto-reconnect."""
        ip = self.camera_info.get("ip", "")
        username = self.camera_info.get("username", "admin")
        password = self.camera_info.get("password", "")
        snapshot_url = self.camera_info.get("snapshot_url")
        vendor = self.camera_info.get("vendor", "hikvision")

        if not snapshot_url and ip:
            if vendor in ("hikvision", "hikvision_dvr"):
                snapshot_url = f"http://{ip}/ISAPI/Streaming/channels/101/picture"
            elif vendor in ("dahua", "amcrest"):
                snapshot_url = f"http://{ip}/cgi-bin/snapshot.cgi?channel=1"
            elif vendor in ("gatocam", "xiongmai"):
                snapshot_url = f"http://{ip}/snapshot.jpg"
            elif vendor == "axis":
                snapshot_url = f"http://{ip}/jpg/image.jpg"
            elif vendor == "reolink":
                snapshot_url = f"http://{ip}/cgi-bin/api.cgi?cmd=Snap&channel=01&user={username}&password={password}"
            elif vendor == "esp32_cam":
                snapshot_url = f"http://{ip}/capture"
            elif vendor == "ip_webcam":
                snapshot_url = f"http://{ip}:8080/shot.jpg"
            else:
                snapshot_url = f"http://{ip}/snapshot.jpg"

        if not snapshot_url:
            self._simulation_loop()
            return

        try:
            parsed = urllib.parse.urlparse(snapshot_url)
            if parsed.username:
                username = parsed.username
            if parsed.password:
                password = parsed.password
            
            port_str = f":{parsed.port}" if parsed.port and parsed.port != 80 else ""
            clean_host = parsed.hostname or ip
            clean_path = parsed.path or "/snapshot.jpg"
            clean_url = f"{parsed.scheme or 'http'}://{clean_host}{port_str}{clean_path}"
        except Exception:
            clean_url = re.sub(r'://[^@]+@', '://', snapshot_url)

        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        if username:
            password_mgr.add_password(None, clean_url, username, password or "")
            if ip:
                password_mgr.add_password(None, f"http://{ip}/", username, password or "")
                password_mgr.add_password(None, f"http://{ip}:80/", username, password or "")
                password_mgr.add_password(None, f"http://{ip}:8080/", username, password or "")

        auth_handler = urllib.request.HTTPDigestAuthHandler(password_mgr)
        basic_handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
        opener = urllib.request.build_opener(auth_handler, basic_handler)

        target_fps = max(2, min(20, self.camera_info.get("fps", 10)))
        interval = 1.0 / target_fps
        consecutive_fails = 0

        while self._running:
            t0 = time.time()
            try:
                sep = "&" if "?" in clean_url else "?"
                req_url = f"{clean_url}{sep}t={int(t0 * 1000)}"
                req = urllib.request.Request(req_url, headers={"User-Agent": "OmniSight/1.0"})
                with opener.open(req, timeout=3.5) as resp:
                    jpeg_bytes = resp.read()
                    if jpeg_bytes and len(jpeg_bytes) > 200:
                        with self._lock:
                            self._latest_jpeg = jpeg_bytes
                            self._last_frame_time = time.time()
                            self.connection_status = "streaming"
                        consecutive_fails = 0
            except Exception:
                consecutive_fails += 1
                if consecutive_fails >= 3:
                    self.connection_status = "reconnecting"
                    err_text = f"{self.camera_info.get('name', 'CAMERA')} @ {ip}\nAWAITING PASSWORD IN SETTINGS" if not password else f"CONNECTING TO {ip}...\nCHECK PASSWORD / NETWORK"
                    with self._lock:
                        self._latest_jpeg = self._draw_connecting_frame(err_text)
                    time.sleep(1.0)

            elapsed = time.time() - t0
            sleep_time = max(0.04, interval - elapsed)
            time.sleep(sleep_time)

    def _draw_connecting_frame(self, message: str, status_color=(255, 159, 10)) -> bytes:
        """Renders an Apple Cupertino frosted-dark HUD status frame."""
        width = 854
        height = 480
        img = Image.new("RGB", (width, height), color=(14, 16, 20))
        draw = ImageDraw.Draw(img)

        # Subtle background grid lines
        for y in range(0, height, 40):
            draw.line([(0, y), (width, y)], fill=(20, 24, 30), width=1)
        for x in range(0, width, 60):
            draw.line([(x, 0), (x, height)], fill=(20, 24, 30), width=1)

        # Center card container
        card_w, card_h = 560, 180
        cx, cy = width // 2, height // 2
        draw.rectangle([cx - card_w // 2, cy - card_h // 2, cx + card_w // 2, cy + card_h // 2], fill=(22, 26, 32), outline=(40, 48, 60))

        # Center status message
        lines = message.split("\n")
        y = cy - (len(lines) * 14)
        for line in lines:
            draw.text((cx - len(line) * 4.5, y), line, fill=status_color)
            y += 26

        # Top-Left Camera Name
        draw.text((20, 20), self.camera_info.get("name", "Camera").upper(), fill=(255, 255, 255))
        draw.text((20, 40), f"VENDOR: {self.camera_info.get('vendor', 'GENERIC').upper()} // PROTOCOL PROBE", fill=(120, 130, 150))

        # Bottom watermark
        draw.text((20, height - 30), "OMNISIGHT // UNIVERSAL SURVEILLANCE HUB", fill=(80, 90, 110))
        now_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime())
        draw.text((width - 200, height - 30), now_str, fill=(80, 90, 110))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    def _simulation_loop(self):
        """Generates procedural surveillance frames with vendor-authentic OSDs."""
        self.connection_status = "streaming"
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
        """Draws realistic surveillance visuals with dynamic overlays."""
        width = 854
        height = 480
        vendor = self.camera_info.get("vendor", "hikvision")
        cam_name = self.camera_info.get("name", "Surveillance Cam")
        
        img = Image.new("RGB", (width, height), color=(12, 14, 18))
        draw = ImageDraw.Draw(img)

        t = time.time()
        offset_x = int(self.pan * 2.0)
        offset_y = int(self.tilt * 2.0)

        horizon = height // 2 + offset_y
        draw.line([(0, horizon), (width, horizon)], fill=(30, 36, 46), width=2)
        
        for i in range(-5, 15):
            gx = width // 2 + (i * 90) + offset_x
            draw.line([(gx, horizon), (gx * 1.5 - (width * 0.25), height)], fill=(20, 26, 35), width=1)

        fence_y = horizon + 30
        for fx in range(-100, width + 100, 40):
            fx_adj = fx + (offset_x % 40)
            draw.line([(fx_adj, fence_y - 25), (fx_adj, fence_y + 40)], fill=(35, 42, 54), width=2)
            draw.line([(fx_adj - 20, fence_y - 15), (fx_adj + 20, fence_y - 15)], fill=(28, 34, 45), width=1)

        cycle = (t * 0.4) % (math.pi * 2)
        target_world_x = width / 2 + math.sin(cycle) * 260
        target_world_y = horizon + 40 + math.cos(cycle * 0.5) * 20

        target_x = int(target_world_x - offset_x)
        target_y = int(target_world_y - offset_y)

        if self.auto_tracking:
            cx_target = width // 2
            cy_target = horizon + 40
            err_x = target_x - cx_target
            err_y = target_y - cy_target
            if abs(err_x) > 8:
                step_x = (err_x / 60.0) * 0.8
                self.pan = max(-180.0, min(180.0, self.pan + step_x))
            if abs(err_y) > 6:
                step_y = (err_y / 50.0) * 0.6
                self.tilt = max(-90.0, min(90.0, self.tilt - step_y))
            offset_x = int(self.pan * 2.0)
            offset_y = int(self.tilt * 2.0)
            target_x = int(target_world_x - offset_x)
            target_y = int(target_world_y - offset_y)

        box_w, box_h = 70, 90
        x1, y1 = target_x - box_w // 2, target_y - box_h // 2
        x2, y2 = x1 + box_w, y1 + box_h

        # Vendor specific styling
        if vendor in ("hikvision", "hikvision_dvr"):
            osd_color = (255, 255, 255)
            ai_color = (255, 193, 7)
            vendor_tag = "HIKVISION DS-2CD • AcuSense AI"
        elif vendor in ("dahua", "amcrest"):
            osd_color = (240, 240, 240)
            ai_color = (0, 230, 118)
            vendor_tag = "DAHUA WizSense / AMCREST • SMD 4.0"
        elif vendor in ("xiongmai", "xiongmai_dvr"):
            osd_color = (0, 255, 0)
            ai_color = (0, 255, 0)
            vendor_tag = "XM NetSurveillance • HiSilicon H.265+"
        elif vendor in ("tapo", "kasa"):
            osd_color = (255, 255, 255)
            ai_color = (0, 200, 255)
            vendor_tag = "TP-LINK TAPO • Smart AI Detection"
        elif vendor == "axis":
            osd_color = (255, 255, 255)
            ai_color = (255, 204, 0)
            vendor_tag = "AXIS COMMUNICATIONS • VAPIX Analytics"
        elif vendor == "reolink":
            osd_color = (240, 240, 240)
            ai_color = (0, 180, 255)
            vendor_tag = "REOLINK AI • Person & Vehicle Detection"
        elif vendor == "usb_webcam":
            osd_color = (255, 255, 255)
            ai_color = (52, 199, 89)
            vendor_tag = "LOCAL HARDWARE WEBCAM • DirectShow / V4L2"
        elif vendor == "browser_node":
            osd_color = (255, 255, 255)
            ai_color = (0, 200, 255)
            vendor_tag = "BROWSER CAMERA NODE • WebRTC Ingestion"
        else:
            osd_color = (220, 220, 220)
            ai_color = (180, 80, 255)
            vendor_tag = "OMNISIGHT UNIVERSAL NVR • Universal Hub"

        draw.rectangle([x1, y1, x2, y2], outline=ai_color, width=2)
        draw.rectangle([x1, y1 - 18, x1 + 65, y1], fill=(15, 18, 24))
        draw.text((x1 + 4, y1 - 16), "OBJECT 98%", fill=ai_color)

        cx, cy = width // 2, height // 2
        draw.line([(cx - 15, cy), (cx + 15, cy)], fill=(60, 70, 90), width=1)
        draw.line([(cx, cy - 15), (cx, cy + 15)], fill=(60, 70, 90), width=1)
        draw.arc([cx - 30, cy - 30, cx + 30, cy + 30], start=0, end=360, fill=(40, 48, 62), width=1)

        if self.auto_tracking:
            track_color = (52, 199, 89)
            draw.line([(cx, cy), (target_x, target_y)], fill=track_color, width=1)
            draw.text((cx - 85, 72), "🎯 AUTO-TRACK: SENTRY LOCKED", fill=track_color)

        if self.intercom_active:
            if time.time() - self.last_audio_tx < 2.5:
                draw.rectangle([cx - 130, 95, cx + 130, 118], fill=(10, 32, 18), outline=(52, 199, 89))
                draw.text((cx - 120, 100), "🎙️ TALKBACK: LIVE AUDIO TX", fill=(52, 199, 89))
            else:
                self.intercom_active = False

        draw.text((20, 15), cam_name.upper(), fill=osd_color)
        draw.text((20, 32), vendor_tag, fill=(140, 150, 170))
        
        kbps = 2048 + int(math.sin(t * 2) * 280)
        draw.text((20, 50), f"{self.camera_info.get('resolution', '1920x1080')}  {self.camera_info.get('fps', 25)} FPS  {kbps} kbps", fill=(100, 120, 140))

        time_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(t))
        millis = int((t % 1) * 1000)
        full_time_str = f"{time_str}.{millis:03d}"
        
        if int(t * 2) % 2 == 0:
            draw.ellipse([width - 240, 18, width - 228, 30], fill=(230, 40, 40))
            draw.text((width - 222, 16), "REC", fill=(230, 40, 40))

        draw.text((width - 175, 16), full_time_str, fill=osd_color)

        ptz_str = f"PAN: {self.pan:+06.1f}°  TILT: {self.tilt:+05.1f}°  ZOOM: {self.zoom:.1f}x"
        draw.text((20, height - 35), ptz_str, fill=(140, 150, 170))
        draw.text((width - 160, height - 35), "OMNISIGHT // SECURE", fill=(70, 80, 100))

        for sl in range(0, height, 4):
            draw.line([(0, sl), (width, sl)], fill=(0, 0, 0, 30))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    def generate_playback_frame(self, target_time: float) -> bytes:
        """Generates historical playback surveillance frame with authentic archive OSD."""
        width = 854
        height = 480
        t = float(target_time)
        now = time.time()
        if t <= 86400:
            today_start = now - (now % 86400)
            t = today_start + t

        local_tm = time.localtime(t)
        hour = local_tm.tm_hour
        is_night = (hour < 6 or hour >= 19)

        bg_color = (10, 12, 14) if is_night else (18, 22, 28)
        img = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)

        horizon = height // 2
        grid_color = (25, 30, 38) if is_night else (45, 55, 70)
        draw.line([(0, horizon), (width, horizon)], fill=grid_color, width=2)
        for i in range(-5, 15):
            gx = width // 2 + (i * 90)
            draw.line([(gx, horizon), (gx * 1.5 - (width * 0.25), height)], fill=grid_color, width=1)

        fence_y = horizon + 30
        for fx in range(-100, width + 100, 40):
            draw.line([(fx, fence_y - 25), (fx, fence_y + 40)], fill=(35, 42, 54), width=2)

        cycle = (t * 0.3) % (math.pi * 2)
        target_x = int(width / 2 + math.sin(cycle) * 220)
        target_y = int(horizon + 40 + math.cos(cycle * 0.5) * 20)
        box_w, box_h = 70, 90
        x1, y1 = target_x - box_w // 2, target_y - box_h // 2
        x2, y2 = x1 + box_w, y1 + box_h
        target_color = (180, 180, 180) if is_night else (0, 200, 255)
        draw.rectangle([x1, y1, x2, y2], outline=target_color, width=2)
        draw.text((x1 + 4, y1 - 16), "RECORDED MOTION", fill=target_color)

        draw.rectangle([0, 0, width, 32], fill=(22, 22, 28))
        draw.text((20, 9), f"⏪ PLAYBACK ARCHIVE • {self.camera_info.get('name', 'Camera').upper()}", fill=(255, 149, 0))
        historical_str = time.strftime("%Y-%m-%d  %H:%M:%S", local_tm)
        draw.text((width - 260, 9), f"RECORDED: {historical_str}", fill=(255, 255, 255))

        draw.text((20, height - 30), f"TIMELINE SCRUB • {self.night_vision.upper()} PROFILE • 1.0X SPEED", fill=(120, 130, 150))
        draw.text((width - 240, height - 30), "OMNISIGHT HISTORICAL SYNC", fill=(90, 100, 120))

        for sl in range(0, height, 4):
            draw.line([(0, sl), (width, sl)], fill=(0, 0, 0, 30))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()


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

            for cid in existing_ids - current_ids:
                self.sessions[cid].stop()
                del self.sessions[cid]

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
