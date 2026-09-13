/**
 * OmniSight-NVR - Universal Surveillance Dashboard Frontend Logic
 */

let cameras = [];
let vendorPresets = {};
let currentLayout = "2x2";
let activeFilter = "All";
let activePtzCamId = null;
let activePtzSession = { pan: 0.0, tilt: 0.0, zoom: 1.0 };

// DOM Elements
const cameraGrid = document.getElementById("cameraGrid");
const clockDisplay = document.getElementById("clockDisplay");
const groupPills = document.getElementById("groupPills");
const totalCamCount = document.getElementById("totalCamCount");
const ffmpegStatus = document.getElementById("ffmpegStatus");

// Modals
const cameraModal = document.getElementById("cameraModal");
const discoveryModal = document.getElementById("discoveryModal");
const galleryModal = document.getElementById("galleryModal");
const vendorGuideModal = document.getElementById("vendorGuideModal");
const ptzPanel = document.getElementById("ptzPanel");

// Forms
const cameraForm = document.getElementById("cameraForm");
const camVendor = document.getElementById("camVendor");
const quirkText = document.getElementById("quirkText");

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  fetchPresets();
  fetchStatus();
  fetchCameras();
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

// Fetch System Status
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.ffmpeg_available) {
      ffmpegStatus.textContent = "RTSP Transcoder: FFmpeg Hardware Active";
      ffmpegStatus.style.color = "var(--accent-green)";
    } else {
      ffmpegStatus.textContent = "RTSP Transcoder: Standalone Engine (Install ffmpeg for native RTSP)";
      ffmpegStatus.style.color = "var(--accent-amber)";
    }
  } catch (err) {
    console.error("Status fetch failed:", err);
  }
}

// Fetch Presets
async function fetchPresets() {
  try {
    const res = await fetch("/api/presets");
    vendorPresets = await res.json();
    updateVendorQuirks();
  } catch (err) {
    console.error("Failed to load presets:", err);
  }
}

// Fetch Cameras
async function fetchCameras() {
  try {
    const res = await fetch("/api/cameras");
    const data = await res.json();
    cameras = data.cameras || [];
    currentLayout = data.layout || "2x2";
    setLayout(currentLayout, false);
    renderGroupPills(data.groups || ["All"]);
    renderGrid();
  } catch (err) {
    console.error("Failed to fetch cameras:", err);
  }
}

// Render Filter Group Pills
function renderGroupPills(groups) {
  groupPills.innerHTML = "";
  const allBtn = document.createElement("button");
  allBtn.className = `pill ${activeFilter === "All" ? "active" : ""}`;
  allBtn.textContent = `All Cameras (${cameras.length})`;
  allBtn.onclick = () => setFilter("All");
  groupPills.appendChild(allBtn);

  groups.forEach(g => {
    if (g === "All") return;
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

// Set Layout Matrix
function setLayout(layout, save = true) {
  currentLayout = layout;
  cameraGrid.className = `camera-grid grid-${layout}`;
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.layout === layout);
  });

  if (save) {
    fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout })
    });
  }
}

// Render Camera Grid
function renderGrid() {
  cameraGrid.innerHTML = "";
  const filtered = activeFilter === "All" 
    ? cameras 
    : cameras.filter(c => c.group === activeFilter);

  if (filtered.length === 0) {
    cameraGrid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">No cameras registered in this group. Click "+ ADD CAMERA" above.</div>`;
    return;
  }

  filtered.forEach(cam => {
    const card = document.createElement("div");
    card.className = "camera-card";
    card.dataset.id = cam.id;

    // Header
    const vendorClass = cam.vendor || "generic";
    card.innerHTML = `
      <div class="card-header">
        <div class="card-title-group">
          <span class="cam-status-dot"></span>
          <span class="cam-name" title="${cam.name}">${cam.name}</span>
          <span class="vendor-tag ${vendorClass}">${cam.vendor || "CAM"}</span>
        </div>
        <div class="card-actions">
          <button class="btn-icon" title="Take Snapshot" onclick="captureSnapshot('${cam.id}', '${cam.name}')">📷</button>
          ${cam.ptz ? `<button class="btn-icon" title="PTZ Controls" onclick="openPtz('${cam.id}', '${cam.name}')">🎮</button>` : ''}
          <button class="btn-icon" title="Edit Camera" onclick="openEditCameraModal('${cam.id}')">⚙️</button>
          <button class="btn-icon" title="Delete Camera" onclick="deleteCamera('${cam.id}')">🗑️</button>
        </div>
      </div>
      <div class="video-container" ondblclick="toggleFocus('${cam.id}')">
        <img class="video-feed" src="/api/cameras/${cam.id}/stream" alt="${cam.name}" loading="lazy">
        <div class="video-overlay-hud">${cam.resolution || "1080p"} • ${cam.fps || 25} FPS</div>
      </div>
      <div class="card-footer">
        <span>IP: ${cam.ip || "Direct Stream"}</span>
        <span>${cam.group || "Default"}</span>
      </div>
    `;
    cameraGrid.appendChild(card);
  });
}

// Double click to focus single camera
function toggleFocus(camId) {
  if (currentLayout === "1x1") {
    setLayout("2x2");
  } else {
    setLayout("1x1");
    // Reorder so this camera is first
    const camIndex = cameras.findIndex(c => c.id === camId);
    if (camIndex > -1) {
      const [focusCam] = cameras.splice(camIndex, 1);
      cameras.unshift(focusCam);
      renderGrid();
    }
  }
}

// Snapshot
async function captureSnapshot(camId, camName) {
  try {
    const res = await fetch("/api/snapshots/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ camera_id: camId })
    });
    if (res.ok) {
      const snap = await res.json();
      flashScreen();
      alert(`Snapshot captured: ${snap.filename}`);
    }
  } catch (err) {
    alert("Snapshot capture failed: " + err);
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

// PTZ Floating Controller
function openPtz(camId, camName) {
  activePtzCamId = camId;
  document.getElementById("ptzCamTitle").textContent = `PTZ: ${camName}`;
  ptzPanel.classList.remove("hidden");
}

document.querySelectorAll(".ptz-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!activePtzCamId) return;
    const action = btn.dataset.ptz;
    try {
      const res = await fetch(`/api/cameras/${activePtzCamId}/ptz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      const data = await res.json();
      document.getElementById("ptzTelemetry").textContent = 
        `PAN: ${data.pan >= 0 ? '+' : ''}${data.pan.toFixed(1)}° | TILT: ${data.tilt >= 0 ? '+' : ''}${data.tilt.toFixed(1)}° | ZOOM: ${data.zoom.toFixed(1)}x`;
    } catch (err) {
      console.error("PTZ error:", err);
    }
  });
});

document.getElementById("btnClosePtz").onclick = () => {
  ptzPanel.classList.add("hidden");
  activePtzCamId = null;
};

// Add / Edit Camera Modal
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
  document.getElementById("camSimulated").checked = !!cam.is_simulated;

  updateVendorQuirks();
  cameraModal.classList.remove("hidden");
}

function updateVendorQuirks() {
  const selected = camVendor.value;
  const preset = vendorPresets[selected];
  if (preset && preset.quirks) {
    quirkText.innerHTML = preset.quirks.map(q => `• ${q}`).join("<br>");
  } else {
    quirkText.textContent = "Standard RTSP configuration.";
  }
}

camVendor.addEventListener("change", () => {
  const selected = camVendor.value;
  const preset = vendorPresets[selected];
  if (preset) {
    document.getElementById("camPort").value = preset.default_ports?.rtsp || 554;
    document.getElementById("camChannel").value = preset.default_channel ?? 1;
    if (preset.default_credentials) {
      document.getElementById("camUser").value = preset.default_credentials.username || "admin";
      document.getElementById("camPass").value = preset.default_credentials.password || "";
    }
  }
  updateVendorQuirks();
  autoGenerateUrl();
});

async function autoGenerateUrl() {
  const vendor = camVendor.value;
  const ip = document.getElementById("camIp").value || "192.168.1.100";
  const port = parseInt(document.getElementById("camPort").value) || 554;
  const username = document.getElementById("camUser").value;
  const password = document.getElementById("camPass").value;
  const channel = document.getElementById("camChannel").value;

  try {
    const res = await fetch("/api/presets/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor, ip, port, username, password, channel })
    });
    const data = await res.json();
    document.getElementById("camStreamUrl").value = data.stream_url;
  } catch (err) {
    console.error("Generate error:", err);
  }
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
    is_simulated: document.getElementById("camSimulated").checked
  };

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
    } else {
      alert("Failed to save camera.");
    }
  } catch (err) {
    alert("Error: " + err);
  }
});

async function deleteCamera(camId) {
  if (!confirm("Remove this camera from the matrix?")) return;
  try {
    const res = await fetch(`/api/cameras/${camId}`, { method: "DELETE" });
    if (res.ok) {
      await fetchCameras();
    }
  } catch (err) {
    alert("Delete failed: " + err);
  }
}

// Discovery Scan
async function startDiscoveryScan() {
  const scanStatusMsg = document.getElementById("scanStatusMsg");
  const tbody = document.getElementById("discoveryTableBody");
  
  scanStatusMsg.textContent = "Broadcasting ONVIF probe & scanning subnet camera ports...";
  tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Scanning active LAN subnet... Please wait 3 seconds.</td></tr>`;

  try {
    const res = await fetch("/api/discovery/scan");
    const data = await res.json();
    scanStatusMsg.textContent = `Scan complete. Discovered ${data.device_count} device(s).`;
    
    if (data.devices.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No cameras responded to ONVIF or RTSP probes. Ensure cameras are on the same subnet.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    data.devices.forEach(dev => {
      const tr = document.createElement("tr");
      const ports = dev.open_ports ? dev.open_ports.join(", ") : "ONVIF 3702";
      tr.innerHTML = `
        <td><strong>${dev.ip}</strong></td>
        <td>${dev.type}</td>
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
  } catch (err) {
    scanStatusMsg.textContent = "Scan error: " + err;
  }
}

function addDiscoveredCamera(ip, vendorPreset) {
  discoveryModal.classList.add("hidden");
  openAddCameraModal();
  document.getElementById("camIp").value = ip;
  document.getElementById("camVendor").value = vendorPreset || "generic_onvif";
  document.getElementById("camName").value = `${vendorPreset.toUpperCase()} Camera (${ip})`;
  updateVendorQuirks();
  autoGenerateUrl();
}

// Gallery
async function openGallery() {
  galleryModal.classList.remove("hidden");
  const grid = document.getElementById("galleryGrid");
  grid.innerHTML = "<div class='empty-state'>Loading snapshots...</div>";

  try {
    const res = await fetch("/api/snapshots");
    const snaps = await res.json();
    if (snaps.length === 0) {
      grid.innerHTML = "<div class='empty-state'>No snapshots captured yet.</div>";
      return;
    }

    grid.innerHTML = "";
    snaps.forEach(snap => {
      const card = document.createElement("div");
      card.className = "gallery-card";
      card.innerHTML = `
        <a href="${snap.url}" target="_blank">
          <img src="${snap.url}" alt="${snap.filename}">
        </a>
        <div class="gallery-meta">
          <span>${snap.date_formatted}</span>
          <button class="btn-icon" title="Delete" onclick="deleteSnapshot('${snap.filename}')">🗑️</button>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch (err) {
    grid.innerHTML = "<div class='empty-state'>Error loading gallery.</div>";
  }
}

async function deleteSnapshot(filename) {
  if (!confirm(`Delete snapshot ${filename}?`)) return;
  try {
    const res = await fetch(`/api/snapshots/${filename}`, { method: "DELETE" });
    if (res.ok) openGallery();
  } catch (err) {
    alert("Delete failed: " + err);
  }
}

// Event Listeners
function attachEventListeners() {
  // Layout Buttons
  document.querySelectorAll(".btn-layout").forEach(btn => {
    btn.onclick = () => setLayout(btn.dataset.layout);
  });

  // Top Nav Modals
  document.getElementById("btnAddCamera").onclick = openAddCameraModal;
  document.getElementById("btnScanNetwork").onclick = () => discoveryModal.classList.remove("hidden");
  document.getElementById("btnOpenGallery").onclick = openGallery;
  document.getElementById("btnVendorGuide").onclick = () => vendorGuideModal.classList.remove("hidden");

  // Close Modals
  document.getElementById("btnCloseCameraModal").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCancelCam").onclick = () => cameraModal.classList.add("hidden");
  document.getElementById("btnCloseDiscoveryModal").onclick = () => discoveryModal.classList.add("hidden");
  document.getElementById("btnCloseGalleryModal").onclick = () => galleryModal.classList.add("hidden");
  document.getElementById("btnCloseGuideModal").onclick = () => vendorGuideModal.classList.add("hidden");

  // DVR Modal
  const dvrModal = document.getElementById("dvrModal");
  const dvrForm = document.getElementById("dvrForm");
  document.getElementById("btnImportDvr").onclick = () => dvrModal.classList.remove("hidden");
  document.getElementById("btnCloseDvrModal").onclick = () => dvrModal.classList.add("hidden");
  document.getElementById("btnCancelDvr").onclick = () => dvrModal.classList.add("hidden");

  dvrForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(dvrForm);
    const payload = {
      vendor: formData.get("vendor"),
      channels: parseInt(formData.get("channels")) || 8,
      ip: formData.get("ip"),
      port: parseInt(formData.get("port")) || 554,
      username: formData.get("username") || "admin",
      password: formData.get("password") || "",
      label: formData.get("label") || "DVR",
      group: formData.get("group") || "CCTV Analog"
    };

    try {
      const res = await fetch("/api/dvr/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const result = await res.json();
        dvrModal.classList.add("hidden");
        alert(`Successfully imported ${result.imported_count} CCTV BNC channels into matrix!`);
        await fetchCameras();
      } else {
        alert("Failed to import DVR channels.");
      }
    } catch (err) {
      alert("Error importing DVR: " + err);
    }
  });

  // Scanner
  document.getElementById("btnStartScan").onclick = startDiscoveryScan;

  // Auto URL on IP blur
  document.getElementById("camIp").addEventListener("blur", autoGenerateUrl);
}
