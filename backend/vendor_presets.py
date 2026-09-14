"""
OmniSight-NVR - Vendor Presets and Quirks Database
Centralized definitions for Hikvision, Dahua, Xiongmai (XM/CMS),
TP-Link Tapo, Reolink, V380, Yoosee, and Generic ONVIF/RTSP cameras.
"""

from typing import Dict, Any, Optional, List

VENDOR_PRESETS: Dict[str, Dict[str, Any]] = {
    "hikvision": {
        "id": "hikvision",
        "name": "Hikvision (DS-2CD / ColorVu / AcuSense)",
        "brand": "Hikvision",
        "default_ports": {"rtsp": 554, "http": 80, "sdk": 8000, "onvif": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}02",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
        "ptz_supported": True,
        "quirks": [
            "ONVIF is often disabled by default on newer firmware. Enable it in Configuration > Network > Advanced Settings > Integration Protocol.",
            "Create a dedicated ONVIF user with 'Digest/basic' authentication, not just Digest.",
            "Channel number is typically 1 (becomes 101 for main, 102 for sub)."
        ],
        "default_channel": 1
    },
    "dahua": {
        "id": "dahua",
        "name": "Dahua / Imou (IPC / WizSense / TiOC)",
        "brand": "Dahua",
        "default_ports": {"rtsp": 554, "http": 80, "tcp": 37777, "onvif": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
        "ptz_supported": True,
        "quirks": [
            "Subtype 0 = Main Stream (high resolution, 2K/4K), Subtype 1 = Sub Stream (fluency/mobile).",
            "Port 37777 is the proprietary Dahua TCP port.",
            "For Imou consumer cameras, the ONVIF password is often the Safety Code printed on the QR label."
        ],
        "default_channel": 1
    },
    "hikvision_dvr": {
        "id": "hikvision_dvr",
        "name": "Hikvision CCTV DVR / TurboHD (Analog BNC Multi-channel)",
        "brand": "Hikvision",
        "default_ports": {"rtsp": 554, "http": 80, "sdk": 8000},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}02",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
        "ptz_supported": True,
        "quirks": [
            "Hikvision DVR / TurboHD digitizes analog coaxial BNC cameras.",
            "Channel 1 BNC = 101, Channel 2 BNC = 201, Channel 3 = 301, Channel 4 = 401, etc.",
            "Sub-stream for mobile / multi-grid uses suffix 02 (e.g., 102, 202, 302)."
        ],
        "default_channel": 1
    },
    "xiongmai_dvr": {
        "id": "xiongmai_dvr",
        "name": "Chinese AHD/TVI/CVI DVR (Xiongmai H.264/H.265 NetSurveillance)",
        "brand": "Xiongmai (XM)",
        "default_ports": {"rtsp": 554, "media": 34567, "onvif": 8899, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}_sub",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Standard Chinese CCTV DVR for coaxial BNC cameras (AHD, TVI, CVI, CVBS).",
            "Channels are 0-indexed: BNC Ch 1 = /live/ch0, BNC Ch 2 = /live/ch1, Ch 3 = /live/ch2.",
            "Desktop software port is 34567 (CMS / XMeye). Password on 'admin' is almost always blank."
        ],
        "default_channel": 1
    },
    "xiongmai": {
        "id": "xiongmai",
        "name": "Xiongmai / XM / NetSurveillance (Generic Chinese Cam)",
        "brand": "Xiongmai (XM)",
        "default_ports": {"rtsp": 554, "media": 34567, "onvif": 8899, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
            "alternate": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/main/av_stream",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "The quintessential 'Random Chinese IP Camera' chipset (HiSilicon / XM530 / Sofia).",
            "Typically operates on Media Port 34567 for CMS / VMS desktop software.",
            "ONVIF is usually on port 8899 or 80. Default password is often completely empty.",
            "If /live/ch0 fails, try /mpeg4 or /h264/ch1/main/av_stream."
        ],
        "default_channel": 0
    },
    "gatocam": {
        "id": "gatocam",
        "name": "Shenzhen GatoCam (Indoor / Outdoor / PTZ)",
        "brand": "Shenzhen Gato",
        "default_ports": {"rtsp": 554, "http": 80, "onvif": 8899, "media": 34567},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
            "stream1": "rtsp://{username}:{password}@{ip}:{port}/stream1",
            "onvif1": "rtsp://{username}:{password}@{ip}:{port}/onvif1"
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Shenzhen Gato / XM / Sofia OEM architecture with HiSilicon/Goke SoC.",
            "Primary RTSP pattern: rtsp://<ip>:554/live/ch0 or /stream1.",
            "Legacy Snapshot URL: http://<ip>/snapshot.jpg or http://<ip>/tmpfs/auto.jpg.",
            "Default password is empty or '123456' / 'admin'.",
            "Zero-IE HTML5 engine bypasses required ActiveX plugins.",
            "Eligible for OpenIPC flashing (HiSilicon Hi3516 / XM530) for full cloud-free autonomy."
        ],
        "default_channel": 0
    },
    "tapo": {
        "id": "tapo",
        "name": "TP-Link Tapo (C100, C200, C310, C500)",
        "brand": "TP-Link",
        "default_ports": {"rtsp": 554, "onvif": 2020, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/stream1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/stream2",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "CRITICAL: Do NOT use your TP-Link cloud account password!",
            "You MUST create a local 'Camera Account' in the Tapo App: Device Settings > Advanced Settings > Camera Account."
        ],
        "default_channel": 1
    },
    "reolink": {
        "id": "reolink",
        "name": "Reolink (RLC, Duo, TrackMix, E1 Pro)",
        "brand": "Reolink",
        "default_ports": {"rtsp": 554, "http": 80, "https": 443, "onvif": 8000},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/h264Preview_{channel}_main",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/h264Preview_{channel}_sub",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/api.cgi?cmd=Snap&channel={channel}&user={username}&password={password}",
        "ptz_supported": True,
        "quirks": [
            "Channel is padded to 2 digits for some models (e.g., 01 for channel 1).",
            "Enable RTSP and ONVIF in Network > Advanced > Server Settings on the Reolink Client/Web UI."
        ],
        "default_channel": "01"
    },
    "yoosee": {
        "id": "yoosee",
        "name": "Yoosee / Cooau / VStarcam (CloudLinks)",
        "brand": "Yoosee",
        "default_ports": {"rtsp": 554, "onvif": 5000, "http": 80},
        "default_credentials": {"username": "admin", "password": "123456"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Turn on RTSP in the Yoosee app under Device Settings > NVR Connections / PC Monitoring.",
            "Port 5000 is usually the ONVIF port; RTSP is standard 554."
        ],
        "default_channel": 1
    },
    "v380": {
        "id": "v380",
        "name": "V380 / V380 Pro / Macro-Video",
        "brand": "V380",
        "default_ports": {"rtsp": 554, "http": 80, "onvif": 8899},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Many V380 cameras lock RTSP by default. Enable ONVIF in app settings if available.",
            "Common Chinese security cam hardware OEM."
        ],
        "default_channel": 0
    },
    "v360": {
        "id": "v360",
        "name": "V360 Pro / 360 Smart Camera (Qihoo)",
        "brand": "V360",
        "default_ports": {"rtsp": 554, "http": 80, "onvif": 8899},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "V360 Pro panoramic & PTZ camera OEM.",
            "Supports 360-degree rotation, dual-light night vision, humanoid alarm siren, and hold-to-talk audio."
        ],
        "default_channel": 0
    },
    "uniview": {
        "id": "uniview",
        "name": "Uniview (UNV)",
        "brand": "Uniview",
        "default_ports": {"rtsp": 554, "http": 80, "onvif": 80},
        "default_credentials": {"username": "admin", "password": "123456"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s1/live",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Path format is c1/s0/live where c is channel and s is stream."
        ],
        "default_channel": 1
    },
    "axis": {
        "id": "axis",
        "name": "Axis Communications",
        "brand": "Axis",
        "default_ports": {"rtsp": 554, "http": 80, "https": 443},
        "default_credentials": {"username": "root", "password": "pass"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264&resolution=640x360",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/jpg/image.jpg",
        "ptz_supported": True,
        "quirks": [
            "Root user is default administrator."
        ],
        "default_channel": 1
    },
    "generic_onvif": {
        "id": "generic_onvif",
        "name": "Generic ONVIF Camera",
        "brand": "ONVIF",
        "default_ports": {"rtsp": 554, "onvif": 80, "http": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Standard ONVIF Profile S stream URL."
        ],
        "default_channel": 1
    },
    "generic_rtsp": {
        "id": "generic_rtsp",
        "name": "Generic RTSP Stream / Custom URL",
        "brand": "Custom",
        "default_ports": {"rtsp": 554},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/{path}",
        },
        "snapshot_url": "",
        "ptz_supported": False,
        "quirks": [
            "Provide your exact RTSP path in the URL field."
        ],
        "default_channel": 1
    },
    "mjpeg_http": {
        "id": "mjpeg_http",
        "name": "HTTP MJPEG Stream (ESP32-CAM / IP Webcam)",
        "brand": "HTTP/MJPEG",
        "default_ports": {"http": 80, "stream": 8080},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/stream",
            "mjpeg": "http://{ip}:{port}/mjpeg",
        },
        "snapshot_url": "http://{ip}:{port}/snapshot.jpg",
        "ptz_supported": False,
        "quirks": [
            "Direct multipart MJPEG stream over HTTP. Perfect for ESP32-CAM and Android IP Webcam apps."
        ],
        "default_channel": 1
    },
    "simulated": {
        "id": "simulated",
        "name": "OmniSight Virtual / Simulated Camera",
        "brand": "OmniSight Simulator",
        "default_ports": {"stream": 8000},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "sim://{scene}",
        },
        "snapshot_url": "/api/cameras/{id}/snapshot",
        "ptz_supported": True,
        "quirks": [
            "Built-in procedural CCTV video engine. Simulates vendor OSD, night vision, motion triggers, and pan/tilt."
        ],
        "default_channel": 1
    }
}


def build_stream_url(
    preset_id: str,
    ip: str,
    port: Optional[int] = None,
    username: str = "",
    password: str = "",
    channel: Any = 1,
    stream_type: str = "main",
    custom_path: str = ""
) -> str:
    """Builds a formatted RTSP or HTTP URL based on vendor preset conventions."""
    preset = VENDOR_PRESETS.get(preset_id, VENDOR_PRESETS["generic_rtsp"])
    
    if preset_id == "simulated":
        return f"sim://{ip or 'gate'}"

    # Determine port
    if port is None or port == 0:
        port = preset["default_ports"].get("rtsp", 554)

    # Format channel
    if preset_id == "reolink" and isinstance(channel, int):
        channel = f"{channel:02d}"
    
    # Select pattern
    patterns = preset.get("rtsp_patterns", {})
    template = patterns.get(stream_type) or patterns.get("main") or "rtsp://{username}:{password}@{ip}:{port}/{path}"

    # Handle credentials
    cred_part = ""
    if username and password:
        cred_part = f"{username}:{password}@"
    elif username:
        cred_part = f"{username}@"

    # Replace in template
    # Replace credentials placeholder cleanly
    if "{username}:{password}@" in template:
        url = template.replace("{username}:{password}@", cred_part)
    elif "{username}@" in template:
        url = template.replace("{username}@", cred_part)
    else:
        url = template

    try:
        ch_int = int(channel)
        channel_index = max(0, ch_int - 1)
    except (ValueError, TypeError):
        channel_index = 0

    url = url.format(
        ip=ip,
        port=port,
        channel=channel,
        channel_index=channel_index,
        subtype=0 if stream_type == "main" else 1,
        path=custom_path.lstrip("/")
    )
    return url


def detect_vendor_by_ports(open_ports: List[int]) -> Dict[str, Any]:
    """Identifies the likely camera brand based on signature listening ports."""
    open_set = set(open_ports)
    
    if 34567 in open_set:
        return {
            "preset_id": "xiongmai",
            "confidence": "High",
            "reason": "Port 34567 is the distinctive Xiongmai / XM NetSurveillance CMS port."
        }
    if 37777 in open_set:
        return {
            "preset_id": "dahua",
            "confidence": "High",
            "reason": "Port 37777 is the proprietary Dahua TCP management port."
        }
    if 8000 in open_set and 554 in open_set:
        return {
            "preset_id": "hikvision",
            "confidence": "High",
            "reason": "Port 8000 (Hikvision SDK / ISAPI) alongside RTSP 554 indicates Hikvision."
        }
    if 2020 in open_set:
        return {
            "preset_id": "tapo",
            "confidence": "Medium",
            "reason": "Port 2020 is commonly used by TP-Link Tapo ONVIF services."
        }
    if 8899 in open_set:
        return {
            "preset_id": "xiongmai",
            "confidence": "Medium",
            "reason": "Port 8899 is the standard ONVIF port for Xiongmai and generic Chinese cams."
        }
    if 5000 in open_set and 554 in open_set:
        return {
            "preset_id": "yoosee",
            "confidence": "Medium",
            "reason": "Port 5000 is common for Yoosee / Cooau ONVIF services."
        }
    if 554 in open_set:
        return {
            "preset_id": "generic_onvif",
            "confidence": "Low",
            "reason": "Standard RTSP port 554 is open."
        }
    return {
        "preset_id": "generic_rtsp",
        "confidence": "Low",
        "reason": "No signature camera ports matched."
    }
