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

def _find_ffmpeg() -> Optional[str]:
    candidates = [
        shutil.which("ffmpeg"),
        os.path.expanduser("~/.local/bin/ffmpeg"),
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

FFMPEG_BIN = _find_ffmpeg()


#: Still-image / MJPEG endpoints used by IE & ActiveX-era cameras (and by Chinese
#: OEM boxes whose only "web UI" is an ActiveX control). OmniSight polls these
#: directly in HTML5, which is what removes the Internet Explorer requirement.
#: Placeholders: {ip} {port} {username} {password} {channel} {channel_index}
LEGACY_SNAPSHOT_CANDIDATES = (
    "/webcapture.jpg?command=snap&channel={channel}",
    "/webcapture.jpg?command=snap&channel={channel_index}",
    "/snapshot.jpg",
    "/cgi-bin/snapshot.cgi?channel={channel}",
    "/ISAPI/Streaming/channels/{channel}01/picture",
    "/PSIA/Streaming/channels/{channel}01/picture",
    "/onvif-http/snapshot?Profile_1",
    "/image/jpeg.cgi",
    "/cgi-bin/viewer/video.jpg?channel={channel}",
    "/tmpfs/auto.jpg",
    "/videostream.cgi?user={username}&pwd={password}",
    "/cgi-bin/CGIProxy.fcgi?cmd=snapPicture2&usr={username}&pwd={password}",
)

#: Continuous multipart-MJPEG endpoints. These deliver live video over plain HTTP with
#: no RTSP, no FFmpeg and no browser plugin, which makes them the best possible source
#: for cameras whose only officially "supported" client was an ActiveX control.
#: Hikvision's /ISAPI/Streaming/channels/<ch>01/httpPreview is the classic example - it
#: is exactly what the WebComponents.exe plugin consumed, and it answers a plain HTTP
#: GET with HTTP Digest auth.
VENDOR_MJPEG_CANDIDATES = {
    "hikvision": (
        "/ISAPI/Streaming/channels/{channel}01/httpPreview",
        "/PSIA/Streaming/channels/{channel}01/httpPreview",
    ),
    "hikvision_dvr": (
        "/ISAPI/Streaming/channels/{channel}01/httpPreview",
        "/PSIA/Streaming/channels/{channel}01/httpPreview",
    ),
    "dahua": ("/cgi-bin/mjpg/video.cgi?channel={channel}&subtype=1",),
    "amcrest": ("/cgi-bin/mjpg/video.cgi?channel={channel}&subtype=1",),
    "foscam": ("/cgi-bin/CGIStream.cgi?cmd=GetMJStream&usr={username}&pwd={password}",),
    "axis": ("/axis-cgi/mjpg/video.cgi",),
    "esp32_cam": ("/stream",),
    "ip_webcam": ("/videofeed", "/mjpegfeed", "/video"),
}

#: Vendor-preferred endpoints, tried before the generic legacy list. These are the
#: native "no plugin" still-image CGIs for the big CCTV families.
VENDOR_SNAPSHOT_CANDIDATES = {
    "legacy_activex": LEGACY_SNAPSHOT_CANDIDATES,
    "xiongmai": ("/webcapture.jpg?command=snap&channel={channel}", "/snapshot.jpg", "/cgi-bin/snapshot.cgi"),
    "gatocam": ("/webcapture.jpg?command=snap&channel={channel}", "/snapshot.jpg", "/cgi-bin/snapshot.cgi"),
    "xiongmai_dvr": ("/webcapture.jpg?command=snap&channel={channel}", "/snapshot.jpg"),
    "v380": ("/snapshot.jpg", "/webcapture.jpg?command=snap&channel={channel}", "/cgi-bin/snapshot.cgi"),
    "v360": ("/snapshot.jpg", "/webcapture.jpg?command=snap&channel={channel}", "/cgi-bin/snapshot.cgi"),
    "yoosee": ("/snapshot.jpg", "/webcapture.jpg?command=snap&channel={channel}"),
    "icsee": ("/snapshot.jpg", "/webcapture.jpg?command=snap&channel={channel}"),
    # Hikvision (incl. DS-2CD* R6 platform, which is the family that demands
    # WebComponents.exe in Internet Explorer): ISAPI first, then the older PSIA
    # API and the pre-ISAPI /Streaming/Channels path used by early firmware.
    "hikvision": (
        "/ISAPI/Streaming/channels/{channel}01/picture",
        "/PSIA/Streaming/channels/{channel}01/picture",
        "/Streaming/Channels/{channel}01/picture",
        "/onvif-http/snapshot?Profile_1",
        "/cgi-bin/snapshot.cgi",
    ),
    "hikvision_dvr": (
        "/ISAPI/Streaming/channels/{channel}01/picture",
        "/PSIA/Streaming/channels/{channel}01/picture",
        "/Streaming/Channels/{channel}01/picture",
        "/cgi-bin/snapshot.cgi?chn={channel}",
        "/onvif-http/snapshot?Profile_1",
    ),
    "dahua": ("/cgi-bin/snapshot.cgi?channel={channel}", "/cgi-bin/snapshot.cgi", "/onvif-http/snapshot?Profile_1"),
    "amcrest": ("/cgi-bin/snapshot.cgi?channel={channel}", "/cgi-bin/snapshot.cgi", "/onvif-http/snapshot?Profile_1"),
    "uniview": ("/images/snapshot.jpg", "/cgi-bin/snapshot.cgi"),
    "axis": ("/axis-cgi/jpg/image.cgi", "/jpg/image.jpg"),
    "dlink": ("/image/jpeg.cgi", "/cgi-bin/video.jpg"),
    "trendnet": ("/cgi-bin/video.jpg", "/tmpfs/auto.jpg"),
    "vivotek": ("/cgi-bin/viewer/video.jpg?channel={channel}",),
    "foscam": ("/cgi-bin/CGIProxy.fcgi?cmd=snapPicture2&usr={username}&pwd={password}", "/snapshot.jpg"),
    "reolink": ("/cgi-bin/api.cgi?cmd=Snap&channel={channel}&user={username}&password={password}",),
    "tapo": ("/cgi-bin/snapshot.jpg", "/snapshot.jpg"),
    "kasa": ("/cgi-bin/snapshot.jpg", "/snapshot.jpg"),
    "esp32_cam": ("/capture", "/snapshot.jpg"),
    "ip_webcam": ("/shot.jpg", "/photo.jpg"),
}


class _PasswordMgr(urllib.request.HTTPPasswordMgr):
    """Attaches the session's camera credentials to every auth realm of one host."""

    def __init__(self, session, url: str):
        super().__init__()
        camera = session.camera_info
        self._username = camera.get("username", "") or ""
        self._password = camera.get("password", "") or ""
        self._origin = session._origin_of(url)

    def find_user_password(self, realm, authuri):
        if self._username and authuri.startswith(self._origin):
            return self._username, self._password
        return None, None


def format_snapshot_url(pattern: str, ip: str, port: Any, channel: Any, username: str = "", password: str = "") -> str:
    """Expands a snapshot endpoint template into a fully qualified URL."""
    try:
        channel_int = int(channel)
    except (ValueError, TypeError):
        channel_int = 1
    try:
        port_int = int(port) if port else 80
    except (ValueError, TypeError):
        port_int = 80
    if port_int <= 0:
        port_int = 80

    url = pattern
    if not url.startswith(("http://", "https://")):
        url = f"http://{ip}:{port_int}{url if url.startswith('/') else '/' + url}"

    return (
        url.replace("{ip}", ip or "")
        .replace("{port}", str(port_int))
        .replace("{username}", urllib.parse.quote(username or "", safe=""))
        .replace("{password}", urllib.parse.quote(password or "", safe=""))
        .replace("{channel_index}", str(max(0, channel_int - 1)))
        .replace("{channel}", str(channel_int))
    )


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
        self.source_kind = "unknown"  # webcam, browser_node, ffmpeg, snapshot, simulation
        self.last_error = ""
        self.started_at = time.time()
        # Remembered still-image endpoint for IE/ActiveX-era cameras
        self._working_snapshot_url: str = ""
        # Remembered continuous-MJPEG endpoint (e.g. Hikvision ISAPI httpPreview)
        self._working_mjpeg_url: str = ""
        
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
            status = self.connection_status
            name = self.camera_info.get("name", "CAMERA")
            src = self.camera_info.get("ip") or self.stream_url or "NO SOURCE"
        # Nothing has arrived yet: draw an honest HUD frame instead of a fake camera scene.
        msg = f"{name.upper()} @ {src}\nINITIALIZING {self.source_kind.upper()} INGEST...\nSTATUS: {status.upper()}"
        return self._draw_connecting_frame(msg, status_color=(0, 200, 255))

    def get_status(self) -> Dict[str, Any]:
        """Live telemetry for the dashboard: real online/offline state for this camera."""
        with self._lock:
            now = time.time()
            age = (now - self._last_frame_time) if self._last_frame_time else None
            status = self.connection_status
            # A stream that stopped delivering frames is not really "streaming".
            if status == "streaming" and (age is None or age > 10.0):
                status = "reconnecting"
            return {
                "camera_id": self.camera_id,
                "status": status,
                "online": status == "streaming",
                "source_kind": self.source_kind,
                "last_frame_age": age,
                "reconnect_count": self.reconnect_count,
                "has_frame": self._latest_jpeg is not None,
                "last_error": self.last_error,
                "uptime": now - self.started_at,
            }

    def _draw_error_loop(self, message: str):
        """Keeps a camera visible with an actionable HUD when it cannot be ingested at all."""
        while self._running:
            with self._lock:
                self._latest_jpeg = self._draw_connecting_frame(message, status_color=(255, 69, 58))
            time.sleep(2.0)

    #: URL schemes that require an FFmpeg ingest pipeline
    STREAM_FEED_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "rtmps://", "http://", "https://")

    #: Cameras that historically only worked in Internet Explorer / ActiveX.
    #: Their native RTSP paths are undocumented or absent, so they are driven
    #: through HTTP still-image polling (endpoint discovered automatically).
    LEGACY_VENDORS = ("legacy_activex", "activex", "legacy_ie")

    def is_legacy_ie_camera(self) -> bool:
        vendor = (self.camera_info.get("vendor") or "").strip().lower()
        return (
            vendor in self.LEGACY_VENDORS
            or bool(self.camera_info.get("requires_activex"))
            or bool(self.camera_info.get("activex"))
        )

    def classify_source(self) -> str:
        """Resolves which ingestion engine this camera actually needs.

        A camera is only treated as simulated when it has no real source URL.
        This matters because the UI stores a legacy ``is_simulated`` flag that
        used to silently disable RTSP ingestion for real cameras.
        """
        url = (self.stream_url or "").strip()
        vendor = (self.camera_info.get("vendor") or "").strip()

        if url.startswith("webcam://") or vendor == "usb_webcam":
            return "webcam"
        if url.startswith("node://") or vendor == "browser_node":
            return "browser_node"
        if url.startswith("sim://") or vendor == "simulated" or not url:
            return "simulation"

        # ActiveX-era cameras: never trust a fabricated RTSP path. If the camera
        # is on the LAN, drive it through still-image polling instead.
        if self.is_legacy_ie_camera():
            if url.startswith(("http://", "https://")) or self.camera_info.get("ip"):
                return "snapshot"
            return "simulation"

        if any(url.startswith(p) for p in self.STREAM_FEED_SCHEMES) or url.endswith(".m3u8"):
            # RTSP/RTMP/HLS always needs FFmpeg; plain HTTP may be a snapshot URL.
            if any(url.startswith(p) for p in ("rtsp://", "rtsps://", "rtmp://", "rtmps://")) or url.endswith(".m3u8"):
                return "ffmpeg"
            # HTTP(S): treat as a live feed only when FFmpeg is available and we
            # are not explicitly configured for snapshot polling.
            if FFMPEG_BIN and not self.camera_info.get("legacy_polling") and not self.camera_info.get("snapshot_url"):
                return "ffmpeg"
            return "snapshot" if self._snapshot_capable() else "ffmpeg"
        return "snapshot" if self._snapshot_capable() else "simulation"

    def _snapshot_capable(self) -> bool:
        """True when this camera can be polled through an HTTP still-image endpoint."""
        if (
            self.camera_info.get("snapshot_url")
            or self.camera_info.get("legacy_polling")
            or self.is_legacy_ie_camera()
        ):
            return True

        ip = self.camera_info.get("ip")
        if not ip:
            return False
        if self.stream_url.startswith(("http://", "https://")) or self.is_simulated:
            return True

        # We know plugin-free HTTP endpoints for this vendor (e.g. Hikvision ISAPI /
        # PSIA snapshots and httpPreview MJPEG), so the camera can always be ingested
        # even if its RTSP stream is unavailable or FFmpeg is missing.
        vendor = (self.camera_info.get("vendor") or "").strip().lower()
        return bool(VENDOR_SNAPSHOT_CANDIDATES.get(vendor) or VENDOR_MJPEG_CANDIDATES.get(vendor))

    def _worker_loop(self):
        """Universal Dispatcher: FFmpeg (RTSP/RTMP/HLS), USB Webcam, Browser Node, HTTP Snapshot, or Simulator."""
        source_kind = self.classify_source()
        self.source_kind = source_kind

        # 1. Local USB / DirectShow Webcam
        if source_kind == "webcam":
            if FFMPEG_BIN:
                self._ffmpeg_webcam_loop()
            else:
                self._simulation_loop()
            return

        # 2. Browser Camera Node (Phone or Laptop streaming to NVR)
        if source_kind == "browser_node":
            self._browser_node_loop()
            return

        # 3. Live Stream Feeds (RTSP, RTSPS, RTMP, HLS .m3u8) -> FFmpeg ingest
        if source_kind == "ffmpeg":
            if FFMPEG_BIN:
                self._ffmpeg_universal_stream_loop()
                return
            # No FFmpeg on this host: degrade gracefully instead of disabling the camera.
            if self._snapshot_capable():
                self.last_error = "FFmpeg unavailable - using plugin-free HTTP ingest."
                # Prefer a continuous MJPEG endpoint (full framerate), then still images.
                if self._mjpeg_stream_loop():
                    return
                self.source_kind = "snapshot"
                self._http_snapshot_polling_loop()
                return
            self.connection_status = "error"
            self.last_error = "FFmpeg is not installed; cannot ingest this live stream."
            self._draw_error_loop("FFMPEG NOT INSTALLED\nINSTALL FFMPEG TO INGEST RTSP/RTMP/HLS")
            return

        # 3b. Continuous MJPEG over HTTP (Hikvision ISAPI httpPreview, Dahua mjpg,
        # Axis, ESP32-CAM...). Live video with no RTSP, no FFmpeg and no browser
        # plugin - the direct replacement for an ActiveX control like
        # Hikvision's WebComponents.exe. Falls through to snapshot polling if the
        # camera exposes no MJPEG endpoint.
        if source_kind == "snapshot" and self._snapshot_capable():
            if self._mjpeg_stream_loop():
                return
            # 4. HTTP Snapshot Polling (Direct camera picture polling with zero IE or ActiveX)
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
                    # Re-check under the lock: a frame pushed by the browser node between
                    # the check above and here must never be overwritten by the placeholder.
                    if self._latest_jpeg and (time.time() - self._last_frame_time < 5.0):
                        self.connection_status = "streaming"
                    else:
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
        transports = ["udp", "tcp", "http"]
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
                        if proc.stdout:
                            proc.stdout.close()
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

            # RTSP keeps failing but the vendor exposes a still-image CGI (Hikvision ISAPI,
            # Dahua CGI, XM snapshot.jpg ...): fall back to snapshot polling instead of
            # showing a dead card forever.
            if frames_received == 0 and self.reconnect_count >= 3 and self._snapshot_capable():
                self.last_error = (
                    f"{transport.upper()} ingest failed {self.reconnect_count}x - "
                    "switched to plugin-free HTTP ingest."
                )
                self.connection_status = "connecting"
                if self._mjpeg_stream_loop():
                    return
                self.source_kind = "snapshot"
                self._http_snapshot_polling_loop()
                return

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

    def _snapshot_url_candidates(self) -> list:
        """Ordered list of snapshot URLs to try for this camera.

        The configured/explicit URL wins; otherwise vendor-specific endpoints are
        tried before the generic IE/ActiveX-era list. The endpoint that last
        worked is remembered first so polling stays stable.
        """
        ip = (self.camera_info.get("ip") or "").strip()
        channel = self.camera_info.get("channel", 1)
        vendor = (self.camera_info.get("vendor") or "").strip().lower()
        username = self.camera_info.get("username", "")
        password = self.camera_info.get("password", "")

        candidates = []
        if self._working_snapshot_url:
            candidates.append(self._working_snapshot_url)

        explicit = (self.camera_info.get("snapshot_url") or "").strip()
        if explicit:
            candidates.append(format_snapshot_url(explicit, ip, self._snapshot_port(), channel, username, password))

        # The stream_url of a legacy/polling camera is often itself the snapshot URL
        if self.stream_url.startswith(("http://", "https://")):
            candidates.append(self.stream_url)

        if ip:
            patterns = list(VENDOR_SNAPSHOT_CANDIDATES.get(vendor, ()))
            if self.is_legacy_ie_camera():
                patterns += [p for p in LEGACY_SNAPSHOT_CANDIDATES if p not in patterns]
            for pattern in patterns:
                candidates.append(
                    format_snapshot_url(pattern, ip, self._snapshot_port(), channel, username, password)
                )

        # Preserve order while removing duplicates
        seen = set()
        ordered = []
        for url in candidates:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        return ordered

    def _snapshot_port(self) -> int:
        """HTTP port to use for still-image polling (RTSP ports are never relevant here)."""
        port = self.camera_info.get("port")
        try:
            port_int = int(port)
        except (ValueError, TypeError):
            port_int = 0
        if port_int in (0, 554, 8554, 7447, 10554):
            return 80
        return port_int

    def _mjpeg_candidates(self) -> list:
        """Ordered multipart-MJPEG endpoints to try (explicit URL first, then vendor ones)."""
        ip = (self.camera_info.get("ip") or "").strip()
        if not ip:
            return []
        channel = self.camera_info.get("channel", 1)
        vendor = (self.camera_info.get("vendor") or "").strip().lower()
        username = self.camera_info.get("username", "")
        password = self.camera_info.get("password", "")

        candidates = []
        if self._working_mjpeg_url:
            candidates.append(self._working_mjpeg_url)
        explicit = (self.camera_info.get("mjpeg_url") or "").strip()
        if explicit:
            candidates.append(
                format_snapshot_url(explicit, ip, self._snapshot_port(), channel, username, password)
            )
        for pattern in VENDOR_MJPEG_CANDIDATES.get(vendor, ()):
            candidates.append(
                format_snapshot_url(pattern, ip, self._snapshot_port(), channel, username, password)
            )

        seen = set()
        return [url for url in candidates if url and not (url in seen or seen.add(url))]

    def _consume_mjpeg_stream(self, url: str, first_frame_timeout: float = 5.0) -> bool:
        """Reads JPEG frames continuously from one MJPEG endpoint.

        Returns True once at least one complete frame was received (the stream is live),
        False if the endpoint never produced a frame. Handles the endless
        multipart/x-mixed-replace response body by framing on JPEG SOI/EOI markers.
        """
        got_frame = False
        deadline = time.time() + first_frame_timeout

        try:
            pwd_mgr = _PasswordMgr(self, url)
            opener = urllib.request.build_opener(
                urllib.request.HTTPDigestAuthHandler(pwd_mgr),
                urllib.request.HTTPBasicAuthHandler(pwd_mgr),
            )
            req = urllib.request.Request(
                self._strip_credentials(url), headers={"User-Agent": "OmniSight/1.0"}
            )
            with opener.open(req, timeout=max(4.0, first_frame_timeout)) as resp:
                reader = getattr(resp, "read1", None) or resp.read
                buffer = bytearray()
                while self._running:
                    if not got_frame and time.time() > deadline:
                        self.last_error = (
                            f"MJPEG endpoint produced no frames: {self._snapshot_path_label(url)}"
                        )
                        return False
                    chunk = reader(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if len(buffer) > 4 * 1024 * 1024:
                        buffer = buffer[-1024 * 1024:]

                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start == -1:
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end == -1:
                            if start > 0:
                                del buffer[:start]
                            break
                        frame = bytes(buffer[start:end + 2])
                        del buffer[:end + 2]
                        if len(frame) > 200:
                            with self._lock:
                                self._latest_jpeg = frame
                                self._last_frame_time = time.time()
                                self.connection_status = "streaming"
                                self.last_error = ""
                            if not got_frame:
                                self._working_mjpeg_url = url
                                self.camera_info["mjpeg_url"] = url
                                self.source_kind = "mjpeg"
                            got_frame = True
        except Exception as exc:
            if not got_frame:
                self.last_error = str(exc) or exc.__class__.__name__
            return got_frame

        if not got_frame:
            self.last_error = f"No frames from MJPEG endpoint {self._snapshot_path_label(url)}"
        return got_frame

    def _mjpeg_stream_loop(self) -> bool:
        """Streams live MJPEG video without RTSP/FFmpeg. False if no endpoint produced frames."""
        candidates = self._mjpeg_candidates()
        if not candidates:
            return False

        name = self.camera_info.get("name", "CAMERA")
        ip = self.camera_info.get("ip", "")

        for url in candidates:
            if not self._running:
                return False
            self.connection_status = "connecting"
            with self._lock:
                self._latest_jpeg = self._draw_connecting_frame(
                    f"{name.upper()} @ {ip}\nHTML5 MJPEG INGEST (NO IE PLUGIN NEEDED)\n"
                    f"PROBING {self._snapshot_path_label(url)}",
                    status_color=(0, 200, 255),
                )
            if not self._consume_mjpeg_stream(url):
                continue

            # Live: keep reading, reconnecting through temporary dropouts.
            backoff = 1.0
            while self._running:
                if self._consume_mjpeg_stream(url, first_frame_timeout=8.0):
                    backoff = 1.0
                    continue
                if not self._running:
                    break
                self.connection_status = "reconnecting"
                with self._lock:
                    self._latest_jpeg = self._draw_connecting_frame(
                        f"{name.upper()} @ {ip}\nMJPEG STREAM LOST - RECONNECTING...\n"
                        f"{self._snapshot_path_label(url)}",
                        status_color=(255, 159, 10),
                    )
                time.sleep(backoff)
                backoff = min(5.0, backoff * 1.5)
            return True
        return False

    def _legacy_hint(self) -> str:
        """Vendor-specific guidance shown on the HUD when a camera has not produced frames."""
        vendor = (self.camera_info.get("vendor") or "").strip().lower()
        if vendor in ("hikvision", "hikvision_dvr"):
            return "NO IE PLUGIN NEEDED (WebComponents.exe)\nOMNISIGHT USES ISAPI / RTSP DIRECTLY"
        if vendor in ("dahua", "amcrest"):
            return "NO IE PLUGIN NEEDED (webplugin.exe)\nOMNISIGHT USES CGI / RTSP DIRECTLY"
        if vendor in ("legacy_activex", "activex", "legacy_ie"):
            return "NO ACTIVEX NEEDED - POLLING RAW JPEG ENDPOINTS"
        return ""

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
            self.camera_info["snapshot_url"] = snapshot_url

        snapshot_candidates = self._snapshot_url_candidates()
        if not snapshot_candidates:
            self._simulation_loop()
            return

        # Credentials embedded in the URL take precedence
        try:
            parsed = urllib.parse.urlparse(snapshot_candidates[0])
            if parsed.username:
                username = parsed.username
            if parsed.password:
                password = parsed.password
        except Exception:
            pass

        def build_opener(url: str):
            pwd_mgr = _PasswordMgr(self, url)
            auth_handler = urllib.request.HTTPDigestAuthHandler(pwd_mgr)
            basic_handler = urllib.request.HTTPBasicAuthHandler(pwd_mgr)
            return urllib.request.build_opener(auth_handler, basic_handler)

        target_fps = max(2, min(20, self.camera_info.get("fps", 10)))
        interval = 1.0 / target_fps

        self.connection_status = "connecting"
        self.last_error = ""

        candidate_idx = 0
        consecutive_fails = 0
        # Persist the discovered endpoint so the dashboard (and next reboot) use it too.
        try:
            if not self.camera_info.get("snapshot_url") and snapshot_candidates:
                self.camera_info["snapshot_url"] = snapshot_candidates[0]
        except Exception:
            pass

        while self._running:
            t0 = time.time()
            target = snapshot_candidates[candidate_idx % len(snapshot_candidates)]
            try:
                opener = build_opener(target)
                clean_url = self._strip_credentials(target)
                sep = "&" if "?" in clean_url else "?"
                req_url = f"{clean_url}{sep}t={int(t0 * 1000)}"
                req = urllib.request.Request(req_url, headers={"User-Agent": "OmniSight/1.0"})
                with opener.open(req, timeout=3.5) as resp:
                    jpeg_bytes = self._read_single_jpeg(resp)
                    if jpeg_bytes and len(jpeg_bytes) > 200:
                        with self._lock:
                            self._latest_jpeg = jpeg_bytes
                            self._last_frame_time = time.time()
                            self.connection_status = "streaming"
                            self.last_error = ""
                        consecutive_fails = 0
                        if self._working_snapshot_url != target:
                            self._working_snapshot_url = target
                            self.camera_info["snapshot_url"] = target
            except Exception as exc:
                consecutive_fails += 1
                self.last_error = str(exc) or exc.__class__.__name__

                # Snapshot endpoint not found yet: walk the candidate list quickly.
                if not self._working_snapshot_url and len(snapshot_candidates) > 1:
                    candidate_idx += 1
                    self.connection_status = "connecting"
                    note = "AUTO-DETECTING SNAPSHOT ENDPOINT"
                elif consecutive_fails >= 3:
                    self.connection_status = "reconnecting"
                    note = "CHECK PASSWORD / NETWORK"
                else:
                    note = ""

                if note:
                    if self._working_snapshot_url:
                        note = f"RETRYING {self._snapshot_path_label(self._working_snapshot_url)}"
                    hint = self._legacy_hint()
                    err_text = (
                        f"{self.camera_info.get('name', 'CAMERA')} @ {ip}\n{note}"
                        + (f"\n{hint}" if hint else "")
                    )
                    with self._lock:
                        self._latest_jpeg = self._draw_connecting_frame(err_text)
                    time.sleep(0.5 if not self._working_snapshot_url else 1.0)

            elapsed = time.time() - t0
            sleep_time = max(0.04, interval - elapsed)
            time.sleep(sleep_time)

    @staticmethod
    def _strip_credentials(url: str) -> str:
        """Removes user:pass@ from a URL (urllib handles auth via its password manager)."""
        return re.sub(r"://[^/@]+@", "://", url)

    def _origin_of(self, url: str) -> str:
        """Returns scheme://host[:port] for a URL, so credentials can be scoped to it."""
        parsed = urllib.parse.urlparse(self._strip_credentials(url))
        netloc = parsed.netloc or (self.camera_info.get("ip") or "")
        return f"{parsed.scheme or 'http'}://{netloc}"

    @staticmethod
    def _snapshot_path_label(url: str) -> str:
        try:
            return urllib.parse.urlparse(url).path.upper().lstrip("/")[:40] or "SNAPSHOT"
        except Exception:
            return "SNAPSHOT"

    def discover_snapshot_endpoint(self, timeout: float = 3.0) -> Optional[str]:
        """Actively probes every known still-image endpoint and returns the first that works.

        This is what lets an Internet-Explorer/ActiveX-only camera stream into a
        modern browser: we find the raw JPEG the camera serves and poll it.
        """
        for candidate in self._snapshot_url_candidates():
            try:
                opener = urllib.request.build_opener(
                    urllib.request.HTTPBasicAuthHandler(_PasswordMgr(self, candidate)),
                    urllib.request.HTTPDigestAuthHandler(_PasswordMgr(self, candidate)),
                )
                req = urllib.request.Request(
                    self._strip_credentials(candidate),
                    headers={"User-Agent": "OmniSight/1.0"},
                )
                with opener.open(req, timeout=timeout) as resp:
                    frame = self._read_single_jpeg(resp)
                    if frame and len(frame) > 200 and frame.startswith(b"\xff\xd8"):
                        self._working_snapshot_url = candidate
                        self.camera_info["snapshot_url"] = candidate
                        return candidate
            except Exception:
                continue
        return None

    @staticmethod
    def _read_single_jpeg(resp) -> bytes:
        """Reads exactly one JPEG frame from an HTTP response.

        Works for both plain still-image CGIs and endless multipart/x-mixed-replace
        MJPEG feeds, where a naive resp.read() would block forever.
        """
        buffer = bytearray()
        reader = getattr(resp, "read1", None) or resp.read
        deadline = time.time() + 3.5
        while len(buffer) < 4 * 1024 * 1024 and time.time() < deadline:
            chunk = reader(65536)
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b"\xff\xd8")
            if start != -1:
                end = buffer.find(b"\xff\xd9", start + 2)
                if end != -1:
                    return bytes(buffer[start:end + 2])
        # No complete frame boundary found: hand back whatever looks like image data.
        start = buffer.find(b"\xff\xd8")
        return bytes(buffer[start:]) if start != -1 else bytes(buffer)

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

    #: Camera fields that change how a stream is ingested. A change in any of
    #: these requires the running worker to be restarted with the new config.
    CONFIG_FINGERPRINT_FIELDS = (
        "name", "vendor", "ip", "port", "username", "password",
        "stream_url", "sub_stream_url", "snapshot_url", "channel",
        "is_simulated", "legacy_polling", "fps", "talkback_port",
    )

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.sessions: Dict[str, CameraStreamSession] = {}
        self._fingerprints: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._sync_sessions()

    @classmethod
    def _fingerprint(cls, cam: Dict[str, Any]) -> tuple:
        return tuple(str(cam.get(field, "")) for field in cls.CONFIG_FINGERPRINT_FIELDS)

    def _sync_sessions(self):
        with self._lock:
            cameras = self.config_manager.get_all_cameras()
            current_ids = {c["id"] for c in cameras}

            for cid in set(self.sessions.keys()) - current_ids:
                self.sessions[cid].stop()
                del self.sessions[cid]
                self._fingerprints.pop(cid, None)

            for c in cameras:
                cid = c["id"]
                fingerprint = self._fingerprint(c)
                existing = self.sessions.get(cid)

                if existing is None:
                    session = CameraStreamSession(c)
                    session.start()
                    self.sessions[cid] = session
                elif self._fingerprints.get(cid) != fingerprint:
                    # Camera was edited (credentials, IP, source URL, simulator flag...):
                    # restart the worker so the new settings actually take effect.
                    existing.stop()
                    session = CameraStreamSession(c)
                    session.start()
                    self.sessions[cid] = session

                self._fingerprints[cid] = fingerprint

    def get_session(self, camera_id: str) -> Optional[CameraStreamSession]:
        with self._lock:
            if camera_id in self.sessions:
                return self.sessions[camera_id]
            cam = self.config_manager.get_camera(camera_id)
            if cam:
                session = CameraStreamSession(cam)
                session.start()
                self.sessions[camera_id] = session
                self._fingerprints[camera_id] = self._fingerprint(cam)
                return session
            return None

    def refresh_cameras(self):
        self._sync_sessions()
