"""
OmniSight-NVR - Universal Vendor Presets, Quirks & Protocol Database
Comprehensive definitions for Hikvision, Dahua, Xiongmai, Amcrest, Reolink,
TP-Link Tapo & Kasa, Uniview, Axis, Hanwha/Samsung, Bosch, Sony, Panasonic,
Vivotek, Foscam, Wyze, Eufy, Tuya, Yoosee, V380, V360, SriHome, ZOSI/Lorex,
UniFi, D-Link, Milesight, Mobotix, ESP32-CAM, Raspberry Pi, Webcams, and ONVIF.
"""

from typing import Dict, Any, Optional, List

VENDOR_PRESETS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # MAINSTREAM COMMERCIAL & ENTERPRISE CCTV
    # =========================================================================
    "hikvision": {
        "id": "hikvision",
        "name": "Hikvision (DS-2CD / ColorVu / AcuSense)",
        "brand": "Hikvision",
        "category": "mainstream",
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
            "Channel number is typically 1 (becomes 101 for main stream, 102 for sub stream)."
        ],
        "default_channel": 1
    },
    "dahua": {
        "id": "dahua",
        "name": "Dahua / Imou (IPC / WizSense / TiOC / XVR)",
        "brand": "Dahua",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "tcp": 37777, "onvif": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
        "ptz_supported": True,
        "quirks": [
            "Subtype 0 = Main Stream (2K/4K/H.265), Subtype 1 = Sub Stream (mobile / multi-view).",
            "Port 37777 is the proprietary Dahua TCP management port.",
            "For Imou consumer cameras, the password is often the Safety Code printed on the label."
        ],
        "default_channel": 1
    },
    "amcrest": {
        "id": "amcrest",
        "name": "Amcrest (IPC / ProHD / 4K / UltraHD / Doorbell)",
        "brand": "Amcrest",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "tcp": 37777, "onvif": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
        "ptz_supported": True,
        "quirks": [
            "Amcrest runs Dahua OEM architecture. Uses Dahua CGI & realmonitor RTSP syntax.",
            "Digest authentication is standard. Password must be configured on initial device setup."
        ],
        "default_channel": 1
    },
    "uniview": {
        "id": "uniview",
        "name": "Uniview (UNV / Tri-Guard / Prime)",
        "brand": "Uniview",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "onvif": 80},
        "default_credentials": {"username": "admin", "password": "123456"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s1/live",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/images/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "URL format uses c{channel}/s0 for main stream, c{channel}/s1 for sub stream.",
            "Default password on unactivated cameras is '123456'."
        ],
        "default_channel": 1
    },
    "axis": {
        "id": "axis",
        "name": "Axis Communications (VAPIX / M / P / Q Series)",
        "brand": "Axis",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "https": 443},
        "default_credentials": {"username": "root", "password": "pass"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264&resolution=640x360",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/jpg/image.jpg",
        "ptz_supported": True,
        "quirks": [
            "Root user is the primary administrative account on Axis hardware.",
            "Supports VAPIX HTTP API and native RTSP over TCP or UDP."
        ],
        "default_channel": 1
    },
    "hanwha": {
        "id": "hanwha",
        "name": "Hanwha Techwin / Wisenet / Samsung",
        "brand": "Hanwha",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "https": 443},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/profile2/media.smp",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/profile3/media.smp",
            "alternate": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/stw-cgi/video.cgi?msubmenu=snapshot&action=view",
        "ptz_supported": True,
        "quirks": [
            "Wisenet cameras use profile2 for high-res stream and profile3 for mobile sub-stream.",
            "Requires Digest authentication over HTTP/RTSP."
        ],
        "default_channel": 1
    },
    "bosch": {
        "id": "bosch",
        "name": "Bosch Security (FLEXIDOME / DINION / AUTODOME)",
        "brand": "Bosch",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80, "https": 443},
        "default_credentials": {"username": "service", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/rtsp_tunnel?inst=1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/rtsp_tunnel?inst=2",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snap.jpg",
        "ptz_supported": True,
        "quirks": [
            "Bosch uses rtsp_tunnel URI endpoint with inst=1 for main, inst=2 for sub.",
            "Default service accounts include 'service' or 'admin'."
        ],
        "default_channel": 1
    },
    "sony": {
        "id": "sony",
        "name": "Sony Surveillance (SNC Series / IPELA)",
        "brand": "Sony",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/media/video1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/media/video2",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/oneshotimage.jpg",
        "ptz_supported": True,
        "quirks": [
            "Sony IPELA cameras stream on /media/video1.",
            "Snapshot endpoint is /oneshotimage.jpg."
        ],
        "default_channel": 1
    },
    "panasonic": {
        "id": "panasonic",
        "name": "Panasonic / i-PRO (WV Series)",
        "brand": "Panasonic",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80},
        "default_credentials": {"username": "admin", "password": "12345"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/MediaInput/h264",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/MediaInput/h264/stream_2",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/camera",
        "ptz_supported": True,
        "quirks": [
            "i-PRO / Panasonic uses MediaInput/h264 path.",
            "Default password on classic firmware is '12345'."
        ],
        "default_channel": 1
    },
    "vivotek": {
        "id": "vivotek",
        "name": "Vivotek (FD / IB / FE Series)",
        "brand": "Vivotek",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80},
        "default_credentials": {"username": "root", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live.sdp",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live2.sdp",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/viewer/video.jpg",
        "ptz_supported": True,
        "quirks": [
            "Vivotek uses live.sdp for stream 1 and live2.sdp for stream 2.",
            "Default account is 'root' with empty password or user-configured."
        ],
        "default_channel": 1
    },
    "milesight": {
        "id": "milesight",
        "name": "Milesight (Mini / Pro / Vandal Dome)",
        "brand": "Milesight",
        "category": "mainstream",
        "default_ports": {"rtsp": 554, "http": 80},
        "default_credentials": {"username": "admin", "password": "ms1234"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/main",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/sub",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot",
        "ptz_supported": True,
        "quirks": [
            "Milesight uses clean /main and /sub RTSP paths.",
            "Default factory password is 'ms1234'."
        ],
        "default_channel": 1
    },
    "mobotix": {
        "id": "mobotix",
        "name": "Mobotix (MxPEG / IP)",
        "brand": "Mobotix",
        "category": "mainstream",
        "default_ports": {"http": 80, "rtsp": 554},
        "default_credentials": {"username": "admin", "password": "meinsm"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/stream-0",
            "mjpeg": "http://{username}:{password}@{ip}:{port}/control/faststream.jpg?stream=full",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/record/current.jpg",
        "ptz_supported": True,
        "quirks": [
            "Default password on older models was 'meinsm'.",
            "Supports faststream.jpg continuous multipart MJPEG stream over HTTP."
        ],
        "default_channel": 1
    },

    # =========================================================================
    # CONSUMER, SMART HOME & WIRELESS IP CAMERAS
    # =========================================================================
    "icsee": {
        "id": "icsee",
        "name": "ICSee / XMeye / iCSee Pro (App-Paired IP Camera)",
        "brand": "ICSee",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "media": 34567, "onvif": 8899, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "App-First Camera: Configured via ICSee or XMeye mobile app with zero password prompt.",
            "LOCAL PASSWORD IS BLANK: On your local Wi-Fi network, username is 'admin' and the password is completely BLANK / EMPTY ('')!",
            "Snapshot feed is accessible without credentials at http://<ip>/snapshot.jpg.",
            "CMS management port is 34567; ONVIF port is 8899."
        ],
        "default_channel": 0
    },
    "ezviz": {
        "id": "ezviz",
        "name": "EZVIZ (Hikvision App-Paired Camera)",
        "brand": "EZVIZ",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "http": 80, "sdk": 8000},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/main",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/sub",
            "alternate": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/101"
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/101/picture",
        "ptz_supported": True,
        "quirks": [
            "App-First Camera: Configured via EZVIZ mobile app.",
            "WHERE TO FIND PASSWORD: The EZVIZ app never asks for a password when viewing video. However, local RTSP is protected!",
            "PASSWORD = VERIFICATION CODE: Look at the sticker on the bottom/back of the camera. The 6-capital-letter 'Verification Code' (e.g. ABCDEF) is your password!",
            "Username is always 'admin'."
        ],
        "default_channel": 1
    },
    "imou": {
        "id": "imou",
        "name": "Imou Life (Dahua App-Paired Camera)",
        "brand": "Imou",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "tcp": 37777, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1"
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
        "ptz_supported": True,
        "quirks": [
            "App-First Camera: Configured via Imou Life mobile app.",
            "PASSWORD = SAFETY CODE: Viewing in the Imou app requires no password. For local NVR / RTSP streaming, the password is the 'Safety Code' printed on the camera bottom label.",
            "Username is 'admin'."
        ],
        "default_channel": 1
    },
    "tapo": {
        "id": "tapo",
        "name": "TP-Link Tapo (C100, C200, C310, C500, D230)",
        "brand": "TP-Link",
        "category": "consumer",
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
            "You MUST create a local 'Camera Account' in the Tapo App: Device Settings > Advanced Settings > Camera Account.",
            "ONVIF service is on port 2020."
        ],
        "default_channel": 1
    },
    "kasa": {
        "id": "kasa",
        "name": "TP-Link Kasa (KC100, KC120, KC200, KC420WS)",
        "brand": "TP-Link",
        "category": "consumer",
        "default_ports": {"rtsp": 554},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "stream1": "rtsp://{username}:{password}@{ip}:{port}/stream1",
        },
        "snapshot_url": "",
        "ptz_supported": False,
        "quirks": [
            "Enable 24/7 recording or RTSP in Kasa app settings if supported by firmware."
        ],
        "default_channel": 1
    },
    "reolink": {
        "id": "reolink",
        "name": "Reolink (RLC, Duo, TrackMix, E1 Pro)",
        "brand": "Reolink",
        "category": "consumer",
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
    "wyze": {
        "id": "wyze",
        "name": "Wyze Cam (v2 / v3 / v4 / Pan with RTSP / Wyze Bridge)",
        "brand": "Wyze",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "bridge": 8554},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live",
            "bridge": "rtsp://{ip}:8554/{path}",
        },
        "snapshot_url": "http://{ip}:5000/snapshot/{path}",
        "ptz_supported": True,
        "quirks": [
            "Stock Wyze cams require either official Wyze RTSP firmware, 'Thingino' / 'dafang' open-source firmware, or docker-wyze-bridge."
        ],
        "default_channel": 1
    },
    "eufy": {
        "id": "eufy",
        "name": "Eufy Security (SoloCam / Indoor Cam 2K / Outdoor RTSP)",
        "brand": "Eufy",
        "category": "consumer",
        "default_ports": {"rtsp": 554},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live1",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Enable RTSP (NAS/RTSP Streaming) in the Eufy Security mobile app under Camera Settings > General > Storage > NAS (RTSP).",
            "Copy the generated RTSP username and password from the app."
        ],
        "default_channel": 0
    },
    "foscam": {
        "id": "foscam",
        "name": "Foscam (R2 / FI98 / G4 / VD1 / X4)",
        "brand": "Foscam",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "http": 88, "stream": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/videoMain",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/videoSub",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/CGIProxy.fcgi?cmd=snapPicture2&usr={username}&pwd={password}",
        "ptz_supported": True,
        "quirks": [
            "Foscam cameras use /videoMain for primary RTSP and /videoSub for secondary stream.",
            "HTTP port is often 88 or 80."
        ],
        "default_channel": 1
    },
    "tuya": {
        "id": "tuya",
        "name": "Tuya / Smart Life / Nedis / Woox (Smart Wi-Fi Cameras)",
        "brand": "Tuya",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "onvif": 8000, "http": 8080},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "onvif": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Many Tuya-based smart Wi-Fi cameras support ONVIF on port 8000 or RTSP on 554.",
            "Enable ONVIF / PC View in the Smart Life / Tuya mobile app settings."
        ],
        "default_channel": 0
    },
    "yoosee": {
        "id": "yoosee",
        "name": "Yoosee / Cooau / VStarcam (CloudLinks)",
        "brand": "Yoosee",
        "category": "consumer",
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
        "category": "consumer",
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
            "Common Chinese security cam hardware OEM with Macro-Video firmware."
        ],
        "default_channel": 0
    },
    "v360": {
        "id": "v360",
        "name": "V360 Pro / Qianniao Xiangyun (CFEO Series / Cloudbirds / KeepEyes)",
        "brand": "Shenzhen Qianniao Xiangyun Technology",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "alt_rtsp": 8554, "onvif": 6688, "http": 80, "cms": 8899},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
            "alt8554": "rtsp://{username}:{password}@{ip}:8554/profile0",
            "alt_ch00": "rtsp://{username}:{password}@{ip}:{port}/live/ch00_0",
            "onvif": "rtsp://{username}:{password}@{ip}:{port}/onvif1"
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Manufacturer: Shenzhen Qianniao Xiangyun Technology Co., Ltd (Cloudbirds / sz-cloudbirds.com).",
            "Device Model & Cloud UID format: CFEO-XXXXXX-XXXXX (e.g., CFEO-164806-HRZJY).",
            "No Password in App: The V360 Pro app pairs via cloud P2P with zero password prompt. On your local Wi-Fi, the camera accepts username 'admin' with a BLANK (empty) password ('')!",
            "Port 8554 vs 554: Many Qianniao / Fullhan firmware builds run RTSP on port 8554 (/profile0) or port 554 (/live/ch0).",
            "ONVIF port is commonly 6688 or 8899. If locked, check V360 Pro app settings for 'PC View' or 'Local Monitoring'."
        ],
        "default_channel": 0
    },
    "srihome": {
        "id": "srihome",
        "name": "SriHome / Sricam (SH029, SH030, SP017)",
        "brand": "SriHome",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "onvif": 5000},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "RTSP port is 554, ONVIF port is 5000.",
            "App password defaults to 'admin' or user set in SriHome app."
        ],
        "default_channel": 1
    },
    "dlink": {
        "id": "dlink",
        "name": "D-Link (DCS Series / mydlink)",
        "brand": "D-Link",
        "category": "consumer",
        "default_ports": {"rtsp": 554, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live.sdp",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live2.sdp",
            "h264": "rtsp://{username}:{password}@{ip}:{port}/play1.sdp",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/image/jpeg.cgi",
        "ptz_supported": True,
        "quirks": [
            "DCS series commonly uses /live.sdp or /play1.sdp.",
            "Snapshot endpoint is /image/jpeg.cgi."
        ],
        "default_channel": 1
    },
    "unifi": {
        "id": "unifi",
        "name": "Ubiquiti UniFi Protect (RTSP Re-stream)",
        "brand": "Ubiquiti",
        "category": "consumer",
        "default_ports": {"rtsp": 7447, "rtsps": 7441, "standard": 554},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{ip}:{port}/{path}",
        },
        "snapshot_url": "http://{ip}/snap.jpeg",
        "ptz_supported": False,
        "quirks": [
            "In UniFi Protect web app: Click Camera > Settings > Advanced > Enable RTSP.",
            "Change rtsps:// to rtsp:// and port 7441 to 7447 for unencrypted fast LAN streaming."
        ],
        "default_channel": 1
    },

    # =========================================================================
    # GENERIC CHINESE OEM CHIPSETS (Xiongmai / Gato / Sofia / HiSilicon)
    # =========================================================================
    "xiongmai": {
        "id": "xiongmai",
        "name": "Xiongmai / XM / NetSurveillance (Generic Chinese Cam)",
        "brand": "Xiongmai (XM)",
        "category": "chinese_oem",
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
            "The quintessential 'Random Chinese IP Camera' chipset (HiSilicon / XM530 / Sofia / Goke).",
            "Typically operates on Media Port 34567 for CMS / VMS desktop software.",
            "ONVIF is usually on port 8899 or 80. Default password is often completely empty.",
            "If camera demands Internet Explorer ActiveX, use OmniSight's direct snapshot polling or RTSP feed!"
        ],
        "default_channel": 0
    },
    "gatocam": {
        "id": "gatocam",
        "name": "Shenzhen GatoCam (Indoor / Outdoor / PTZ)",
        "brand": "Shenzhen Gato",
        "category": "chinese_oem",
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
            "Zero-IE HTML5 engine bypasses required ActiveX plugins."
        ],
        "default_channel": 0
    },

    # =========================================================================
    # ANALOG CCTV DVRs & COAXIAL BNC HUBS
    # =========================================================================
    "hikvision_dvr": {
        "id": "hikvision_dvr",
        "name": "Hikvision CCTV DVR / TurboHD (Analog BNC Multi-channel)",
        "brand": "Hikvision",
        "category": "dvr",
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
        "category": "dvr",
        "default_ports": {"rtsp": 554, "media": 34567, "onvif": 8899, "http": 80},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}_sub",
        },
        "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Standard Chinese CCTV DVR for coaxial BNC cameras (AHD, TVI, CVI, CVBS).",
            "Channels are 0-indexed: BNC Ch 1 = /live/ch0, BNC Ch 2 = /live/ch1, Ch 3 = /live/ch2.",
            "Desktop software port is 34567 (CMS / XMeye). Password on 'admin' is almost always blank."
        ],
        "default_channel": 1
    },
    "zosi_dvr": {
        "id": "zosi_dvr",
        "name": "ZOSI / Lorex / Swann / Night Owl / Annke (Analog & IP NVR)",
        "brand": "ZOSI / Lorex",
        "category": "dvr",
        "default_ports": {"rtsp": 554, "http": 80, "media": 9000},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/ucast/{channel}1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/ucast/{channel}2",
            "alternate": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Common OEM for ZOSI, Lorex, Swann, and Night Owl DVRs.",
            "Uses /ucast/11 (Channel 1 Main), /ucast/12 (Channel 1 Sub), /ucast/21 (Channel 2 Main)."
        ],
        "default_channel": 1
    },

    # =========================================================================
    # DIY, IOT & MICROCONTROLLER CAMERAS
    # =========================================================================
    "esp32_cam": {
        "id": "esp32_cam",
        "name": "ESP32-CAM / ESP32-S3 Eye / Seeed Xiao",
        "brand": "ESP32",
        "category": "diy",
        "default_ports": {"http": 80, "stream": 81, "alt": 8080},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/stream",
            "mjpeg": "http://{ip}:81/stream",
        },
        "snapshot_url": "http://{ip}:{port}/capture",
        "ptz_supported": False,
        "quirks": [
            "Standard Espressif camera web server firmware streams multipart MJPEG on port 80/stream or 81/stream.",
            "Single still frame capture on /capture."
        ],
        "default_channel": 1
    },
    "raspberry_pi": {
        "id": "raspberry_pi",
        "name": "Raspberry Pi Camera / OctoPrint / Prusa / Klipper",
        "brand": "Raspberry Pi",
        "category": "diy",
        "default_ports": {"http": 8080, "stream": 5000, "standard": 80},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/?action=stream",
            "mjpg": "http://{ip}:{port}/webcam/?action=stream",
            "rtsp": "rtsp://{ip}:8554/unicast",
        },
        "snapshot_url": "http://{ip}:{port}/?action=snapshot",
        "ptz_supported": False,
        "quirks": [
            "Standard mjpg-streamer or ustreamer endpoint used by OctoPrint and Mainsail / Fluidd.",
            "RTSP available when running mediamtx or libcamera-vid."
        ],
        "default_channel": 1
    },
    "ip_webcam": {
        "id": "ip_webcam",
        "name": "Android & iOS IP Webcam Apps (IP Webcam / DroidCam)",
        "brand": "IP Webcam",
        "category": "diy",
        "default_ports": {"http": 8080, "droidcam": 4747},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/video",
            "mjpeg": "http://{ip}:{port}/videofeed",
            "droid": "http://{ip}:{port}/mjpegfeed",
        },
        "snapshot_url": "http://{ip}:{port}/shot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Turn any old smartphone into an HD CCTV camera in seconds.",
            "Supports torch control, front/back camera switch, and live MJPEG streaming."
        ],
        "default_channel": 1
    },
    "usb_webcam": {
        "id": "usb_webcam",
        "name": "Local USB Webcam / Built-in Camera (DirectShow / V4L2)",
        "brand": "Local Hardware",
        "category": "diy",
        "default_ports": {"stream": 0},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "webcam://{path}",
        },
        "snapshot_url": "/api/cameras/{id}/snapshot",
        "ptz_supported": False,
        "quirks": [
            "Direct USB or integrated webcam hardware ingestion from the host system.",
            "Uses DirectShow on Windows, V4L2 on Linux (/dev/video0), and AVFoundation on macOS."
        ],
        "default_channel": 0
    },
    "browser_node": {
        "id": "browser_node",
        "name": "Browser Camera Node (Stream Phone / Laptop into NVR)",
        "brand": "HTML5 Node",
        "category": "diy",
        "default_ports": {"stream": 8080},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "node://{id}",
        },
        "snapshot_url": "/api/cameras/{id}/snapshot",
        "ptz_supported": False,
        "quirks": [
            "Zero installation: Uses browser navigator.mediaDevices.getUserMedia() to push frames straight into the NVR!",
            "Any phone, iPad, or laptop can act as a surveillance node."
        ],
        "default_channel": 1
    },

    # =========================================================================
    # UNIVERSAL PROTOCOLS & EMULATION
    # =========================================================================
    "legacy_activex": {
        "id": "legacy_activex",
        "name": "Legacy Camera (Requires Internet Explorer / ActiveX)",
        "brand": "Legacy CCTV",
        "category": "generic",
        "default_ports": {"http": 80, "rtsp": 554},
        "default_credentials": {"username": "admin", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
        },
        "snapshot_url": "http://{ip}:{port}/snapshot.jpg",
        "ptz_supported": True,
        "quirks": [
            "Bypasses ActiveX! OmniSight polls the camera's raw snapshot endpoint at 15 FPS, so you can view it in Chrome/Edge/Firefox without Internet Explorer."
        ],
        "default_channel": 0
    },
    "generic_onvif": {
        "id": "generic_onvif",
        "name": "Generic ONVIF Camera (Profile S / G / T)",
        "brand": "ONVIF",
        "category": "generic",
        "default_ports": {"rtsp": 554, "onvif": 80, "http": 80},
        "default_credentials": {"username": "admin", "password": "admin"},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
            "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2",
        },
        "snapshot_url": "",
        "ptz_supported": True,
        "quirks": [
            "Standard ONVIF Profile S stream URL. OmniSight auto-negotiates RTSP URI dynamically."
        ],
        "default_channel": 1
    },
    "generic_rtsp": {
        "id": "generic_rtsp",
        "name": "Custom RTSP Stream (TCP / UDP / Auto)",
        "brand": "Custom RTSP",
        "category": "generic",
        "default_ports": {"rtsp": 554},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "rtsp://{username}:{password}@{ip}:{port}/{path}",
        },
        "snapshot_url": "",
        "ptz_supported": False,
        "quirks": [
            "Provide your exact RTSP path in the URL field. OmniSight automatically retries UDP if TCP times out."
        ],
        "default_channel": 1
    },
    "rtmp_stream": {
        "id": "rtmp_stream",
        "name": "RTMP / RTMPS Live Stream (OBS / Dji / Action Cam)",
        "brand": "RTMP",
        "category": "generic",
        "default_ports": {"rtmp": 1935},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "rtmp://{ip}:{port}/{path}",
        },
        "snapshot_url": "",
        "ptz_supported": False,
        "quirks": [
            "Ingest live broadcast streams from OBS Studio, action cams, drones, or RTMP re-streamers."
        ],
        "default_channel": 1
    },
    "mjpeg_http": {
        "id": "mjpeg_http",
        "name": "HTTP MJPEG Stream",
        "brand": "HTTP/MJPEG",
        "category": "generic",
        "default_ports": {"http": 80, "stream": 8080},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/stream",
            "mjpeg": "http://{ip}:{port}/mjpeg",
        },
        "snapshot_url": "http://{ip}:{port}/snapshot.jpg",
        "ptz_supported": False,
        "quirks": [
            "Direct multipart MJPEG stream over HTTP. Fully functional without external dependencies."
        ],
        "default_channel": 1
    },
    "hls_stream": {
        "id": "hls_stream",
        "name": "HLS Stream (.m3u8)",
        "brand": "HLS",
        "category": "generic",
        "default_ports": {"http": 80, "https": 443},
        "default_credentials": {"username": "", "password": ""},
        "rtsp_patterns": {
            "main": "http://{ip}:{port}/{path}",
        },
        "snapshot_url": "",
        "ptz_supported": False,
        "quirks": [
            "HTTP Live Streaming playlist (.m3u8). Transcoded to low-latency MJPEG for instant matrix display."
        ],
        "default_channel": 1
    },
    "simulated": {
        "id": "simulated",
        "name": "OmniSight Virtual CCTV Generator (Simulation)",
        "brand": "OmniSight Simulator",
        "category": "generic",
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

# Ordered list of common RTSP candidate paths for rapid parallel probing
COMMON_RTSP_CANDIDATE_PATHS = [
    "/Streaming/Channels/101",
    "/cam/realmonitor?channel=1&subtype=0",
    "/live/ch0",
    "/profile0",
    "/live/ch00_0",
    "/stream1",
    "/h264Preview_01_main",
    "/onvif1",
    "/live",
    "/unicast/c1/s0/live",
    "/axis-media/media.amp?videocodec=h264",
    "/videoMain",
    "/live/ch1",
    "/Streaming/Channels/1",
    "/profile2/media.smp",
    "/MediaInput/h264",
    "/live.sdp",
    "/ch0_0.264",
    "/main",
    "/ucast/11",
    "/h264/ch1/main/av_stream",
    "/media/video1",
    "/rtsp_tunnel?inst=1"
]

COMMON_SNAPSHOT_CANDIDATE_PATHS = [
    "/ISAPI/Streaming/channels/101/picture",
    "/cgi-bin/snapshot.cgi?channel=1",
    "/snapshot.jpg",
    "/jpg/image.jpg",
    "/cgi-bin/api.cgi?cmd=Snap&channel=01",
    "/tmpfs/auto.jpg",
    "/oneshotimage.jpg",
    "/snap.jpg",
    "/image/jpeg.cgi",
    "/capture",
    "/?action=snapshot"
]


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
    if preset_id == "usb_webcam":
        return f"webcam://{custom_path or ip or '0'}"
    if preset_id == "browser_node":
        return f"node://{custom_path or ip or 'local'}"

    # Determine default port
    if port is None or port == 0:
        default_ports = preset.get("default_ports", {})
        port = default_ports.get("rtsp", default_ports.get("http", default_ports.get("stream", 554)))

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

    # Replace in template cleanly
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
            "reason": "Port 37777 is the proprietary Dahua / Amcrest TCP management port."
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
            "confidence": "High",
            "reason": "Port 2020 is the signature TP-Link Tapo ONVIF service port."
        }
    if 6688 in open_set:
        return {
            "preset_id": "v360",
            "confidence": "High",
            "reason": "Port 6688 is the signature ONVIF service port for V360 Pro / Qianniao Xiangyun cameras."
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
            "reason": "Port 5000 alongside 554 indicates Yoosee / Cooau / SriHome camera."
        }
    if 7447 in open_set or 7441 in open_set:
        return {
            "preset_id": "unifi",
            "confidence": "High",
            "reason": "Port 7447 is the Ubiquiti UniFi Protect RTSP streaming port."
        }
    if 8554 in open_set:
        return {
            "preset_id": "v360",
            "confidence": "Medium",
            "reason": "Port 8554 is the standard RTSP port for V360 Pro (Qianniao) and Wyze Bridge re-streamers."
        }
    if 4747 in open_set:
        return {
            "preset_id": "ip_webcam",
            "confidence": "High",
            "reason": "Port 4747 is the DroidCam / IP Webcam port."
        }
    if 8080 in open_set and 554 not in open_set:
        return {
            "preset_id": "ip_webcam",
            "confidence": "Medium",
            "reason": "Port 8080 without RTSP 554 frequently indicates Android IP Webcam or ESP32-CAM."
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
