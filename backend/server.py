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

try:
    from .config_manager import ConfigManager
    from .stream_proxy import StreamManager
    from .vendor_presets import VENDOR_PRESETS, build_stream_url
    from .discovery import run_full_discovery
    from .recorder import RecorderManager
    from .cloud_relay import CloudRelayManager
except (ImportError, ValueError):
    from config_manager import ConfigManager
    from stream_proxy import StreamManager
    from vendor_presets import VENDOR_PRESETS, build_stream_url
    from discovery import run_full_discovery
    from recorder import RecorderManager
    from cloud_relay import CloudRelayManager

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
SNAPSHOTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))

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

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Static root
        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
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
            ffmpeg_path = shutil.which("ffmpeg")
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

        # Protect all remaining /api/* endpoints
        if path.startswith("/api/"):
            session = self.get_authenticated_user(query)
            if not session:
                self.send_json({"error": "Unauthorized", "auth_required": True}, 401)
                return

        # API: Get all cameras
        if path == "/api/cameras":
            cameras = config_manager.get_all_cameras()
            layout = config_manager.get_layout()
            groups = config_manager.get_groups()
            self.send_json({
                "cameras": cameras,
                "layout": layout,
                "groups": groups
            })
            return

        # API: Get single camera
        if path.startswith("/api/cameras/") and not path.endswith("/stream") and not path.endswith("/snapshot") and not path.endswith("/ptz"):
            cam_id = path.split("/")[3]
            cam = config_manager.get_camera(cam_id)
            if cam:
                self.send_json(cam)
            else:
                self.send_json({"error": "Camera not found"}, 404)
            return

        # API: Stream Camera (MJPEG boundary stream)
        if path.startswith("/api/cameras/") and path.endswith("/stream"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return

            self.serve_mjpeg_stream(session)
            return

        # API: Snapshot of Camera
        if path.startswith("/api/cameras/") and path.endswith("/snapshot"):
            cam_id = path.split("/")[3]
            session = stream_manager.get_session(cam_id)
            if not session:
                self.send_json({"error": "Camera not found"}, 404)
                return
            frame = session.get_latest_frame()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(frame)
            return

        # API: Get Presets
        if path == "/api/presets":
            self.send_json(VENDOR_PRESETS)
            return

        # API: Discovery Scan
        if path == "/api/discovery/scan":
            result = run_full_discovery()
            self.send_json(result)
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
        parsed = urllib.parse.urlparse(self.path)
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
                "presets": getattr(session, "presets", {})
            })
            return

        # API: V380 Pro / V360 Pro Smart Controls (Night Vision, Siren, Intercom, Presets)
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
            elif ctrl_type == "save_preset":
                session.save_preset(int(val))
            elif ctrl_type == "goto_preset":
                session.goto_preset(int(val))

            self.send_json({
                "status": "ok",
                "camera_id": cam_id,
                "night_vision": session.night_vision,
                "siren_active": session.siren_active,
                "intercom_active": session.intercom_active,
                "pan": session.pan,
                "tilt": session.tilt,
                "zoom": session.zoom,
                "presets": session.presets
            })
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

        self.send_json({"error": "Endpoint not found"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
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
        parsed = urllib.parse.urlparse(self.path)
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

    def read_json_body(self) -> Dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode("utf-8")
                return json.loads(body)
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
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def serve_mjpeg_stream(self, session):
        """Streams continuous multipart/x-mixed-replace JPEG frames to client."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        target_fps = max(10, session.camera_info.get("fps", 25))
        frame_interval = 1.0 / target_fps

        try:
            while True:
                t0 = time.time()
                frame = session.get_latest_frame()
                
                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")

                elapsed = time.time() - t0
                sleep_time = max(0.01, frame_interval - elapsed)
                time.sleep(sleep_time)
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected gracefully
            pass
        except Exception as e:
            # Handle client close
            pass


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
