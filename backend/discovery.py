"""
OmniSight-NVR - Universal Camera Discovery & Auto-Detection Diagnostic Engine
Performs ONVIF WS-Discovery probes, LAN port scanning, rapid RTSP DESCRIBE probing,
HTTP snapshot verification, and local system webcam enumeration.
"""

import os
import re
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
import hashlib
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

try:
    from .vendor_presets import (
        detect_vendor_by_ports,
        VENDOR_PRESETS,
        build_stream_url,
        COMMON_RTSP_CANDIDATE_PATHS,
        COMMON_SNAPSHOT_CANDIDATE_PATHS
    )
except (ImportError, ValueError):
    from vendor_presets import (
        detect_vendor_by_ports,
        VENDOR_PRESETS,
        build_stream_url,
        COMMON_RTSP_CANDIDATE_PATHS,
        COMMON_SNAPSHOT_CANDIDATE_PATHS
    )

WS_DISCOVERY_PROBE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

COMMON_CAMERA_PORTS = [554, 8554, 6688, 34567, 37777, 8000, 8899, 2020, 5000, 80, 8080, 7447]


def get_local_ip() -> str:
    """Discovers the active primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip


def get_arp_ips() -> List[str]:
    """Reads the Linux ARP cache or Windows arp table to locate active devices on the local subnet."""
    ips = []
    # 1. Linux /proc/net/arp
    try:
        if os.path.exists("/proc/net/arp"):
            with open("/proc/net/arp", "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] != "0x0":
                        ip = parts[0]
                        if not ip.startswith("127."):
                            ips.append(ip)
            return ips
    except Exception:
        pass

    # 2. Windows / fallback: arp -a
    try:
        proc = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=2.0)
        for line in proc.stdout.splitlines():
            m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
            if m:
                ip = m.group(1)
                if not ip.startswith("127.") and not ip.startswith("255.") and not ip.endswith(".255"):
                    ips.append(ip)
    except Exception:
        pass

    return list(dict.fromkeys(ips))


def run_onvif_discovery(timeout: float = 2.5) -> List[Dict[str, Any]]:
    """Sends multicast WS-Discovery probe and gathers responding ONVIF devices."""
    devices = []
    seen_ips = set()
    msg_id = str(uuid.uuid4())
    probe_msg = WS_DISCOVERY_PROBE_XML.format(msg_id=msg_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    ttl = struct.pack('b', 4)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    try:
        sock.sendto(probe_msg, ('239.255.255.250', 3702))
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                xml_str = data.decode("utf-8", errors="ignore")
                
                xaddrs_match = re.search(r'<[^:]*:XAddrs>([^<]+)</[^:]*:XAddrs>', xml_str)
                xaddrs = xaddrs_match.group(1).strip() if xaddrs_match else f"http://{ip}/onvif/device_service"

                scopes_match = re.search(r'<[^:]*:Scopes>([^<]+)</[^:]*:Scopes>', xml_str)
                scopes = scopes_match.group(1) if scopes_match else ""

                vendor_guess = "generic_onvif"
                lower_xml = xml_str.lower()
                if "hikvision" in lower_xml or "hik" in lower_xml:
                    vendor_guess = "hikvision"
                elif "dahua" in lower_xml or "imou" in lower_xml:
                    vendor_guess = "dahua"
                elif "amcrest" in lower_xml:
                    vendor_guess = "amcrest"
                elif "xiongmai" in lower_xml or "xm" in lower_xml:
                    vendor_guess = "xiongmai"
                elif "reolink" in lower_xml:
                    vendor_guess = "reolink"
                elif "tapo" in lower_xml or "tp-link" in lower_xml:
                    vendor_guess = "tapo"
                elif "axis" in lower_xml:
                    vendor_guess = "axis"
                elif "uniview" in lower_xml:
                    vendor_guess = "uniview"
                elif "hanwha" in lower_xml or "wisenet" in lower_xml:
                    vendor_guess = "hanwha"
                elif "foscam" in lower_xml:
                    vendor_guess = "foscam"

                devices.append({
                    "ip": ip,
                    "type": "ONVIF",
                    "xaddrs": xaddrs,
                    "vendor_preset": vendor_guess,
                    "vendor_name": VENDOR_PRESETS.get(vendor_guess, {}).get("name", "Generic ONVIF"),
                    "details": f"ONVIF Device responded at {ip}"
                })
            except socket.timeout:
                break
            except Exception:
                continue
    except Exception as e:
        print(f"[Discovery] ONVIF multicast error: {e}")
    finally:
        sock.close()

    return devices


def test_single_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    """Tests if a single TCP port is listening on the host."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        res = s.connect_ex((ip, port))
        return res == 0
    except Exception:
        return False
    finally:
        s.close()


def scan_host_camera_ports(ip: str, custom_ports: Optional[List[int]] = None) -> List[int]:
    """Tests standard and custom camera ports on a single host."""
    open_ports = []
    ports_to_test = list(dict.fromkeys(COMMON_CAMERA_PORTS + (custom_ports or [])))
    for p in ports_to_test:
        if test_single_port(ip, p):
            open_ports.append(p)
    return open_ports


def probe_single_rtsp_path(ip: str, port: int, path: str, timeout: float = 1.2) -> Optional[Dict[str, Any]]:
    """
    Sends raw RTSP DESCRIBE request to test if a specific RTSP path exists on the camera.
    Returns status code and SDP video/audio codecs if valid.
    """
    if not path.startswith("/"):
        path = f"/{path}"
    
    clean_path = path.split("?")[0]
    
    req_text = (
        f"DESCRIBE rtsp://{ip}:{port}{path} RTSP/1.0\r\n"
        f"CSeq: 1\r\n"
        f"User-Agent: OmniSight-Universal-NVR/2.0\r\n"
        f"Accept: application/sdp\r\n\r\n"
    )

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.connect((ip, port))
        s.sendall(req_text.encode("utf-8"))
        resp = s.recv(4096).decode("utf-8", errors="ignore")
        elapsed = time.time() - t0

        if not resp:
            return None

        # Parse RTSP Status Line
        status_match = re.search(r"RTSP/1\.\d\s+(\d{3})", resp)
        if not status_match:
            return None

        status_code = int(status_match.group(1))

        # Check for 200 OK or 401 Unauthorized (401 proves the RTSP endpoint is valid!)
        if status_code in (200, 401):
            detected_codec = "H.264"
            has_audio = False

            if "H265" in resp or "hevc" in resp.lower():
                detected_codec = "H.265 / HEVC"
            elif "H264" in resp or "avc" in resp.lower():
                detected_codec = "H.264"
            elif "JPEG" in resp or "mjpeg" in resp.lower():
                detected_codec = "MJPEG"

            if "m=audio" in resp:
                has_audio = True

            www_auth = ""
            if status_code == 401:
                auth_match = re.search(r"WWW-Authenticate:\s*([^\r\n]+)", resp, re.IGNORECASE)
                if auth_match:
                    www_auth = auth_match.group(1).strip()

            return {
                "path": path,
                "clean_path": clean_path,
                "status_code": status_code,
                "auth_required": (status_code == 401),
                "www_auth": www_auth,
                "codec": detected_codec,
                "has_audio": has_audio,
                "latency_ms": round(elapsed * 1000, 1)
            }
        return None
    except Exception:
        return None
    finally:
        s.close()


def probe_rtsp_with_credentials(
    ip: str,
    port: int,
    path: str,
    username: str,
    password: str,
    www_auth: str = "",
    timeout: float = 1.0
) -> bool:
    """
    Tests credentials against an RTSP endpoint using Basic or Digest authentication.
    Returns True if the camera returns 200 OK.
    """
    if not path.startswith("/"):
        path = f"/{path}"
    uri = f"rtsp://{ip}:{port}{path}"

    auth_header = ""
    if www_auth and "digest" in www_auth.lower():
        realm_m = re.search(r'realm="([^"]+)"', www_auth, re.IGNORECASE)
        nonce_m = re.search(r'nonce="([^"]+)"', www_auth, re.IGNORECASE)
        if realm_m and nonce_m:
            realm = realm_m.group(1)
            nonce = nonce_m.group(1)
            ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode("utf-8")).hexdigest()
            ha2 = hashlib.md5(f"DESCRIBE:{uri}".encode("utf-8")).hexdigest()
            response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode("utf-8")).hexdigest()
            auth_header = f'Authorization: Digest username="{username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response_hash}"\r\n'

    if not auth_header:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        auth_header = f"Authorization: Basic {token}\r\n"

    req_text = (
        f"DESCRIBE {uri} RTSP/1.0\r\n"
        f"CSeq: 2\r\n"
        f"{auth_header}"
        f"User-Agent: OmniSight-Universal-NVR/2.0\r\n"
        f"Accept: application/sdp\r\n\r\n"
    )

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        s.sendall(req_text.encode("utf-8"))
        resp = s.recv(2048).decode("utf-8", errors="ignore")
        if "RTSP/1." in resp and " 200 " in resp:
            return True
    except Exception:
        pass
    finally:
        s.close()
    return False


def probe_single_http_snapshot(ip: str, port: int, path: str, username: str = "", password: str = "", timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    """
    Tests an HTTP snapshot endpoint with Digest/Basic auth to see if valid JPEG frames return.
    """
    if not path.startswith("/"):
        path = f"/{path}"
    
    url = f"http://{ip}:{port}{path}"
    pwd_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    if username:
        pwd_mgr.add_password(None, url, username, password or "")
        pwd_mgr.add_password(None, f"http://{ip}:{port}/", username, password or "")

    auth_h = urllib.request.HTTPDigestAuthHandler(pwd_mgr)
    basic_h = urllib.request.HTTPBasicAuthHandler(pwd_mgr)
    opener = urllib.request.build_opener(auth_h, basic_h)

    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OmniSight/1.0"})
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            data = resp.read(2048)
            elapsed = time.time() - t0
            # JPEG magic bytes \xff\xd8
            is_jpeg = data.startswith(b"\xff\xd8") or "image" in content_type
            if is_jpeg or resp.status == 200:
                return {
                    "url": url,
                    "path": path,
                    "content_type": content_type or "image/jpeg",
                    "latency_ms": round(elapsed * 1000, 1)
                }
    except Exception:
        pass
    return None


def probe_camera_connection(
    ip: str,
    port: Optional[int] = None,
    username: str = "",
    password: str = "",
    vendor_hint: str = ""
) -> Dict[str, Any]:
    """
    Universal Camera Auto-Detection & Diagnostic Engine.
    Examines ports, auto-probes RTSP candidate endpoints, verifies HTTP snapshots,
    detects codecs (H.264/H.265/MJPEG), and builds optimal configuration URLs.
    """
    if not ip:
        return {"success": False, "error": "IP address is required"}

    # Handle simulation shortcut
    if ip == "127.0.0.1" and vendor_hint == "simulated":
        return {
            "success": True,
            "detected_vendor": "simulated",
            "vendor_name": "OmniSight Virtual Generator",
            "stream_url": "sim://gate",
            "sub_stream_url": "sim://gate_sub",
            "snapshot_url": "/api/cameras/sim/snapshot",
            "codec": "Procedural H.264",
            "resolution": "1920x1080",
            "fps": 25,
            "open_ports": [8000],
            "latency_ms": 1.0,
            "ptz_supported": True,
            "details": "OmniSight Virtual CCTV Engine verified."
        }

    # 1. Test signature ports
    target_ports = [port] if (port and port not in COMMON_CAMERA_PORTS) else []
    open_ports = scan_host_camera_ports(ip, target_ports)

    if not open_ports:
        return {
            "success": False,
            "reachable": False,
            "ip": ip,
            "error": f"Device at {ip} is unreachable on standard camera ports (554, 80, 8080, 8000, 34567, 37777)."
        }

    # 2. Identify vendor signature
    vendor_match = detect_vendor_by_ports(open_ports)
    detected_vendor = vendor_hint or vendor_match["preset_id"]
    preset = VENDOR_PRESETS.get(detected_vendor, VENDOR_PRESETS["generic_rtsp"])

    rtsp_port = port if (port and port in (554, 8554, 7447, 5000, 10554)) else (554 if 554 in open_ports else None)
    if not rtsp_port:
        for p in (554, 8554, 7447, 5000):
            if p in open_ports:
                rtsp_port = p
                break

    http_port = 80 if 80 in open_ports else (8080 if 8080 in open_ports else (88 if 88 in open_ports else None))

    confirmed_rtsp_path = None
    detected_codec = "H.264"
    audio_present = False
    auth_required = False
    best_latency = 999.0

    # 3. Parallel RTSP DESCRIBE Probing
    if rtsp_port:
        # Build candidate paths tailored to detected vendor first, then generic
        candidate_paths = []
        preset_patterns = preset.get("rtsp_patterns", {})
        for key in ("main", "sub", "alternate"):
            if key in preset_patterns:
                p = preset_patterns[key]
                path_only = re.sub(r"^rtsp://[^/]+/", "/", p).split("?")[0]
                # Replace placeholders
                path_clean = path_only.replace("{channel}", "1").replace("{channel_index}", "0")
                if path_clean not in candidate_paths:
                    candidate_paths.append(path_clean)

        for p in COMMON_RTSP_CANDIDATE_PATHS:
            if p not in candidate_paths:
                candidate_paths.append(p)

        confirmed_www_auth = ""
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(probe_single_rtsp_path, ip, rtsp_port, path): path for path in candidate_paths[:14]}
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    confirmed_rtsp_path = res["path"]
                    detected_codec = res["codec"]
                    audio_present = res["has_audio"]
                    auth_required = res["auth_required"]
                    confirmed_www_auth = res.get("www_auth", "")
                    best_latency = min(best_latency, res["latency_ms"])
                    break

        password_status = "none_required" if not auth_required else "unknown"
        discovered_username = username
        discovered_password = password
        auth_summary = ""

        if confirmed_rtsp_path:
            if not auth_required:
                password_status = "none_required"
                discovered_username = ""
                discovered_password = ""
                auth_summary = "🔓 Verified: Camera accepts anonymous local streaming with NO password required."
            else:
                # Camera returned 401 Unauthorized. Probe for blank password and factory defaults.
                candidates = []
                if username or password:
                    candidates.append((username, password))
                default_candidates = [
                    ("admin", ""),        # Blank password - ICSee, V380, XMeye, Sofia, GatoCam
                    ("admin", "admin"),   # Dahua, generic
                    ("admin", "123456"),  # Yoosee, Uniview
                    ("admin", "admin123"),# Hikvision legacy
                    ("root", ""),         # OpenIPC, Axis
                    ("root", "pass"),     # Axis default
                ]
                for c in default_candidates:
                    if c not in candidates:
                        candidates.append(c)

                auth_found = False
                for u, p in candidates:
                    if probe_rtsp_with_credentials(ip, rtsp_port, confirmed_rtsp_path, u, p, confirmed_www_auth):
                        auth_found = True
                        discovered_username = u
                        discovered_password = p
                        if not p:
                            password_status = "blank_password"
                            auth_summary = f"🔓 Unlocked! Camera streams with username '{u}' and a BLANK (empty) password."
                        else:
                            password_status = "default_found"
                            auth_summary = f"🔑 Unlocked! Camera streams with username '{u}' and default password '{p}'."
                        break

                if not auth_found:
                    password_status = "custom_required"
                    if detected_vendor in ("ezviz", "hikvision"):
                        auth_summary = "🔒 Password Required. For EZVIZ / Hikvision cameras: Look on the camera sticker for the 6-letter 'Verification Code'. That is your password! Username is 'admin'."
                    elif detected_vendor in ("imou", "dahua"):
                        auth_summary = "🔒 Password Required. For Imou / Dahua cameras: Look on the bottom sticker for the 'Safety Code'. That is your password! Username is 'admin'."
                    elif detected_vendor == "tapo":
                        auth_summary = "🔒 Password Required. For Tapo cameras: Cloud passwords will not work. Create a local 'Camera Account' in Tapo App → Settings ⚙️ → Advanced Settings → Camera Account."
                    elif detected_vendor == "eufy":
                        auth_summary = "🔒 Password Required. For Eufy cameras: Enable RTSP in Eufy App → Camera Settings → Storage → NAS (RTSP) Stream to get credentials."
                    elif detected_vendor == "tuya":
                        auth_summary = "🔒 Password Required. For Tuya cameras: Enable PC View / ONVIF in Tuya app device settings."
                    elif detected_vendor == "v360":
                        auth_summary = "🔒 Password Required. For V360 Pro (Qianniao Xiangyun CFEO Series): Username is 'admin'. Password is usually BLANK (Empty). If locked, check V360 Pro app settings for 'PC View' or 'Local Monitoring'."
                    else:
                        auth_summary = "🔒 Password Required. This camera requires credentials configured in its companion mobile app."
    else:
        password_status = "unknown"
        discovered_username = username
        discovered_password = password
        auth_summary = ""

    # 4. HTTP Snapshot Probing
    confirmed_snapshot_url = ""
    snapshot_unauthenticated = False
    if http_port:
        candidate_snaps = []
        if preset.get("snapshot_url"):
            snap_path = re.sub(r"^http://[^/]+/", "/", preset["snapshot_url"]).split("?")[0]
            candidate_snaps.append(snap_path.replace("{channel}", "1"))
        for s_path in COMMON_SNAPSHOT_CANDIDATE_PATHS:
            if s_path not in candidate_snaps:
                candidate_snaps.append(s_path)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(probe_single_http_snapshot, ip, http_port, path, discovered_username, discovered_password): path for path in candidate_snaps[:8]}
            for fut in as_completed(futures):
                sres = fut.result()
                if sres:
                    confirmed_snapshot_url = sres["url"]
                    break

        # Also test if snapshot works with zero credentials
        if not confirmed_snapshot_url:
            for s_path in candidate_snaps[:4]:
                sres = probe_single_http_snapshot(ip, http_port, s_path, "", "")
                if sres:
                    confirmed_snapshot_url = sres["url"]
                    snapshot_unauthenticated = True
                    break

    # 5. Build Final Working URLs
    final_stream_url = ""
    final_sub_url = ""

    if confirmed_rtsp_path and rtsp_port:
        if password_status == "none_required":
            cred = ""
        elif discovered_username or discovered_password:
            cred = f"{discovered_username}:{discovered_password}@" if (discovered_username and discovered_password) else (f"{discovered_username}@" if discovered_username else "")
        else:
            cred = f"{username}:{password}@" if (username and password) else (f"{username}@" if username else "")

        final_stream_url = f"rtsp://{cred}{ip}:{rtsp_port}{confirmed_rtsp_path}"
        # Guess sub-stream
        sub_path = confirmed_rtsp_path.replace("101", "102").replace("subtype=0", "subtype=1").replace("stream1", "stream2").replace("main", "sub")
        if sub_path != confirmed_rtsp_path:
            final_sub_url = f"rtsp://{cred}{ip}:{rtsp_port}{sub_path}"
    elif rtsp_port:
        final_stream_url = build_stream_url(detected_vendor, ip, rtsp_port, discovered_username, discovered_password, channel=1, stream_type="main")
        final_sub_url = build_stream_url(detected_vendor, ip, rtsp_port, discovered_username, discovered_password, channel=1, stream_type="sub")
    elif confirmed_snapshot_url:
        final_stream_url = confirmed_snapshot_url

    if not confirmed_snapshot_url and preset.get("snapshot_url"):
        confirmed_snapshot_url = preset["snapshot_url"].format(
            ip=ip,
            port=http_port or 80,
            username=discovered_username,
            password=discovered_password,
            channel=1
        )

    summary_text = auth_summary or f"Camera responded at {ip} on port {rtsp_port or http_port}. Codec: {detected_codec}."
    if snapshot_unauthenticated and password_status == "custom_required":
        summary_text += " (Note: Live HTTP snapshot stream is unlocked with NO password!)"

    return {
        "success": True,
        "reachable": True,
        "ip": ip,
        "detected_vendor": detected_vendor,
        "vendor_name": preset.get("name", "Generic Camera"),
        "open_ports": open_ports,
        "stream_url": final_stream_url,
        "sub_stream_url": final_sub_url,
        "snapshot_url": confirmed_snapshot_url,
        "codec": detected_codec,
        "audio_detected": audio_present,
        "auth_required": auth_required,
        "password_status": password_status,
        "discovered_username": discovered_username,
        "discovered_password": discovered_password,
        "auth_summary": auth_summary,
        "snapshot_unauthenticated": snapshot_unauthenticated,
        "summary": summary_text,
        "latency_ms": best_latency if best_latency < 900 else 15.0,
        "ptz_supported": preset.get("ptz_supported", False),
        "quirks": preset.get("quirks", []),
        "details": f"Camera responded at {ip} on port {rtsp_port or http_port}. Stream codec: {detected_codec}."
    }


def list_system_webcams() -> List[Dict[str, Any]]:
    """
    Discovers local USB and integrated webcams on the host system.
    Supports Windows (DirectShow), Linux (V4L2), and macOS.
    """
    devices = []

    # Windows DirectShow Enumeration
    if os.name == "nt":
        ffmpeg = shutil_which("ffmpeg")
        if ffmpeg:
            try:
                proc = subprocess.run(
                    [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                    capture_output=True,
                    text=True,
                    timeout=2.5
                )
                output = proc.stderr or proc.stdout
                # Extract device names like: "Integrated Camera" (video)
                matches = re.findall(r'"([^"]+)"\s+\(video\)', output)
                for idx, dev_name in enumerate(matches):
                    devices.append({
                        "id": f"webcam-{idx}",
                        "name": dev_name,
                        "type": "DirectShow USB/Internal Webcam",
                        "stream_url": f"webcam://{dev_name}",
                        "path": dev_name
                    })
            except Exception:
                pass

        if not devices:
            devices.append({
                "id": "webcam-0",
                "name": "Integrated Camera / USB Webcam (DirectShow: 0)",
                "type": "DirectShow Camera",
                "stream_url": "webcam://0",
                "path": "0"
            })
    else:
        # Linux V4L2 devices
        import glob
        v4l_devices = glob.glob("/dev/video*")
        for dev_path in sorted(v4l_devices):
            devices.append({
                "id": os.path.basename(dev_path),
                "name": f"V4L2 Camera ({dev_path})",
                "type": "Linux V4L2 Device",
                "stream_url": f"webcam://{dev_path}",
                "path": dev_path
            })
        if not devices:
            devices.append({
                "id": "webcam-0",
                "name": "Default USB Camera (/dev/video0)",
                "type": "Linux V4L2 Camera",
                "stream_url": "webcam:///dev/video0",
                "path": "/dev/video0"
            })

    return devices


def shutil_which(cmd: str) -> Optional[str]:
    import shutil
    return shutil.which(cmd)


def scan_lan_subnet(subnet_base: str = "", max_hosts: int = 40) -> List[Dict[str, Any]]:
    """Scans the local subnet for cameras with open RTSP or surveillance ports."""
    if not subnet_base:
        local_ip = get_local_ip()
        parts = local_ip.split(".")
        if len(parts) == 4 and parts[0] != "127":
            subnet_base = f"{parts[0]}.{parts[1]}.{parts[2]}"
        else:
            subnet_base = "192.168.1"

    results = []
    arp_ips = [ip for ip in get_arp_ips() if ip.startswith(subnet_base)]
    range_ips = [f"{subnet_base}.{i}" for i in range(1, min(max_hosts + 1, 255))]
    common_cam_ips = [f"{subnet_base}.{i}" for i in range(100, 130)] + [f"{subnet_base}.{i}" for i in range(200, 215)]
    ips_to_scan = list(dict.fromkeys(arp_ips + range_ips + common_cam_ips))

    def check_ip(ip):
        ports = scan_host_camera_ports(ip)
        if ports:
            vendor_info = detect_vendor_by_ports(ports)
            preset_id = vendor_info["preset_id"]
            return {
                "ip": ip,
                "type": "TCP Port Scan",
                "open_ports": ports,
                "vendor_preset": preset_id,
                "vendor_name": VENDOR_PRESETS.get(preset_id, {}).get("name", "Unknown"),
                "confidence": vendor_info["confidence"],
                "reason": vendor_info["reason"]
            }
        return None

    with ThreadPoolExecutor(max_workers=25) as executor:
        scan_results = executor.map(check_ip, ips_to_scan)
        for res in scan_results:
            if res:
                results.append(res)

    return results


def run_full_discovery() -> Dict[str, Any]:
    """Combines ONVIF discovery, LAN scanning, and local webcam detection."""
    onvif_devices = run_onvif_discovery(timeout=2.0)
    seen_ips = {d["ip"] for d in onvif_devices}

    devices = list(onvif_devices)

    lan_devices = scan_lan_subnet(max_hosts=30)
    for dev in lan_devices:
        if dev["ip"] not in seen_ips:
            devices.append(dev)

    # Local webcams
    webcams = list_system_webcams()
    for wc in webcams:
        devices.append({
            "ip": "localhost",
            "type": "Local Hardware Webcam",
            "vendor_preset": "usb_webcam",
            "vendor_name": wc["name"],
            "stream_url": wc["stream_url"],
            "open_ports": [],
            "confidence": "High",
            "reason": f"Local video device available on host ({wc['path']})"
        })

    # Always ensure simulated templates are discoverable
    devices.append({
        "ip": "127.0.0.1",
        "type": "OmniSight Virtual Generator",
        "vendor_preset": "simulated",
        "vendor_name": "OmniSight Virtual CCTV Engine",
        "open_ports": [8000],
        "confidence": "High",
        "reason": "Internal high-speed surveillance generator ready for zero-hardware testing."
    })

    return {
        "timestamp": time.time(),
        "device_count": len(devices),
        "devices": devices
    }
