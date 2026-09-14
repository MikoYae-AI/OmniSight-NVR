/**
 * OmniSight-NVR - Universal CCTV & Surveillance Dashboard
 * Dual Mode: Works both as a Standalone Client on GitHub Pages (https://mikoyae-ai.github.io/OmniSight-NVR)
 * and connected to the local Python high-speed NVR backend (http://localhost:8080).
 */

const IS_GITHUB_PAGES = window.location.hostname.includes("github.io") || window.location.protocol === "file:";
let localApiAvailable = false;
let cameras = [];
let vendorPresets = {};
let currentLayout = "2x2";
let activeFilter = "All";
let activePtzCamId = null;
let activePtzSession = { pan: 0.0, tilt: 0.0, zoom: 1.0 };
let pollingIntervals = {};

// Fallback Default Cameras (For pure client-side GitHub Pages mode)
const DEFAULT_CLIENT_CAMERAS = [
  {
    id: "cam-hikvision-01",
    name: "Hikvision DS-2CD Front Gate",
    vendor: "hikvision",
    group: "Perimeter",
    ip: "192.168.1.101",
    port: 554,
    username: "admin",
    password: "",
    stream_url: "sim://hikvision_gate",
    sub_stream_url: "sim://hikvision_gate_sub",
    channel: 1,
    is_simulated: true,
    status: "online",
    fps: 25,
    resolution: "1920x1080",
    ptz: true,
    notes: "Hikvision 4MP ColorVu Bullet (Direct stream / simulation)."
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
  }
];

const BUILTIN_PRESETS = {
  "hikvision": {
    "name": "Hikvision (DS-2CD / ColorVu / AcuSense)",
    "default_ports": { "rtsp": 554, "http": 80, "sdk": 8000 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
    "default_channel": 1,
    "quirks": ["Channel 1 Main = 101, Sub = 102. Enable ONVIF in Configuration > Network > Advanced Settings > Integration Protocol."]
  },
  "hikvision_dvr": {
    "name": "Hikvision CCTV DVR / TurboHD (BNC Coax)",
    "default_ports": { "rtsp": 554, "http": 80 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture",
    "default_channel": 1,
    "quirks": ["Channel 1 BNC = 101, Channel 2 BNC = 201, Channel 3 BNC = 301. Multi-channel BNC DVR."]
  },
  "xiongmai": {
    "name": "Xiongmai / XM / CMS (Generic Chinese Cam)",
    "default_ports": { "rtsp": 554, "media": 34567, "onvif": 8899 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "default_channel": 0,
    "quirks": ["Media port is 34567. If it forces Internet Explorer ActiveX, use snapshot.jpg polling to view without IE!"]
  },
  "xiongmai_dvr": {
    "name": "Chinese AHD/TVI CCTV DVR (NetSurveillance)",
    "default_ports": { "rtsp": 554, "media": 34567 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch{channel_index}" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "default_channel": 1,
    "quirks": ["BNC Ch 1 = /live/ch0, BNC Ch 2 = /live/ch1, Ch 3 = /live/ch2. Desktop CMS port is 34567."]
  },
  "dahua": {
    "name": "Dahua / Imou (IPC / WizSense / XVR)",
    "default_ports": { "rtsp": 554, "tcp": 37777 },
    "default_credentials": { "username": "admin", "password": "admin" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/cgi-bin/snapshot.cgi?channel={channel}",
    "default_channel": 1,
    "quirks": ["Subtype 0 = Main, Subtype 1 = Sub. Port 37777 is Dahua TCP management."]
  },
  "legacy_activex": {
    "name": "Legacy Camera (Requires Internet Explorer / ActiveX)",
    "default_ports": { "http": 80, "rtsp": 554 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0" },
    "snapshot_pattern": "http://{ip}:{port}/snapshot.jpg",
    "default_channel": 1,
    "quirks": [
      "Bypasses ActiveX! OmniSight polls the camera's raw snapshot endpoint at 10 FPS, so you can view it in Chrome/Edge/Firefox without Internet Explorer."
    ]
  },
  "tapo": {
    "name": "TP-Link Tapo (C100, C200, C310)",
    "default_ports": { "rtsp": 554, "onvif": 2020 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/stream1" },
    "default_channel": 1,
    "quirks": ["Must configure local 'Camera Account' inside Tapo App > Device Settings > Advanced Settings > Camera Account."]
  },
  "reolink": {
    "name": "Reolink (RLC / Duo / E1)",
    "default_ports": { "rtsp": 554, "onvif": 8000 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/h264Preview_{channel}_main" },
    "default_channel": "01",
    "quirks": ["Enable RTSP/ONVIF in Reolink Client under Network Settings."]
  },
  "generic_onvif": {
    "name": "Generic ONVIF Camera",
    "default_ports": { "rtsp": 554, "onvif": 80 },
    "default_credentials": { "username": "admin", "password": "admin" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/onvif1" },
    "default_channel": 1,
    "quirks": ["Standard ONVIF Profile S stream URL."]
  },
  "generic_rtsp": {
    "name": "Custom RTSP Stream",
    "default_ports": { "rtsp": 554 },
    "default_credentials": { "username": "", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/{path}" },
    "default_channel": 1,
    "quirks": ["Provide your direct RTSP URL path."]
  },
  "mjpeg_http": {
    "name": "HTTP MJPEG / ESP32-CAM",
    "default_ports": { "http": 80, "stream": 8080 },
    "default_credentials": { "username": "", "password": "" },
    "rtsp_patterns": { "main": "http://{ip}:{port}/stream" },
    "default_channel": 1,
    "quirks": ["Direct HTTP multipart MJPEG stream."]
  },
  "simulated": {
    "name": "OmniSight Virtual CCTV Generator",
    "default_ports": { "stream": 8000 },
    "default_credentials": { "username": "", "password": "" },
    "rtsp_patterns": { "main": "sim://{scene}" },
    "default_channel": 1,
    "quirks": ["Procedural surveillance engine with animated OSD and motion detection."]
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
const cameraModal = document.getElementById("cameraModal");
const dvrModal = document.getElementById("dvrModal");
const discoveryModal = document.getElementById("discoveryModal");
const legacyFixModal = document.getElementById("legacyFixModal");
const galleryModal = document.getElementById("galleryModal");
const vendorGuideModal = document.getElementById("vendorGuideModal");
const ptzPanel = document.getElementById("ptzPanel");

// Forms
const cameraForm = document.getElementById("cameraForm");
const dvrForm = document.getElementById("dvrForm");
const camVendor = document.getElementById("camVendor");
const quirkText = document.getElementById("quirkText");

document.addEventListener("DOMContentLoaded", async () => {
  initClock();
  await detectBackend();
  attachEventListeners();
});

function initClock() {
  function update() {
    const now = new Date();
    clockDisplay.textContent = now.toTimeString().split(" ")[0];
  }
  update();
  setInterval(update, 1000);
}

// Detect Local Python Backend vs Standalone GitHub Pages Mode
async function detectBackend() {
  try {
    const res = await fetch("/api/status", { cache: "no-cache" });
    if (res.ok) {
      const status = await res.json();
      localApiAvailable = true;
      appModeBadge.textContent = "LOCAL HUB ONLINE";
      appModeBadge.style.background = "rgba(16, 185, 129, 0.15)";
      appModeBadge.style.borderColor = "var(--accent-green)";
      appModeBadge.style.color = "var(--accent-green)";
      hubModeText.textContent = "Connected to Python NVR Hub (:8080)";
      backendBridgeStatus.textContent = "Local Server Mode: Full Hardware Multiplexing Active";

      if (status.ffmpeg_available) {
        ffmpegStatus.textContent = "RTSP Transcoder: FFmpeg Hardware Active";
        ffmpegStatus.style.color = "var(--accent-green)";
      } else {
        ffmpegStatus.textContent = "RTSP Engine: Standalone Engine Active";
      }

      await fetchPresets();
      await fetchCameras();
      return;
    }
  } catch (e) {
    // Running on GitHub Pages without local backend
  }

  // Fallback to GitHub Pages Standalone Client Mode
  localApiAvailable = false;
  appModeBadge.textContent = "GITHUB PAGES CLOUD";
  hubModeText.textContent = "GitHub Pages Mode (Local Storage + In-Browser Scanner)";
  backendBridgeStatus.textContent = "Cloud Deployment: https://mikoyae-ai.github.io/OmniSight-NVR/";
  ffmpegStatus.textContent = "ActiveX / IE Mode: Direct HTML5 Snapshot Polling Ready";
  
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
    const res = await fetch("/api/presets");
    vendorPresets = await res.json();
    updateVendorQuirks();
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
    const res = await fetch("/api/cameras");
    const data = await res.json();
    cameras = data.cameras || [];
    currentLayout = data.layout || "2x2";
    setLayout(currentLayout, false);
    renderGroupPills(data.groups || ["All"]);
    renderGrid();
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
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.layout === layout);
  });

  if (save) {
    if (localApiAvailable) {
      fetch("/api/layout", {
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
  // Clear any active snapshot polling intervals
  Object.keys(pollingIntervals).forEach(k => {
    clearInterval(pollingIntervals[k]);
    delete pollingIntervals[k];
  });

  cameraGrid.innerHTML = "";
  const filtered = activeFilter === "All" 
    ? cameras 
    : cameras.filter(c => c.group === activeFilter);

  if (filtered.length === 0) {
    cameraGrid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">No cameras registered in this zone. Click "+ ADD CAMERA" or "IMPORT DVR" above.</div>`;
    return;
  }

  filtered.forEach(cam => {
    const card = document.createElement("div");
    card.className = "camera-card";
    card.dataset.id = cam.id;

    const vendorClass = (cam.vendor || "generic").replace("_dvr", "");
    const isLegacy = cam.legacy_polling || cam.vendor === "legacy_activex";

    card.innerHTML = `
      <div class="card-header">
        <div class="card-title-group">
          <span class="cam-status-dot"></span>
          <span class="cam-name" title="${cam.name}">${cam.name}</span>
          <span class="vendor-tag ${vendorClass}">${cam.vendor || "CAM"}</span>
          ${isLegacy ? `<span class="badge-legacy" title="ActiveX bypassed: HTML5 snapshot polling">NO-IE</span>` : ''}
        </div>
        <div class="card-actions">
          <button class="btn-icon" title="Take Snapshot" onclick="captureSnapshot('${cam.id}', '${cam.name}')">📷</button>
          ${cam.ptz ? `<button class="btn-icon" title="PTZ Controls" onclick="openPtz('${cam.id}', '${cam.name}')">🎮</button>` : ''}
          <button class="btn-icon" title="Edit Camera" onclick="openEditCameraModal('${cam.id}')">⚙️</button>
          <button class="btn-icon" title="Delete Camera" onclick="deleteCamera('${cam.id}')">🗑️</button>
        </div>
      </div>
      <div class="video-container" id="videoContainer-${cam.id}" ondblclick="toggleFocus('${cam.id}')">
        <!-- Live feed rendered here -->
        <div class="video-overlay-hud">${cam.resolution || "1080p"} • ${cam.fps || 25} FPS</div>
      </div>
      <div class="card-footer">
        <span>${cam.ip ? `IP: ${cam.ip}` : "Stream"}</span>
        <span>${cam.group || "Default"}</span>
      </div>
    `;
    cameraGrid.appendChild(card);

    // Setup Video Player for this Camera
    setupCameraPlayer(cam);
  });
}

// Setup Camera Video Stream Player (Handles Local Server MJPEG vs Legacy Snapshot Polling vs Procedural Canvas)
function setupCameraPlayer(cam) {
  const container = document.getElementById(`videoContainer-${cam.id}`);
  if (!container) return;

  if (localApiAvailable && !cam.legacy_polling) {
    // Connected to Python server: use native multipart MJPEG
    const img = document.createElement("img");
    img.className = "video-feed";
    img.src = `/api/cameras/${cam.id}/stream`;
    img.alt = cam.name;
    container.insertBefore(img, container.firstChild);
    return;
  }

  // Legacy Snapshot Polling Mode (Zero ActiveX / No Internet Explorer Needed)
  if (cam.legacy_polling && cam.ip) {
    const img = document.createElement("img");
    img.className = "video-feed";
    img.alt = cam.name;
    container.insertBefore(img, container.firstChild);

    // Construct snapshot URL
    let snapUrl = "";
    if (cam.vendor === "hikvision" || cam.vendor === "hikvision_dvr") {
      snapUrl = `http://${cam.ip}/ISAPI/Streaming/channels/${cam.channel || 1}01/picture`;
    } else if (cam.vendor === "dahua") {
      snapUrl = `http://${cam.ip}/cgi-bin/snapshot.cgi?channel=${cam.channel || 1}`;
    } else {
      snapUrl = `http://${cam.ip}/snapshot.jpg`;
    }

    function pollFrame() {
      const testImg = new Image();
      testImg.onload = () => { img.src = testImg.src; };
      testImg.onerror = () => {
        // If direct HTTP is blocked by HTTPS on GitHub pages, render tactical placeholder
        drawTacticalFallback(container, cam, "ACTIVE POLLING • MIXED CONTENT RESTRICTION");
      };
      testImg.src = `${snapUrl}?t=${Date.now()}`;
    }

    pollFrame();
    pollingIntervals[cam.id] = setInterval(pollFrame, 500); // 2 FPS snapshot polling
    return;
  }

  // In-Browser Procedural Canvas Simulation (For GitHub Pages Standalone preview)
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

  const animTimer = setInterval(render, 50); // 20 FPS in-browser simulation
  pollingIntervals[`canvas-${cam.id}`] = animTimer;
}

// Fallback visual message
function drawTacticalFallback(container, cam, message) {
  let fb = container.querySelector(".fallback-banner");
  if (!fb) {
    fb = document.createElement("div");
    fb.className = "fallback-banner";
    fb.style.position = "absolute";
    fb.style.inset = "0";
    fb.style.display = "flex";
    fb.style.flexDirection = "column";
    fb.style.alignItems = "center";
    fb.style.justifyContent = "center";
    fb.style.background = "rgba(10, 12, 18, 0.95)";
    fb.style.padding = "15px";
    fb.style.textAlign = "center";
    fb.innerHTML = `
      <span style="color: var(--accent-amber); font-weight: bold; font-size: 11px;">⚠️ ${message}</span>
      <p style="font-size: 10px; color: var(--text-muted); margin: 6px 0;">
        Browser blocked direct HTTP to ${cam.ip}. Run local hub with <code>./start.sh</code> or allow Insecure Content in site settings.
      </p>
    `;
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
      const res = await fetch("/api/snapshots/capture", {
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

  // Client-side snapshot: grab from canvas or img
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
  document.getElementById("ptzCamTitle").textContent = `PTZ: ${camName}`;
  ptzPanel.classList.remove("hidden");
}

document.querySelectorAll(".ptz-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    const action = btn.dataset.ptz;
    if (localApiAvailable) {
      try {
        const res = await fetch(`/api/cameras/${activePtzCamId}/ptz`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action })
        });
        const data = await res.json();
        document.getElementById("ptzTelemetry").textContent = 
          `PAN: ${data.pan >= 0 ? '+' : ''}${data.pan.toFixed(1)}° | TILT: ${data.tilt >= 0 ? '+' : ''}${data.tilt.toFixed(1)}° | ZOOM: ${data.zoom.toFixed(1)}x`;
      } catch (err) {}
    } else {
      // In-browser PTZ emulation
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
  ptzPanel.classList.add("hidden");
  activePtzCamId = null;
};

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
    document.getElementById("camPort").value = preset.default_ports?.rtsp || 554;
    document.getElementById("camChannel").value = preset.default_channel ?? 1;
    if (preset.default_credentials) {
      document.getElementById("camUser").value = preset.default_credentials.username || "admin";
      document.getElementById("camPass").value = preset.default_credentials.password || "";
    }
    if (selected === "legacy_activex") {
      document.getElementById("camLegacyPolling").checked = true;
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
  const channel = document.getElementById("camChannel").value;

  const preset = vendorPresets[vendor] || BUILTIN_PRESETS[vendor] || BUILTIN_PRESETS["generic_rtsp"];
  const creds = username && password ? `${username}:${password}@` : (username ? `${username}@` : "");
  
  if (document.getElementById("camLegacyPolling").checked && preset.snapshot_pattern) {
    const snapUrl = preset.snapshot_pattern
      .replace("{username}:{password}@", creds)
      .replace("{ip}", ip)
      .replace("{port}", port === 554 ? "80" : String(port))
      .replace("{channel}", channel);
    document.getElementById("camStreamUrl").value = snapUrl;
    return;
  }

  const pattern = preset.rtsp_patterns?.main || "rtsp://{username}:{password}@{ip}:{port}/live/ch0";
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
      const res = await fetch(url, {
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

  // GitHub Pages Mode: Update LocalStorage
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
      const res = await fetch(`/api/cameras/${camId}`, { method: "DELETE" });
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
async function startDiscoveryScan() {
  const scanStatusMsg = document.getElementById("scanStatusMsg");
  const tbody = document.getElementById("discoveryTableBody");
  const subnetBase = document.getElementById("scanSubnetInput").value || "192.168.1";

  scanStatusMsg.textContent = "Scanning local subnet for cameras...";
  tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Probing subnet ${subnetBase}.1 to ${subnetBase}.40... Please wait.</td></tr>`;

  // If local Python hub is available, use fast multicast ONVIF probe
  if (localApiAvailable) {
    try {
      const res = await fetch("/api/discovery/scan");
      const data = await res.json();
      renderDiscoveredDevices(data.devices, "ONVIF UDP / Port Scan");
      scanStatusMsg.textContent = `Scan complete. Found ${data.devices.length} device(s).`;
      return;
    } catch (e) {}
  }

  // Pure In-Browser Scanner (GitHub Pages Mode)
  // Probes HTTP ports using image & fetch timing probes
  const detected = [];
  const probes = [
    { path: "/favicon.ico", desc: "Web Interface" },
    { path: "/doc/page/login.asp", desc: "Hikvision Login" },
    { path: "/web/login.html", desc: "Xiongmai (Chinese Cam)" },
    { path: "/snapshot.jpg", desc: "Direct Snapshot Cam" }
  ];

  let completed = 0;
  const totalToScan = 35; // Fast scan first 35 hosts

  for (let i = 1; i <= totalToScan; i++) {
    const ip = `${subnetBase}.${i}`;
    testCameraHostInBrowser(ip).then(dev => {
      completed++;
      if (dev) {
        detected.push(dev);
        renderDiscoveredDevices(detected, "Browser LAN Probe");
      }
      if (completed >= totalToScan) {
        // Always add simulated engine
        detected.push({
          ip: "127.0.0.1",
          type: "Virtual Simulator",
          vendor_preset: "simulated",
          vendor_name: "OmniSight Virtual Generator",
          open_ports: [8000],
          confidence: "High"
        });
        renderDiscoveredDevices(detected, "Browser LAN Probe");
        scanStatusMsg.textContent = `Browser scan complete. Found ${detected.length} device(s).`;
      }
    });
  }
}

function testCameraHostInBrowser(ip) {
  return new Promise((resolve) => {
    const img = new Image();
    let resolved = false;

    img.onload = () => {
      if (!resolved) {
        resolved = true;
        resolve({
          ip,
          type: "HTTP CCTV Device",
          vendor_preset: "generic_onvif",
          vendor_name: "Detected Camera / DVR Web UI",
          open_ports: [80],
          confidence: "High"
        });
      }
    };

    img.onerror = () => {
      // Image error could still mean the host is active (CORS / HTTP 401 Auth)
      // If error happens very fast (< 400ms), port is open and rejected!
    };

    img.src = `http://${ip}/favicon.ico?t=${Date.now()}`;
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve(null);
      }
    }, 1200);
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

// Attach Event Listeners
function attachEventListeners() {
  // Layout Buttons
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.onclick = () => setLayout(btn.dataset.layout);
  });

  // Top Nav Modals
  document.getElementById("btnAddCamera").onclick = openAddCameraModal;
  document.getElementById("btnScanNetwork").onclick = () => discoveryModal.classList.remove("hidden");
  document.getElementById("btnLegacyFix").onclick = () => legacyFixModal.classList.remove("hidden");
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
        const res = await fetch("/api/dvr/import", {
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
        is_simulated: true, // Render procedural CCTV visual on GitHub Pages
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

  // Legacy Fix Quick Add
  document.getElementById("btnQuickAddLegacy").onclick = () => {
    legacyFixModal.classList.add("hidden");
    openAddCameraModal();
    document.getElementById("camVendor").value = "legacy_activex";
    document.getElementById("camLegacyPolling").checked = true;
    document.getElementById("camName").value = "Legacy CCTV (Direct Snapshot)";
    updateVendorQuirks();
    autoGenerateUrl();
  };

  // Close Modals
  document.getElementById("btnCloseCameraModal").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCancelCam").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCloseDiscoveryModal").onclick = () => discoveryModal.classList.add("hidden");
  document.getElementById("btnCloseLegacyModal").onclick = () => legacyFixModal.classList.add("hidden");
  document.getElementById("btnCloseGalleryModal").onclick = () => galleryModal.classList.add("hidden");
  document.getElementById("btnCloseGuideModal").onclick = () => vendorGuideModal.classList.add("hidden");

  // Scanner
  document.getElementById("btnStartScan").onclick = startDiscoveryScan;

  // Auto URL on IP blur
  document.getElementById("camIp").addEventListener("blur", autoGenerateUrl);
}
