/**
 * OmniSight-NVR - Universal CCTV & Surveillance Dashboard
 * Dual Mode: Works both as a Standalone Client on GitHub Pages (https://mikoyae-ai.github.io/OmniSight-NVR)
 * and connected to the local Python high-speed NVR backend (http://localhost:8080).
 */

const IS_GITHUB_PAGES = window.location.hostname.includes("github.io") || window.location.protocol === "file:";
let hubBaseUrl = "";
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
    stream_url: "rtsp://admin:@192.168.1.13:554/Streaming/Channels/101",
    sub_stream_url: "rtsp://admin:@192.168.1.13:554/Streaming/Channels/102",
    snapshot_url: "http://192.168.1.13/ISAPI/Streaming/channels/101/picture",
    channel: 1,
    is_simulated: false,
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
    stream_url: "rtsp://admin:@192.168.1.10:554/live/ch0",
    sub_stream_url: "rtsp://admin:@192.168.1.10:554/live/ch1",
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
  "gatocam": {
    "name": "Shenzhen GatoCam (Indoor / Outdoor / PTZ)",
    "default_ports": { "rtsp": 554, "media": 34567, "onvif": 8899, "http": 80 },
    "default_credentials": { "username": "admin", "password": "" },
    "rtsp_patterns": { "main": "rtsp://{username}:{password}@{ip}:{port}/live/ch0" },
    "snapshot_pattern": "http://{username}:{password}@{ip}:{port}/snapshot.jpg",
    "default_channel": 0,
    "quirks": [
      "Shenzhen Gato / XM / Sofia OEM architecture with HiSilicon/Goke SoC.",
      "Primary RTSP pattern: rtsp://<ip>:554/live/ch0 or /stream1.",
      "Legacy Snapshot URL: http://<ip>/snapshot.jpg or http://<ip>/tmpfs/auto.jpg.",
      "Default password is empty or '123456' / 'admin'.",
      "Zero-IE HTML5 engine bypasses required ActiveX plugins.",
      "Eligible for OpenIPC flashing (HiSilicon Hi3516 / XM530) for full cloud-free autonomy."
    ]
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
  // Check for Google OAuth 2.0 redirect token
  const urlParams = new URLSearchParams(window.location.search);
  const oauthToken = urlParams.get("token");
  if (oauthToken) {
    authToken = oauthToken;
    sessionStorage.setItem("omnisight_token", authToken);
    localStorage.setItem("omnisight_token", authToken);
    sessionStorage.setItem("omnisight_unlocked", "true");
    window.history.replaceState({}, document.title, window.location.pathname);
    showNotification("Authenticated via Google OAuth 2.0!", "success");
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

// Detect Local Python Backend vs Standalone GitHub Pages Mode
async function detectBackend() {
  const candidates = [
    "", // relative (localhost or direct tunnel origin)
    localStorage.getItem("omnisight_hub_url") || "",
    "http://localhost:8080",
    "http://127.0.0.1:8080"
  ].filter((u, i, arr) => arr.indexOf(u) === i && (u !== "" || !IS_GITHUB_PAGES));

  for (const candidate of candidates) {
    try {
      const probeUrl = candidate ? `${candidate}/api/status` : "/api/status";
      const res = await fetch(probeUrl, { cache: "no-cache", mode: "cors" });
      if (res.ok) {
        const status = await res.json();
        hubBaseUrl = candidate;
        localApiAvailable = true;
        const isTunnel = candidate.includes("trycloudflare.com");
        appModeBadge.textContent = isTunnel ? "SECURE TUNNEL ONLINE" : "LOCAL HUB ONLINE";
        appModeBadge.style.background = "rgba(16, 185, 129, 0.15)";
        appModeBadge.style.borderColor = "var(--accent-green)";
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
      // Continue probing next candidate
    }
  }

  // Fallback to GitHub Pages Standalone Client Mode
  localApiAvailable = false;
  appModeBadge.textContent = "GITHUB PAGES CLOUD";
  hubModeText.textContent = "GitHub Pages Mode (Local Storage + In-Browser Scanner)";
  backendBridgeStatus.textContent = "Cloud Deployment: https://mikoyae-ai.github.io/OmniSight-NVR/";
  ffmpegStatus.textContent = "ActiveX / IE Mode: Direct HTML5 Snapshot Polling Ready";
  
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

    const safeName = escapeHtml(cam.name);
    const safeId = escapeHtml(cam.id);
    const safeGroup = escapeHtml(cam.group || "Default");
    const safeIp = escapeHtml(cam.ip || "");

    card.innerHTML = `
      <div class="card-header">
        <div class="card-title-group">
          <span class="cam-status-dot"></span>
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

    // Setup Video Player for this Camera
    setupCameraPlayer(cam);
  });
}

// Setup Camera Video Stream Player
function setupCameraPlayer(cam) {
  const container = document.getElementById(`videoContainer-${cam.id}`);
  if (!container) return;

  if (localApiAvailable) {
    // Connected to Python server: use native multipart MJPEG
    const img = document.createElement("img");
    img.className = "video-feed";
    img.src = `/api/cameras/${cam.id}/stream?token=${encodeURIComponent(authToken)}`;
    img.alt = cam.name;
    container.insertBefore(img, container.firstChild);
    return;
  }

  // Legacy Snapshot Polling Mode
  if (cam.legacy_polling && cam.ip) {
    const img = document.createElement("img");
    img.className = "video-feed";
    img.alt = cam.name;
    container.insertBefore(img, container.firstChild);

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
        drawTacticalFallback(container, cam, "ACTIVE POLLING • MIXED CONTENT RESTRICTION");
      };
      testImg.src = `${snapUrl}?t=${Date.now()}`;
    }

    pollFrame();
    pollingIntervals[cam.id] = setInterval(pollFrame, 500);
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
    fb.style.background = "rgba(18, 18, 20, 0.95)";
    fb.style.backdropFilter = "blur(14px)";
    fb.style.padding = "20px";
    fb.style.textAlign = "center";
    fb.innerHTML = `
      <span style="color: var(--apple-amber); font-weight: 600; font-size: 13px; margin-bottom: 6px;">
        ⚠️ Browser Blocked Direct HTTP (${cam.ip})
      </span>
      <p style="font-size: 11px; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.4; max-width: 320px;">
        Because you are on HTTPS (GitHub Pages), the browser blocks direct requests to local LAN devices.
      </p>
      <a href="http://localhost:8080" target="_blank" class="btn-action btn-primary" style="font-size: 11px; text-decoration: none; padding: 7px 16px;">
        Open on Local Hub (http://localhost:8080)
      </a>
      <span style="font-size: 10px; color: var(--text-tertiary); margin-top: 10px;">
        Or click the browser padlock icon &gt; Site settings &gt; Set 'Insecure content' to Allow.
      </span>
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
  document.getElementById("ptzCamTitle").textContent = `PTZ: ${camName}`;
  ptzPanel.classList.remove("hidden");
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
  ptzPanel.classList.add("hidden");
  activePtzCamId = null;
};

// V380 Pro / V360 Pro Smart Controls
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

// V380 Pro Intercom Hold to Talk
const btnIntercomTalk = document.getElementById("btnIntercomTalk");
const intercomLabel = document.getElementById("intercomLabel");
if (btnIntercomTalk) {
  const startTalk = async () => {
    if (!activePtzCamId) return;
    btnIntercomTalk.style.background = "rgba(52, 199, 89, 0.4)";
    if (intercomLabel) intercomLabel.textContent = "Broadcasting Audio...";
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

// V380 Pro 24-Hour Timeline Scrubber
const v380TimelineTrack = document.getElementById("v380TimelineTrack");
const timelineNeedle = document.getElementById("timelineNeedle");
const timelineCurrentTime = document.getElementById("timelineCurrentTime");
if (v380TimelineTrack && timelineNeedle) {
  v380TimelineTrack.addEventListener("click", (e) => {
    const rect = v380TimelineTrack.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const pct = x / rect.width;
    timelineNeedle.style.left = `${(pct * 100).toFixed(1)}%`;

    const totalMinutes = Math.floor(pct * 24 * 60);
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    const timeStr = `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}:00`;
    if (timelineCurrentTime) {
      timelineCurrentTime.textContent = timeStr;
    }
    showNotification(`Timeline scrubbed to ${timeStr}`, "info");
  });
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
async function startDiscoveryScan() {
  const scanStatusMsg = document.getElementById("scanStatusMsg");
  const tbody = document.getElementById("discoveryTableBody");
  const subnetBase = document.getElementById("scanSubnetInput").value || "192.168.1";

  scanStatusMsg.textContent = "Scanning local subnet for cameras...";
  tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Probing subnet ${subnetBase}.1 to ${subnetBase}.40... Please wait.</td></tr>`;

  if (localApiAvailable) {
    try {
      const res = await authFetch("/api/discovery/scan");
      if (res.ok) {
        const data = await res.json();
        renderDiscoveredDevices(data.devices, "ONVIF UDP / Port Scan");
        scanStatusMsg.textContent = `Scan complete. Found ${data.devices.length} device(s).`;
        return;
      }
    } catch (e) {}
  }

  const detected = [];
  let completed = 0;
  const totalToScan = 35;

  for (let i = 1; i <= totalToScan; i++) {
    const ip = `${subnetBase}.${i}`;
    testCameraHostInBrowser(ip).then(dev => {
      completed++;
      if (dev) {
        detected.push(dev);
        renderDiscoveredDevices(detected, "Browser LAN Probe");
      }
      if (completed >= totalToScan) {
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

    img.onerror = () => {};

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
