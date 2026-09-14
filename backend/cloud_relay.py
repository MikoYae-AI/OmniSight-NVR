"""
OmniSight-NVR - 4G Outbound Cloud Relay Manager
Enables zero-config, carrier-grade NAT traversal using Cloudflare Edge tunnels.
Allows remote viewing from mobile devices on 4G/5G/remote networks without
port forwarding, dynamic DNS, or same-network restrictions.
"""

import os
import sys
import re
import socket
import shutil
import time
import base64
import io
import threading
import subprocess
from typing import Optional, Dict, Any

try:
    import qrcode
    from PIL import Image
    QR_SUPPORT = True
except ImportError:
    QR_SUPPORT = False


class CloudRelayManager:
    """Manages zero-config outbound tunnels and mobile pairing QR codes."""

    def __init__(self, port: int = 8080):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.cloud_url: Optional[str] = None
        self.status: str = "idle"  # idle, connecting, connected, error, stopped
        self.error_msg: Optional[str] = None
        self.qr_data_url: Optional[str] = None
        self.local_ip: str = self._detect_local_ip()
        self.tailscale_ip: Optional[str] = self._detect_tailscale_ip()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _find_cloudflared(self) -> Optional[str]:
        candidates = [
            shutil.which("cloudflared"),
            os.path.expanduser("~/.local/bin/cloudflared"),
            "/usr/local/bin/cloudflared",
            "/usr/bin/cloudflared",
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _detect_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _detect_tailscale_ip(self) -> Optional[str]:
        try:
            res = subprocess.run(
                ["tailscale", "ip", "-4"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass
        return None

    def _generate_qr(self, url: str):
        if not QR_SUPPORT:
            return
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#000000", back_color="#ffffff")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            self.qr_data_url = f"data:image/png;base64,{b64}"
        except Exception as e:
            print(f"[CloudRelay] Error generating QR data URL: {e}")

    def _print_banner(self, url: str):
        print("\n" + "═" * 68)
        print("  ✦ OMNISIGHT-NVR 4G CLOUD RELAY ACTIVE ✦")
        print("═" * 68)
        print(f"  ✦ Global 4G/Cloud URL : \033[1;36m{url}\033[0m")
        print(f"  ✦ Local Network (LAN) : http://{self.local_ip}:{self.port}")
        if self.tailscale_ip:
            print(f"  ✦ Tailscale Mesh VPN  : http://{self.tailscale_ip}:{self.port}")
        print("═" * 68)
        print("  ✦ Scan with iPhone/Android Camera to View on 4G Cellular:")

        if QR_SUPPORT:
            try:
                qr = qrcode.QRCode()
                qr.add_data(url)
                qr.print_ascii(invert=True)
            except Exception:
                pass
        print("═" * 68 + "\n")

    def start(self):
        """Starts the outbound tunnel daemon in a background thread."""
        if self.status in ("connecting", "connected"):
            return

        binary = self._find_cloudflared()
        if not binary:
            self.status = "error"
            self.error_msg = "cloudflared binary not found on system"
            print(f"[CloudRelay] {self.error_msg}")
            return

        self.status = "connecting"
        self.error_msg = None
        self._stop_event.clear()

        def _worker():
            cmd = [
                binary,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{self.port}",
                "--no-autoupdate",
            ]
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                start_time = time.time()
                while not self._stop_event.is_set():
                    line = self.process.stdout.readline()
                    if not line:
                        if self.process.poll() is not None:
                            break
                        continue

                    # Search for public trycloudflare URL
                    if not self.cloud_url:
                        m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                        if m and m.group(0) != "https://api.trycloudflare.com":
                            self.cloud_url = m.group(0)
                            self.status = "connected"
                            self._generate_qr(self.cloud_url)
                            self._print_banner(self.cloud_url)

                    # Timeout safety: if 30s elapsed with no URL found
                    if not self.cloud_url and (time.time() - start_time > 30):
                        self.status = "error"
                        self.error_msg = "Timeout waiting for Cloudflare tunnel assignment"
                        break

                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=3)
            except Exception as e:
                self.status = "error"
                self.error_msg = str(e)
                print(f"[CloudRelay] Process error: {e}")
            finally:
                if self.status != "error":
                    self.status = "stopped"

        self._thread = threading.Thread(target=_worker, daemon=True, name="OmniSight-CloudRelay")
        self._thread.start()

    def stop(self):
        """Stops the outbound cloud relay."""
        self._stop_event.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.status = "stopped"
        self.cloud_url = None
        self.qr_data_url = None

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.status in ("connecting", "connected"),
            "status": self.status,
            "cloud_url": self.cloud_url,
            "local_ip": self.local_ip,
            "local_url": f"http://{self.local_ip}:{self.port}",
            "tailscale_ip": self.tailscale_ip,
            "tailscale_url": f"http://{self.tailscale_ip}:{self.port}" if self.tailscale_ip else None,
            "qr_image": self.qr_data_url,
            "error": self.error_msg,
        }
