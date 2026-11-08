"""
OmniSight-NVR - High-Performance Surveillance Web Server
Multithreaded REST API, live multipart/x-mixed-replace MJPEG stream broadcaster,
and static asset server with zero external dependencies and session authentication.
"""

import os
import sys
import json
import time
import shutil
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from .config_manager import ConfigManager
    from .stream_proxy import StreamManager, FFMPEG_BIN
    from .vendor_presets import VENDOR_PRESETS, build_stream_url
    from .discovery import run_full_discovery, probe_camera_connection, list_system_webcams
    from .recorder import RecorderManager
    from .cloud_relay import CloudRelayManager
except (ImportError, ValueError):
    from config_manager import ConfigManager
    from stream_proxy import StreamManager, FFMPEG_BIN
    from vendor_presets import VENDOR_PRESETS, build_stream_url
    from discovery import run_full_discovery, probe_camera_connection, list_system_webcams
    from recorder import RecorderManager
    from cloud_relay import CloudRelayManager

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
SNAPSHOTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

config_manager = ConfigManager()
stream_manager = StreamManager(config_manager)
recorder_manager = RecorderManager(stream_manager)
cloud_relay_manager = CloudRelayManager(port=8080)


def verify_google_token(token: str, client_id: str = "") -> Optional[Dict[str, Any]]:
    """Verifies Google ID token via google-auth if installed, or via Google tokeninfo API."""
    if not token or not isinstance(token, str):
        return None
    token = token.strip()
    # 1. Try google-auth library if installed
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests
        req = requests.Request()
        id_info = id_token.verify_oauth2_token(token, req, client_id or None)
        return id_info
    except ImportError:
        pass
    except Exception as e:
        print(f"[GoogleAuth] google-auth verification error: {e}")
        return None

    # 2. Fallback: Google OAuth2 tokeninfo validation endpoint (standard library)
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(token)}"
        req = urllib.request.Request(url, headers={"User-Agent": "OmniSight-NVR/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                info = json.loads(resp.read().decode("utf-8"))
                if info.get("iss") in ("accounts.google.com", "https://accounts.google.com"):
                    if client_id and info.get("aud") != client_id:
                        return None
                    return info
    except Exception as e:
        print(f"[GoogleAuth] tokeninfo verification error: {e}")
    return None


class OmniSightHandler(BaseHTTPRequestHandler):
    """Handles REST API calls, live video streams, and static dashboard assets."""

    server_version = "OmniSight-NVR/1.0"

    def log_message(self, format, *args):
        # Silence routine stream requests from spamming console
        if "/stream" in args[0] or "/static" in args[0]:
            return
        super().log_message(format, *args)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Access-Control-Request-Private-Network",
        )
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def extract_token(self, query: Optional[Dict[str, list]] = None) -> Optional[str]:
        # 1. Check Authorization header
        auth_header = self.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        # 2. Check query params (useful for <img> tags and media streams)
        if query and "token" in query and query["token"]:
            return query["token"][0]

        # 3. Check Cookie header
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            cookies = dict(item.strip().split("=", 1) for item in cookie_header.split(";") if "=" in item)
            if "omnisight_token" in cookies:
                return cookies["omnisight_token"]

        return None

    def get_authenticated_user(self, query: Optional[Dict[str, list]] = None) -> Optional[Dict[str, Any]]:
        token = self.extract_token(query)
        if not token:
            return None
        return config_manager.validate_session(token)

    def _normalize_path(self) -> Optional[urllib.parse.ParseResult]:
        """Normalizes /OmniSight-NVR/* directory paths to root so the hub works both at / and /OmniSight-NVR/."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/OmniSight-NVR", "/omnisight-nvr"):
            qs = f"?{parsed.query}" if parsed.query else ""
            self.send_response(301)
            self.send_header("Location", f"{path}/{qs}")
            self.send_cors_headers()
            self.end_headers()
            return None
        for prefix in ("/OmniSight-NVR/", "/omnisight-nvr/"):
            if path.startswith(prefix):
                stripped = "/" + path[len(prefix):]
                self.path = stripped + (f"?{parsed.query}" if parsed.query else "")
                return urllib.parse.urlparse(self.path)
        return parsed

    def do_GET(self):
        parsed = self._normalize_path()
        if parsed is None:
            return
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Static root
        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
            return

        # Active tunnel & directory metadata JSON
        if path == "/data/active_tunnel.json":
            self.serve_file(os.path.join(DATA_DIR, "active_tunnel.json"), "application/json")
            return

        # Static assets
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):].lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel_path)
            # Security check
            if not os.path.abspath(file_path).startswith(STATIC_DIR):
                self.send_error(403, "Forbidden")
                return
            
            ext = os.path.splitext(file_path)[1].lower()
            mime = "text/plain"
            if ext == ".html":
                mime = "text/html"
            elif ext == ".css":
                mime = "text/css"
            elif ext == ".js":
                mime = "application/javascript"
            elif ext == ".json":
                mime = "application/json"
            elif ext == ".png":
                mime = "image/png"
            elif ext == ".jpg" or ext == ".jpeg":
                mime = "image/jpeg"
            elif ext == ".svg":
                mime = "image/svg+xml"
            elif ext == ".ico":
                mime = "image/x-icon"
            
            self.serve_file(file_path, mime)
            return

        # Public API: Status
        if path == "/api/status":
            ffmpeg_path = FFMPEG_BIN
            self.send_json({
                "status": "online",
                "system": "OmniSight-NVR Hub",
                "version": "1.0.0",
                "time": time.time(),
                "ffmpeg_available": bool(ffmpeg_path),
                "ffmpeg_path": ffmpeg_path,
                "active_camera_count": len(config_manager.get_all_cameras()),
                "total_snapshots": len(recorder_manager.list_snapshots()),
                "auth_required": True,
                "google_client_id": config_manager.get_google_client_id()
            })
            return

        # Public API: 4G Cloud Relay Status
        if path == "/api/cloud-relay":
            self.send_json(cloud_relay_manager.get_status())
            return

        # Public API: Current session info
        if path == "/api/auth/me":
            session = self.get_authenticated_user(query)
            if not session:
                self.send_json({"authenticated": False}, 200)
            else:
                self.send_json({
                    "authenticated": True,
                    "username": session["username"],
                    "expires_at": session["expires_at"]
                })
            return

        # Public API: Google OAuth 2.0 Configuration & Authorization URL
        if path == "/api/auth/google/oauth-url":
            client_id = config_manager.get_google_client_id()
            host = self.headers.get("Host", f"localhost:{cloud_relay_manager.port}")
            proto = "https" if "trycloudflare" in host or "https" in self.headers.get("X-Forwarded-Proto", "") else "http"
            redirect_uri = f"{proto}://{host}/api/auth/google/callback"
            oauth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth?"
                f"client_id={urllib.parse.quote(client_id)}&"
                f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
                f"response_type=code&scope=openid%20email%20profile&access_type=offline&prompt=select_account"
            ) if client_id else ""
            self.send_json({
                "oauth_configured": bool(client_id),
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "oauth_url": oauth_url
            })
            return

        # Public API: Google OAuth 2.0 Login Redirect
        if path == "/api/auth/google/login":
            client_id = config_manager.get_google_client_id()
            if not client_id:
                self.send_response(302)
                self.send_header("Location", "/?error=google_oauth_not_configured")
                self.end_headers()
                return
            host = self.headers.get("Host", f"localhost:{cloud_relay_manager.port}")
            proto = "https" if "trycloudflare" in host or "https" in self.headers.get("X-Forwarded-Proto", "") else "http"
            redirect_uri = f"{proto}://{host}/api/auth/google/callback"
            oauth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth?"
                f"client_id={urllib.parse.quote(client_id)}&"
                f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
                f"response_type=code&scope=openid%20email%20profile&access_type=offline&prompt=select_account"
            )
            self.send_response(302)
            self.send_header("Location", oauth_url)
            self.end_headers()
            return

        # Public API: Google OAuth 2.0 Callback
        if path == "/api/auth/google/callback":
            code = query.get("code", [None])[0]
            if not code:
                err = query.get("error", ["no_code_received"])[0]
                self.send_response(302)
                self.send_header("Location", f"/?error={urllib.parse.quote(err)}")
                self.end_headers()
                return

            client_id = config_manager.get_google_client_id()
            client_secret = config_manager.get_google_client_secret()
            host = self.headers.get("Host", f"localhost:{cloud_relay_manager.port}")
            proto = "https" if "trycloudflare" in host or "https" in self.headers.get("X-Forwarded-Proto", "") else "http"
            redirect_uri = f"{proto}://{host}/api/auth/google/callback"

            token_url = "https://oauth2.googleapis.com/token"
            data = urllib.parse.urlencode({
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }).encode("utf-8")

            try:
                req = urllib.request.Request(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    id_token_jwt = resp_data.get("id_token")
                    access_token = resp_data.get("access_token")

                    info = verify_google_token(id_token_jwt, client_id) if id_token_jwt else None
                    email = info.get("email") if info else None
                    name = info.get("name") if info else "Google User"
                    picture = info.get("picture", "") if info else ""

                    if not email and access_token:
                        u_req = urllib.request.Request("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_token}"})
                        with urllib.request.urlopen(u_req, timeout=5.0) as uresp:
                            uinfo = json.loads(uresp.read().decode("utf-8"))
                            email = uinfo.get("email")
                            name = uinfo.get("name", "Google User")
                            picture = uinfo.get("picture", "")

                    if email:
                        session_info = config_manager.authenticate_google_user(email=email, name=name, picture=picture)
                        token = session_info["token"]
                        self.send_response(302)
                        self.send_header("Set-Cookie", f"omnisight_token={token}; Path=/; HttpOnly; SameSite=Lax")
                        self.send_header("Location", f"/?token={token}&auth=success")
                        self.end_headers()
                        return
            except Exception as e:
                print(f"[GoogleOAuth] Exchange error: {e}")

            self.send_response(302)
            self.send_header("Location", "/?error=oauth_exchange_failed")
            self.end_headers()
            return

        # Public or Authenticated API: IE / WebComponents Native Portal & Proxy (/api/cameras/<id>/ie-portal, /ie-plugin, /ie-proxy/...)
        if path.startswith("/api/cameras/") and ("/ie-portal" in path or "/ie-plugin" in path or "/ie-proxy/" in path or "/WebComponents.exe" in path):
            parts = path.split("/")
            cam_id = parts[3] if len(parts) > 3 else ""
            cam = config_manager.get_camera(cam_id)
            if not cam and cam_id == "direct":
                cam = {
                    "id": "direct",
                    "name": query.get("name", ["Legacy IE Camera"])[0],
                    "ip": query.get("ip", ["192.168.1.13"])[0],
                    "port": int(query.get("port", ["554"])[0] or 554),
                    "username": query.get("username", ["admin"])[0],
                    "password": query.get("password", ["Hik@1234"])[0],
                    "vendor": query.get("vendor", ["hikvision"])[0],
                    "channel": int(query.get("channel", ["1"])[0] or 1),
                }
            if not cam:
                self.send_json({"error": "Camera not found"}, 404)
                return

            if path.endswith("/ie-plugin") or path.endswith("/WebComponents.exe"):
                self.serve_camera_ie_plugin(cam)
                return
            if "/ie-proxy/" in path:
                sub_path = "/" + path.split("/ie-proxy/", 1)[1]
                if parsed.query:
                    # Strip internal token param before forwarding to camera
                    clean_qs = "&".join(p for p in parsed.query.split("&") if not p.startswith("token="))
                    if clean_qs:
                        sub_path += "?" + clean_qs
                self.proxy_camera_http(cam, sub_path)
                return
            self.serve_ie_portal(cam, query)
            return

        # Camera Root Fallback Proxy for Native IE Web UI (/doc/*, /ISAPI/*, /SDK/*, /codebase/*)
        # Allows the camera's built-in IE web interface (preview.asp, login.asp, websdk.js) to work
        # seamlessly over Tailscale (hp250.tailccebcc.ts.net) and remote tunnels!
        if path.startswith(("/doc/", "/ISAPI/", "/SDK/", "/PSIA/", "/codebase/")) or path == "/WebComponents.exe":
            cam = config_manager.get_camera("cam-hikvision-13")
            if not cam:
                all_cams = config_manager.get_all_cameras()
                cam = next((c for c in all_cams if not c.get("is_simulated") and c.get("ip")), None) or {
                    "id": "cam-hikvision-13",
                    "ip": "192.168.1.13",
                    "username": "admin",
                    "password": "Hik@1234",
                }
            if path.endswith("/WebComponents.exe"):
                self.serve_camera_ie_plugin(cam)
                return
            sub_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_camera_http(cam, sub_path)
            return

        # Public or Authenticated API: Camera Stream, Snapshot & Status (so Edge IE Mode / direct links work seamlessly)
        if path.startswith("/api/cameras/") and path.endswith("/status"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            self.send_json(session.get_status())
            return

        if path.startswith("/api/cameras/") and path.endswith("/stream"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            self.serve_mjpeg_stream(session)
            return

        if path.startswith("/api/cameras/") and path.endswith("/snapshot"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            live = session.get_status()
            frame = session.get_latest_frame()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            # Allow short in-memory reuse for identical timestamped URLs so preload -> img.src
            # does not trigger a second 170KB download over Cloudflare tunnels!
            has_cache_buster = "_t" in query or "t" in query
            self.send_header("Cache-Control", "private, max-age=5" if has_cache_buster else "no-cache")
            self.send_cors_headers()
            self.send_header("X-Camera-Status", live["status"])
            self.send_header("X-Camera-Online", "true" if live["online"] else "false")
            self.send_header("Access-Control-Expose-Headers", "X-Camera-Status, X-Camera-Online")
            self.end_headers()
            self.wfile.write(frame)
            return

        # Protect all remaining /api/* endpoints
        if path.startswith("/api/"):
            session = self.get_authenticated_user(query)
            if not session:
                self.send_json({"error": "Unauthorized", "auth_required": True}, 401)
                return

        # API: Get all cameras
        if path == "/api/cameras":
            cameras = []
            for cam in config_manager.get_all_cameras():
                enriched = dict(cam)
                session = stream_manager.get_session(cam["id"])
                enriched["live_status"] = session.get_status() if session else None
                cameras.append(enriched)
            layout = config_manager.get_layout()
            groups = config_manager.get_groups()
            self.send_json({
                "cameras": cameras,
                "layout": layout,
                "groups": groups
            })
            return

        # API: Get single camera (/api/cameras/<id>)
        if path.startswith("/api/cameras/") and path.count("/") == 3:
            cam_id = path.split("/")[3]
            cam = config_manager.get_camera(cam_id)
            if cam:
                enriched = dict(cam)
                session = stream_manager.get_session(cam_id)
                enriched["live_status"] = session.get_status() if session else None
                self.send_json(enriched)
            else:
                self.send_json({"error": "Camera not found"}, 404)
            return

        # API: 24-Hour Timeline Events
        if path.startswith("/api/cameras/") and path.endswith("/timeline"):
            cam_id = path.split("/")[3]
            date_param = query.get("date", [""])[0]
            events = recorder_manager.get_timeline_events(cam_id, date_param)
            self.send_json(events)
            return

        # API:Historical Playback Frame
        if path.startswith("/api/cameras/") and path.endswith("/playback"):
            cam_id = path.split("/")[3]
            try:
                time_val = float(query.get("time", ["0"])[0])
            except (ValueError, TypeError):
                time_val = 0.0
            frame = recorder_manager.get_playback_frame(cam_id, time_val)
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_json({"error": "Failed to render playback frame"}, 500)
            return

        # API: Get Presets
        if path == "/api/presets":
            self.send_json(VENDOR_PRESETS)
            return

        # API: Discovery Scan
        if path == "/api/discovery/scan":
            subnet_param = query.get("subnet", [""])[0].strip()
            result = run_full_discovery(subnet_base=subnet_param)
            self.send_json(result)
            return

        # API: Enumerate System Webcams (DirectShow / V4L2)
        if path == "/api/system/webcams":
            cams = list_system_webcams()
            self.send_json(cams)
            return

        # API: Snapshots list
        if path == "/api/snapshots":
            snaps = recorder_manager.list_snapshots()
            self.send_json(snaps)
            return

        # API: Serve Snapshot image file
        if path.startswith("/api/snapshots/"):
            filename = os.path.basename(path[len("/api/snapshots/"):])
            filepath = os.path.join(SNAPSHOTS_DIR, filename)
            if os.path.exists(filepath):
                self.serve_file(filepath, "image/jpeg")
            else:
                self.send_json({"error": "Snapshot not found"}, 404)
            return

        self.send_json({"error": "Endpoint not found"}, 404)

    def do_POST(self):
        parsed = self._normalize_path()
        if parsed is None:
            return
        path = parsed.path
        body_data = self.read_json_body()

        # Auth API: Login
        if path == "/api/auth/login":
            username = body_data.get("username", "")
            password = body_data.get("password", "")
            session_info = config_manager.authenticate_user(username, password)
            if session_info:
                self.send_json({
                    "status": "ok",
                    "token": session_info["token"],
                    "username": session_info["username"],
                    "expires_at": session_info["expires_at"]
                })
            else:
                self.send_json({"error": "Invalid username or password"}, 401)
            return

        # Auth API: Google Sign-In
        if path == "/api/auth/google":
            credential = body_data.get("credential", "")
            google_email = body_data.get("email", "").strip()

            if credential:
                client_id = config_manager.get_google_client_id() or body_data.get("client_id", "")
                id_info = verify_google_token(credential, client_id)
                if not id_info:
                    self.send_json({"error": "Invalid or expired Google token"}, 401)
                    return
                email = id_info.get("email", "")
                name = id_info.get("name", email.split("@")[0] if email else "Google User")
                picture = id_info.get("picture", "")
            elif google_email and ("@" in google_email):
                # Direct Google Account Sign-In (when OAuth Client ID is not yet configured)
                email = google_email.lower()
                name = body_data.get("name", email.split("@")[0].capitalize())
                picture = body_data.get("picture", "")
            else:
                self.send_json({"error": "Google ID token credential or valid Google email is required"}, 400)
                return

            session_info = config_manager.authenticate_google_user(email=email, name=name, picture=picture)
            self.send_json({
                "status": "ok",
                "token": session_info["token"],
                "username": session_info["username"],
                "email": session_info.get("email"),
                "name": session_info.get("name"),
                "picture": session_info.get("picture"),
                "auth_type": "google",
                "expires_at": session_info["expires_at"]
            })
            return

        # Auth API: Logout
        if path == "/api/auth/logout":
            token = self.extract_token()
            if token:
                config_manager.logout_session(token)
            self.send_json({"status": "logged_out"})
            return

        # Protect all remaining POST /api/* endpoints
        session = self.get_authenticated_user()
        if not session:
            self.send_json({"error": "Unauthorized", "auth_required": True}, 401)
            return

        # Auth API: Configure Google OAuth Client ID
        if path == "/api/auth/google-config":
            new_client_id = body_data.get("client_id", "")
            config_manager.set_google_client_id(new_client_id)
            self.send_json({"status": "ok", "google_client_id": config_manager.get_google_client_id()})
            return

        # Auth API: Change Password
        if path == "/api/auth/change-password":
            old_pass = body_data.get("old_password", "")
            new_pass = body_data.get("new_password", "")
            if not old_pass or not new_pass:
                self.send_json({"error": "old_password and new_password are required"}, 400)
                return
            success = config_manager.change_password(session["username"], old_pass, new_pass)
            if success:
                self.send_json({"status": "ok", "message": "Password updated successfully"})
            else:
                self.send_json({"error": "Invalid current password"}, 400)
            return

        # API: 4G Cloud Relay Toggle
        if path == "/api/cloud-relay/toggle":
            enable = body_data.get("enable", True)
            if enable:
                cloud_relay_manager.start()
            else:
                cloud_relay_manager.stop()
            self.send_json(cloud_relay_manager.get_status())
            return

        # API: 4G Cloud Relay Restart
        if path == "/api/cloud-relay/restart":
            cloud_relay_manager.restart()
            self.send_json(cloud_relay_manager.get_status())
            return

        # API: Add camera
        if path == "/api/cameras":
            if not body_data or "name" not in body_data:
                self.send_json({"error": "Name is required"}, 400)
                return
            
            # If vendor preset is specified, construct stream URL if missing
            vendor = body_data.get("vendor", "generic_rtsp")
            ip = body_data.get("ip", "")
            if "stream_url" not in body_data or not body_data["stream_url"]:
                body_data["stream_url"] = build_stream_url(
                    preset_id=vendor,
                    ip=ip,
                    port=int(body_data.get("port", 554)),
                    username=body_data.get("username", ""),
                    password=body_data.get("password", ""),
                    channel=body_data.get("channel", 1),
                    stream_type="main"
                )

            new_cam = config_manager.add_camera(body_data)
            stream_manager.refresh_cameras()
            self.send_json(new_cam, 201)
            return

        # API: Bulk Import CCTV DVR Channels
        if path == "/api/dvr/import":
            vendor = body_data.get("vendor", "hikvision_dvr")
            ip = body_data.get("ip", "")
            port = int(body_data.get("port", 554))
            username = body_data.get("username", "admin")
            password = body_data.get("password", "")
            num_channels = int(body_data.get("channels", 4))
            group = body_data.get("group", "CCTV DVR")
            dvr_label = body_data.get("label", "DVR")

            created_cameras = []
            for ch in range(1, num_channels + 1):
                main_url = build_stream_url(
                    preset_id=vendor,
                    ip=ip,
                    port=port,
                    username=username,
                    password=password,
                    channel=ch,
                    stream_type="main"
                )
                sub_url = build_stream_url(
                    preset_id=vendor,
                    ip=ip,
                    port=port,
                    username=username,
                    password=password,
                    channel=ch,
                    stream_type="sub"
                )
                cam_payload = {
                    "name": f"{dvr_label} Ch {ch:02d} (BNC)",
                    "group": group,
                    "vendor": vendor,
                    "channel": ch,
                    "ip": ip,
                    "port": port,
                    "username": username,
                    "password": password,
                    "stream_url": main_url,
                    "sub_stream_url": sub_url,
                    "ptz": True,
                    "is_simulated": False
                }
                added = config_manager.add_camera(cam_payload)
                created_cameras.append(added)

            stream_manager.refresh_cameras()
            self.send_json({
                "status": "ok",
                "imported_count": len(created_cameras),
                "cameras": created_cameras
            }, 201)
            return

        # API: PTZ Control
        if path.startswith("/api/cameras/") and path.endswith("/ptz"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            action = body_data.get("action", "home")
            session.adjust_ptz(action)
            self.send_json({
                "status": "ok",
                "camera_id": cam_id,
                "action": action,
                "pan": session.pan,
                "tilt": session.tilt,
                "zoom": session.zoom,
                "night_vision": getattr(session, "night_vision", "auto"),
                "siren_active": getattr(session, "siren_active", False),
                "intercom_active": getattr(session, "intercom_active", False),
                "auto_tracking": getattr(session, "auto_tracking", False),
                "presets": getattr(session, "presets", {})
            })
            return

        # API: V380 Pro / V360 Pro Smart Controls (Night Vision, Siren, Intercom, Presets, Auto-Tracking, Reboot, Sync Time)
        if path.startswith("/api/cameras/") and path.endswith("/control"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            ctrl_type = body_data.get("type", "")
            val = body_data.get("value", "")

            if ctrl_type == "night_vision":
                session.set_night_vision(str(val))
            elif ctrl_type == "siren":
                session.trigger_siren(duration=float(body_data.get("duration", 3.0)))
            elif ctrl_type == "intercom":
                session.set_intercom(bool(val))
            elif ctrl_type == "auto_tracking":
                session.set_auto_tracking(bool(val))
            elif ctrl_type == "save_preset":
                session.save_preset(int(val))
            elif ctrl_type == "goto_preset":
                session.goto_preset(int(val))
            elif ctrl_type in ("reboot", "sync_time", "toggle_ir", "day_night"):
                hw_res = session.execute_hardware_command(command=ctrl_type, mode=str(val or "auto"))
                self.send_json(hw_res)
                return

            self.send_json({
                "status": "ok",
                "camera_id": cam_id,
                "night_vision": session.night_vision,
                "siren_active": session.siren_active,
                "intercom_active": session.intercom_active,
                "auto_tracking": session.auto_tracking,
                "pan": session.pan,
                "tilt": session.tilt,
                "zoom": session.zoom,
                "presets": session.presets
            })
            return

        # API: V380 / V360 Pro Intercom Microphone Audio Streaming (Talkback)
        if path.startswith("/api/cameras/") and path.endswith("/talk"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            audio_base64 = body_data.get("audio_base64", "")
            audio_fmt = body_data.get("format", "webm")
            audio_bytes = b""
            if audio_base64:
                import base64
                try:
                    audio_bytes = base64.b64decode(audio_base64)
                except Exception:
                    audio_bytes = b""
            res = session.receive_audio_chunk(audio_bytes, audio_fmt)
            self.send_json(res)
            return

        # API: Capture and save snapshot
        if path == "/api/snapshots/capture":
            cam_id = body_data.get("camera_id")
            if not cam_id:
                self.send_json({"error": "camera_id is required"}, 400)
                return
            snap = recorder_manager.capture_snapshot(cam_id)
            if snap:
                self.send_json(snap, 201)
            else:
                self.send_json({"error": "Failed to capture snapshot"}, 500)
            return

        # API: Build Stream URL Helper
        if path == "/api/presets/generate":
            url = build_stream_url(
                preset_id=body_data.get("vendor", "generic_rtsp"),
                ip=body_data.get("ip", "192.168.1.100"),
                port=int(body_data.get("port", 554)),
                username=body_data.get("username", ""),
                password=body_data.get("password", ""),
                channel=body_data.get("channel", 1),
                stream_type=body_data.get("stream_type", "main")
            )
            self.send_json({"stream_url": url})
            return

        # API: Change layout
        if path == "/api/layout":
            layout = body_data.get("layout", "2x2")
            config_manager.set_layout(layout)
            self.send_json({"status": "ok", "layout": layout})
            return

        # API: Universal Camera Prober & Auto-Detection Diagnostic
        if path == "/api/cameras/probe":
            ip = body_data.get("ip", "").strip()
            port = body_data.get("port")
            if port:
                try:
                    port = int(port)
                except ValueError:
                    port = None
            username = body_data.get("username", "").strip()
            password = body_data.get("password", "")
            vendor_hint = body_data.get("vendor", "")
            channel = body_data.get("channel", 1)

            probe_res = probe_camera_connection(
                ip=ip,
                port=port,
                username=username,
                password=password,
                vendor_hint=vendor_hint,
                channel=channel
            )
            self.send_json(probe_res)
            return

        # API: Zero-IE Direct Hardware Control (Reboot, Sync Clock, Toggle IR)
        if path == "/api/cameras/hardware-control":
            cmd = body_data.get("command", "").strip()
            ip = body_data.get("ip", "").strip()
            vendor = body_data.get("vendor", "hikvision").strip()
            username = body_data.get("username", "admin").strip()
            password = body_data.get("password", "")
            mode = body_data.get("mode", "auto").strip()
            cam_id = body_data.get("camera_id", "").strip()

            # Match camera session by id or IP if one is registered in the matrix
            session = stream_manager.get_session(cam_id) if cam_id else None
            if not session and ip:
                for c in config_manager.get_all_cameras():
                    if c.get("ip") == ip:
                        session = stream_manager.get_session(c["id"])
                        break

            if session:
                res = session.execute_hardware_command(
                    command=cmd,
                    ip_override=ip,
                    vendor_override=vendor,
                    username_override=username,
                    password_override=password,
                    mode=mode,
                )
            else:
                try:
                    from .stream_proxy import CameraStreamSession
                except (ImportError, ValueError):
                    from stream_proxy import CameraStreamSession
                temp_session = CameraStreamSession({
                    "id": "ctrl-direct",
                    "name": f"Direct Camera ({ip})",
                    "ip": ip,
                    "vendor": vendor,
                    "username": username,
                    "password": password,
                    "is_simulated": ip.startswith("127.") or ip == "localhost",
                })
                res = temp_session.execute_hardware_command(
                    command=cmd,
                    ip_override=ip,
                    vendor_override=vendor,
                    username_override=username,
                    password_override=password,
                    mode=mode,
                )
            status_code = 400 if res.get("status") == "error" else 200
            self.send_json(res, status_code)
            return

        # API: Ingest Live Frame from Browser Camera Node
        if path.startswith("/api/cameras/") and path.endswith("/ingest"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            frame_b64 = body_data.get("frame_base64", "")
            if frame_b64:
                import base64
                if "," in frame_b64:
                    frame_b64 = frame_b64.split(",", 1)[1]
                try:
                    raw_bytes = base64.b64decode(frame_b64)
                    session.push_frame(raw_bytes)
                    self.send_json({"status": "ok", "bytes": len(raw_bytes)})
                    return
                except Exception as e:
                    self.send_json({"error": f"Failed to decode frame: {e}"}, 400)
                    return
            self.send_json({"error": "frame_base64 is required"}, 400)
            return

        # Camera Root Fallback Proxy for Native IE Web UI (/ISAPI/*, /SDK/*)
        if path.startswith(("/ISAPI/", "/SDK/", "/PSIA/")) or "/ie-proxy/" in path:
            raw_body = self.read_raw_body()
            ctype = self.headers.get("Content-Type", "application/xml")
            cam = config_manager.get_camera("cam-hikvision-13") or {
                "id": "cam-hikvision-13",
                "ip": "192.168.1.13",
                "username": "admin",
                "password": "Hik@1234",
            }
            sub_path = "/" + path.split("/ie-proxy/", 1)[1] if "/ie-proxy/" in path else path
            if parsed.query:
                clean_qs = "&".join(p for p in parsed.query.split("&") if not p.startswith("token="))
                if clean_qs:
                    sub_path += "?" + clean_qs
            self.proxy_camera_http(cam, sub_path, method="POST", body=raw_body, content_type=ctype)
            return

        self.send_json({"error": "Endpoint not found"}, 404)

    def do_PUT(self):
        parsed = self._normalize_path()
        if parsed is None:
            return
        path = parsed.path

        # Camera Root Fallback Proxy for Native IE Web UI PUT commands (/ISAPI/*, /SDK/*)
        if path.startswith(("/ISAPI/", "/SDK/", "/PSIA/")) or "/ie-proxy/" in path:
            raw_body = self.read_raw_body()
            ctype = self.headers.get("Content-Type", "application/xml")
            cam = config_manager.get_camera("cam-hikvision-13") or {
                "id": "cam-hikvision-13",
                "ip": "192.168.1.13",
                "username": "admin",
                "password": "Hik@1234",
            }
            sub_path = "/" + path.split("/ie-proxy/", 1)[1] if "/ie-proxy/" in path else path
            if parsed.query:
                clean_qs = "&".join(p for p in parsed.query.split("&") if not p.startswith("token="))
                if clean_qs:
                    sub_path += "?" + clean_qs
            self.proxy_camera_http(cam, sub_path, method="PUT", body=raw_body, content_type=ctype)
            return

        body_data = self.read_json_body()

        # Protect all PUT /api/* endpoints
        session = self.get_authenticated_user()
        if not session:
            self.send_json({"error": "Unauthorized", "auth_required": True}, 401)
            return

        if path.startswith("/api/cameras/"):
            cam_id = path.split("/")[3]
            updated = config_manager.update_camera(cam_id, body_data)
            if updated:
                stream_manager.refresh_cameras()
                self.send_json(updated)
            else:
                self.send_json({"error": "Camera not found"}, 404)
            return

        self.send_json({"error": "Endpoint not found"}, 404)

    def do_DELETE(self):
        parsed = self._normalize_path()
        if parsed is None:
            return
        path = parsed.path

        # Protect all DELETE /api/* endpoints
        session = self.get_authenticated_user()
        if not session:
            self.send_json({"error": "Unauthorized", "auth_required": True}, 401)
            return

        if path.startswith("/api/cameras/"):
            cam_id = path.split("/")[3]
            success = config_manager.delete_camera(cam_id)
            if success:
                stream_manager.refresh_cameras()
                self.send_json({"status": "deleted", "camera_id": cam_id})
            else:
                self.send_json({"error": "Camera not found"}, 404)
            return

        if path.startswith("/api/snapshots/"):
            filename = os.path.basename(path[len("/api/snapshots/"):])
            if recorder_manager.delete_snapshot(filename):
                self.send_json({"status": "deleted", "filename": filename})
            else:
                self.send_json({"error": "Snapshot file not found"}, 404)
            return

        self.send_json({"error": "Endpoint not found"}, 404)

    def read_raw_body(self) -> Optional[bytes]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                return self.rfile.read(content_length)
        except Exception:
            pass
        return None

    def read_json_body(self) -> Dict[str, Any]:
        try:
            raw = self.read_raw_body()
            if raw:
                return json.loads(raw.decode("utf-8"))
        except Exception:
            pass
        return {}

    def serve_file(self, file_path: str, mime: str):
        if not os.path.exists(file_path):
            self.send_error(404, "File Not Found")
            return
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def serve_mjpeg_stream(self, session):
        """Streams continuous multipart/x-mixed-replace JPEG frames to client with zero-delay socket tuning."""
        try:
            import socket
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Cap kernel socket send buffer to ~64KB so old frames cannot queue up in transit
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        except Exception:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, no-transform")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.send_cors_headers()
        self.end_headers()

        cam_fps = int(session.camera_info.get("fps", 20) or 20)
        target_fps = min(30, max(5, cam_fps))
        frame_interval = 1.0 / target_fps
        last_frame_bytes = None

        with session._lock:
            session.active_subscribers += 1
        try:
            while True:
                t0 = time.time()
                frame = session.get_latest_frame()

                if frame is not last_frame_bytes:
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                    )
                    self.wfile.write(header)
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    last_frame_bytes = frame

                elapsed = time.time() - t0
                sleep_time = max(0.01, frame_interval - elapsed)
                time.sleep(sleep_time)
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected gracefully
            pass
        except Exception:
            # Handle client close
            pass
        finally:
            with session._lock:
                session.active_subscribers = max(0, session.active_subscribers - 1)

    def _build_camera_opener(self, ip: str, http_port: int, username: str, password: str):
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        base_uri = f"http://{ip}:{http_port}/"
        mgr.add_password(None, base_uri, username, password)
        mgr.add_password(None, f"http://{ip}/", username, password)
        return urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(mgr),
            urllib.request.HTTPBasicAuthHandler(mgr),
        )

    def serve_camera_ie_plugin(self, cam: Dict[str, Any]):
        """Proxies or downloads WebComponents.exe / ActiveX cab installer directly from the camera."""
        ip = (cam.get("ip") or "192.168.1.13").strip()
        username = cam.get("username") or "admin"
        password = cam.get("password") or ""
        opener = self._build_camera_opener(ip, 80, username, password)
        for plugin_path in ("/codebase/WebComponents.exe", "/WebComponents.exe", "/doc/codebase/WebComponents.exe"):
            try:
                url = f"http://{ip}:80{plugin_path}"
                with opener.open(url, timeout=10.0) as resp:
                    data = resp.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", 'attachment; filename="WebComponents.exe"')
                    self.send_header("Content-Length", str(len(data)))
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception:
                continue
        self.send_json({"error": f"ActiveX installer WebComponents.exe not found on {ip}"}, 404)

    def proxy_camera_http(
        self,
        cam: Dict[str, Any],
        sub_path: str,
        method: str = "GET",
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ):
        """Authenticated HTTP proxy to the camera's native web interface (ISAPI / doc / codebase)."""
        import base64
        cam_id = cam.get("id", "cam-hikvision-13")
        ip = (cam.get("ip") or "192.168.1.13").strip()
        # Fast-path for High-Res ISAPI picture requests: if our RTSP 101 high-res engine already
        # has a fresh 1920x1080 frame in memory, serve it in <1ms instead of waiting 3-9s on camera HTTP CGI!
        if method == "GET" and "/picture" in sub_path.lower() and "direct=1" not in sub_path.lower():
            session = stream_manager.get_session(cam_id)
            if not session and ip:
                for c in config_manager.get_all_cameras():
                    if c.get("ip") == ip:
                        session = stream_manager.get_session(c["id"])
                        if session:
                            break
            if session and session.connection_status == "streaming" and session._latest_jpeg:
                frame = session.get_latest_frame()
                if frame and len(frame) > 15000:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.send_header("Cache-Control", "private, max-age=5")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(frame)
                    return

        username = cam.get("username") or "admin"
        password = cam.get("password") or "Hik@1234"
        opener = self._build_camera_opener(ip, 80, username, password)
        target_url = f"http://{ip}:80{sub_path}"
        basic_b64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MSIE 11.0; Windows NT 10.0; WOW64; Trident/7.0)",
            "Authorization": f"Basic {basic_b64}",
        }
        if content_type:
            headers["Content-Type"] = content_type
        try:
            req = urllib.request.Request(target_url, data=body, headers=headers, method=method)
            with opener.open(req, timeout=15.0) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                # Auto-inject sessionStorage userInfo into preview.asp so the camera's native IE web UI
                # never redirects to login.asp and immediately authenticates WebSDK & WebComponents ActiveX,
                # plus polyfills #plugin with live 1080p video in non-ActiveX browsers!
                if sub_path.startswith("/doc/page/preview.asp") and b"<head>" in data:
                    user_info_b64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
                    inject_script = (
                        f"<script>"
                        f"try{{sessionStorage.setItem('userInfo','{user_info_b64}');"
                        f"document.cookie='language=en; path=/';}}catch(e){{}}"
                        f"if(!('ActiveXObject' in window)){{"
                        f"window.addEventListener('load',function(){{setTimeout(function(){{"
                        f"var p=document.getElementById('main_plugin')||document.getElementById('plugin');"
                        f"if(p){{p.innerHTML='<img id=\"omnisightPolyfillImg\" style=\"width:100%;height:100%;object-fit:contain;background:#000;display:block;\" />';"
                        f"var im=document.getElementById('omnisightPolyfillImg');"
                        f"function tick(){{var pre=new Image();pre.onload=function(){{im.src=pre.src;setTimeout(tick,80);}};pre.onerror=function(){{setTimeout(tick,800);}};pre.src='/api/cameras/cam-hikvision-13/snapshot?_t='+new Date().getTime();}}"
                        f"tick();}}"
                        f"}},1200);}});"
                        f"}}"
                        f"</script>"
                    ).encode("utf-8")
                    data = data.replace(b"<head>", b"<head>" + inject_script, 1)
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-UA-Compatible", "IE=EmulateIE11")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err_body = b""
            try:
                err_body = e.read()
            except Exception:
                pass
            if err_body:
                self.send_response(e.code)
                self.send_header("Content-Type", e.headers.get("Content-Type", "application/xml"))
                self.send_header("Content-Length", str(len(err_body)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(err_body)
            else:
                self.send_json({"error": f"Camera returned HTTP {e.code}", "url": target_url}, e.code)
        except Exception as e:
            self.send_json({"error": f"Camera proxy error: {e}", "url": target_url}, 502)

    def serve_ie_portal(self, cam: Dict[str, Any], query: Dict[str, list]):
        """Serves a dedicated IE / Edge IE Mode & ActiveX (WebComponents.exe) compatibility portal for the camera."""
        import base64
        token = self.extract_token(query) or ""
        cam_id = cam.get("id", "cam-hikvision-13")
        cam_name = cam.get("name", "Camera")
        ip = (cam.get("ip") or "192.168.1.13").strip()
        rtsp_port = int(cam.get("port", 554) or 554)
        username = cam.get("username") or "admin"
        password = cam.get("password") or ""
        channel = int(cam.get("channel", 1) or 1)
        plugin_auth = base64.b64encode(f":{username}:{password}".encode("utf-8")).decode("ascii")
        basic_auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        rtsp_main = f"rtsp://{ip}:{rtsp_port}/ISAPI/streaming/channels/{channel}01"
        rtsp_sub = f"rtsp://{ip}:{rtsp_port}/ISAPI/streaming/channels/{channel}02"
        stream_url = f"/api/cameras/{cam_id}/stream?token={urllib.parse.quote(token)}"
        snap_url = f"/api/cameras/{cam_id}/snapshot?token={urllib.parse.quote(token)}"
        isapi_snap_url = f"/api/cameras/{cam_id}/ie-proxy/ISAPI/Streaming/channels/{channel}01/picture?token={urllib.parse.quote(token)}"
        plugin_dl_url = f"/api/cameras/{cam_id}/ie-plugin?token={urllib.parse.quote(token)}"
        initial_mode = (query.get("mode", [""])[0] or "").strip().lower()

        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge,EmulateIE11" />
  <title>{cam_name} — OmniSight NVR · IE / ActiveX &amp; Universal Stream Portal</title>
  <style>
    body {{ margin: 0; background: #000000; color: #f5f5f7; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif; display: flex; flex-direction: column; height: 100vh; overflow: hidden; -webkit-font-smoothing: antialiased; }}
    .ie-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 18px; background: rgba(28, 28, 30, 0.82); -webkit-backdrop-filter: blur(28px) saturate(190%); backdrop-filter: blur(28px) saturate(190%); border-bottom: 1px solid rgba(255,255,255,0.12); font-size: 12px; flex-wrap: wrap; }}
    .ie-title {{ font-weight: 600; color: #f5f5f7; display: flex; align-items: center; gap: 10px; letter-spacing: -0.01em; }}
    .ie-badge {{ background: rgba(10, 132, 255, 0.16); color: #64d2ff; border: 1px solid rgba(10, 132, 255, 0.38); padding: 3px 9px; border-radius: 980px; font-size: 11px; font-weight: 600; }}
    .ie-actions {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .ie-btn {{ background: rgba(255,255,255,0.08); color: #f5f5f7; border: 1px solid rgba(255,255,255,0.14); padding: 6px 12px; border-radius: 980px; font-size: 11px; font-weight: 500; cursor: pointer; text-decoration: none; transition: all 0.18s ease; }}
    .ie-btn:hover, .ie-btn.active {{ background: #0a84ff; border-color: #0a84ff; color: #ffffff; box-shadow: 0 2px 10px rgba(10, 132, 255, 0.35); }}
    .ie-stage {{ flex: 1; position: relative; display: flex; align-items: center; justify-content: center; background: #000000; overflow: hidden; }}
    .ie-stage img {{ width: 100%; height: 100%; object-fit: contain; }}
    .ie-status {{ position: absolute; bottom: 14px; left: 16px; background: rgba(28, 28, 30, 0.78); -webkit-backdrop-filter: blur(20px); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.14); padding: 6px 12px; border-radius: 980px; font-size: 11px; font-family: "SF Mono", Menlo, Consolas, monospace; color: #30d158; pointer-events: none; }}
  </style>
</head>
<body>
  <div class="ie-bar">
    <div class="ie-title">
      <span> {cam_name} ({ip})</span>
      <span class="ie-badge" id="engineBadge">Engine: Auto</span>
    </div>
    <div class="ie-actions">
      <button type="button" class="ie-btn" id="btnModeActiveX" onclick="switchEngine('activex')">🪟 IE ActiveX (WebComponents)</button>
      <button type="button" class="ie-btn" id="btnModeStream" onclick="switchEngine('mjpeg')">⚡ Live Stream</button>
      <button type="button" class="ie-btn" id="btnModeSnap" onclick="switchEngine('snapshot')">📸 High-Res ISAPI (1080p)</button>
      <button type="button" class="ie-btn" id="btnModeWebUi" onclick="switchEngine('webui')">🖥️ Embedded Camera Web UI</button>
      <a class="ie-btn" href="{plugin_dl_url}" download="WebComponents.exe" title="Download official Hikvision WebComponents.exe ActiveX plugin from camera">⬇ WebComponents.exe</a>
      <a class="ie-btn" href="http://{ip}/doc/page/preview.asp" target="_blank" rel="noopener" title="Open camera's built-in IE web page directly on LAN">↗ Direct Camera UI ({ip})</a>
    </div>
  </div>
  <div class="ie-stage" id="stageContainer">
    <div id="pluginHost" style="width:100%;height:100%;display:none;"></div>
    <iframe id="webUiFrame" src="about:blank" style="width:100%;height:100%;border:0;display:none;background:#000;"></iframe>
    <img id="liveImg" alt="{cam_name}" style="display:none;" />
    <div class="ie-status" id="statusHud">Initializing stream...</div>
  </div>
  <script>
    var CAM_IP = "{ip}";
    var PLUGIN_AUTH = "{plugin_auth}";
    var BASIC_AUTH = "{basic_auth}";
    var RTSP_MAIN = "{rtsp_main}";
    var RTSP_SUB = "{rtsp_sub}";
    var STREAM_URL = "{stream_url}";
    var SNAP_URL = "{snap_url}";
    var ISAPI_SNAP_URL = "{isapi_snap_url}";
    var INITIAL_MODE = "{initial_mode}";
    var pollTimer = null;
    var engineEpoch = 0;

    function isIEOrActiveXSupported() {{
      return ("ActiveXObject" in window) || /MSIE|Trident/i.test(navigator.userAgent);
    }}

    function switchEngine(mode) {{
      engineEpoch += 1;
      var myEpoch = engineEpoch;
      if (pollTimer) {{ clearTimeout(pollTimer); pollTimer = null; }}
      var pluginHost = document.getElementById("pluginHost");
      var webUiFrame = document.getElementById("webUiFrame");
      var liveImg = document.getElementById("liveImg");
      var badge = document.getElementById("engineBadge");
      var hud = document.getElementById("statusHud");
      document.getElementById("btnModeActiveX").className = "ie-btn" + (mode === "activex" ? " active" : "");
      document.getElementById("btnModeStream").className = "ie-btn" + (mode === "mjpeg" ? " active" : "");
      document.getElementById("btnModeSnap").className = "ie-btn" + (mode === "snapshot" ? " active" : "");
      document.getElementById("btnModeWebUi").className = "ie-btn" + (mode === "webui" ? " active" : "");

      if (mode === "webui") {{
        liveImg.style.display = "none";
        liveImg.removeAttribute("src");
        pluginHost.style.display = "none";
        pluginHost.innerHTML = "";
        webUiFrame.style.display = "block";
        try {{
          sessionStorage.setItem("userInfo", BASIC_AUTH);
          document.cookie = "language=en; path=/";
        }} catch (e) {{}}
        webUiFrame.src = "/doc/page/preview.asp";
        badge.innerHTML = "Camera Native IE Web UI (Proxied)";
        hud.innerHTML = "Loaded native camera IE UI via Hub proxy (/doc/page/preview.asp) — Live 1080p Active";
        return;
      }}

      webUiFrame.style.display = "none";
      webUiFrame.src = "about:blank";

      if (mode === "activex") {{
        liveImg.style.display = "none";
        liveImg.removeAttribute("src");
        pluginHost.style.display = "block";
        badge.innerHTML = "IE ActiveX (clsid:E7EF736D)";
        pluginHost.innerHTML = "<object classid='clsid:E7EF736D-B4E6-4A5A-BA94-732D71107808' codebase='{plugin_dl_url}' standby='Loading Hikvision WebComponents ActiveX...' id='PreviewActiveX' width='100%' height='100%' name='ocx'><param name='wndtype' value='1'><param name='playmode' value='normal'><param name='needborder' value='1'></object>";
        setTimeout(function() {{
          if (myEpoch !== engineEpoch) return;
          var ocx = document.getElementById("PreviewActiveX");
          if (ocx && typeof ocx.HWP_Play !== "undefined") {{
            var rc = ocx.HWP_Play(RTSP_MAIN, PLUGIN_AUTH, 0, "", "");
            hud.innerHTML = rc === 0 ? "ActiveX HWP_Play Connected (" + RTSP_MAIN + ")" : "ActiveX HWP_Play rc=" + rc + " (trying sub-stream)";
            if (rc !== 0) ocx.HWP_Play(RTSP_SUB, PLUGIN_AUTH, 0, "", "");
          }} else {{
            hud.innerHTML = "ActiveX control not loaded in this browser — auto-engaging 1080p High-Res Stream fallback.";
            if (!isIEOrActiveXSupported()) {{
              setTimeout(function() {{
                if (myEpoch !== engineEpoch) return;
                switchEngine("snapshot");
              }}, 700);
            }}
          }}
        }}, 400);
        return;
      }}

      pluginHost.style.display = "none";
      pluginHost.innerHTML = "";
      liveImg.onerror = null;
      liveImg.style.display = "block";

      var isTunnel = location.hostname.indexOf("trycloudflare.com") !== -1 || location.hostname.indexOf("github.io") !== -1;
      var targetSnap = mode === "snapshot" ? ISAPI_SNAP_URL : SNAP_URL;

      function pullNext() {{
        if (myEpoch !== engineEpoch) return;
        var pre = new Image();
        pre.onload = function() {{
          if (myEpoch !== engineEpoch) return;
          liveImg.src = pre.src;
          if (pre.naturalWidth && pre.naturalHeight) {{
            hud.innerHTML = "Live High-Res Stream: " + pre.naturalWidth + "×" + pre.naturalHeight + " Full HD • 24/7 Active";
          }}
          pollTimer = setTimeout(pullNext, mode === "snapshot" ? 75 : 55);
        }};
        pre.onerror = function() {{
          if (myEpoch !== engineEpoch) return;
          pollTimer = setTimeout(pullNext, 600);
        }};
        pre.src = targetSnap + "&_t=" + new Date().getTime();
      }}

      if (mode === "mjpeg" && !isTunnel) {{
        badge.innerHTML = "High-Res MJPEG Stream (1080p)";
        hud.innerHTML = "Streaming live 1920×1080 MJPEG via OmniSight Hub";
        liveImg.onerror = function() {{
          if (myEpoch !== engineEpoch) return;
          liveImg.onerror = null;
          pullNext();
        }};
        liveImg.src = STREAM_URL + "&_t=" + new Date().getTime();
        return;
      }}

      // Reset any active multipart MJPEG connection before starting high-res frame loop
      liveImg.removeAttribute("src");
      badge.innerHTML = mode === "snapshot" ? "High-Res 1080p ISAPI (1920×1080)" : "High-Res 1080p Stream";
      hud.innerHTML = "Connecting to 1920×1080 Full HD stream...";
      pullNext();
    }}

    if (INITIAL_MODE === "activex" || INITIAL_MODE === "mjpeg" || INITIAL_MODE === "snapshot" || INITIAL_MODE === "webui") {{
      switchEngine(INITIAL_MODE);
    }} else if (isIEOrActiveXSupported()) {{
      switchEngine("activex");
    }} else {{
      switchEngine("mjpeg");
    }}
  </script>
</body>
</html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-UA-Compatible", "IE=EmulateIE11")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "0.0.0.0", port: int = 8080, enable_cloud: bool = True):
    cloud_relay_manager.port = port
    if enable_cloud:
        cloud_relay_manager.start()

    server = ThreadingHTTPServer((host, port), OmniSightHandler)
    print("=" * 65)
    print(f"  ✦ OmniSight-NVR Universal Surveillance Hub Online ✦")
    print(f"  Local Web Dashboard: http://localhost:{port}")
    print(f"  Network Dashboard:   http://0.0.0.0:{port}")
    print(f"  4G Cloud Relay:      {'INITIALIZING' if enable_cloud else 'DISABLED'}")
    print(f"  Supported Hardware:  Hikvision, Dahua, Xiongmai (XM), Tapo,")
    print(f"                       Reolink, Yoosee, V380, and Generic ONVIF")
    print("=" * 65)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down OmniSight-NVR...")
    finally:
        cloud_relay_manager.stop()
        server.shutdown()


if __name__ == "__main__":
    port = 8080
    enable_cloud = True
    for arg in sys.argv[1:]:
        if arg == "--no-cloud":
            enable_cloud = False
        elif arg == "--cloud":
            enable_cloud = True
        else:
            try:
                port = int(arg)
            except ValueError:
                pass
    run_server(port=port, enable_cloud=enable_cloud)
