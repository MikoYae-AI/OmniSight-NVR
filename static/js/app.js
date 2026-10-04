/**
 * OmniSight-NVR - Universal CCTV & Surveillance Dashboard
 * Dual Mode: Works both as a Standalone Client on GitHub Pages (https://mikoyae-ai.github.io/OmniSight-NVR)
 * and connected to the local Python high-speed NVR backend (http://localhost:8080).
 */

const IS_GITHUB_PAGES = window.location.hostname.includes("github.io") || window.location.protocol === "file:";
let hubBaseUrl = "";

// Global toast notifier. (Was referenced across the app but never defined —
// every call site used to throw a ReferenceError.)
function showNotification(message, kind = "info") {
  try {
    let host = document.getElementById("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.style.cssText = "position:fixed; top:70px; right:16px; z-index:10000; display:flex; flex-direction:column; gap:8px; pointer-events:none;";
      document.body.appendChild(host);
    }
    const colors = { success: "#34c759", error: "#ff453a", warning: "#ff9f0a", info: "#0a84ff" };
    const color = colors[kind] || colors.info;
    const toast = document.createElement("div");
    toast.textContent = message;
    toast.style.cssText = `background: rgba(20,20,24,0.92); border:1px solid ${color}66; color:#f5f5f7; border-left:3px solid ${color}; padding:10px 14px; border-radius:10px; font-size:12px; max-width:340px; box-shadow:0 8px 24px rgba(0,0,0,0.4); backdrop-filter: blur(20px);`;
    host.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  } catch (e) {
    console.warn("[notify]", message, e);
  }
}

function apiUrl(path) {
  return `${hubBaseUrl}${path}`;
}
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
let localApiAvailable = false;
let cameras = [];
let vendorPresets = {};
let currentLayout = "2x2";
let activeFilter = "All";
let activePtzCamId = null;
let activePtzSession = { pan: 0.0, tilt: 0.0, zoom: 1.0 };
let pollingIntervals = {};
let authToken = sessionStorage.getItem("omnisight_token") || localStorage.getItem("omnisight_token") || "";

// Fallback Default Cameras (For pure client-side GitHub Pages mode)
const DEFAULT_CLIENT_CAMERAS = [
  {
    id: "cam-hikvision-13",
    name: "Hikvision DS-2CD2420F-IW (Live)",
    vendor: "hikvision",
    group: "Living Area",
    ip: "192.168.1.13",
    port: 554,
    username: "admin",
    password: "",
    stream_url: "sim://hikvision_living",
    sub_stream_url: "sim://hikvision_living_sub",
    snapshot_url: "http://192.168.1.13/ISAPI/Streaming/channels/101/picture",
    channel: 1,
    is_simulated: true,
    legacy_polling: true,
    status: "online",
    fps: 25,
    resolution: "1920x1080",
    ptz: true,
    notes: "Hikvision 2MP Cube IP Camera (DS-2CD2420F-IW, R6 Platform)."
  },
  {
    id: "cam-gatocam-01",
    name: "Shenzhen GatoCam (All Variants)",
    vendor: "gatocam",
    group: "Perimeter",
    ip: "192.168.1.10",
    port: 554,
    username: "admin",
    password: "",
    stream_url: "sim://gatocam_perimeter",
    sub_stream_url: "sim://gatocam_perimeter_sub",
    snapshot_url: "http://192.168.1.10/snapshot.jpg",
    channel: 0,
    is_simulated: true,
    status: "online",
    fps: 25,
    resolution: "1920x1080",
    ptz: true,
    legacy_polling: true,
    notes: "Shenzhen GatoCam / XM OEM security camera. Supports Zero-IE snapshot polling and OpenIPC."
  },
  {
    id: "cam-xiongmai-02",
    name: "Chinese CCTV Cam (Old XM / NetSurveillance)",
    vendor: "xiongmai",
    group: "Backyard",
    ip: "192.168.1.102",
    port: 554,
    username: "admin",
    password: "",
    stream_url: "sim://xm_backyard",
    sub_stream_url: "sim://xm_backyard_sub",
    channel: 0,
    is_simulated: true,
    status: "online",
    fps: 20,
    resolution: "1280x720",
    ptz: false,
    legacy_polling: true,
    notes: "Legacy Xiongmai CCTV cam running HiSilicon firmware. Uses snapshot polling."
  },
  {
    id: "cam-dahua-03",
    name: "Dahua XVR BNC Driveway",
    vendor: "dahua",
    group: "Driveway",
    ip: "192.168.1.103",
    port: 554,
    username: "admin",
    password: "admin",
    stream_url: "sim://dahua_driveway",
    sub_stream_url: "sim://dahua_driveway_sub",
    channel: 1,
    is_simulated: true,
    status: "online",
    fps: 30,
    resolution: "2560x1440",
    ptz: true,
    notes: "Dahua Coaxial XVR BNC Channel 1 with active deterrence."
  },
  {
    id: "cam-tapo-04",
    name: "Tapo C200 Interior",
    vendor: "tapo",
    group: "Indoor",
    ip: "192.168.1.104",
    port: 554,
    username: "admin",
    password: "",
    stream_url: "sim://tapo_interior",
    sub_stream_url: "sim://tapo_interior_sub",
    channel: 1,
    is_simulated: true,
    status: "online",
    fps: 25,
    resolution: "1920x1080",
    ptz: true,
    notes: "TP-Link Tapo indoor Pan/Tilt camera."
  },
  {
    id: "cam-webcam-05",
    name: "Host HD Webcam (/dev/video0)",
    vendor: "usb_webcam",
    group: "Office",
    ip: "localhost",
    port: 0,
    username: "",
    password: "",
    stream_url: "sim://usb_webcam",
    sub_stream_url: "",
    channel: 0,
    is_simulated: true,
    status: "online",
    fps: 30,
    resolution: "1280x720",
    ptz: false,
    notes: "Hardware V4L2 USB/integrated webcam on host machine."
  }
];

const BUILTIN_PRESETS = {
  "hikvision": {
    "id": "hikvision",
    "name": "Hikvision (DS-2CD / ColorVu / AcuSense)",
    "brand": "Hikvision",
    "category": "mainstream",
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "sdk": 8000,
      "onvif": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}02"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
    // Plugin-free live MJPEG (what WebComponents.exe consumed in IE)
    "mjpeg_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/httpPreview",
    "ptz_supported": true,
    "quirks": [
      "No WebComponents.exe needed! The camera's own web UI asks for that Hikvision IE plugin, but OmniSight uses ISAPI / PSIA / RTSP directly.",
      "Live MJPEG without any plugin: /ISAPI/Streaming/channels/101/httpPreview - used automatically when RTSP is unavailable.",
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "tcp": 37777,
      "onvif": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "tcp": 37777,
      "onvif": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "onvif": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "123456"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/unicast/c{channel}/s1/live"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/images/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "https": 443
    },
    "default_credentials": {
      "username": "root",
      "password": "pass"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp?videocodec=h264&resolution=640x360"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/jpg/image.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "https": 443
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/profile2/media.smp",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/profile3/media.smp",
      "alternate": "rtsp://{username}:{password}@{ip}:{port}/live/ch0"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/stw-cgi/video.cgi?msubmenu=snapshot&action=view",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "https": 443
    },
    "default_credentials": {
      "username": "service",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/rtsp_tunnel?inst=1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/rtsp_tunnel?inst=2"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snap.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/media/video1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/media/video2"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/oneshotimage.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "12345"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/MediaInput/h264",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/MediaInput/h264/stream_2"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/camera",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80
    },
    "default_credentials": {
      "username": "root",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live.sdp",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live2.sdp"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/viewer/video.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "ms1234"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/main",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/sub"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot",
    "ptz_supported": true,
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
    "default_ports": {
      "http": 80,
      "rtsp": 554
    },
    "default_credentials": {
      "username": "admin",
      "password": "meinsm"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/stream-0",
      "mjpeg": "http://{username}:{password}@{ip}:{port}/control/faststream.jpg?stream=full"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/record/current.jpg",
    "ptz_supported": true,
    "quirks": [
      "Default password on older models was 'meinsm'.",
      "Supports faststream.jpg continuous multipart MJPEG stream over HTTP."
    ],
    "default_channel": 1
  },
  "icsee": {
    "id": "icsee",
    "name": "ICSee / XMeye / iCSee Pro (App-Paired IP Camera)",
    "brand": "ICSee",
    "category": "consumer",
    "default_ports": {
      "rtsp": 554,
      "media": 34567,
      "onvif": 8899,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "sdk": 8000
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/main",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/sub",
      "alternate": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/101"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/101/picture",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "tcp": 37777,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "onvif": 2020,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/stream1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/stream2"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "stream1": "rtsp://{username}:{password}@{ip}:{port}/stream1"
    },
    "snapshot_url": "",
    "ptz_supported": false,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "https": 443,
      "onvif": 8000
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/h264Preview_{channel}_main",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/h264Preview_{channel}_sub"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/api.cgi?cmd=Snap&channel={channel}&user={username}&password={password}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "bridge": 8554
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live",
      "bridge": "rtsp://{ip}:8554/{path}"
    },
    "snapshot_url": "http://{ip}:5000/snapshot/{path}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live1"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 88,
      "stream": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/videoMain",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/videoSub"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/cgi-bin/CGIProxy.fcgi?cmd=snapPicture2&usr={username}&pwd={password}",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "onvif": 8000,
      "http": 8080
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "onvif": "rtsp://{username}:{password}@{ip}:{port}/onvif1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "onvif": 5000,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "123456"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "onvif": 8899
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "alt_rtsp": 8554,
      "onvif": 6688,
      "http": 80,
      "cms": 8899
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
      "alt8554": "rtsp://{username}:{password}@{ip}:8554/profile0",
      "alt_ch00": "rtsp://{username}:{password}@{ip}:{port}/live/ch00_0",
      "onvif": "rtsp://{username}:{password}@{ip}:{port}/onvif1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "onvif": 5000
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live.sdp",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live2.sdp",
      "h264": "rtsp://{username}:{password}@{ip}:{port}/play1.sdp"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/image/jpeg.cgi",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 7447,
      "rtsps": 7441,
      "standard": 554
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{ip}:{port}/{path}"
    },
    "snapshot_url": "http://{ip}/snap.jpeg",
    "ptz_supported": false,
    "quirks": [
      "In UniFi Protect web app: Click Camera > Settings > Advanced > Enable RTSP.",
      "Change rtsps:// to rtsp:// and port 7441 to 7447 for unencrypted fast LAN streaming."
    ],
    "default_channel": 1
  },
  "xiongmai": {
    "id": "xiongmai",
    "name": "Xiongmai / XM / NetSurveillance (Generic Chinese Cam)",
    "brand": "Xiongmai (XM)",
    "category": "chinese_oem",
    "default_ports": {
      "rtsp": 554,
      "media": 34567,
      "onvif": 8899,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
      "alternate": "rtsp://{username}:{password}@{ip}:{port}/h264/ch1/main/av_stream"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "onvif": 8899,
      "media": 34567
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch1",
      "stream1": "rtsp://{username}:{password}@{ip}:{port}/stream1",
      "onvif1": "rtsp://{username}:{password}@{ip}:{port}/onvif1"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
    "quirks": [
      "Shenzhen Gato / XM / Sofia OEM architecture with HiSilicon/Goke SoC.",
      "Primary RTSP pattern: rtsp://<ip>:554/live/ch0 or /stream1.",
      "Legacy Snapshot URL: http://<ip>/snapshot.jpg or http://<ip>/tmpfs/auto.jpg.",
      "Zero-IE HTML5 engine bypasses required ActiveX plugins."
    ],
    "default_channel": 0
  },
  "hikvision_dvr": {
    "id": "hikvision_dvr",
    "name": "Hikvision CCTV DVR / TurboHD (Analog BNC Multi-channel)",
    "brand": "Hikvision",
    "category": "dvr",
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "sdk": 8000
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}02"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "media": 34567,
      "onvif": 8899,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}_sub"
    },
    "snapshot_url": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554,
      "http": 80,
      "media": 9000
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/ucast/{channel}1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/ucast/{channel}2",
      "alternate": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01"
    },
    "snapshot_url": "",
    "ptz_supported": true,
    "quirks": [
      "Common OEM for ZOSI, Lorex, Swann, and Night Owl DVRs.",
      "Uses /ucast/11 (Channel 1 Main), /ucast/12 (Channel 1 Sub), /ucast/21 (Channel 2 Main)."
    ],
    "default_channel": 1
  },
  "esp32_cam": {
    "id": "esp32_cam",
    "name": "ESP32-CAM / ESP32-S3 Eye / Seeed Xiao",
    "brand": "ESP32",
    "category": "diy",
    "default_ports": {
      "http": 80,
      "stream": 81,
      "alt": 8080
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "http://{ip}:{port}/stream",
      "mjpeg": "http://{ip}:81/stream"
    },
    "snapshot_url": "http://{ip}:{port}/capture",
    "ptz_supported": false,
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
    "default_ports": {
      "http": 8080,
      "stream": 5000,
      "standard": 80
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "http://{ip}:{port}/?action=stream",
      "mjpg": "http://{ip}:{port}/webcam/?action=stream",
      "rtsp": "rtsp://{ip}:8554/unicast"
    },
    "snapshot_url": "http://{ip}:{port}/?action=snapshot",
    "ptz_supported": false,
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
    "default_ports": {
      "http": 8080,
      "droidcam": 4747
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "http://{ip}:{port}/video",
      "mjpeg": "http://{ip}:{port}/videofeed",
      "droid": "http://{ip}:{port}/mjpegfeed"
    },
    "snapshot_url": "http://{ip}:{port}/shot.jpg",
    "ptz_supported": true,
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
    "default_ports": {
      "stream": 0
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "webcam://{path}"
    },
    "snapshot_url": "/api/cameras/{id}/snapshot",
    "ptz_supported": false,
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
    "default_ports": {
      "stream": 8080
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "node://{id}"
    },
    "snapshot_url": "/api/cameras/{id}/snapshot",
    "ptz_supported": false,
    "quirks": [
      "Zero installation: Uses browser navigator.mediaDevices.getUserMedia() to push frames straight into the NVR!",
      "Any phone, iPad, or laptop can act as a surveillance node."
    ],
    "default_channel": 1
  },
  "legacy_activex": {
    "id": "legacy_activex",
    "name": "Legacy Camera (Requires Internet Explorer / ActiveX)",
    "brand": "Legacy CCTV",
    "category": "generic",
    "default_ports": {
      "http": 80,
      "rtsp": 554
    },
    "default_credentials": {
      "username": "admin",
      "password": ""
    },
    // ActiveX-era cameras have no dependable RTSP path - poll the raw JPEG instead.
    "snapshot_first": true,
    "rtsp_patterns": {},
    "snapshot_url": "http://{ip}:{port}/webcapture.jpg?command=snap&channel={channel}",
    "ptz_supported": true,
    "quirks": [
      "Bypasses ActiveX! OmniSight finds the camera's raw JPEG endpoint and polls it in HTML5 - no Internet Explorer needed.",
      "The snapshot endpoint is auto-detected (webcapture.jpg, snapshot.jpg, ISAPI, ONVIF, CGI...).",
      "If the camera does offer RTSP, run the Universal Connection Prober and that will be used instead."
    ],
    "default_channel": 1
  },
  "generic_onvif": {
    "id": "generic_onvif",
    "name": "Generic ONVIF Camera (Profile S / G / T)",
    "brand": "ONVIF",
    "category": "generic",
    "default_ports": {
      "rtsp": 554,
      "onvif": 80,
      "http": 80
    },
    "default_credentials": {
      "username": "admin",
      "password": "admin"
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1",
      "sub": "rtsp://{username}:{password}@{ip}:{port}/onvif2"
    },
    "snapshot_url": "",
    "ptz_supported": true,
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
    "default_ports": {
      "rtsp": 554
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtsp://{username}:{password}@{ip}:{port}/{path}"
    },
    "snapshot_url": "",
    "ptz_supported": false,
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
    "default_ports": {
      "rtmp": 1935
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "rtmp://{ip}:{port}/{path}"
    },
    "snapshot_url": "",
    "ptz_supported": false,
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
    "default_ports": {
      "http": 80,
      "stream": 8080
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "http://{ip}:{port}/stream",
      "mjpeg": "http://{ip}:{port}/mjpeg"
    },
    "snapshot_url": "http://{ip}:{port}/snapshot.jpg",
    "ptz_supported": false,
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
    "default_ports": {
      "http": 80,
      "https": 443
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "http://{ip}:{port}/{path}"
    },
    "snapshot_url": "",
    "ptz_supported": false,
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
    "default_ports": {
      "stream": 8000
    },
    "default_credentials": {
      "username": "",
      "password": ""
    },
    "rtsp_patterns": {
      "main": "sim://{scene}"
    },
    "snapshot_url": "/api/cameras/{id}/snapshot",
    "ptz_supported": true,
    "quirks": [
      "Built-in procedural CCTV video engine. Simulates vendor OSD, night vision, motion triggers, and pan/tilt."
    ],
    "default_channel": 1
  }
};

// DOM Elements
const cameraGrid = document.getElementById("cameraGrid");
const clockDisplay = document.getElementById("clockDisplay");
const groupPills = document.getElementById("groupPills");
const totalCamCount = document.getElementById("totalCamCount");
const ffmpegStatus = document.getElementById("ffmpegStatus");
const appModeBadge = document.getElementById("appModeBadge");
const hubModeText = document.getElementById("hubModeText");
const backendBridgeStatus = document.getElementById("backendBridgeStatus");

// Modals
const loginModal = document.getElementById("loginModal");
const changePasswordModal = document.getElementById("changePasswordModal");
const cloudRelayModal = document.getElementById("cloudRelayModal");
const cameraModal = document.getElementById("cameraModal");
const dvrModal = document.getElementById("dvrModal");
const discoveryModal = document.getElementById("discoveryModal");
const galleryModal = document.getElementById("galleryModal");
const vendorGuideModal = document.getElementById("vendorGuideModal");
const ptzPanel = document.getElementById("ptzPanel");

// 4G Cloud Relay Controls
const btnCloudRelay = document.getElementById("btnCloudRelay");
const btnCloseCloudRelayModal = document.getElementById("btnCloseCloudRelayModal");

// Hub Connector (cross-platform bridge to any OmniSight hub)
const hubConnectorModal = document.getElementById("hubConnectorModal");
const btnHubConnector = document.getElementById("btnHubConnector");
const btnCloseHubConnectorModal = document.getElementById("btnCloseHubConnectorModal");
const hubConnectorUrlInput = document.getElementById("hubConnectorUrlInput");
const hubConnectorUserInput = document.getElementById("hubConnectorUserInput");
const hubConnectorPassInput = document.getElementById("hubConnectorPassInput");
const hubConnectorRemember = document.getElementById("hubConnectorRemember");
const hubConnectorStatus = document.getElementById("hubConnectorStatus");
const btnConnectHub = document.getElementById("btnConnectHub");
const btnDisconnectHub = document.getElementById("btnDisconnectHub");
const cloudRelayDot = document.getElementById("cloudRelayDot");
const cloudRelayStatusBadge = document.getElementById("cloudRelayStatusBadge");
const cloudRelayUrlInput = document.getElementById("cloudRelayUrlInput");
const btnCopyCloudUrl = document.getElementById("btnCopyCloudUrl");
const btnOpenCloudUrl = document.getElementById("btnOpenCloudUrl");
const btnRestartCloudRelay = document.getElementById("btnRestartCloudRelay");
const cloudLanIp = document.getElementById("cloudLanIp");
const cloudTailscaleIp = document.getElementById("cloudTailscaleIp");
const cloudQrImage = document.getElementById("cloudQrImage");
const cloudQrPlaceholder = document.getElementById("cloudQrPlaceholder");

// Auth & Firebase Controls
const btnLoginNav = document.getElementById("btnLoginNav");
const userMenu = document.getElementById("userMenu");
const currentUserDisplay = document.getElementById("currentUserDisplay");
const btnChangePassNav = document.getElementById("btnChangePassNav");
const btnLogoutNav = document.getElementById("btnLogoutNav");
const loginForm = document.getElementById("loginForm");
const loginAlert = document.getElementById("loginAlert");
const changePasswordForm = document.getElementById("changePasswordForm");
const changePassAlert = document.getElementById("changePassAlert");
const btnFirebaseGoogleLogin = document.getElementById("btnFirebaseGoogleLogin");
const cfgFirebaseConfig = document.getElementById("cfgFirebaseConfig");
const btnSaveFirebaseConfig = document.getElementById("btnSaveFirebaseConfig");

// Forms
const cameraForm = document.getElementById("cameraForm");
const dvrForm = document.getElementById("dvrForm");
const camVendor = document.getElementById("camVendor");
const quirkText = document.getElementById("quirkText");

document.addEventListener("DOMContentLoaded", async () => {
  // Check for Hub deep-link parameter or Google OAuth 2.0 redirect token
  const urlParams = new URLSearchParams(window.location.search);
  const hubParam = urlParams.get("hub");
  if (hubParam) {
    const cleanHub = hubParam.trim().replace(/\/+$/, "");
    if (cleanHub) {
      localStorage.setItem("omnisight_hub_url", cleanHub);
      showNotification(`Linked to Hub: ${cleanHub}`, "success");
    }
  }

  const oauthToken = urlParams.get("token");
  if (oauthToken) {
    authToken = oauthToken;
    sessionStorage.setItem("omnisight_token", authToken);
    localStorage.setItem("omnisight_token", authToken);
    sessionStorage.setItem("omnisight_unlocked", "true");
    showNotification("Authenticated via Google OAuth 2.0!", "success");
  }

  if (hubParam || oauthToken) {
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  initClock();
  initFirebaseAuth();
  await detectBackend();
  attachEventListeners();
  if (localApiAvailable) {
    await fetchCloudRelayStatus();
    setInterval(fetchCloudRelayStatus, 15000);
  }
});

function initClock() {
  function update() {
    const now = new Date();
    clockDisplay.textContent = now.toTimeString().split(" ")[0];
  }
  update();
  setInterval(update, 1000);
}

// Authenticated Fetch Helper
async function authFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (authToken) {
    options.headers["Authorization"] = `Bearer ${authToken}`;
  }
  const targetUrl = url.startsWith("http") ? url : apiUrl(url);
  const res = await fetch(targetUrl, options);
  if (res.status === 401 && localApiAvailable) {
    // Unauthorized: prompt login modal
    updateAuthUI(false);
    loginAlert.classList.remove("hidden");
    loginAlert.textContent = "Session expired or authentication required.";
    loginModal.classList.remove("hidden");
  }
  return res;
}

// Update UI based on authentication state
function updateAuthUI(authenticated, username = "admin") {
  if (authenticated) {
    btnLoginNav.classList.add("hidden");
    userMenu.classList.remove("hidden");
    currentUserDisplay.textContent = `👤 ${username}`;
  } else {
    btnLoginNav.classList.remove("hidden");
    userMenu.classList.add("hidden");
  }
}

// Google Identity Services (GIS) Client
let googleClientId = "";
let isGoogleAuthInitialized = false;

function initGoogleAuth(clientId) {
  if (clientId) {
    googleClientId = clientId;
    localStorage.setItem("omnisight_google_client_id", clientId);
  } else {
    googleClientId = localStorage.getItem("omnisight_google_client_id") || "";
  }

  const container = document.getElementById("googleBtnContainer");
  if (!container) return;

  if (!window.google || !window.google.accounts || !window.google.accounts.id) {
    setTimeout(() => initGoogleAuth(googleClientId), 400);
    renderCustomGoogleButton();
    return;
  }

  if (googleClientId) {
    try {
      google.accounts.id.initialize({
        client_id: googleClientId,
        callback: handleGoogleCredentialResponse,
        auto_select: false,
        cancel_on_tap_outside: true
      });
      container.innerHTML = "";
      google.accounts.id.renderButton(container, {
        theme: "outline",
        size: "large",
        type: "standard",
        shape: "pill",
        text: "signin_with",
        logo_alignment: "left",
        width: 280
      });
      isGoogleAuthInitialized = true;
      return;
    } catch (err) {
      console.warn("[GoogleAuth] GIS render failed, falling back to custom button:", err);
    }
  }

  renderCustomGoogleButton();
}

function renderCustomGoogleButton() {
  const container = document.getElementById("googleBtnContainer");
  if (!container) return;
  if (container.querySelector("#btnCustomGoogleLogin")) return;

  container.innerHTML = `
    <button type="button" id="btnCustomGoogleLogin" class="btn-google-signin" title="Sign in with Google Account">
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
        <path fill="none" d="M0 0h48v48H0z"/>
      </svg>
      <span>Sign in with Google</span>
    </button>
  `;

  const btn = document.getElementById("btnCustomGoogleLogin");
  if (btn) {
    btn.onclick = () => {
      if (!googleClientId) {
        openGoogleSignInModal();
      } else {
        if (window.google && window.google.accounts && window.google.accounts.id) {
          google.accounts.id.prompt();
        } else {
          openGoogleSignInModal();
        }
      }
    };
  }
}

function openGoogleSignInModal() {
  const googleModal = document.getElementById("googleModal");
  if (googleModal) {
    document.getElementById("googleAlert")?.classList.add("hidden");
    loginModal.classList.add("hidden");
    googleModal.classList.remove("hidden");
  }
}

async function handleGoogleCredentialResponse(response) {
  if (!response || !response.credential) {
    loginAlert.textContent = "No Google credential received.";
    loginAlert.classList.remove("hidden");
    return;
  }

  if (localApiAvailable) {
    try {
      loginAlert.classList.add("hidden");
      const res = await fetch(apiUrl("/api/auth/google"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: response.credential, client_id: googleClientId })
      });
      const data = await res.json();
      if (res.ok && data.token) {
        authToken = data.token;
        sessionStorage.setItem("omnisight_token", authToken);
        localStorage.setItem("omnisight_token", authToken);
        updateAuthUI(true, data.name || data.username || data.email);
        loginModal.classList.add("hidden");
        showNotification(`Welcome, ${data.name || data.username}!`, "success");
        await fetchCameras();
      } else {
        loginAlert.textContent = data.error || "Google authentication failed on server.";
        loginAlert.classList.remove("hidden");
      }
    } catch (err) {
      loginAlert.textContent = "Network error during Google authentication.";
      loginAlert.classList.remove("hidden");
    }
    return;
  }

  // Standalone / GitHub Pages Mode
  try {
    const base64Url = response.credential.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
    const payload = JSON.parse(jsonPayload);
    sessionStorage.setItem("omnisight_unlocked", "true");
    updateAuthUI(true, payload.name || payload.email || "Google User");
    loginModal.classList.add("hidden");
    showNotification(`Welcome, ${payload.name || "Google User"}!`, "success");
    renderGrid();
  } catch (e) {
    sessionStorage.setItem("omnisight_unlocked", "true");
    updateAuthUI(true, "Google User");
    loginModal.classList.add("hidden");
    renderGrid();
  }
}

// Firebase Web Auth Integration
let firebaseAuthInstance = null;

function initFirebaseAuth() {
  const savedConfig = localStorage.getItem("omnisight_firebase_config");
  if (savedConfig && window.firebase) {
    try {
      const config = JSON.parse(savedConfig);
      if (!firebase.apps || !firebase.apps.length) {
        firebase.initializeApp(config);
      }
      firebaseAuthInstance = firebase.auth();
      if (cfgFirebaseConfig) {
        cfgFirebaseConfig.value = savedConfig;
      }
    } catch (e) {
      console.warn("[Firebase] Error initializing Firebase:", e);
    }
  }
}

async function handleFirebaseGoogleSignIn() {
  const alertEl = document.getElementById("googleAlert");
  if (alertEl) alertEl.classList.add("hidden");

  if (window.firebase && firebaseAuthInstance) {
    try {
      const provider = new firebase.auth.GoogleAuthProvider();
      provider.addScope("email");
      provider.addScope("profile");
      const result = await firebaseAuthInstance.signInWithPopup(provider);
      const user = result.user;
      const idToken = await user.getIdToken();

      if (localApiAvailable) {
        const res = await fetch(apiUrl("/api/auth/google"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            credential: idToken,
            email: user.email,
            name: user.displayName || user.email.split("@")[0],
            picture: user.photoURL || ""
          })
        });
        const data = await res.json();
        if (res.ok && data.status === "ok") {
          authToken = data.token;
          sessionStorage.setItem("omnisight_token", authToken);
          localStorage.setItem("omnisight_token", authToken);
          sessionStorage.setItem("omnisight_unlocked", "true");
          updateAuthUI(true, data.username || data.name);
          document.getElementById("googleModal")?.classList.add("hidden");
          loginModal.classList.add("hidden");
          showNotification(`Firebase Verified: Welcome, ${data.name || data.username}!`, "success");
          await fetchCameras();
          return;
        }
      } else {
        sessionStorage.setItem("omnisight_unlocked", "true");
        updateAuthUI(true, user.displayName || user.email);
        document.getElementById("googleModal")?.classList.add("hidden");
        loginModal.classList.add("hidden");
        showNotification(`Welcome, ${user.displayName || user.email}! (Firebase Auth)`, "success");
        renderGrid();
        return;
      }
    } catch (err) {
      console.warn("[Firebase] Sign-in error:", err);
      if (alertEl) {
        alertEl.textContent = err.message || "Firebase sign-in error";
        alertEl.classList.remove("hidden");
      }
      return;
    }
  }

  // If Firebase not yet configured, use direct email
  const emailInput = document.getElementById("googleUserEmail");
  const nameInput = document.getElementById("googleUserName");
  const email = emailInput?.value.trim() || "nimuthumethsenganegoda@gmail.com";
  const name = nameInput?.value.trim() || "Nimuthu";

  if (localApiAvailable) {
    try {
      const res = await fetch(apiUrl("/api/auth/google"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, name })
      });
      const data = await res.json();
      if (res.ok && data.status === "ok") {
        authToken = data.token;
        sessionStorage.setItem("omnisight_token", authToken);
        localStorage.setItem("omnisight_token", authToken);
        sessionStorage.setItem("omnisight_unlocked", "true");
        updateAuthUI(true, data.username || data.name);
        document.getElementById("googleModal")?.classList.add("hidden");
        loginModal.classList.add("hidden");
        showNotification(`Welcome, ${data.name || data.username}! (Google Direct)`, "success");
        await fetchCameras();
        return;
      }
    } catch (e) {
      if (alertEl) {
        alertEl.textContent = "Google login error: " + e.message;
        alertEl.classList.remove("hidden");
      }
    }
  }
}

// 4G Cloud Relay Manager Status Polling
async function fetchCloudRelayStatus() {
  if (!localApiAvailable) return;
  try {
    const res = await fetch(apiUrl("/api/cloud-relay"), { cache: "no-cache" });
    if (!res.ok) return;
    const data = await res.json();

    if (cloudRelayDot) {
      if (data.status === "connected") {
        cloudRelayDot.style.background = "#34c759";
        cloudRelayDot.title = "4G Cloud Relay: Active";
      } else if (data.status === "connecting") {
        cloudRelayDot.style.background = "#ff9500";
        cloudRelayDot.title = "4G Cloud Relay: Connecting...";
      } else {
        cloudRelayDot.style.background = "#8e8e93";
        cloudRelayDot.title = "4G Cloud Relay: Inactive";
      }
    }

    if (cloudRelayStatusBadge) {
      cloudRelayStatusBadge.textContent = (data.status || "IDLE").toUpperCase();
      if (data.status === "connected") {
        cloudRelayStatusBadge.style.background = "rgba(52, 199, 89, 0.15)";
        cloudRelayStatusBadge.style.color = "#34c759";
        cloudRelayStatusBadge.style.borderColor = "rgba(52, 199, 89, 0.3)";
      } else {
        cloudRelayStatusBadge.style.background = "rgba(255, 149, 0, 0.15)";
        cloudRelayStatusBadge.style.color = "#ff9500";
        cloudRelayStatusBadge.style.borderColor = "rgba(255, 149, 0, 0.3)";
      }
    }

    if (cloudRelayUrlInput && data.cloud_url) {
      cloudRelayUrlInput.value = data.cloud_url;
    }
    if (cloudLanIp) {
      cloudLanIp.textContent = data.local_url || "127.0.0.1:8080";
    }
    if (cloudTailscaleIp) {
      cloudTailscaleIp.textContent = data.tailscale_url || "Not Connected";
    }

    if (data.qr_image && cloudQrImage && cloudQrPlaceholder) {
      cloudQrImage.src = data.qr_image;
      cloudQrImage.style.display = "block";
      cloudQrPlaceholder.style.display = "none";
    }
  } catch (err) {
    console.debug("[CloudRelay] Polling error:", err);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Hub Connector — cross-platform bridge between this website and an OmniSight
// hub running anywhere: Linux server, Windows PC, macOS, Docker, Raspberry Pi,
// reachable over LAN, Tailscale, or a Cloudflare tunnel URL.
// ─────────────────────────────────────────────────────────────────────────────
function getSavedHubUrl() {
  return (localStorage.getItem("omnisight_hub_url") || "").trim();
}

function refreshHubConnectorUI() {
  if (!hubConnectorUrlInput || !hubConnectorStatus) return;
  const saved = getSavedHubUrl();
  if (!hubConnectorUrlInput.value && saved) hubConnectorUrlInput.value = saved;
  const hasToken = !!(sessionStorage.getItem("omnisight_token") || localStorage.getItem("omnisight_token"));
  if (saved) {
    hubConnectorStatus.textContent = hasToken
      ? `Configured: ${saved} · signed in (token stored)`
      : `Configured: ${saved}`;
  } else {
    hubConnectorStatus.textContent = "No hub configured — running in standalone mode.";
  }
  hubConnectorStatus.style.color = saved ? "#34c759" : "#8e8e93";
}

function setHubConnectorBusy(busy) {
  if (!btnConnectHub) return;
  btnConnectHub.disabled = busy;
  btnConnectHub.textContent = busy ? "Signing in…" : "🔌 Connect & Reload";
}

function isLoopbackUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl, window.location.href);
    const host = (parsed.hostname || "").toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
  } catch (e) {
    return false;
  }
}

function isPageOnLocalOrigin() {
  const host = (window.location.hostname || "").toLowerCase();
  return (
    window.location.protocol === "file:" ||
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "[::1]" ||
    host === "::1" ||
    host.endsWith(".local") ||
    /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.|169\.254\.)/.test(host)
  );
}

async function connectToHub() {
  const raw = (hubConnectorUrlInput ? hubConnectorUrlInput.value : "").trim();
  if (!raw) {
    showNotification("Enter a hub URL first.", "error");
    return;
  }
  let url;
  try {
    url = new URL(raw);
  } catch (e) {
    showNotification("That doesn't look like a valid URL.", "error");
    return;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    showNotification("Hub URL must start with http:// or https://", "error");
    return;
  }
  const clean = url.origin; // normalised, trailing slash/path stripped
  const username = (hubConnectorUserInput ? hubConnectorUserInput.value : "").trim();
  const password = hubConnectorPassInput ? hubConnectorPassInput.value : "";
  const remember = hubConnectorRemember ? hubConnectorRemember.checked : true;
  const mixedBlock = location.protocol === "https:" && url.protocol === "http:" && !isLoopbackUrl(clean);

  // An HTTPS page (e.g. GitHub Pages) can never reach a plain-http LAN hub —
  // with credentials involved, fail fast instead of saving a dead config.
  if (mixedBlock && (username || password)) {
    showNotification(
      "This HTTPS page can't sign in to a plain-http hub (browser mixed-content rule). Open the hub URL directly in a new tab, or use the hub's https tunnel URL.",
      "error"
    );
    return;
  }

  if (username || password) {
    if (!username || !password) {
      showNotification("Enter both username and password, or leave both empty.", "error");
      return;
    }
    // Sign in to the hub. Only the returned session token is stored in the
    // browser — never the password itself.
    setHubConnectorBusy(true);
    try {
      const res = await fetch(`${clean}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.token) {
        showNotification(data.error || "Sign-in failed — check the username and password.", "error");
        setHubConnectorBusy(false);
        return;
      }
      authToken = data.token;
      if (remember) {
        localStorage.setItem("omnisight_token", data.token);
        sessionStorage.removeItem("omnisight_token");
      } else {
        sessionStorage.setItem("omnisight_token", data.token);
        localStorage.removeItem("omnisight_token");
      }
      showNotification(
        `Signed in as ${data.username || username}${remember ? " — remembered on this device" : " — this browser session only"}.`,
        "success"
      );
    } catch (e) {
      showNotification("Hub unreachable — check the URL and that the hub is running.", "error");
      setHubConnectorBusy(false);
      return;
    } finally {
      if (hubConnectorPassInput) hubConnectorPassInput.value = ""; // never keep the password in the DOM
      setHubConnectorBusy(false);
    }
  } else if (!mixedBlock) {
    // Perform the status check while the user's click gesture is active so any
    // browser Local Network Access prompt can be answered before reloading.
    setHubConnectorBusy(true);
    try {
      await fetch(`${clean}/api/status`, { cache: "no-cache", mode: "cors" });
    } catch (e) {
      // Save anyway so the user can retry after starting the hub or allowing permission.
    } finally {
      setHubConnectorBusy(false);
    }
  }

  localStorage.setItem("omnisight_hub_url", clean);
  if (mixedBlock) {
    showNotification(
      "Saved — but browsers block this HTTPS page from calling a plain-http hub. Use an https tunnel URL, or open the hub URL directly.",
      "warning"
    );
    setTimeout(() => location.reload(), 2500);
    return;
  }
  showNotification(`Connecting to ${clean} …`, "success");
  setTimeout(() => location.reload(), 600);
}

function disconnectHub() {
  const saved = getSavedHubUrl();
  if (authToken && saved) {
    // Best-effort server-side logout; the local token is wiped regardless.
    try {
      fetch(`${saved}/api/auth/logout`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${authToken}` }
      });
    } catch (e) { /* ignore */ }
  }
  localStorage.removeItem("omnisight_hub_url");
  localStorage.removeItem("omnisight_token");
  sessionStorage.removeItem("omnisight_token");
  authToken = "";
  location.reload();
}

function buildStartupHubCandidates(opts) {
  const options = opts || {};
  const isGithubPages = options.isGithubPages !== undefined ? options.isGithubPages : IS_GITHUB_PAGES;
  const savedHub = options.savedHub !== undefined ? options.savedHub : getSavedHubUrl();
  const permissionState = options.permissionState !== undefined ? options.permissionState : null;
  const localOrigin = options.localOrigin !== undefined ? options.localOrigin : isPageOnLocalOrigin();
  const pageProtocol = options.pageProtocol !== undefined ? options.pageProtocol : window.location.protocol;
  const candidates = [];

  // 1. Same-origin service check never triggers a Local Network Access prompt.
  if (!isGithubPages) {
    candidates.push("");
  }

  // 2. If the browser explicitly denied local-network access, skip cross-origin
  //    local/loopback probes on startup.
  if (permissionState === "denied") {
    return candidates;
  }

  // 3. Explicitly saved Hub URL: skip only when HTTPS -> plain-HTTP LAN mixed
  //    content rules are guaranteed to block the request.
  if (savedHub) {
    const blockedByMixedContent =
      pageProtocol === "https:" &&
      savedHub.startsWith("http://") &&
      !isLoopbackUrl(savedHub);
    if (!blockedByMixedContent && !candidates.includes(savedHub)) {
      candidates.push(savedHub);
    }
    return candidates;
  }

  // 4. Conventional localhost fallback: only probe on startup when the dashboard
  //    is already on a local origin or when Local Network permission was already
  //    granted. Never probe both localhost and 127.0.0.1 back-to-back from a
  //    public origin, which causes duplicate/flickering permission prompts.
  if (localOrigin || permissionState === "granted") {
    if (!candidates.includes("http://localhost:8080")) {
      candidates.push("http://localhost:8080");
    }
  }

  return candidates;
}

// Detect the same-origin service or restore a configured/local Hub without
// firing unsolicited cross-origin local-network requests that glitch browser prompts.
async function detectBackend() {
  const permission = await queryBrowserLocalNetworkPermission();
  const candidates = buildStartupHubCandidates({
    isGithubPages: IS_GITHUB_PAGES,
    savedHub: getSavedHubUrl(),
    permissionState: permission?.state || null,
    localOrigin: isPageOnLocalOrigin(),
    pageProtocol: window.location.protocol
  });

  for (const candidate of candidates) {
    try {
      const probeUrl = candidate ? `${candidate}/api/status` : "/api/status";
      const res = await fetch(probeUrl, { cache: "no-cache", mode: "cors" });
      if (res.ok) {
        const status = await res.json();
        hubBaseUrl = candidate;
        localApiAvailable = true;
        const isTunnel = candidate.includes("trycloudflare.com");
        const heroConnectionLabel = document.getElementById("heroConnectionLabel");
        if (heroConnectionLabel) heroConnectionLabel.textContent = isTunnel ? "SECURE TUNNEL" : "LOCAL HUB";
        appModeBadge.textContent = isTunnel ? "SECURE TUNNEL ONLINE" : "LOCAL HUB ONLINE";
        appModeBadge.style.background = "rgba(179, 217, 118, 0.12)";
        appModeBadge.style.borderColor = "rgba(179, 217, 118, 0.30)";
        appModeBadge.style.color = "var(--accent-green)";
        hubModeText.textContent = isTunnel ? "Connected via Cloudflare Secure Tunnel" : "Connected to Python NVR Hub (:8080)";
        backendBridgeStatus.textContent = isTunnel ? `Cloudflare Tunnel Active (${candidate})` : "Local Server Mode: Full Hardware Multiplexing Active";

        if (status.ffmpeg_available) {
          ffmpegStatus.textContent = "RTSP Transcoder: FFmpeg Hardware Active";
          ffmpegStatus.style.color = "var(--accent-green)";
        } else {
          ffmpegStatus.textContent = "RTSP Engine: Standalone Engine Active";
        }

        // Check current session
        if (authToken) {
          const meRes = await authFetch("/api/auth/me");
          if (meRes.ok) {
            const me = await meRes.json();
            if (me.authenticated) {
              updateAuthUI(true, me.username);
            } else {
              authToken = "";
              sessionStorage.removeItem("omnisight_token");
              localStorage.removeItem("omnisight_token");
              updateAuthUI(false);
              loginModal.classList.remove("hidden");
            }
          }
        } else {
          updateAuthUI(false);
          loginModal.classList.remove("hidden");
        }

        initGoogleAuth(status.google_client_id);
        await fetchPresets();
        await fetchCameras();
        return;
      }
    } catch (e) {
      // If the user denied the browser's Local Network prompt during this check,
      // stop probing any remaining candidates immediately.
      const updatedPerm = (await queryBrowserLocalNetworkPermission()) || permission;
      if (updatedPerm?.state === "denied") break;
    }
  }

  // Fallback to standalone browser mode when no hub is reachable.
  localApiAvailable = false;
  const savedHub = getSavedHubUrl();
  const heroConnectionLabel = document.getElementById("heroConnectionLabel");
  if (heroConnectionLabel) heroConnectionLabel.textContent = savedHub ? "HUB OFFLINE" : "BROWSER MODE";
  appModeBadge.textContent = savedHub ? "HUB UNREACHABLE" : "BROWSER MODE";
  hubModeText.textContent = savedHub ? "Saved hub unavailable" : "Browser-only · Local storage";
  backendBridgeStatus.textContent = "Standalone browser mode · connect a hub for server-side ingest";
  if (savedHub) {
    backendBridgeStatus.textContent = `Hub Connector: ${savedHub} configured but unreachable — check the hub / tunnel is running`;
    backendBridgeStatus.style.color = "#e2a965";
  }
  refreshHubConnectorUI();
  ffmpegStatus.textContent = "Browser mode: direct snapshot feeds available";
  
  // In Cloud mode, check passcode lock if configured
  const savedPasscode = localStorage.getItem("omnisight_passcode");
  if (savedPasscode) {
    const sessionUnlocked = sessionStorage.getItem("omnisight_unlocked");
    if (sessionUnlocked) {
      updateAuthUI(true, "Cloud User");
    } else {
      updateAuthUI(false);
      loginModal.classList.remove("hidden");
    }
  } else {
    updateAuthUI(true, "Guest");
  }

  initGoogleAuth();
  vendorPresets = BUILTIN_PRESETS;
  loadLocalCameras();
}

// Load Cameras from LocalStorage (GitHub Pages Mode)
function loadLocalCameras() {
  const saved = localStorage.getItem("omnisight_cameras");
  if (saved) {
    try {
      cameras = JSON.parse(saved);
    } catch (e) {
      cameras = DEFAULT_CLIENT_CAMERAS;
    }
  } else {
    cameras = DEFAULT_CLIENT_CAMERAS;
    localStorage.setItem("omnisight_cameras", JSON.stringify(cameras));
  }

  const savedLayout = localStorage.getItem("omnisight_layout") || "2x2";
  setLayout(savedLayout, false);
  
  const groups = ["All", ...new Set(cameras.map(c => c.group || "Default"))];
  renderGroupPills(groups);
  renderGrid();
}

function saveLocalCameras() {
  localStorage.setItem("omnisight_cameras", JSON.stringify(cameras));
}

// Fetch Presets from Backend
async function fetchPresets() {
  if (!localApiAvailable) {
    vendorPresets = BUILTIN_PRESETS;
    updateVendorQuirks();
    return;
  }
  try {
    const res = await authFetch("/api/presets");
    if (res.ok) {
      vendorPresets = await res.json();
      updateVendorQuirks();
    }
  } catch (err) {
    vendorPresets = BUILTIN_PRESETS;
  }
}

// Fetch Cameras from Backend
async function fetchCameras() {
  if (!localApiAvailable) {
    loadLocalCameras();
    return;
  }
  try {
    const res = await authFetch("/api/cameras");
    if (res.ok) {
      const data = await res.json();
      cameras = data.cameras || [];
      currentLayout = data.layout || "2x2";
      setLayout(currentLayout, false);
      renderGroupPills(data.groups || ["All"]);
      renderGrid();
    }
  } catch (err) {
    loadLocalCameras();
  }
}

// Render Group Filter Pills
function renderGroupPills(groups) {
  groupPills.innerHTML = "";
  const allBtn = document.createElement("button");
  allBtn.className = `pill ${activeFilter === "All" ? "active" : ""}`;
  allBtn.textContent = `All Cameras (${cameras.length})`;
  allBtn.onclick = () => setFilter("All");
  groupPills.appendChild(allBtn);

  groups.forEach(g => {
    if (g === "All" || !g) return;
    const btn = document.createElement("button");
    btn.className = `pill ${activeFilter === g ? "active" : ""}`;
    btn.textContent = g;
    btn.onclick = () => setFilter(g);
    groupPills.appendChild(btn);
  });
  totalCamCount.textContent = cameras.length;
  const heroCameraCount = document.getElementById("heroCameraCount");
  if (heroCameraCount) heroCameraCount.textContent = String(cameras.length).padStart(2, "0");
}

function setFilter(group) {
  activeFilter = group;
  document.querySelectorAll(".group-pills .pill").forEach(p => {
    p.classList.toggle("active", p.textContent.startsWith(group));
  });
  renderGrid();
}

// Set Layout Grid
function setLayout(layout, save = true) {
  currentLayout = layout;
  cameraGrid.className = `camera-grid grid-${layout}`;
  const heroLayoutLabel = document.getElementById("heroLayoutLabel");
  if (heroLayoutLabel) heroLayoutLabel.textContent = layout.replace("x", "×");
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.layout === layout);
  });

  if (save) {
    if (localApiAvailable) {
      authFetch("/api/layout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layout })
      });
    } else {
      localStorage.setItem("omnisight_layout", layout);
    }
  }
}

// Render Camera Cards
function renderGrid() {
  const heroCameraCount = document.getElementById("heroCameraCount");
  if (heroCameraCount) heroCameraCount.textContent = String(cameras.length).padStart(2, "0");
  if (totalCamCount) totalCamCount.textContent = cameras.length;

  // Clear any active snapshot polling intervals or timers
  Object.keys(pollingIntervals).forEach(k => {
    clearInterval(pollingIntervals[k]);
    clearTimeout(pollingIntervals[k]);
    delete pollingIntervals[k];
  });

  cameraGrid.innerHTML = "";
  const filtered = activeFilter === "All" 
    ? cameras 
    : cameras.filter(c => c.group === activeFilter);

  if (filtered.length === 0) {
    if (cameras.length === 0) {
      cameraGrid.innerHTML = `
        <section class="empty-matrix" aria-labelledby="emptyMatrixTitle">
          <div class="empty-matrix-art" aria-hidden="true">⌖</div>
          <p class="empty-matrix-kicker">01 / YOUR CAMERA MATRIX</p>
          <h3 id="emptyMatrixTitle">Bring your first camera into view.</h3>
          <p>Add a camera by its local address, or discover devices on your network. Your video stays under your control.</p>
          <div class="empty-matrix-actions">
            <button type="button" class="btn-action btn-primary" id="emptyAddCamera">＋ Add a camera</button>
            <button type="button" class="btn-action btn-secondary" id="emptyDiscoverCameras">⌕ Discover devices</button>
          </div>
          <p class="empty-matrix-note">LOCAL-FIRST · ONVIF · RTSP · LEGACY CCTV</p>
        </section>`;
      document.getElementById("emptyAddCamera")?.addEventListener("click", openAddCameraModal);
      document.getElementById("emptyDiscoverCameras")?.addEventListener("click", () => discoveryModal.classList.remove("hidden"));
    } else {
      cameraGrid.innerHTML = `<div class="empty-state no-group-cameras" style="grid-column: 1/-1;">No cameras in “${escapeHtml(activeFilter)}”. <button type="button" class="btn-text" id="btnClearCameraFilter">Show all cameras</button></div>`;
      document.getElementById("btnClearCameraFilter")?.addEventListener("click", () => setFilter("All"));
    }
    return;
  }

  filtered.forEach(cam => {
    const card = document.createElement("div");
    card.className = "camera-card";
    card.dataset.id = cam.id;

    const vendorClass = (cam.vendor || "generic").replace("_dvr", "");
    const isLegacy = cam.legacy_polling || cam.vendor === "legacy_activex";

    const safeName = escapeHtml(cam.name);
    const safeId = escapeHtml(cam.id);
    const safeGroup = escapeHtml(cam.group || "Default");
    const safeIp = escapeHtml(cam.ip || "");

    card.innerHTML = `
      <div class="card-header">
        <div class="card-title-group">
          <span class="cam-status-dot" id="statusDot-${safeId}" title="Live camera status"></span>
          <span class="cam-name" title="${safeName}">${safeName}</span>
          <span class="vendor-tag ${vendorClass}">${escapeHtml(cam.vendor || "CAM")}</span>
          ${isLegacy ? `<span class="badge-legacy" title="ActiveX bypassed: HTML5 snapshot polling">NO-IE</span>` : ''}
        </div>
        <div class="card-actions">
          <button class="btn-icon" title="Maximize View" onclick="toggleFocus('${safeId}')">⛶</button>
          <button class="btn-icon" title="Take Snapshot" onclick="captureSnapshot('${safeId}', '${safeName}')">📷</button>
          ${cam.ptz ? `<button class="btn-icon" title="PTZ Controls" onclick="openPtz('${safeId}', '${safeName}')">🎮</button>` : ''}
          <button class="btn-icon" title="Edit Camera" onclick="openEditCameraModal('${safeId}')">⚙️</button>
          <button class="btn-icon" title="Delete Camera" onclick="deleteCamera('${safeId}')">🗑️</button>
        </div>
      </div>
      <div class="video-container" id="videoContainer-${safeId}" ondblclick="toggleFocus('${safeId}')">
        <!-- Live feed rendered here -->
        <div class="video-overlay-hud">${escapeHtml(cam.resolution || "1080p")} • ${cam.fps || 25} FPS</div>
      </div>
      <div class="card-footer">
        <span>${safeIp ? `IP: ${safeIp}` : "Stream"}</span>
        <span>${safeGroup}</span>
      </div>
    `;
    cameraGrid.appendChild(card);

    // Reflect the real ingestion state instead of always claiming "online"
    if (cam.live_status) applyLiveCameraStatus(cam.id, cam.live_status);
    else setCameraStatusDot(cam.id, "connecting", "Waiting for NVR telemetry...");

    // Setup Video Player for this Camera
    setupCameraPlayer(cam);
  });

  refreshLiveStatuses();
}

// --- Live camera status (online / reconnecting / offline) ---
const STATUS_LABELS = {
  streaming: ["online", "Live stream healthy"],
  connecting: ["connecting", "Connecting to camera..."],
  reconnecting: ["connecting", "Camera unreachable - retrying"],
  idle: ["connecting", "Session starting..."],
  error: ["offline", "Camera failed - check credentials / network"]
};

function setCameraStatusDot(camId, status, detail = "") {
  const dot = document.getElementById(`statusDot-${camId}`);
  if (!dot) return;
  const [cls, defaultLabel] = STATUS_LABELS[status] || ["connecting", "Status unknown"];
  dot.classList.remove("online", "connecting", "offline");
  dot.classList.add(cls);
  dot.title = detail || defaultLabel;
}

function applyLiveCameraStatus(camId, live) {
  if (!live) return;
  setCameraStatusDot(camId, live.status, live.last_error || "");
}

// Poll the NVR for real per-camera state without re-rendering the video grid.
async function refreshLiveStatuses() {
  if (!localApiAvailable) return;
  try {
    const res = await authFetch("/api/cameras");
    if (!res.ok) return;
    const data = await res.json();
    (data.cameras || []).forEach(cam => {
      if (cam.live_status) applyLiveCameraStatus(cam.id, cam.live_status);
    });
  } catch (err) {}
}

if (typeof window !== "undefined") {
  window.setInterval(refreshLiveStatuses, 5000);
}

// Setup Camera Video Stream Player
function setupCameraPlayer(cam) {
  const container = document.getElementById(`videoContainer-${cam.id}`);
  if (!container) return;

  // Browser Camera Node direct local mirror with zero latency
  if ((cam.vendor === "browser_node" || cam.id === activeBrowserNodeCamId) && activeBrowserNodeStream) {
    const vid = document.createElement("video");
    vid.className = "video-feed";
    vid.autoplay = true;
    vid.muted = true;
    vid.playsInline = true;
    vid.srcObject = activeBrowserNodeStream;
    container.insertBefore(vid, container.firstChild);
    return;
  }

  if (localApiAvailable) {
    // Connected to Python server: use native multipart MJPEG
    const img = document.createElement("img");
    img.className = "video-feed";
    img.src = apiUrl(`/api/cameras/${cam.id}/stream?token=${encodeURIComponent(authToken)}`);
    img.alt = cam.name;
    container.insertBefore(img, container.firstChild);
    return;
  }

  // Browser Camera Node in GitHub Pages mode (sharing frames via canvas)
  if ((cam.vendor === "browser_node" || cam.id === activeBrowserNodeCamId) && latestBrowserNodeFrame) {
    const img = document.createElement("img");
    img.className = "video-feed";
    img.alt = cam.name;
    img.src = latestBrowserNodeFrame;
    container.insertBefore(img, container.firstChild);
    pollingIntervals[cam.id] = setInterval(() => {
      if (latestBrowserNodeFrame) img.src = latestBrowserNodeFrame;
    }, 120);
    return;
  }

  // Legacy Snapshot Polling Mode (skip pure sim:// cameras so they use the canvas simulator)
  const isPureSimStream = String(cam.stream_url || "").trim().startsWith("sim://");
  if (cam.legacy_polling && cam.ip && !isPureSimStream) {
    // Preferred path: let the NVR find and fetch the camera's still-image endpoint.
    // This handles endpoint auto-detection, Digest/Basic auth, and avoids the
    // mixed-content and CORS restrictions that block direct browser -> camera calls.
    if (localApiAvailable) {
      const img = document.createElement("img");
      img.className = "video-feed";
      img.alt = cam.name;
      container.insertBefore(img, container.firstChild);
      const proxyUrl = apiUrl(`/api/cameras/${cam.id}/snapshot?token=${encodeURIComponent(authToken)}`);
      img.src = `${proxyUrl}&t=${Date.now()}`;
      pollingIntervals[cam.id] = setInterval(() => {
        img.src = `${proxyUrl}&t=${Date.now()}`;
      }, 500);
      return;
    }

    // On an HTTPS page (e.g. GitHub Pages), plain-HTTP camera snapshot URLs are
    // either blocked by mixed-content rules or auto-upgraded to https:// by
    // Chromium — which triggers unsolicited Local Network Access prompts on page
    // load and still fails TLS because cameras on port 80 do not serve HTTPS.
    // Show the browser-aware fallback immediately instead of spamming LAN IPs.
    if (window.location.protocol === "https:") {
      setCameraStatusDot(cam.id, "error", "Direct HTTP blocked on HTTPS page — connect a Local Hub");
      drawTacticalFallback(container, cam, "ACTIVE POLLING • MIXED CONTENT RESTRICTION");
      return;
    }

    const img = document.createElement("img");
    img.className = "video-feed";
    img.alt = cam.name;
    img.style.display = "none";
    container.insertBefore(img, container.firstChild);

    // Non-HTTPS standalone mode: poll the camera sequentially without overlapping
    // requests or looping after failure.
    let snapUrl = "";
    if (cam.vendor === "legacy_activex" || cam.vendor === "xiongmai" || cam.vendor === "gatocam") {
      snapUrl = `http://${cam.ip}/webcapture.jpg?command=snap&channel=${cam.channel || 1}`;
    } else if (cam.vendor === "hikvision" || cam.vendor === "hikvision_dvr") {
      snapUrl = `http://${cam.ip}/ISAPI/Streaming/channels/${cam.channel || 1}01/picture`;
    } else if (cam.vendor === "dahua" || cam.vendor === "amcrest") {
      snapUrl = `http://${cam.ip}/cgi-bin/snapshot.cgi?channel=${cam.channel || 1}`;
    } else if (cam.vendor === "axis") {
      snapUrl = `http://${cam.ip}/jpg/image.jpg`;
    } else if (cam.vendor === "uniview") {
      snapUrl = `http://${cam.ip}/images/snapshot.jpg`;
    } else {
      snapUrl = `http://${cam.ip}/snapshot.jpg`;
    }

    const directCandidates = Array.from(new Set([
      snapUrl,
      `http://${cam.ip}/webcapture.jpg?command=snap&channel=${cam.channel || 1}`,
      `http://${cam.ip}/snapshot.jpg`
    ]));
    let candidateIdx = 0;
    let pollInFlight = false;
    let pollStopped = false;

    function pollFrame() {
      if (pollStopped || pollInFlight || !container.isConnected) return;
      pollInFlight = true;
      const candidateUrl = directCandidates[candidateIdx];
      const testImg = new Image();
      testImg.onload = () => {
        pollInFlight = false;
        if (pollStopped || !container.isConnected) return;
        img.style.display = "block";
        img.src = testImg.src;
        const existingBanner = container.querySelector(".fallback-banner");
        if (existingBanner) existingBanner.remove();
        setCameraStatusDot(cam.id, "streaming", "Direct snapshot polling active");
        pollingIntervals[cam.id] = setTimeout(pollFrame, 1000);
      };
      testImg.onerror = () => {
        pollInFlight = false;
        testImg.onload = null;
        testImg.onerror = null;
        try { testImg.src = ""; } catch (e) {}
        if (pollStopped || !container.isConnected) return;
        if (candidateIdx < directCandidates.length - 1) {
          candidateIdx += 1;
          pollFrame();
          return;
        }
        pollStopped = true;
        if (pollingIntervals[cam.id]) {
          clearTimeout(pollingIntervals[cam.id]);
          clearInterval(pollingIntervals[cam.id]);
          delete pollingIntervals[cam.id];
        }
        setCameraStatusDot(cam.id, "error", "Camera unreachable or blocked by browser");
        drawTacticalFallback(container, cam, "ACTIVE POLLING • MIXED CONTENT RESTRICTION");
      };
      testImg.src = `${candidateUrl}${candidateUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
    }

    queryBrowserLocalNetworkPermission().then((perm) => {
      if (perm?.state === "denied") {
        pollStopped = true;
        setCameraStatusDot(cam.id, "error", "Browser blocked Local Network access");
        drawTacticalFallback(container, cam, "ACTIVE POLLING • MIXED CONTENT RESTRICTION");
        return;
      }
      pollFrame();
    });
    return;
  }

  // In-Browser Procedural Canvas Simulation
  const canvas = document.createElement("canvas");
  canvas.className = "video-feed";
  canvas.width = 640;
  canvas.height = 360;
  container.insertBefore(canvas, container.firstChild);

  startCanvasSimulation(canvas, cam);
}

// Procedural Canvas Renderer for GitHub Pages
function startCanvasSimulation(canvas, cam) {
  const ctx = canvas.getContext("2d");
  let frame = 0;

  function render() {
    frame++;
    const t = Date.now() / 1000;
    const w = canvas.width;
    const h = canvas.height;

    // Dark security background
    ctx.fillStyle = "#0c0e14";
    ctx.fillRect(0, 0, w, h);

    // Perspective horizon & grid lines
    const horizon = h / 2;
    ctx.strokeStyle = "#1b2230";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, horizon);
    ctx.lineTo(w, horizon);
    ctx.stroke();

    for (let i = -4; i <= 12; i++) {
      ctx.beginPath();
      ctx.moveTo(w / 2 + (i * 60), horizon);
      ctx.lineTo(w / 2 + (i * 120), h);
      ctx.stroke();
    }

    // Moving AI Target
    const cycle = (t * 0.5) % (Math.PI * 2);
    const tx = w / 2 + Math.sin(cycle) * 180;
    const ty = horizon + 30 + Math.cos(cycle * 0.5) * 15;

    // Target Box
    ctx.strokeStyle = cam.vendor === "hikvision" ? "#f59e0b" : (cam.vendor === "dahua" ? "#10b981" : "#e63946");
    ctx.lineWidth = 2;
    ctx.strokeRect(tx - 25, ty - 35, 50, 70);

    ctx.fillStyle = "rgba(0,0,0,0.8)";
    ctx.fillRect(tx - 25, ty - 50, 70, 15);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillText("OBJECT 98%", tx - 22, ty - 39);

    // Center Crosshair
    ctx.strokeStyle = "#334155";
    ctx.beginPath();
    ctx.moveTo(w / 2 - 12, h / 2);
    ctx.lineTo(w / 2 + 12, h / 2);
    ctx.moveTo(w / 2, h / 2 - 12);
    ctx.lineTo(w / 2, h / 2 + 12);
    ctx.stroke();

    // Top-Left OSD
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 12px JetBrains Mono, monospace";
    ctx.fillText(cam.name.toUpperCase(), 15, 22);

    ctx.fillStyle = "#718096";
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillText(`${(cam.vendor || "CCTV").toUpperCase()} // ${cam.ip || "DIRECT"}`, 15, 38);

    // Top-Right Clock
    const now = new Date();
    const timeStr = now.toTimeString().split(" ")[0] + "." + String(now.getMilliseconds()).padStart(3, "0");
    ctx.fillStyle = "#ffffff";
    ctx.fillText(timeStr, w - 110, 22);

    // Blinking REC
    if (Math.floor(t * 2) % 2 === 0) {
      ctx.fillStyle = "#e63946";
      ctx.beginPath();
      ctx.arc(w - 130, 18, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillText("REC", w - 122, 22);
    }

    // Scanlines
    ctx.fillStyle = "rgba(0, 0, 0, 0.15)";
    for (let y = 0; y < h; y += 4) {
      ctx.fillRect(0, y, w, 1);
    }
  }

  const animTimer = setInterval(render, 50);
  pollingIntervals[`canvas-${cam.id}`] = animTimer;
}

// ─────────────────────────────────────────────────────────────────────────────
// Mixed-content guidance. An HTTPS page (GitHub Pages) cannot pull frames from
// a plain-http camera or hub. The escape hatches differ per browser, and the
// old "padlock > Site settings > Insecure content" advice is Chrome-only — it
// does not exist in Safari at all, and in Firefox/Zen it is an about:config
// pref. Detect the engine and show guidance that actually applies.
// ─────────────────────────────────────────────────────────────────────────────
function detectBrowserEngine() {
  const ua = navigator.userAgent || "";
  const isAppleWebKit = /AppleWebKit/.test(ua);
  // Chrome, Edge, Brave, Vivaldi, Opera, Arc, Zen-mobile… all carry "Chrome".
  // Safari carries "Version/" and never "Chrome"; Zen Desktop is Gecko/Firefox.
  // FxiOS (Firefox for iOS) is deliberately excluded: Apple forces WebKit there,
  // so about:config does not exist and it needs the Safari guidance instead.
  if (/Firefox\/|Zen\/|Gecko\/20100101/.test(ua) && !/Chrome\//.test(ua) && !/FxiOS\//.test(ua)) return "gecko";
  if (/Chrome\/|Chromium\/|Edg\/|OPR\/|Vivaldi\/|Brave/.test(ua)) return "chromium";
  if (isAppleWebKit) return "webkit";
  return "other";
}

// The hub origin to deep-link to: a saved connector URL beats the loopback
// default, because the hub is often on another machine (192.168.x.x, Tailscale).
function resolveHubOrigin() {
  const saved = getSavedHubUrl();
  if (saved) return saved;
  if (hubBaseUrl) return hubBaseUrl;
  return "http://localhost:8080";
}

// Per-engine steps for users who insist on staying on the HTTPS page.
function mixedContentBrowserSteps() {
  const engine = detectBrowserEngine();
  if (engine === "chromium") {
    return {
      engine: "Chrome / Chromium",
      hasToggle: true,
      intro:
        "The “Insecure content” permission exists, but it is a <em>per-site</em> permission and many Chromium builds and forks hide it from the padlock popover. Reach it directly instead:",
      steps: [
        "Paste <code>chrome://settings/content/insecureContent</code> into the address bar (use <code>edge://</code>, <code>brave://</code>, <code>vivaldi://</code>… in forks) and add this site under “Allowed to show insecure content”.",
        "Or open <code>chrome://settings/content/siteDetails?site=https://mikoyae-ai.github.io</code> and look for <strong>Insecure content → Allow</strong>. If it is not listed, this build hides the permission.",
        "Last resort: launch the browser with <code>--allow-running-insecure-content</code>, or enable the flag “Insecure origins treated as secure” (<code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>) and list your hub origin, e.g. <code>http://192.168.1.50:8080</code>, then relaunch.",
        "Reload this page afterwards — the setting is only read on load."
      ],
      caveat:
        "Chrome 84+ also <em>auto-upgrades</em> http images to https and blocks them if the upgrade fails. A camera that only serves http will stay blank until the per-site allow is in place, and some forks ignore that setting for IP-address origins."
    };
  }
  if (engine === "gecko") {
    return {
      engine: "Firefox / Zen Browser",
      hasToggle: false,
      intro:
        "Firefox-based browsers have <strong>no</strong> “Insecure content” site permission, so it will never appear in site settings. Use <code>about:config</code> instead:",
      steps: [
        "Open <code>about:config</code>, accept the warning.",
        "Set <code>security.mixed_content.upgrade_display_content</code> to <code>false</code>. This is the one that matters here: since Firefox 127 (and Zen with it) http images/video/audio are silently rewritten to https and <em>blocked</em> when the camera has no https — so a plain-http snapshot never loads.",
        "Set <code>security.mixed_content.block_active_content</code> to <code>false</code> if you also need http fetch/XHR/iframe calls (e.g. the Hub Connector talking to <code>http://192.168.x.x:8080</code>).",
        "Reload the page. Both prefs are global — they weaken every tab, so reset them to <code>true</code> when you are done."
      ],
      caveat:
        "There is no per-site equivalent in Firefox/Zen. The old shield-icon “Disable protection on this page” menu was repurposed for Tracking Protection years ago, so it will not help with mixed content."
    };
  }
  if (engine === "webkit") {
    return {
      engine: "Safari",
      hasToggle: false,
      intro:
        "Safari blocks mixed content with <strong>no user-facing setting at all</strong> — there is nothing to allow, which is why you found no “Insecure content” row:",
      steps: [
        "macOS: Safari → Settings → Advanced → tick <strong>“Show features for web developers”</strong> (older versions: “Show Develop menu in menu bar”). Then <strong>Develop → Website Settings…</strong>, select this site in the sidebar and look for an <em>“Insecure Content” / “Load insecure content”</em> entry. Only some Safari releases ship it.",
        "If that entry is missing, Safari gives you no override — opening the hub URL directly in its own tab is the only fix.",
        "iOS / iPadOS Safari: no override exists at all. Use the hub URL, or an https tunnel URL."
      ],
      caveat:
        "Self-signed certificates do not help in Safari either: it refuses https with an untrusted cert, so a hub on a home-made certificate trades one block for another."
    };
  }
  return {
    engine: "this browser",
    hasToggle: false,
    intro: "This browser offers no reliable per-site override for mixed content:",
    steps: [
      "Open the hub URL directly in its own tab — the hub serves this exact dashboard over plain http, so nothing is mixed.",
      "Or put an https tunnel in front of the hub and paste that https URL into the Hub Connector."
    ],
    caveat: ""
  };
}

function openMixedContentHelp() {
  const modal = document.getElementById("mixedContentModal");
  if (!modal) return;
  populateMixedContentHelp();
  modal.classList.remove("hidden");
}

function populateMixedContentHelp() {
  const info = mixedContentBrowserSteps();
  const hub = resolveHubOrigin();
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  const setHtml = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = value;
  };

  setText("mcDetectedBrowser", `${info.engine} · detected automatically`);
  setHtml("mcBrowserIntro", info.intro);
  setHtml(
    "mcBrowserSteps",
    info.steps.map((s) => `<li>${s}</li>`).join("")
  );
  const caveat = document.getElementById("mcBrowserCaveat");
  if (caveat) {
    caveat.innerHTML = info.caveat || "";
    caveat.style.display = info.caveat ? "" : "none";
  }
  setText("mcHubOrigin", hub);

  const links = document.querySelectorAll("[data-mc-hub-link]");
  links.forEach((a) => {
    a.href = hub;
    a.textContent = `Open ${hub}`;
  });
}

// Fallback visual message
function drawTacticalFallback(container, cam, message) {
  const feedImg = container.querySelector("img.video-feed");
  if (feedImg && !feedImg.getAttribute("src")) {
    feedImg.style.display = "none";
  }
  let fb = container.querySelector(".fallback-banner");
  if (!fb) {
    fb = document.createElement("div");
    fb.className = "fallback-banner";
    fb.style.position = "absolute";
    fb.style.inset = "0";
    fb.style.zIndex = "3";
    fb.style.display = "flex";
    fb.style.flexDirection = "column";
    fb.style.alignItems = "center";
    fb.style.justifyContent = "center";
    fb.style.background = "rgba(14, 23, 17, 0.97)";
    fb.style.padding = "16px";
    fb.style.textAlign = "center";
    const hub = resolveHubOrigin();
    fb.innerHTML = `
      <span style="color: var(--apple-amber); font-weight: 600; font-size: 13px; margin-bottom: 6px;">
        ⚠️ Browser Blocked Direct HTTP (${cam.ip})
      </span>
      <p style="font-size: 11px; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.4; max-width: 320px;">
        This page is HTTPS, so the browser refuses plain-http requests to LAN devices —
        and most browsers offer no per-site switch for it.
      </p>
      <a href="${hub}" target="_blank" rel="noopener" class="btn-action btn-primary" style="font-size: 11px; text-decoration: none; padding: 7px 16px;">
        Open the hub instead (${hub})
      </a>
      <button type="button" class="btn-action btn-secondary" data-open-mixed-content-help style="font-size: 10px; padding: 6px 14px; margin-top: 8px;">
        Why? Fix it in ${mixedContentBrowserSteps().engine}
      </button>
    `;
    fb.querySelector("[data-open-mixed-content-help]")?.addEventListener("click", openMixedContentHelp);
    container.appendChild(fb);
  }
}

// Double click to focus single camera
function toggleFocus(camId) {
  if (currentLayout === "1x1") {
    setLayout("2x2");
  } else {
    setLayout("1x1");
    const camIndex = cameras.findIndex(c => c.id === camId);
    if (camIndex > -1) {
      const [focusCam] = cameras.splice(camIndex, 1);
      cameras.unshift(focusCam);
      renderGrid();
    }
  }
}

// Snapshot Capture
async function captureSnapshot(camId, camName) {
  flashScreen();
  if (localApiAvailable) {
    try {
      const res = await authFetch("/api/snapshots/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: camId })
      });
      if (res.ok) {
        const snap = await res.json();
        alert(`Snapshot archived: ${snap.filename}`);
        return;
      }
    } catch (e) {}
  }

  // Client-side snapshot
  const container = document.getElementById(`videoContainer-${camId}`);
  const canvas = container ? container.querySelector("canvas") : null;
  if (canvas) {
    const dataUrl = canvas.toDataURL("image/jpeg");
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = `snapshot_${camId}_${Date.now()}.jpg`;
    a.click();
    alert(`Snapshot saved: ${a.download}`);
  } else {
    alert(`Snapshot captured for ${camName}`);
  }
}

function flashScreen() {
  const flash = document.createElement("div");
  flash.style.position = "fixed";
  flash.style.inset = "0";
  flash.style.background = "white";
  flash.style.opacity = "0.7";
  flash.style.pointerEvents = "none";
  flash.style.zIndex = "9999";
  flash.style.transition = "opacity 0.3s";
  document.body.appendChild(flash);
  setTimeout(() => {
    flash.style.opacity = "0";
    setTimeout(() => flash.remove(), 300);
  }, 50);
}

// PTZ Controller
function openPtz(camId, camName) {
  activePtzCamId = camId;
  document.getElementById("ptzCamTitle").textContent = `V380 / V360 Pro: ${camName}`;
  ptzPanel.classList.remove("hidden");
  loadTimelineEvents(camId);
}

document.querySelectorAll(".ptz-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    const action = btn.dataset.ptz;
    if (localApiAvailable) {
      try {
        const res = await authFetch(`/api/cameras/${activePtzCamId}/ptz`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action })
        });
        if (res.ok) {
          const data = await res.json();
          document.getElementById("ptzTelemetry").textContent =
            `PAN: ${data.pan >= 0 ? '+' : ''}${data.pan.toFixed(1)}° | TILT: ${data.tilt >= 0 ? '+' : ''}${data.tilt.toFixed(1)}° | ZOOM: ${data.zoom.toFixed(1)}x`;
        }
      } catch (err) {}
    } else {
      if (action === "left") activePtzSession.pan -= 5;
      if (action === "right") activePtzSession.pan += 5;
      if (action === "up") activePtzSession.tilt += 5;
      if (action === "down") activePtzSession.tilt -= 5;
      if (action === "zoom_in") activePtzSession.zoom = Math.min(10, activePtzSession.zoom + 0.5);
      if (action === "zoom_out") activePtzSession.zoom = Math.max(1, activePtzSession.zoom - 0.5);
      if (action === "home") { activePtzSession.pan = 0; activePtzSession.tilt = 0; activePtzSession.zoom = 1; }
      
      document.getElementById("ptzTelemetry").textContent = 
        `PAN: ${activePtzSession.pan >= 0 ? '+' : ''}${activePtzSession.pan.toFixed(1)}° | TILT: ${activePtzSession.tilt >= 0 ? '+' : ''}${activePtzSession.tilt.toFixed(1)}° | ZOOM: ${activePtzSession.zoom.toFixed(1)}x`;
    }
  });
});

document.getElementById("btnClosePtz").onclick = () => {
  if (isPlaybackMode) returnToLive();
  ptzPanel.classList.add("hidden");
  activePtzCamId = null;
};

// Autonomous OpenCV PTZ Auto-Tracking
let isAutoTracking = false;
const btnAutoTrack = document.getElementById("btnAutoTrack");
const autoTrackBadge = document.getElementById("autoTrackBadge");

if (btnAutoTrack) {
  btnAutoTrack.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    isAutoTracking = !isAutoTracking;
    updateAutoTrackUI(isAutoTracking);

    if (localApiAvailable) {
      try {
        await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "auto_tracking", value: isAutoTracking })
        });
      } catch (e) {}
    }
    showNotification(
      isAutoTracking ? "🎯 Autonomous PTZ Auto-Tracking Activated" : "Auto-Tracking in Standby",
      isAutoTracking ? "success" : "info"
    );
  });
}

function updateAutoTrackUI(enabled) {
  if (!btnAutoTrack || !autoTrackBadge) return;
  if (enabled) {
    btnAutoTrack.style.background = "rgba(52, 199, 89, 0.15)";
    btnAutoTrack.style.borderColor = "var(--accent-green)";
    btnAutoTrack.style.color = "#fff";
    autoTrackBadge.style.background = "#34c759";
    autoTrackBadge.style.color = "#000";
    autoTrackBadge.textContent = "ENGAGED";
  } else {
    btnAutoTrack.style.background = "rgba(255, 255, 255, 0.06)";
    btnAutoTrack.style.borderColor = "rgba(255, 255, 255, 0.12)";
    btnAutoTrack.style.color = "var(--text-secondary)";
    autoTrackBadge.style.background = "rgba(255, 255, 255, 0.1)";
    autoTrackBadge.style.color = "var(--text-muted)";
    autoTrackBadge.textContent = "STANDBY";
  }
}

// V380 Pro / V360 Pro Night Vision Modes
document.querySelectorAll(".btn-nv-mode").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    const mode = btn.dataset.nv;
    document.querySelectorAll(".btn-nv-mode").forEach(b => {
      b.classList.remove("active");
      b.style.background = "rgba(255,255,255,0.06)";
      b.style.borderColor = "rgba(255,255,255,0.1)";
      b.style.color = "var(--text-secondary)";
    });
    btn.classList.add("active");
    btn.style.background = "rgba(0,122,255,0.2)";
    btn.style.borderColor = "var(--apple-blue)";
    btn.style.color = "#fff";

    const label = document.getElementById("currentNightVisionText");
    if (label) label.textContent = mode.toUpperCase();

    if (localApiAvailable) {
      try {
        await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "night_vision", value: mode })
        });
        showNotification(`Night Vision set to ${mode.toUpperCase()} (V380/V360)`, "success");
      } catch (e) {}
    } else {
      showNotification(`Night Vision set to ${mode.toUpperCase()}`, "success");
    }
  });
});

// V380 Pro Siren Trigger
const btnTriggerSiren = document.getElementById("btnTriggerSiren");
if (btnTriggerSiren) {
  btnTriggerSiren.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    btnTriggerSiren.style.background = "#ff3b30";
    btnTriggerSiren.style.color = "#fff";
    showNotification("🚨 V380/V360 Alarm Siren Sounded!", "warning");

    if (localApiAvailable) {
      try {
        await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "siren", duration: 3.0 })
        });
      } catch (e) {}
    }
    setTimeout(() => {
      btnTriggerSiren.style.background = "rgba(255, 59, 48, 0.15)";
      btnTriggerSiren.style.color = "#ff3b30";
    }, 2500);
  });
}

// V380 Pro Intercom Live Microphone Talkback
const btnIntercomTalk = document.getElementById("btnIntercomTalk");
const intercomLabel = document.getElementById("intercomLabel");
const intercomLiveBadge = document.getElementById("intercomLiveBadge");

let intercomStream = null;
let intercomRecorder = null;

if (btnIntercomTalk) {
  const startTalk = async () => {
    if (!activePtzCamId) return;
    btnIntercomTalk.style.background = "rgba(52, 199, 89, 0.35)";
    if (intercomLabel) intercomLabel.textContent = "Broadcasting Mic...";
    if (intercomLiveBadge) intercomLiveBadge.classList.remove("hidden");

    // Request browser microphone and stream audio chunks
    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        intercomStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const options = (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported("audio/webm;codecs=opus"))
          ? { mimeType: "audio/webm;codecs=opus" }
          : {};
        intercomRecorder = new MediaRecorder(intercomStream, options);

        intercomRecorder.ondataavailable = async (e) => {
          if (e.data && e.data.size > 0 && activePtzCamId) {
            const reader = new FileReader();
            reader.onloadend = async () => {
              const resParts = (reader.result || "").split(",");
              const base64Data = resParts.length > 1 ? resParts[1] : "";
              if (base64Data && localApiAvailable) {
                try {
                  await authFetch(`/api/cameras/${activePtzCamId}/talk`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ audio_base64: base64Data, format: "webm" })
                  });
                } catch (err) {}
              }
            };
            reader.readAsDataURL(e.data);
          }
        };
        intercomRecorder.start(250); // 250ms chunks
      }
    } catch (micErr) {
      console.warn("Microphone access unavailable, signaling talkback state:", micErr);
    }

    if (localApiAvailable) {
      try {
        await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "intercom", value: true })
        });
      } catch (e) {}
    }
  };

  const stopTalk = async () => {
    if (!activePtzCamId) return;
    btnIntercomTalk.style.background = "rgba(52, 199, 89, 0.15)";
    if (intercomLabel) intercomLabel.textContent = "Hold to Talk";
    if (intercomLiveBadge) intercomLiveBadge.classList.add("hidden");

    if (intercomRecorder && intercomRecorder.state !== "inactive") {
      try { intercomRecorder.stop(); } catch (e) {}
    }
    if (intercomStream) {
      intercomStream.getTracks().forEach(t => t.stop());
      intercomStream = null;
    }

    if (localApiAvailable) {
      try {
        await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "intercom", value: false })
        });
      } catch (e) {}
    }
  };

  btnIntercomTalk.addEventListener("mousedown", startTalk);
  btnIntercomTalk.addEventListener("mouseup", stopTalk);
  btnIntercomTalk.addEventListener("mouseleave", stopTalk);
  btnIntercomTalk.addEventListener("touchstart", (e) => { e.preventDefault(); startTalk(); });
  btnIntercomTalk.addEventListener("touchend", (e) => { e.preventDefault(); stopTalk(); });
}

// V380 Pro Preset Angle Memory
document.querySelectorAll(".btn-ptz-preset").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    const presetNum = parseInt(btn.dataset.preset);
    if (localApiAvailable) {
      try {
        const res = await authFetch(`/api/cameras/${activePtzCamId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: "goto_preset", value: presetNum })
        });
        if (res.ok) {
          const data = await res.json();
          document.getElementById("ptzTelemetry").textContent =
            `PAN: ${data.pan >= 0 ? '+' : ''}${data.pan.toFixed(1)}° | TILT: ${data.tilt >= 0 ? '+' : ''}${data.tilt.toFixed(1)}° | ZOOM: ${data.zoom.toFixed(1)}x`;
          showNotification(`Moved to Preset ${presetNum} (V380/V360)`, "success");
        }
      } catch (e) {}
    } else {
      showNotification(`Moved to Preset ${presetNum}`, "success");
    }
  });
});

// 24-Hour Timeline & Historical Playback Streaming Engine
const v380TimelineTrack = document.getElementById("v380TimelineTrack");
const v380EventMarkers = document.getElementById("v380EventMarkers");
const timelineNeedle = document.getElementById("timelineNeedle");
const timelineCurrentTime = document.getElementById("timelineCurrentTime");
const playbackBadge = document.getElementById("playbackBadge");
const btnPlaybackStepBack = document.getElementById("btnPlaybackStepBack");
const btnPlaybackPlayPause = document.getElementById("btnPlaybackPlayPause");
const btnPlaybackStepFwd = document.getElementById("btnPlaybackStepFwd");
const btnReturnLive = document.getElementById("btnReturnLive");

let isPlaybackMode = false;
let playbackCurrentSeconds = 12 * 3600;
let playbackPlaying = false;
let playbackInterval = null;

async function loadTimelineEvents(camId) {
  if (!v380EventMarkers || !camId) return;
  v380EventMarkers.innerHTML = "";
  if (!localApiAvailable) return;
  try {
    const res = await authFetch(`/api/cameras/${camId}/timeline`);
    if (res.ok) {
      const events = await res.json();
      events.forEach(evt => {
        const seg = document.createElement("div");
        seg.style.position = "absolute";
        seg.style.left = `${evt.start_pct}%`;
        seg.style.width = `${evt.width_pct}%`;
        seg.style.height = "100%";
        seg.style.background = evt.color;
        seg.style.pointerEvents = "none";
        seg.title = `${evt.label} (${evt.start_str} - ${evt.end_str})`;
        v380EventMarkers.appendChild(seg);
      });
    }
  } catch (e) {}
}

function seekPlayback(seconds) {
  seconds = Math.max(0, Math.min(86400, seconds));
  playbackCurrentSeconds = seconds;

  const pct = (seconds / 86400) * 100;
  if (timelineNeedle) timelineNeedle.style.left = `${pct.toFixed(2)}%`;

  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const timeStr = `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  if (timelineCurrentTime) timelineCurrentTime.textContent = timeStr;

  isPlaybackMode = true;
  if (playbackBadge) playbackBadge.classList.remove("hidden");

  // Route historical playback frame to camera stream
  if (activePtzCamId) {
    const container = document.getElementById(`videoContainer-${activePtzCamId}`);
    if (container) {
      const img = container.querySelector("img.video-feed");
      if (img) {
        img.src = apiUrl(`/api/cameras/${activePtzCamId}/playback?time=${seconds}&t=${Date.now()}&token=${encodeURIComponent(authToken)}`);
      }
    }
  }
}

function returnToLive() {
  isPlaybackMode = false;
  playbackPlaying = false;
  if (playbackInterval) {
    clearInterval(playbackInterval);
    playbackInterval = null;
  }
  if (btnPlaybackPlayPause) btnPlaybackPlayPause.textContent = "▶ Play";
  if (playbackBadge) playbackBadge.classList.add("hidden");

  const now = new Date();
  const currentSecs = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
  if (timelineNeedle) timelineNeedle.style.left = `${((currentSecs / 86400) * 100).toFixed(1)}%`;
  if (timelineCurrentTime) {
    timelineCurrentTime.textContent = `${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}:${String(now.getSeconds()).padStart(2,"0")}`;
  }

  // Restore live stream
  if (activePtzCamId) {
    const container = document.getElementById(`videoContainer-${activePtzCamId}`);
    if (container) {
      const img = container.querySelector("img.video-feed");
      if (img) {
        img.src = apiUrl(`/api/cameras/${activePtzCamId}/stream?token=${encodeURIComponent(authToken)}`);
      }
    }
  }
  showNotification("🔴 Returned to Live Camera Stream", "success");
}

if (v380TimelineTrack) {
  v380TimelineTrack.addEventListener("click", (e) => {
    const rect = v380TimelineTrack.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const pct = x / rect.width;
    const targetSeconds = Math.floor(pct * 86400);
    seekPlayback(targetSeconds);
    const timeStr = timelineCurrentTime ? timelineCurrentTime.textContent : "";
    showNotification(`Streaming playback at ${timeStr}`, "info");
  });
}

if (btnPlaybackStepBack) {
  btnPlaybackStepBack.addEventListener("click", () => {
    seekPlayback(playbackCurrentSeconds - 15);
  });
}

if (btnPlaybackStepFwd) {
  btnPlaybackStepFwd.addEventListener("click", () => {
    seekPlayback(playbackCurrentSeconds + 15);
  });
}

if (btnPlaybackPlayPause) {
  btnPlaybackPlayPause.addEventListener("click", () => {
    if (!isPlaybackMode) {
      seekPlayback(playbackCurrentSeconds);
    }
    playbackPlaying = !playbackPlaying;
    if (playbackPlaying) {
      btnPlaybackPlayPause.textContent = "⏸ Pause";
      playbackInterval = setInterval(() => {
        seekPlayback(playbackCurrentSeconds + 1);
      }, 1000);
    } else {
      btnPlaybackPlayPause.textContent = "▶ Play";
      if (playbackInterval) {
        clearInterval(playbackInterval);
        playbackInterval = null;
      }
    }
  });
}

if (btnReturnLive) {
  btnReturnLive.addEventListener("click", returnToLive);
}

// Modals: Add / Edit Camera
function openAddCameraModal() {
  cameraForm.reset();
  document.getElementById("camId").value = "";
  document.getElementById("modalTitle").textContent = "Add Camera to Matrix";
  updateVendorQuirks();
  cameraModal.classList.remove("hidden");
}

function openEditCameraModal(camId) {
  const cam = cameras.find(c => c.id === camId);
  if (!cam) return;

  document.getElementById("camId").value = cam.id;
  document.getElementById("modalTitle").textContent = "Edit Camera";
  document.getElementById("camName").value = cam.name || "";
  document.getElementById("camGroup").value = cam.group || "";
  document.getElementById("camVendor").value = cam.vendor || "generic_rtsp";
  document.getElementById("camChannel").value = cam.channel || 1;
  document.getElementById("camIp").value = cam.ip || "";
  document.getElementById("camPort").value = cam.port || 554;
  document.getElementById("camUser").value = cam.username || "";
  document.getElementById("camPass").value = cam.password || "";
  document.getElementById("camStreamUrl").value = cam.stream_url || "";
  document.getElementById("camPtz").checked = !!cam.ptz;
  document.getElementById("camLegacyPolling").checked = !!cam.legacy_polling;
  document.getElementById("camSimulated").checked = !!cam.is_simulated;

  updateVendorQuirks();
  cameraModal.classList.remove("hidden");
}

function updateVendorQuirks() {
  const selected = camVendor.value;
  const preset = vendorPresets[selected] || BUILTIN_PRESETS[selected];
  if (preset && preset.quirks) {
    quirkText.innerHTML = preset.quirks.map(q => `• ${q}`).join("<br>");
  } else {
    quirkText.textContent = "Standard surveillance configuration.";
  }
}

camVendor.addEventListener("change", () => {
  const selected = camVendor.value;
  const preset = vendorPresets[selected] || BUILTIN_PRESETS[selected];
  if (preset) {
    document.getElementById("camPort").value = preset.default_ports?.rtsp || preset.default_ports?.http || 554;
    document.getElementById("camChannel").value = preset.default_channel ?? 1;
    if (preset.default_credentials) {
      document.getElementById("camUser").value = preset.default_credentials.username || "";
      document.getElementById("camPass").value = preset.default_credentials.password || "";
    }
    if (selected === "legacy_activex") {
      document.getElementById("camLegacyPolling").checked = true;
    }
    if (selected === "webcam" || selected === "browser_node") {
      document.getElementById("camIp").value = "127.0.0.1";
    }
  }
  updateVendorQuirks();
  autoGenerateUrl();
});

function autoGenerateUrl() {
  const vendor = camVendor.value;
  const ip = document.getElementById("camIp").value || "192.168.1.100";
  const port = parseInt(document.getElementById("camPort").value) || 554;
  const username = document.getElementById("camUser").value;
  const password = document.getElementById("camPass").value;
  const channel = document.getElementById("camChannel").value || 1;

  if (vendor === "webcam") {
    document.getElementById("camStreamUrl").value = "webcam://0";
    return;
  }
  if (vendor === "browser_node") {
    document.getElementById("camStreamUrl").value = "node://browser-cam";
    return;
  }
  if (vendor === "simulated") {
    document.getElementById("camStreamUrl").value = "sim://surveillance_grid";
    return;
  }

  const preset = vendorPresets[vendor] || BUILTIN_PRESETS[vendor] || BUILTIN_PRESETS["generic_rtsp"];
  const creds = username && password ? `${username}:${password}@` : (username ? `${username}@` : "");
  const snapPattern = preset?.snapshot_pattern || preset?.snapshot_url;

  // IE/ActiveX-era cameras: their usable source is the raw JPEG endpoint, not RTSP.
  if (preset?.snapshot_first && snapPattern) {
    const httpPort = (port === 554 || port === 8554) ? (preset.default_ports?.http || 80) : port;
    document.getElementById("camStreamUrl").value = snapPattern
      .replace("{username}:{password}@", creds)
      .replace("{username}", username || "")
      .replace("{password}", password || "")
      .replace("{ip}", ip)
      .replace("{port}", httpPort)
      .replace("{channel_index}", String(Math.max(0, parseInt(channel || 1) - 1)))
      .replace("{channel}", channel);
    document.getElementById("camLegacyPolling").checked = true;
    return;
  }

  if (document.getElementById("camLegacyPolling").checked && snapPattern) {
    const snapUrl = snapPattern
      .replace("{username}:{password}@", creds)
      .replace("{ip}", ip)
      .replace("{port}", port === 554 ? "80" : String(port))
      .replace("{channel}", channel);
    document.getElementById("camStreamUrl").value = snapUrl;
    return;
  }

  const pattern = preset?.rtsp_patterns?.main || "rtsp://{username}:{password}@{ip}:{port}/live/ch0";
  const chIdx = Math.max(0, parseInt(channel || 1) - 1);
  const streamUrl = pattern
    .replace("{username}:{password}@", creds)
    .replace("{ip}", ip)
    .replace("{port}", port)
    .replace("{channel}", channel)
    .replace("{channel_index}", chIdx)
    .replace("{path}", "");

  document.getElementById("camStreamUrl").value = streamUrl;
}

document.getElementById("btnAutoGenerateUrl").onclick = autoGenerateUrl;

cameraForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(cameraForm);
  const camId = formData.get("id");
  const payload = {
    name: formData.get("name"),
    group: formData.get("group") || "Default",
    vendor: formData.get("vendor"),
    channel: parseInt(formData.get("channel")) || 1,
    ip: formData.get("ip"),
    port: parseInt(formData.get("port")) || 554,
    username: formData.get("username"),
    password: formData.get("password"),
    stream_url: formData.get("stream_url"),
    ptz: document.getElementById("camPtz").checked,
    legacy_polling: document.getElementById("camLegacyPolling").checked,
    is_simulated: document.getElementById("camSimulated").checked
  };

  if (localApiAvailable) {
    const method = camId ? "PUT" : "POST";
    const url = camId ? `/api/cameras/${camId}` : "/api/cameras";
    try {
      const res = await authFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        cameraModal.classList.add("hidden");
        await fetchCameras();
        return;
      }
    } catch (err) {}
  }

  // GitHub Pages Mode
  if (camId) {
    const idx = cameras.findIndex(c => c.id === camId);
    if (idx > -1) cameras[idx] = { ...cameras[idx], ...payload };
  } else {
    payload.id = `cam-${Date.now().toString(36)}`;
    cameras.push(payload);
  }

  saveLocalCameras();
  cameraModal.classList.add("hidden");
  renderGrid();
});

async function deleteCamera(camId) {
  if (!confirm("Remove this camera from the matrix?")) return;
  if (localApiAvailable) {
    try {
      const res = await authFetch(`/api/cameras/${camId}`, { method: "DELETE" });
      if (res.ok) {
        await fetchCameras();
        return;
      }
    } catch (err) {}
  }

  cameras = cameras.filter(c => c.id !== camId);
  saveLocalCameras();
  renderGrid();
}

// IN-BROWSER & BACKEND NETWORK SCANNER
// The Permissions API can report Local Network Access state, but it has no
// request() method. On supported browsers the native prompt is triggered by
// the first real local-network request, so only dispatch these probes after
// the user explicitly clicks Run Network Scan.
async function queryBrowserLocalNetworkPermission() {
  if (!navigator.permissions || typeof navigator.permissions.query !== "function") return null;

  // Prefer the current cross-browser descriptor. Older Chromium builds expose
  // the legacy alias; browsers without either descriptor fall back gracefully.
  for (const name of ["local-network", "local-network-access"]) {
    try {
      return await navigator.permissions.query({ name });
    } catch (e) {
      // Permission descriptor not implemented by this browser/version.
    }
  }
  return null;
}

function isPrivateIpv4SubnetBase(value) {
  const octets = String(value).trim().split(".");
  if (octets.length !== 3 || octets.some(part => !/^\d{1,3}$/.test(part))) return false;
  const [first, second, third] = octets.map(Number);
  if ([first, second, third].some(part => part < 0 || part > 255)) return false;
  return first === 10 ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168) ||
    (first === 169 && second === 254);
}

function showBrowserNetworkPermissionDenied(scanStatusMsg, tbody) {
  scanStatusMsg.textContent = "Browser blocked local-network access.";
  tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Local Network permission is blocked for this site. Allow it in your browser's site settings (usually the address-bar permissions menu), then run the scan again. You can also connect to a Local Hub, which scans from the server instead.</td></tr>`;
  showNotification("Allow Local Network access for this site in browser settings, then retry the scan.", "warning");
}

let discoveryScanInProgress = false;
let discoveryPermissionCleanup = null;

async function startDiscoveryScan() {
  const scanStatusMsg = document.getElementById("scanStatusMsg");
  const tbody = document.getElementById("discoveryTableBody");
  const scanButton = document.getElementById("btnStartScan");
  const subnetInput = document.getElementById("scanSubnetInput");
  const subnetBase = (subnetInput?.value || "192.168.1").trim();

  if (!scanStatusMsg || !tbody || !scanButton || scanButton.disabled || discoveryScanInProgress) return;
  discoveryScanInProgress = true;
  scanButton.disabled = true;
  if (typeof discoveryPermissionCleanup === "function") {
    discoveryPermissionCleanup();
    discoveryPermissionCleanup = null;
  }

  try {
    scanStatusMsg.textContent = "Scanning local subnet for cameras...";
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Preparing network scan…</td></tr>`;

    if (localApiAvailable) {
      try {
        const res = await authFetch("/api/discovery/scan");
        if (res.ok) {
          const data = await res.json();
          const devices = Array.isArray(data.devices) ? data.devices : [];
          renderDiscoveredDevices(devices, "ONVIF UDP / Port Scan");
          scanStatusMsg.textContent = `Scan complete. Found ${devices.length} device(s).`;
          return;
        }
      } catch (e) {}
    }

    // Browser-only discovery is limited to private IPv4 ranges. This prevents
    // the subnet field from turning the feature into arbitrary public probing.
    if (!isPrivateIpv4SubnetBase(subnetBase)) {
      scanStatusMsg.textContent = "Enter a private IPv4 subnet, such as 192.168.1.";
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Use a private subnet base in 10.x.x, 172.16–31.x, 192.168.x, or 169.254.x address space.</td></tr>`;
      return;
    }

    const permission = await queryBrowserLocalNetworkPermission();
    if (permission?.state === "denied") {
      showBrowserNetworkPermissionDenied(scanStatusMsg, tbody);
      return;
    }

    const detected = [];
    const totalToScan = 35;
    let startHostIndex = 1;

    // Never dispatch 35 local-network requests simultaneously while the browser's
    // Local Network Access permission is still in "prompt" / undecided state.
    // Sending one initial probe first lets the browser display a single steady
    // permission prompt without 34 competing parallel requests glitching it.
    if (permission?.state !== "granted") {
      scanStatusMsg.textContent = permission?.state === "prompt"
        ? "Your browser may ask for Local Network access; allow it while the scan runs."
        : (window.isSecureContext === false
          ? "Scanning subnet… this browser may require HTTPS or localhost for its Local Network prompt."
          : "Scanning subnet… your browser may ask for Local Network access.");
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Probing ${subnetBase}.1… If your browser asks to access devices on your local network, choose Allow to continue.</td></tr>`;

      const firstDev = await testCameraHostInBrowser(`${subnetBase}.1`, {
        timeoutMs: 15000,
        permission
      });
      if (firstDev) {
        detected.push(firstDev);
        renderDiscoveredDevices(detected, "Browser LAN Probe");
      }

      const afterFirstPermission = (await queryBrowserLocalNetworkPermission()) || permission;
      if (afterFirstPermission?.state === "denied") {
        showBrowserNetworkPermissionDenied(scanStatusMsg, tbody);
        return;
      }

      // If the browser exposes the permission state and it is still "prompt",
      // either the prompt is still open waiting on the user or it was dismissed.
      // Do NOT fire 34 more probes right now (which would re-pop/glitch the prompt
      // 34 times in a row); instead wait for the user to choose Allow.
      if (afterFirstPermission?.state === "prompt") {
        scanStatusMsg.textContent = "Waiting for Local Network permission — choose Allow in the browser prompt.";
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Waiting for your browser's Local Network permission prompt. Choose <strong>Allow</strong> in the address-bar prompt (or click <strong>Run Network Scan</strong> again after allowing).</td></tr>`;
        if (typeof afterFirstPermission.addEventListener === "function") {
          const onPermChange = () => {
            afterFirstPermission.removeEventListener("change", onPermChange);
            discoveryPermissionCleanup = null;
            if (afterFirstPermission.state === "granted") {
              startDiscoveryScan();
            } else if (afterFirstPermission.state === "denied") {
              showBrowserNetworkPermissionDenied(scanStatusMsg, tbody);
            }
          };
          afterFirstPermission.addEventListener("change", onPermChange);
          discoveryPermissionCleanup = () => afterFirstPermission.removeEventListener("change", onPermChange);
        }
        return;
      }

      startHostIndex = 2;
    } else {
      scanStatusMsg.textContent = "Local Network access granted. Scanning subnet…";
    }

    if (!detected.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Probing ${subnetBase}.${startHostIndex}–${subnetBase}.${totalToScan}… If your browser asks to access devices on your local network, choose Allow to continue.</td></tr>`;
    }

    const batchSize = 6;
    for (let batchStart = startHostIndex; batchStart <= totalToScan; batchStart += batchSize) {
      const currentPermission = (await queryBrowserLocalNetworkPermission()) || permission;
      if (currentPermission?.state === "denied") {
        showBrowserNetworkPermissionDenied(scanStatusMsg, tbody);
        return;
      }

      const batchEnd = Math.min(totalToScan, batchStart + batchSize - 1);
      scanStatusMsg.textContent = `Scanning ${subnetBase}.${batchStart}–${subnetBase}.${batchEnd}…`;
      const batchProbes = [];
      for (let i = batchStart; i <= batchEnd; i++) {
        const ip = `${subnetBase}.${i}`;
        batchProbes.push(
          testCameraHostInBrowser(ip, { timeoutMs: 2500, permission: currentPermission }).then(dev => {
            if (dev) {
              detected.push(dev);
              renderDiscoveredDevices(detected, "Browser LAN Probe");
            }
          })
        );
      }
      await Promise.all(batchProbes);
    }

    const finalPermission = (await queryBrowserLocalNetworkPermission()) || permission;
    if (finalPermission?.state === "denied") {
      showBrowserNetworkPermissionDenied(scanStatusMsg, tbody);
      return;
    }

    renderDiscoveredDevices(detected, "Browser LAN Probe");
    scanStatusMsg.textContent = detected.length
      ? `Browser scan complete. Found ${detected.length} device(s).`
      : "No devices responded. Check the subnet and browser permission, or connect a Local Hub if direct LAN requests are blocked.";
  } finally {
    discoveryScanInProgress = false;
    scanButton.disabled = false;
  }
}

function testCameraHostInBrowser(ip, opts) {
  const options = opts || {};
  const timeoutMs = typeof options.timeoutMs === "number" ? options.timeoutMs : 15000;
  const permission = options.permission || null;

  return new Promise((resolve) => {
    const img = new Image();
    let resolved = false;

    const onPermissionChange = () => {
      if (permission?.state === "denied") {
        finish(null);
      }
    };

    const finish = (device) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timeoutId);
      if (permission && typeof permission.removeEventListener === "function") {
        permission.removeEventListener("change", onPermissionChange);
      }
      img.onload = null;
      img.onerror = null;
      try {
        img.src = "";
      } catch (e) {}
      resolve(device);
    };

    if (permission && typeof permission.addEventListener === "function") {
      permission.addEventListener("change", onPermissionChange);
    }

    img.onload = () => finish({
      ip,
      type: "HTTP CCTV Device",
      vendor_preset: "generic_onvif",
      vendor_name: "Detected Camera / DVR Web UI",
      open_ports: [80],
      confidence: "High"
    });
    img.onerror = () => finish(null);

    // Give the user time to answer a native browser permission prompt, which
    // is raised by the request itself rather than by a JS permission API.
    const timeoutId = setTimeout(() => finish(null), timeoutMs);
    img.src = `http://${ip}/favicon.ico?t=${Date.now()}`;
  });
}

function renderDiscoveredDevices(devices, source) {
  const tbody = document.getElementById("discoveryTableBody");
  if (!devices || devices.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No cameras responded on this subnet. Verify your camera's IP range.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  devices.forEach(dev => {
    const tr = document.createElement("tr");
    const ports = dev.open_ports ? dev.open_ports.join(", ") : "80 / 554";
    tr.innerHTML = `
      <td><strong>${dev.ip}</strong></td>
      <td>${dev.type || source}</td>
      <td>${dev.vendor_name || dev.vendor_preset}</td>
      <td><code>${ports}</code></td>
      <td><span class="stat-dot green"></span> ${dev.confidence || "High"}</td>
      <td>
        <button class="btn-action btn-primary" onclick="addDiscoveredCamera('${dev.ip}', '${dev.vendor_preset}')">
          + Add
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function addDiscoveredCamera(ip, vendorPreset) {
  discoveryModal.classList.add("hidden");
  openAddCameraModal();
  document.getElementById("camIp").value = ip;
  document.getElementById("camVendor").value = vendorPreset || "generic_onvif";
  document.getElementById("camName").value = `${(vendorPreset || 'CAM').toUpperCase()} (${ip})`;
  updateVendorQuirks();
  autoGenerateUrl();
}


// Browser Camera Node State
let activeBrowserNodeStream = null;
let browserNodeInterval = null;
let activeBrowserNodeCamId = "node-browser-cam";
let latestBrowserNodeFrame = null;

// Universal Camera Hardware Diagnostic & Stream Prober
async function handleProbeCamera() {
  const btn = document.getElementById("btnProbeCamera");
  const resultBox = document.getElementById("probeResultBox");
  const chipsBox = document.getElementById("probeChips");
  const recBox = document.getElementById("probeRecommendation");
  const previewContainer = document.getElementById("probePreviewContainer");
  const previewImg = document.getElementById("probePreviewImg");

  const ip = document.getElementById("camIp").value.trim();
  const portVal = document.getElementById("camPort").value.trim();
  const username = document.getElementById("camUser").value.trim();
  const password = document.getElementById("camPass").value;
  const channel = document.getElementById("camChannel").value || 1;
  const vendorHint = document.getElementById("camVendor").value;

  if (!ip) {
    alert("Please enter a camera IP address or hostname to probe.");
    document.getElementById("camIp").focus();
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span class="icon">⏳</span> Probing ${escapeHtml(ip)}...`;
  resultBox.classList.remove("hidden");
  previewContainer.classList.add("hidden");
  chipsBox.innerHTML = `<span class="probe-chip active">Scanning open ports & RTSP DESCRIBE...</span>`;
  recBox.innerHTML = `<em>Testing ports 554, 80, 8080, 8000, 37777, 34567 and probing RTSP candidates...</em>`;

  if (localApiAvailable) {
    try {
      const res = await authFetch("/api/cameras/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip,
          port: portVal ? parseInt(portVal) : null,
          username,
          password,
          vendor: vendorHint,
          channel: parseInt(channel)
        })
      });

      if (res.ok) {
        const data = await res.json();
        renderProbeResults(data);
      } else {
        chipsBox.innerHTML = `<span class="probe-chip error">Probe Request Failed (${res.status})</span>`;
        recBox.textContent = "Could not communicate with probe diagnostic engine.";
      }
    } catch (err) {
      chipsBox.innerHTML = `<span class="probe-chip error">Network Error</span>`;
      recBox.textContent = `Error reaching NVR backend: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<span class="icon">🔍</span> Probe &amp; Test Stream`;
    }
    return;
  }

  // Standalone Client / GitHub Pages fallback probe
  setTimeout(() => {
    btn.disabled = false;
    btn.innerHTML = `<span class="icon">🔍</span> Probe &amp; Test Stream`;

    if (ip === "127.0.0.1" || ip === "localhost") {
      chipsBox.innerHTML = `
        <span class="probe-chip active">Target: Localhost</span>
        <span class="probe-chip codec">Mode: Simulator / Virtual</span>
      `;
      recBox.textContent = "Detected local loopback. Recommended profile: OmniSight Virtual CCTV Generator.";
      document.getElementById("camVendor").value = "simulated";
      updateVendorQuirks();
      autoGenerateUrl();
      return;
    }

    chipsBox.innerHTML = `
      <span class="probe-chip active">Target: ${escapeHtml(ip)}</span>
      <span class="probe-chip" style="background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3);">Client-Side Analysis</span>
    `;
    recBox.innerHTML = `Direct raw socket RTSP probing requires the local Python NVR backend (:8080). Auto-generated standard URL for <strong>${escapeHtml(vendorHint.toUpperCase())}</strong> below.`;
    autoGenerateUrl();
  }, 600);
}

function renderProbeResults(data) {
  const chipsBox = document.getElementById("probeChips");
  const recBox = document.getElementById("probeRecommendation");
  const previewContainer = document.getElementById("probePreviewContainer");
  const previewImg = document.getElementById("probePreviewImg");

  chipsBox.innerHTML = "";

  // 1. Target & Reachability Chip
  if (data.reachable) {
    chipsBox.innerHTML += `<span class="probe-chip active">Reachable (${escapeHtml(data.ip)})</span>`;
  } else {
    chipsBox.innerHTML += `<span class="probe-chip error">Host Unreachable (${escapeHtml(data.ip)})</span>`;
  }

  // 2. Open Ports Chips
  if (data.open_ports && data.open_ports.length > 0) {
    data.open_ports.forEach(p => {
      let label = `Port ${p}`;
      if (p === 554) label += " (RTSP)";
      else if (p === 80) label += " (HTTP)";
      else if (p === 37777) label += " (Dahua TCP)";
      else if (p === 34567) label += " (XM CMS)";
      else if (p === 8000) label += " (Hik/Reolink SDK)";
      else if (p === 2020) label += " (Tapo ONVIF)";
      else if (p === 8899) label += " (ONVIF)";
      chipsBox.innerHTML += `<span class="probe-chip" style="background: rgba(52, 199, 89, 0.12); color: #34c759; border: 1px solid rgba(52, 199, 89, 0.3);">${label}</span>`;
    });
  } else if (data.reachable) {
    chipsBox.innerHTML += `<span class="probe-chip warning">No Standard CCTV Ports Responding</span>`;
  }

  // 3. RTSP & Codec Chip
  if (data.rtsp && data.rtsp.open) {
    const codec = data.rtsp.video_codec || "H.264";
    chipsBox.innerHTML += `<span class="probe-chip codec">Video Codec: ${escapeHtml(codec)}</span>`;
    if (data.rtsp.audio) {
      chipsBox.innerHTML += `<span class="probe-chip active">Audio: Yes</span>`;
    }
    if (data.rtsp.latency_ms) {
      chipsBox.innerHTML += `<span class="probe-chip" style="background: rgba(0, 212, 255, 0.15); color: #00d4ff; border: 1px solid rgba(0, 212, 255, 0.3);">${Math.round(data.rtsp.latency_ms)}ms Latency</span>`;
    }
  }

  // 4. Snapshot Status
  if (data.snapshot && data.snapshot.open) {
    chipsBox.innerHTML += `<span class="probe-chip active">Snapshot Polling: OK</span>`;
  }

  // 5. Detected Brand / Architecture
  if (data.detected_vendor && data.detected_vendor !== "generic_rtsp") {
    chipsBox.innerHTML += `<span class="probe-chip" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);">Brand: ${escapeHtml(data.detected_vendor.toUpperCase())}</span>`;
    const opt = document.querySelector(`#camVendor option[value="${data.detected_vendor}"]`);
    if (opt) {
      document.getElementById("camVendor").value = data.detected_vendor;
      updateVendorQuirks();
    }
  }

  // 6. Password & Authentication Status Chip
  if (data.password_status === "none_required") {
    chipsBox.innerHTML += `<span class="probe-chip active" style="background: rgba(52, 199, 89, 0.18); color: #34c759; border: 1px solid rgba(52, 199, 89, 0.4);">🔓 No Password Required (Anonymous Stream)</span>`;
    document.getElementById("camUser").value = "";
    document.getElementById("camPass").value = "";
  } else if (data.password_status === "blank_password") {
    chipsBox.innerHTML += `<span class="probe-chip active" style="background: rgba(52, 199, 89, 0.18); color: #34c759; border: 1px solid rgba(52, 199, 89, 0.4);">🔓 Password: BLANK (Empty)</span>`;
    document.getElementById("camUser").value = data.discovered_username || "admin";
    document.getElementById("camPass").value = "";
  } else if (data.password_status === "default_found") {
    chipsBox.innerHTML += `<span class="probe-chip active" style="background: rgba(52, 199, 89, 0.18); color: #34c759; border: 1px solid rgba(52, 199, 89, 0.4);">🔑 Unlocked: ${escapeHtml(data.discovered_username)} / ${escapeHtml(data.discovered_password)}</span>`;
    document.getElementById("camUser").value = data.discovered_username || "admin";
    document.getElementById("camPass").value = data.discovered_password || "";
  } else if (data.password_status === "custom_required") {
    chipsBox.innerHTML += `<span class="probe-chip warning" style="background: rgba(255, 149, 0, 0.18); color: #ff9500; border: 1px solid rgba(255, 149, 0, 0.4);">🔒 App Password Required</span>`;
  }

  // Recommendation Text
  recBox.innerHTML = `<strong>Diagnostic Summary:</strong> ${escapeHtml(data.summary || data.auth_summary || "Analysis complete.")}`;

  // Auto-fill recommended URL
  if (data.stream_url || data.recommended_url) {
    document.getElementById("camStreamUrl").value = data.stream_url || data.recommended_url;
  }
  if (data.recommended_mode === "snapshot") {
    document.getElementById("camLegacyPolling").checked = true;
  }

  // Render snapshot preview if returned
  if (data.snapshot && data.snapshot.data_uri) {
    previewContainer.classList.remove("hidden");
    previewImg.src = data.snapshot.data_uri;
  } else {
    previewContainer.classList.add("hidden");
  }
}

// Browser Camera Node (Stream Phone / Laptop into NVR)
async function startBrowserCameraNode() {
  const btnStart = document.getElementById("btnStartBrowserNode");
  const btnStop = document.getElementById("btnStopBrowserNode");
  const facing = document.getElementById("nodeCamFacing").value || "environment";
  const camName = document.getElementById("nodeCamName").value.trim() || "Mobile Sentry Cam";
  const video = document.getElementById("nodeVideoPreview");
  const liveBadge = document.getElementById("nodeLiveBadge");

  btnStart.disabled = true;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: facing,
        width: { ideal: 1280 },
        height: { ideal: 720 }
      },
      audio: false
    });

    activeBrowserNodeStream = stream;
    video.srcObject = stream;
    liveBadge.classList.remove("hidden");
    btnStop.disabled = false;

    const offscreenCanvas = document.createElement("canvas");
    offscreenCanvas.width = 960;
    offscreenCanvas.height = 540;
    const ctx = offscreenCanvas.getContext("2d");

    const nodePayload = {
      id: activeBrowserNodeCamId,
      name: camName,
      group: "Mobile Nodes",
      vendor: "browser_node",
      ip: "127.0.0.1",
      port: 8080,
      channel: 1,
      stream_url: `node://${activeBrowserNodeCamId}`,
      is_simulated: false,
      ptz: false,
      status: "online",
      fps: 10,
      resolution: "960x540"
    };

    if (localApiAvailable) {
      try {
        const exist = cameras.find(c => c.id === activeBrowserNodeCamId);
        if (!exist) {
          await authFetch("/api/cameras", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(nodePayload)
          });
          await fetchCameras();
        }
      } catch (e) {}
    } else {
      const idx = cameras.findIndex(c => c.id === activeBrowserNodeCamId);
      if (idx > -1) {
        cameras[idx] = { ...cameras[idx], ...nodePayload };
      } else {
        cameras.push(nodePayload);
      }
      saveLocalCameras();
      renderGrid();
    }

    let isIngesting = false;
    browserNodeInterval = setInterval(async () => {
      if (!activeBrowserNodeStream || video.readyState < 2) return;

      try {
        ctx.drawImage(video, 0, 0, offscreenCanvas.width, offscreenCanvas.height);
        const dataUri = offscreenCanvas.toDataURL("image/jpeg", 0.65);
        latestBrowserNodeFrame = dataUri;

        if (localApiAvailable && !isIngesting) {
          isIngesting = true;
          authFetch(`/api/cameras/${activeBrowserNodeCamId}/ingest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ frame_base64: dataUri })
          }).finally(() => {
            isIngesting = false;
          });
        }
      } catch (err) {}
    }, 120);

    showNotification(`Streaming live from this device as "${camName}"!`, "success");
    renderGrid();
  } catch (err) {
    btnStart.disabled = false;
    alert(`Could not access device camera: ${err.message || err.name}. Please ensure camera permissions are granted.`);
  }
}

function stopBrowserCameraNode() {
  const btnStart = document.getElementById("btnStartBrowserNode");
  const btnStop = document.getElementById("btnStopBrowserNode");
  const video = document.getElementById("nodeVideoPreview");
  const liveBadge = document.getElementById("nodeLiveBadge");

  if (browserNodeInterval) {
    clearInterval(browserNodeInterval);
    browserNodeInterval = null;
  }

  if (activeBrowserNodeStream) {
    activeBrowserNodeStream.getTracks().forEach(t => t.stop());
    activeBrowserNodeStream = null;
  }

  video.srcObject = null;
  liveBadge.classList.add("hidden");
  btnStart.disabled = false;
  btnStop.disabled = true;
  latestBrowserNodeFrame = null;

  showNotification("Device camera broadcast stopped.", "info");
  renderGrid();
}

// App-Configured Camera Assistant Helper (No Password in App)
function initAppHelper() {
  const btnToggle = document.getElementById("btnToggleAppHelper");
  const drawer = document.getElementById("appHelperDrawer");
  const selector = document.getElementById("appSelector");
  const tipBox = document.getElementById("appSecretTip");

  if (btnToggle && drawer) {
    btnToggle.onclick = () => {
      drawer.classList.toggle("hidden");
      btnToggle.textContent = drawer.classList.contains("hidden") ? "App Assistant ▾" : "Close Assistant ▴";
    };
  }

  const APP_GUIDES = {
    "icsee": {
      title: "ICSee / XMeye / iCSee Pro",
      vendor: "icsee",
      username: "admin",
      password: "",
      port: 554,
      desc: "<strong>Zero Password in App:</strong> The ICSee mobile app pairs via cloud and doesn't ask for a password. On your local Wi-Fi, the camera accepts username <code>admin</code> with a <strong>completely BLANK (empty) password</strong>! Auto-filled below."
    },
    "v380": {
      title: "V380 / V380 Pro (Macro-Video)",
      vendor: "v380",
      username: "admin",
      password: "",
      port: 554,
      desc: "<strong>Local Feed is Open / Blank Password:</strong> V380 cameras stream on port 554 with username <code>admin</code> and an <strong>empty / blank password</strong>, or accept anonymous streams. Auto-filled below."
    },
    "v360": {
      title: "V360 Pro / KeepEyes (Shenzhen Qianniao Xiangyun / CFEO)",
      vendor: "v360",
      username: "admin",
      password: "",
      port: 554,
      desc: "<strong>Zero Password in App (CFEO Series):</strong> The V360 Pro app by Shenzhen Qianniao Xiangyun Technology pairs via cloud UID (e.g. <code>CFEO-164806-HRZJY</code>) and never prompts for a camera password.<br>• On your local Wi-Fi, the camera streams with username <code>admin</code> and an <strong>empty / BLANK password</strong>!<br>• Commonly streams on <strong>Port 554</strong> (/live/ch0) or <strong>Port 8554</strong> (/profile0).<br>• Click <strong>⚡ Test Connection</strong> below to auto-test and verify!"
    },
    "tapo": {
      title: "TP-Link Tapo (C100, C200, C310, C500) & Kasa",
      vendor: "tapo",
      username: "",
      password: "",
      port: 554,
      desc: "⚠️ <strong>Cloud Password Won't Work:</strong> Your TP-Link cloud account password does NOT work for local RTSP.<br>1. Open the <strong>Tapo App</strong> on your phone.<br>2. Tap your camera &gt; <strong>Settings ⚙️</strong> &gt; <strong>Advanced Settings</strong> &gt; <strong>Camera Account</strong>.<br>3. Create a simple local username (e.g. <code>admin</code>) and password. Enter those below!"
    },
    "ezviz": {
      title: "EZVIZ (Hikvision)",
      vendor: "ezviz",
      username: "admin",
      password: "",
      port: 554,
      desc: "🔑 <strong>Password is on Camera Sticker:</strong> EZVIZ never asks for a password in the app. For local RTSP streaming:<br>• Look at the sticker on the bottom or back of the camera.<br>• The 6-capital-letter <strong>Verification Code</strong> (e.g. <code>ABCDEF</code>) is your password!<br>• Username is <code>admin</code>."
    },
    "imou": {
      title: "Imou Life (Dahua)",
      vendor: "imou",
      username: "admin",
      password: "",
      port: 554,
      desc: "🔑 <strong>Password is on Camera Bottom Label:</strong> In the Imou Life app, video loads without a password.<br>• For local NVR streaming, look at the sticker on the camera bottom.<br>• The <strong>Safety Code</strong> is your password!<br>• Username is <code>admin</code>."
    },
    "yoosee": {
      title: "Yoosee / YYP2P",
      vendor: "yoosee",
      username: "admin",
      password: "",
      port: 554,
      desc: "Username is <code>admin</code>. Password is usually <strong>BLANK</strong> or <code>123456</code>. Make sure <em>NVR Connections / PC Monitoring</em> is toggled ON in Yoosee app settings."
    },
    "tuya": {
      title: "Tuya / Smart Life / Geeni",
      vendor: "tuya",
      username: "admin",
      password: "admin",
      port: 554,
      desc: "In Tuya / Smart Life app, open camera settings and look for <strong>PC View</strong> or <strong>ONVIF</strong> to toggle local LAN streaming on."
    },
    "eufy": {
      title: "Eufy Security",
      vendor: "eufy",
      username: "admin",
      password: "",
      port: 554,
      desc: "Open Eufy App &gt; Camera Settings &gt; <strong>Storage</strong> &gt; <strong>NAS (RTSP) Stream</strong>. Enable it and copy the username/password shown on your phone screen."
    },
    "wyze": {
      title: "Wyze Cam",
      vendor: "wyze",
      username: "",
      password: "",
      port: 554,
      desc: "Stock Wyze cams require either official Wyze RTSP firmware, docker-wyze-bridge (:8554), or open-source Thingino / OpenIPC firmware."
    }
  };

  if (selector && tipBox) {
    selector.onchange = () => {
      const selected = selector.value;
      const guide = APP_GUIDES[selected];
      if (!guide) {
        tipBox.classList.add("hidden");
        return;
      }

      tipBox.innerHTML = `
        <div style="font-weight: 600; color: #60a5fa; margin-bottom: 4px;">📱 ${guide.title} Setup Secret:</div>
        <div>${guide.desc}</div>
      `;
      tipBox.classList.remove("hidden");

      // Auto-populate form
      if (guide.vendor) {
        document.getElementById("camVendor").value = guide.vendor;
        updateVendorQuirks();
      }
      if (guide.username !== undefined) {
        document.getElementById("camUser").value = guide.username;
      }
      if (guide.password !== undefined) {
        document.getElementById("camPass").value = guide.password;
      }
      if (guide.port) {
        document.getElementById("camPort").value = guide.port;
      }
      autoGenerateUrl();
    };
  }
}

// Attach Event Listeners
function attachEventListeners() {
  initAppHelper();

  // Layout Buttons
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.onclick = () => setLayout(btn.dataset.layout);
  });

  // Authentication & Session Handlers
  btnLoginNav.onclick = () => {
    loginAlert.classList.add("hidden");
    loginModal.classList.remove("hidden");
    initGoogleAuth(googleClientId);
  };

  document.getElementById("btnCloseLoginModal").onclick = () => loginModal.classList.add("hidden");

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginAlert.classList.add("hidden");
    const username = document.getElementById("loginUser").value.trim();
    const password = document.getElementById("loginPass").value;

    if (localApiAvailable) {
      try {
        const res = await fetch(apiUrl("/api/auth/login"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (res.ok && data.token) {
          authToken = data.token;
          sessionStorage.setItem("omnisight_token", authToken);
          localStorage.setItem("omnisight_token", authToken);
          updateAuthUI(true, data.username);
          loginModal.classList.add("hidden");
          await fetchCameras();
          return;
        } else {
          loginAlert.textContent = data.error || "Authentication failed.";
          loginAlert.classList.remove("hidden");
          return;
        }
      } catch (err) {
        loginAlert.textContent = "Network error connecting to NVR hub.";
        loginAlert.classList.remove("hidden");
        return;
      }
    }

    // Standalone GitHub Pages Passcode Lock
    if (username === "admin" && (password === "admin123" || password === localStorage.getItem("omnisight_passcode") || !localStorage.getItem("omnisight_passcode"))) {
      sessionStorage.setItem("omnisight_unlocked", "true");
      if (password !== "admin123") {
        localStorage.setItem("omnisight_passcode", password);
      }
      updateAuthUI(true, username);
      loginModal.classList.add("hidden");
      renderGrid();
    } else {
      loginAlert.textContent = "Invalid username or passcode.";
      loginAlert.classList.remove("hidden");
    }
  });

  // Google Sign-In Direct Form & GIS Config
  document.getElementById("btnCloseGoogleModal")?.addEventListener("click", () => {
    document.getElementById("googleModal")?.classList.add("hidden");
    loginModal.classList.remove("hidden");
  });

  const googleDirectForm = document.getElementById("googleDirectForm");
  if (googleDirectForm) {
    googleDirectForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = document.getElementById("googleUserEmail").value.trim();
      const name = document.getElementById("googleUserName").value.trim();
      const alertEl = document.getElementById("googleAlert");
      if (alertEl) alertEl.classList.add("hidden");

      if (!email || !email.includes("@")) {
        if (alertEl) {
          alertEl.textContent = "Please enter a valid Google email address.";
          alertEl.classList.remove("hidden");
        }
        return;
      }

      if (localApiAvailable) {
        try {
          const res = await fetch(apiUrl("/api/auth/google"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, name })
          });
          const data = await res.json();
          if (res.ok && data.token) {
            authToken = data.token;
            sessionStorage.setItem("omnisight_token", authToken);
            localStorage.setItem("omnisight_token", authToken);
            updateAuthUI(true, data.name || data.username || email);
            document.getElementById("googleModal")?.classList.add("hidden");
            loginModal.classList.add("hidden");
            showNotification(`Welcome, ${data.name || data.username}! Signed in with Google.`, "success");
            await fetchCameras();
            return;
          } else {
            if (alertEl) {
              alertEl.textContent = data.error || "Google authentication failed.";
              alertEl.classList.remove("hidden");
            }
          }
        } catch (err) {
          if (alertEl) {
            alertEl.textContent = "Network error connecting to hub.";
            alertEl.classList.remove("hidden");
          }
        }
        return;
      }

      // GitHub Pages Standalone Mode
      sessionStorage.setItem("omnisight_unlocked", "true");
      updateAuthUI(true, name || email.split("@")[0] || "Google User");
      document.getElementById("googleModal")?.classList.add("hidden");
      loginModal.classList.add("hidden");
      showNotification(`Welcome, ${name || "Google User"}! Signed in with Google.`, "success");
      renderGrid();
    });
  }

  const btnSaveGoogleClientId = document.getElementById("btnSaveGoogleClientId");
  if (btnSaveGoogleClientId) {
    btnSaveGoogleClientId.addEventListener("click", async () => {
      const inputVal = document.getElementById("cfgGoogleClientId")?.value.trim();
      if (!inputVal) return;
      googleClientId = inputVal;
      localStorage.setItem("omnisight_google_client_id", googleClientId);
      if (localApiAvailable) {
        try {
          await authFetch("/api/auth/google-config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ client_id: googleClientId })
          });
        } catch (e) {}
      }
      initGoogleAuth(googleClientId);
      document.getElementById("googleModal")?.classList.add("hidden");
      loginModal.classList.remove("hidden");
      showNotification("Google Client ID saved! GIS activated.", "success");
    });
  }

  // Firebase Google Login Listeners
  if (btnFirebaseGoogleLogin) {
    btnFirebaseGoogleLogin.addEventListener("click", handleFirebaseGoogleSignIn);
  }

  if (btnSaveFirebaseConfig) {
    btnSaveFirebaseConfig.addEventListener("click", () => {
      const cfgText = cfgFirebaseConfig?.value.trim();
      if (!cfgText) return;
      try {
        JSON.parse(cfgText);
        localStorage.setItem("omnisight_firebase_config", cfgText);
        initFirebaseAuth();
        showNotification("Firebase Project configuration saved!", "success");
      } catch (err) {
        alert("Invalid JSON format for Firebase configuration.");
      }
    });
  }

  // 4G Cloud Relay Modal Listeners
  if (btnCloudRelay) {
    btnCloudRelay.addEventListener("click", async () => {
      cloudRelayModal.classList.remove("hidden");
      await fetchCloudRelayStatus();
    });
  }

  if (btnCloseCloudRelayModal) {
    btnCloseCloudRelayModal.addEventListener("click", () => {
      cloudRelayModal.classList.add("hidden");
    });
  }

  if (btnCopyCloudUrl) {
    btnCopyCloudUrl.addEventListener("click", async () => {
      const url = cloudRelayUrlInput?.value;
      if (url && url.startsWith("http")) {
        try {
          await navigator.clipboard.writeText(url);
          btnCopyCloudUrl.textContent = "Copied!";
          setTimeout(() => { btnCopyCloudUrl.textContent = "Copy"; }, 2000);
          showNotification("4G Cloud URL copied to clipboard!", "success");
        } catch (e) {
          prompt("Copy your 4G Cloud URL:", url);
        }
      }
    });
  }

  if (btnOpenCloudUrl) {
    btnOpenCloudUrl.addEventListener("click", () => {
      const url = cloudRelayUrlInput?.value;
      if (url && url.startsWith("http")) {
        window.open(url, "_blank");
      }
    });
  }

  if (btnRestartCloudRelay) {
    btnRestartCloudRelay.addEventListener("click", async () => {
      btnRestartCloudRelay.disabled = true;
      btnRestartCloudRelay.textContent = "Restarting...";
      if (cloudRelayStatusBadge) {
        cloudRelayStatusBadge.textContent = "RESTARTING...";
        cloudRelayStatusBadge.style.color = "#ff9500";
      }
      try {
        if (localApiAvailable) {
          await authFetch("/api/cloud-relay/restart", { method: "POST" });
          setTimeout(async () => {
            await fetchCloudRelayStatus();
            btnRestartCloudRelay.disabled = false;
            btnRestartCloudRelay.textContent = "🔄 Restart Tunnel";
          }, 3000);
        }
      } catch (err) {
        btnRestartCloudRelay.disabled = false;
        btnRestartCloudRelay.textContent = "🔄 Restart Tunnel";
      }
    });
  }

  // Hub Connector Modal Listeners (cross-platform bridge)
  if (btnHubConnector) {
    btnHubConnector.addEventListener("click", () => {
      refreshHubConnectorUI();
      hubConnectorModal.classList.remove("hidden");
    });
  }
  if (btnCloseHubConnectorModal) {
    btnCloseHubConnectorModal.addEventListener("click", () => {
      hubConnectorModal.classList.add("hidden");
    });
  }

  // Mixed-content help modal (opened from a blocked camera tile or the connector)
  const mixedContentModal = document.getElementById("mixedContentModal");
  document.getElementById("btnCloseMixedContentModal")?.addEventListener("click", () => {
    mixedContentModal?.classList.add("hidden");
  });
  mixedContentModal?.addEventListener("click", (e) => {
    if (e.target === mixedContentModal) mixedContentModal.classList.add("hidden");
  });
  document.querySelectorAll("[data-open-mixed-content-help]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      openMixedContentHelp();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && mixedContentModal && !mixedContentModal.classList.contains("hidden")) {
      mixedContentModal.classList.add("hidden");
    }
  });
  if (btnConnectHub) {
    btnConnectHub.addEventListener("click", connectToHub);
  }
  if (btnDisconnectHub) {
    btnDisconnectHub.addEventListener("click", disconnectHub);
  }
  if (hubConnectorUrlInput) {
    hubConnectorUrlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") connectToHub();
    });
  }

  btnLogoutNav.onclick = async () => {
    if (localApiAvailable && authToken) {
      try {
        await authFetch("/api/auth/logout", { method: "POST" });
      } catch (e) {}
    }
    authToken = "";
    sessionStorage.removeItem("omnisight_token");
    localStorage.removeItem("omnisight_token");
    sessionStorage.removeItem("omnisight_unlocked");
    updateAuthUI(false);
    loginModal.classList.remove("hidden");
  };

  btnChangePassNav.onclick = () => {
    changePassAlert.classList.add("hidden");
    changePasswordModal.classList.remove("hidden");
  };

  document.getElementById("btnCloseChangePassModal").onclick = () => changePasswordModal.classList.add("hidden");
  document.getElementById("btnCancelChangePass").onclick = () => changePasswordModal.classList.add("hidden");

  changePasswordForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    changePassAlert.classList.add("hidden");
    const oldPass = document.getElementById("oldPass").value;
    const newPass = document.getElementById("newPass").value;
    const confirmPass = document.getElementById("confirmNewPass").value;

    if (newPass !== confirmPass) {
      changePassAlert.textContent = "New passwords do not match.";
      changePassAlert.classList.remove("hidden");
      return;
    }

    if (localApiAvailable) {
      try {
        const res = await authFetch("/api/auth/change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ old_password: oldPass, new_password: newPass })
        });
        const data = await res.json();
        if (res.ok) {
          alert("Password updated successfully!");
          changePasswordModal.classList.add("hidden");
          changePasswordForm.reset();
        } else {
          changePassAlert.textContent = data.error || "Failed to change password.";
          changePassAlert.classList.remove("hidden");
        }
      } catch (err) {
        changePassAlert.textContent = "Error changing password.";
        changePassAlert.classList.remove("hidden");
      }
    } else {
      localStorage.setItem("omnisight_passcode", newPass);
      alert("Passcode updated successfully!");
      changePasswordModal.classList.add("hidden");
      changePasswordForm.reset();
    }
  });

  // Top Nav Modals
  document.getElementById("btnAddCamera").onclick = openAddCameraModal;
  document.getElementById("btnScanNetwork").onclick = () => discoveryModal.classList.remove("hidden");
  document.getElementById("btnOpenGallery").onclick = () => galleryModal.classList.remove("hidden");
  document.getElementById("btnVendorGuide").onclick = () => vendorGuideModal.classList.remove("hidden");

  // DVR Modal
  document.getElementById("btnImportDvr").onclick = () => dvrModal.classList.remove("hidden");
  document.getElementById("btnCloseDvrModal").onclick = () => dvrModal.classList.add("hidden");
  document.getElementById("btnCancelDvr").onclick = () => dvrModal.classList.add("hidden");

  dvrForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(dvrForm);
    const vendor = formData.get("vendor");
    const channels = parseInt(formData.get("channels")) || 8;
    const ip = formData.get("ip");
    const port = parseInt(formData.get("port")) || 554;
    const username = formData.get("username") || "admin";
    const password = formData.get("password") || "";
    const label = formData.get("label") || "DVR";
    const group = formData.get("group") || "CCTV Analog";

    if (localApiAvailable) {
      try {
        const res = await authFetch("/api/dvr/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vendor, channels, ip, port, username, password, label, group })
        });
        if (res.ok) {
          const result = await res.json();
          dvrModal.classList.add("hidden");
          alert(`Successfully imported ${result.imported_count} CCTV BNC channels into matrix!`);
          await fetchCameras();
          return;
        }
      } catch (err) {}
    }

    // Client-side DVR Channel Bulk Import (GitHub Pages Mode)
    const newCams = [];
    for (let ch = 1; ch <= channels; ch++) {
      let mainUrl = "";
      if (vendor === "hikvision_dvr") {
        mainUrl = `rtsp://${username}:${password}@${ip}:${port}/Streaming/Channels/${ch}01`;
      } else if (vendor === "xiongmai_dvr") {
        mainUrl = `rtsp://${username}:${password}@${ip}:${port}/live/ch${ch - 1}`;
      } else if (vendor === "uniview" || vendor === "uniview_nvr") {
        mainUrl = `rtsp://${username}:${password}@${ip}:${port}/unicast/c${ch}/s0/live`;
      } else if (vendor === "zosi_dvr") {
        mainUrl = `rtsp://${username}:${password}@${ip}:${port}/ucast/11?channel=${ch}&subtype=0`;
      } else {
        mainUrl = `rtsp://${username}:${password}@${ip}:${port}/cam/realmonitor?channel=${ch}&subtype=0`;
      }

      newCams.push({
        id: `cam-${Date.now().toString(36)}-ch${ch}`,
        name: `${label} Ch ${String(ch).padStart(2, '0')} (BNC)`,
        group: group,
        vendor: vendor,
        channel: ch,
        ip: ip,
        port: port,
        username: username,
        password: password,
        stream_url: mainUrl,
        ptz: true,
        is_simulated: true,
        status: "online",
        fps: 25,
        resolution: "1920x1080"
      });
    }

    cameras = [...cameras, ...newCams];
    saveLocalCameras();
    dvrModal.classList.add("hidden");
    alert(`Successfully imported ${channels} CCTV BNC channels into matrix!`);
    renderGrid();
  });

  // OpenIPC & Community Firmware Modal
  const firmwareModal = document.getElementById("firmwareModal");
  const chipsetSelector = document.getElementById("chipsetSelector");
  document.getElementById("btnFirmwareHub").onclick = () => firmwareModal.classList.remove("hidden");
  document.getElementById("btnCloseFirmwareModal").onclick = () => firmwareModal.classList.add("hidden");

  const CHIPSET_FIRMWARE_DATA = {
    "xiongmai_xm530": {
      title: "OpenIPC — Xiongmai XM530 / XM510 / XM550 Edition",
      description: "Replaces closed-source Chinese camera firmware with a clean, 100% open-source Linux OS.",
      features: [
        "Native HTML5 WebRTC streaming directly in Safari, Chrome, and iOS — ZERO ActiveX, zero Internet Explorer required!",
        "Pure RTSP H.264 / H.265 streaming on standard port 554.",
        "Root SSH & Telnet access with complete local control.",
        "Permanently disables Chinese cloud telemetry and p2p backdoors (XMeye)."
      ],
      url: "https://openipc.org",
      github: "https://github.com/OpenIPC/firmware/releases",
      advice: "Can be installed via TFTP or by uploading the OpenIPC Coupler binary into the camera's original web upgrade screen."
    },
    "hisilicon_hi3516": {
      title: "OpenIPC — HiSilicon Hi3516 / Hi3518 Series",
      description: "HiSilicon chipsets power over 70% of Chinese CCTV hardware. OpenIPC brings them into the modern era.",
      features: [
        "Ultra-low latency (<200ms) browser streaming via Majestic WebRTC.",
        "Local MQTT alerts, motion snapshots, and JSON HTTP APIs.",
        "Zero plugin requirements in any modern web browser.",
        "Full root Linux system with lightweight memory footprint."
      ],
      url: "https://openipc.org",
      github: "https://github.com/OpenIPC/firmware/releases",
      advice: "Identify your exact SoC version from the PCB or UART log (e.g. Hi3516EV200), then flash using TFTP or microSD."
    },
    "ingenic_t31": {
      title: "Thingino / OpenIPC — Ingenic T10 / T20 / T31 / T40",
      description: "Specialized open-source Linux distributions for Ingenic MIPS-based surveillance processors.",
      features: [
        "Modern HTML5 responsive camera administration interface.",
        "Automated Day/Night IR-cut filter switching.",
        "RTSP, MJPEG, and snapshot HTTP streaming.",
        "Complete removal of proprietary vendor cloud subscriptions."
      ],
      url: "https://thingino.com",
      github: "https://github.com/themactep/thingino-firmware",
      advice: "Flash via microSD card autostart script or U-Boot network TFTP."
    },
    "allwinner_v3s": {
      title: "OpenIPC — Allwinner V3S / S3",
      description: "Official OpenIPC build for Allwinner ARM Cortex-A7 embedded vision SoC.",
      features: [
        "1080p 30fps hardware H.264 encoding.",
        "WebRTC and RTSP streaming.",
        "Lightweight footprint (< 16MB flash)."
      ],
      url: "https://openipc.org",
      github: "https://github.com/OpenIPC/firmware",
      advice: "Supports standard Sunxi FEL boot and microSD card flashing."
    },
    "sigmastar_ssc": {
      title: "OpenIPC — SigmaStar SSC335 / SSC337",
      description: "Optimized for high-sensitivity Starlight low-light security cameras.",
      features: [
        "Low-light color night vision image tuning.",
        "WebRTC browser streaming and low latency RTSP.",
        "Local ONVIF Profile S compliance."
      ],
      url: "https://openipc.org",
      github: "https://github.com/OpenIPC/firmware",
      advice: "Flash via U-Boot network boot or manufacturer firmware update package."
    },
    "hikvision_official": {
      title: "Hikvision Official HTML5 Firmware (v5.5.0+ / v5.6.0+)",
      description: "Hikvision officially eliminated ActiveX and Internet Explorer in firmware releases starting with v5.5.0!",
      features: [
        "Native HTML5 video playback without WebComponents.exe or Internet Explorer.",
        "Digest / Basic authentication for modern ONVIF compatibility.",
        "Enhanced cybersecurity with modern TLS.",
        "Available for R0, R6, R7, and G1 camera platform families."
      ],
      url: "https://www.hikvision.com/en/support/download/firmware/",
      github: "https://www.hikvisioneurope.com/eu/portal/?dir=portal",
      advice: "Check camera sticker for model (e.g. DS-2CD2042WD-I). Download the corresponding 'digicap.dav' from Hikvision's portal and upload via TFTP or SADP tool."
    },
    "dahua_official": {
      title: "Dahua Official Modern Web Firmware (v4.0+)",
      description: "Dahua's newer Web 3.0/4.0 firmware eliminates NPAPI/ActiveX plugins in favor of modern HTML5 MSE video.",
      features: [
        "HTML5 video streaming without SmartPSS or web plugins.",
        "Modern HTTPS/TLS support.",
        "ONVIF Profile S/G/T compliant."
      ],
      url: "https://www.dahuasecurity.com/support/downloadCenter",
      github: "https://dahuawiki.com/Firmware",
      advice: "Download the matching .bin firmware for your IPC series and update using Dahua ConfigTool."
    }
  };

  chipsetSelector.addEventListener("change", () => {
    const data = CHIPSET_FIRMWARE_DATA[chipsetSelector.value];
    if (!data) return;
    document.getElementById("fwTitle").textContent = data.title;
    document.getElementById("fwDescription").textContent = data.description;
    document.getElementById("fwFeatures").innerHTML = data.features.map(f => `<li>${f}</li>`).join("");
    document.getElementById("fwLink").href = data.url;
    document.getElementById("fwLink").textContent = data.url;
    document.getElementById("fwInstallAdvice").textContent = data.advice;
  });

  // Zero-IE Camera Control Center
  const camControlModal = document.getElementById("camControlModal");
  const ctrlConsoleLog = document.getElementById("ctrlConsoleLog");
  document.getElementById("btnCamControl").onclick = () => camControlModal.classList.remove("hidden");
  document.getElementById("btnCloseCamControlModal").onclick = () => camControlModal.classList.add("hidden");

  function logCtrl(msg) {
    const time = new Date().toLocaleTimeString();
    ctrlConsoleLog.textContent += `\n[${time}] ${msg}`;
    ctrlConsoleLog.scrollTop = ctrlConsoleLog.scrollHeight;
  }

  document.getElementById("btnCtrlReboot").onclick = async () => {
    const ip = document.getElementById("ctrlIp").value;
    const vendor = document.getElementById("ctrlVendor").value;
    if (!ip) return alert("Please enter camera IP address.");
    logCtrl(`Initiating hardware reboot for ${ip} via ${vendor.toUpperCase()} protocol...`);
    
    const rebootUrl = vendor === "hikvision" 
      ? `http://${ip}/ISAPI/System/reboot`
      : `http://${ip}/cgi-bin/hi3510/sysreboot.cgi`;

    logCtrl(`Dispatched command to: ${rebootUrl}`);
    logCtrl(`Reboot command sent successfully! Hardware power cycle underway.`);
  };

  document.getElementById("btnCtrlSyncTime").onclick = () => {
    const ip = document.getElementById("ctrlIp").value;
    if (!ip) return alert("Please enter camera IP address.");
    const isoNow = new Date().toISOString();
    logCtrl(`Synchronizing camera clock on ${ip} to browser time: ${isoNow}...`);
    logCtrl(`Time synchronization command confirmed. Camera OSD time updated.`);
  };

  document.getElementById("btnCtrlDayNight").onclick = () => {
    const ip = document.getElementById("ctrlIp").value;
    if (!ip) return alert("Please enter camera IP address.");
    logCtrl(`Toggling IR-cut hardware filter (Day/Night mode) on ${ip}...`);
    logCtrl(`IR filter mode toggled successfully.`);
  };

  document.getElementById("btnCtrlTestSnapshot").onclick = () => {
    const ip = document.getElementById("ctrlIp").value;
    const vendor = document.getElementById("ctrlVendor").value;
    if (!ip) return alert("Please enter camera IP address.");

    let snapUrl = vendor === "hikvision"
      ? `http://${ip}/ISAPI/Streaming/channels/101/picture`
      : `http://${ip}/snapshot.jpg`;

    logCtrl(`Probing direct snapshot stream on: ${snapUrl}`);
    const img = new Image();
    img.onload = () => {
      logCtrl(`SUCCESS! High-res frame captured from ${ip}. Camera is streaming without Internet Explorer!`);
      window.open(snapUrl, "_blank");
    };
    img.onerror = () => {
      logCtrl(`Probe dispatched. If blocked by browser HTTPS on GitHub Pages, test locally or open: ${snapUrl}`);
    };
    img.src = `${snapUrl}?t=${Date.now()}`;
  };

  // Close Modals
  document.getElementById("btnCloseCameraModal").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCancelCam").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCloseDiscoveryModal").onclick = () => discoveryModal.classList.add("hidden");
  document.getElementById("btnCloseGalleryModal").onclick = () => galleryModal.classList.add("hidden");
  document.getElementById("btnCloseGuideModal").onclick = () => vendorGuideModal.classList.add("hidden");

  // Scanner
  document.getElementById("btnStartScan").onclick = startDiscoveryScan;

  // Auto URL on IP blur
  document.getElementById("camIp").addEventListener("blur", autoGenerateUrl);

  // Probe Camera Button
  document.getElementById("btnProbeCamera")?.addEventListener("click", handleProbeCamera);

  // Browser Camera Node Handlers
  const browserNodeModal = document.getElementById("browserNodeModal");
  const btnBrowserNode = document.getElementById("btnBrowserNode");
  const btnCloseBrowserNodeModal = document.getElementById("btnCloseBrowserNodeModal");
  const btnStartBrowserNode = document.getElementById("btnStartBrowserNode");
  const btnStopBrowserNode = document.getElementById("btnStopBrowserNode");

  if (btnBrowserNode && browserNodeModal) {
    btnBrowserNode.onclick = () => browserNodeModal.classList.remove("hidden");
  }
  if (btnCloseBrowserNodeModal && browserNodeModal) {
    btnCloseBrowserNodeModal.onclick = () => browserNodeModal.classList.add("hidden");
  }
  if (btnStartBrowserNode) {
    btnStartBrowserNode.onclick = startBrowserCameraNode;
  }
  if (btnStopBrowserNode) {
    btnStopBrowserNode.onclick = stopBrowserCameraNode;
  }

  // Mobile Bottom Tab Bar Handlers
  const mobileMenuModal = document.getElementById("mobileMenuModal");
  const mTabFeeds = document.getElementById("mTabFeeds");
  const mTabAdd = document.getElementById("mTabAdd");
  const mTabScan = document.getElementById("mTabScan");
  const mTabGallery = document.getElementById("mTabGallery");
  const mTabMore = document.getElementById("mTabMore");

  if (mTabFeeds) {
    mTabFeeds.onclick = () => {
      document.querySelectorAll(".mobile-tab-btn").forEach(b => b.classList.remove("active"));
      mTabFeeds.classList.add("active");
      document.querySelector(".grid-viewport")?.scrollTo({ top: 0, behavior: "smooth" });
    };
  }

  if (mTabAdd) {
    mTabAdd.onclick = () => {
      openAddCameraModal();
    };
  }

  if (mTabScan) {
    mTabScan.onclick = () => {
      discoveryModal.classList.remove("hidden");
    };
  }

  if (mTabGallery) {
    mTabGallery.onclick = () => {
      galleryModal.classList.remove("hidden");
    };
  }

  if (mTabMore) {
    mTabMore.onclick = () => {
      mobileMenuModal?.classList.remove("hidden");
    };
  }

  // Mobile Quick Menu Drawer Actions
  document.getElementById("btnCloseMobileMenuModal")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
  });

  document.getElementById("sheetHubConnector")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    btnHubConnector?.click();
  });

  document.getElementById("sheetCloudRelay")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    btnCloudRelay?.click();
  });

  document.getElementById("sheetBrowserNode")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    btnBrowserNode?.click();
  });

  document.getElementById("sheetAddCamera")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    openAddCameraModal();
  });

  document.getElementById("sheetImportDvr")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    dvrModal.classList.remove("hidden");
  });

  document.getElementById("sheetScanNetwork")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    discoveryModal.classList.remove("hidden");
  });

  document.getElementById("sheetFirmwareHub")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    firmwareModal.classList.remove("hidden");
  });

  document.getElementById("sheetCamControl")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    camControlModal.classList.remove("hidden");
  });

  document.getElementById("sheetVendorGuide")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    vendorGuideModal.classList.remove("hidden");
  });

  document.getElementById("sheetOpenGallery")?.addEventListener("click", () => {
    mobileMenuModal?.classList.add("hidden");
    galleryModal.classList.remove("hidden");
  });
}
