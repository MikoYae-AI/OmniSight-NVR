"""
Regression tests for browser Local Network Access prompt glitching.

Why the browser's "access to the local network" prompt used to glitch:
  1. On startup, `detectBackend()` probed both `http://localhost:8080` and
     `http://127.0.0.1:8080` even on public HTTPS origins (GitHub Pages) with
     no configured hub, triggering back-to-back loopback permission prompts.
  2. Immediately after startup, `setupCameraPlayer()` started an overlapping
     `setInterval(pollFrame, 500)` loop for every `legacy_polling` camera
     (192.168.1.13, 192.168.1.10, 192.168.1.102) that never cleared its interval
     on error — hammering private LAN IPs 6 times per second forever while
     Chromium auto-upgraded `http://` image loads to `https://`.
  3. Clicking "Run Network Scan" in `startDiscoveryScan()` launched 35 parallel
     `new Image()` requests to 35 distinct private IP origins in a single tick
     while `permission.state` was still `"prompt"`, causing the prompt to
     flicker/re-open across all 35 requests.
  4. The Python hub omitted `Access-Control-Allow-Private-Network: true` on CORS
     preflights and API responses.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(REPO_ROOT, "static", "js", "app.js")
NODE = shutil.which("node")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_function(source, name):
    """Slice a top-level `[async ]function name(...) {...}` out of app.js by brace depth."""
    for prefix in (f"async function {name}(", f"function {name}("):
        idx = source.find(prefix)
        if idx != -1:
            start = idx
            break
    else:
        raise AssertionError(f"function {name} not found in app.js")

    depth = 0
    opened = False
    for offset in range(start, len(source)):
        char = source[offset]
        if char == "{":
            depth += 1
            opened = True
        elif char == "}":
            depth -= 1
            if opened and depth == 0:
                return source[start : offset + 1]
    raise AssertionError(f"unbalanced braces while extracting {name}")


@unittest.skipUnless(NODE, "node is required to execute browser helpers")
class TestLocalNetworkPromptStability(unittest.TestCase):
    def run_node_json(self, js_code):
        with tempfile.TemporaryDirectory() as tmp:
            script_path = os.path.join(tmp, "check.js")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(js_code)
            completed = subprocess.run(
                [NODE, script_path], capture_output=True, text=True, timeout=30
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_startup_does_not_probe_loopback_on_public_https_without_saved_hub(self):
        source = read(APP_JS)
        helpers = "\n\n".join(
            extract_function(source, name)
            for name in ("isLoopbackUrl", "isPageOnLocalOrigin", "buildStartupHubCandidates")
        )
        script = f"""
        const window = {{ location: {{ href: "https://mikoyae-ai.github.io/OmniSight-NVR/", hostname: "mikoyae-ai.github.io", protocol: "https:" }} }};
        const IS_GITHUB_PAGES = true;
        const getSavedHubUrl = () => "";
        {helpers}
        const promptCandidates = buildStartupHubCandidates({{
          isGithubPages: true,
          savedHub: "",
          permissionState: "prompt",
          localOrigin: false,
          pageProtocol: "https:"
        }});
        const deniedCandidates = buildStartupHubCandidates({{
          isGithubPages: false,
          savedHub: "http://localhost:8080",
          permissionState: "denied",
          localOrigin: false,
          pageProtocol: "https:"
        }});
        const grantedCandidates = buildStartupHubCandidates({{
          isGithubPages: true,
          savedHub: "",
          permissionState: "granted",
          localOrigin: false,
          pageProtocol: "https:"
        }});
        const mixedSavedCandidates = buildStartupHubCandidates({{
          isGithubPages: true,
          savedHub: "http://192.168.1.50:8080",
          permissionState: "granted",
          localOrigin: false,
          pageProtocol: "https:"
        }});
        const tunnelSavedCandidates = buildStartupHubCandidates({{
          isGithubPages: true,
          savedHub: "https://demo.trycloudflare.com",
          permissionState: "prompt",
          localOrigin: false,
          pageProtocol: "https:"
        }});
        console.log(JSON.stringify({{
          promptCandidates,
          deniedCandidates,
          grantedCandidates,
          mixedSavedCandidates,
          tunnelSavedCandidates
        }}));
        """
        result = self.run_node_json(script)
        self.assertEqual(
            result["promptCandidates"],
            [],
            "Public HTTPS startup must not fire unsolicited localhost probes when permission is 'prompt'",
        )
        self.assertEqual(
            result["deniedCandidates"],
            [""],
            "Denied permission must only allow same-origin check, never cross-origin local probes",
        )
        self.assertEqual(
            result["grantedCandidates"],
            ["http://localhost:8080"],
            "When permission is already granted, only a single loopback origin is probed",
        )
        self.assertEqual(
            result["mixedSavedCandidates"],
            [],
            "HTTPS page must not fetch a plain-HTTP private LAN hub URL that mixed-content rules block",
        )
        self.assertEqual(
            result["tunnelSavedCandidates"],
            ["https://demo.trycloudflare.com"],
            "Saved HTTPS tunnel hub URL is probed on startup",
        )

    def test_camera_player_never_uses_unstoppable_setinterval_for_pollframe(self):
        source = read(APP_JS)
        player_fn = extract_function(source, "setupCameraPlayer")
        self.assertNotIn(
            "setInterval(pollFrame",
            player_fn,
            "setupCameraPlayer must not run an overlapping setInterval(pollFrame, 500) loop",
        )

    def test_camera_player_skips_direct_http_probes_on_https_and_stops_on_error(self):
        source = read(APP_JS)
        player_fn = extract_function(source, "setupCameraPlayer")
        script = f"""
        let imageRequests = [];
        let fallbackCalls = 0;
        let activeBrowserNodeCamId = "node-browser-cam";
        let activeBrowserNodeStream = null;
        let latestBrowserNodeFrame = null;
        let localApiAvailable = false;
        let authToken = "";
        let pollingIntervals = {{}};
        const apiUrl = (p) => p;
        const setCameraStatusDot = () => {{}};
        const drawTacticalFallback = () => {{ fallbackCalls += 1; }};
        const startCanvasSimulation = () => {{}};
        const queryBrowserLocalNetworkPermission = async () => ({{ state: "prompt" }});

        class FakeImage {{
          set src(val) {{
            if (val) {{
              imageRequests.push(val);
              if (this.onerror) this.onerror();
            }}
          }}
        }}
        global.Image = FakeImage;

        function makeContainer() {{
          return {{
            isConnected: true,
            firstChild: null,
            children: [],
            insertBefore(el) {{ this.children.push(el); }},
            querySelector() {{ return null; }}
          }};
        }}

        const containers = {{
          "cam-https": makeContainer(),
          "cam-http": makeContainer()
        }};
        const document = {{
          getElementById(id) {{
            if (id === "videoContainer-cam-https") return containers["cam-https"];
            if (id === "videoContainer-cam-http") return containers["cam-http"];
            return null;
          }},
          createElement(tag) {{
            return {{ tagName: tag, style: {{}}, className: "" }};
          }}
        }};

        let window = {{ location: {{ protocol: "https:" }} }};
        {player_fn}

        // 1. On HTTPS, zero Image requests should be fired for plain-HTTP legacy cameras.
        setupCameraPlayer({{
          id: "cam-https",
          name: "Hikvision",
          vendor: "hikvision",
          ip: "192.168.1.13",
          channel: 1,
          legacy_polling: true
        }});
        const httpsRequests = imageRequests.length;
        const httpsFallbacks = fallbackCalls;

        // 2. On HTTP, candidate URLs are tried once sequentially and then stop (no interval).
        window.location.protocol = "http:";
        setupCameraPlayer({{
          id: "cam-http",
          name: "Hikvision",
          vendor: "hikvision",
          ip: "192.168.1.13",
          channel: 1,
          legacy_polling: true
        }});

        setTimeout(() => {{
          console.log(JSON.stringify({{
            httpsRequests,
            httpsFallbacks,
            httpRequests: imageRequests.length,
            totalFallbacks: fallbackCalls,
            activeTimers: Object.keys(pollingIntervals).length
          }}));
        }}, 50);
        """
        result = self.run_node_json(script)
        self.assertEqual(result["httpsRequests"], 0, "HTTPS page must not spam LAN camera IPs on load")
        self.assertEqual(result["httpsFallbacks"], 1)
        self.assertEqual(result["httpRequests"], 3, "HTTP mode should try the 3 unique candidate paths once and stop")
        self.assertEqual(result["totalFallbacks"], 2)
        self.assertEqual(result["activeTimers"], 0, "Failed camera poll must clear timers and stop completely")

    def test_discovery_scan_sends_single_probe_while_permission_is_prompt(self):
        source = read(APP_JS)
        fns = "\n\n".join(
            extract_function(source, name)
            for name in (
                "queryBrowserLocalNetworkPermission",
                "isPrivateIpv4SubnetBase",
                "showBrowserNetworkPermissionDenied",
                "testCameraHostInBrowser",
                "startDiscoveryScan",
            )
        )
        script = f"""
        let probedUrls = [];
        let permissionState = "prompt";
        let listeners = [];
        const permissionObj = {{
          get state() {{ return permissionState; }},
          addEventListener(type, fn) {{ if (type === "change") listeners.push(fn); }},
          removeEventListener(type, fn) {{ listeners = listeners.filter(f => f !== fn); }}
        }};
        const navigator = {{
          permissions: {{
            query: async () => permissionObj
          }}
        }};
        const window = {{ isSecureContext: true }};
        let localApiAvailable = false;
        let discoveryScanInProgress = false;
        let discoveryPermissionCleanup = null;
        const showNotification = () => {{}};
        const renderDiscoveredDevices = () => {{}};

        class FakeImage {{
          set src(val) {{
            if (val) {{
              probedUrls.push(val);
              if (this.onerror) setImmediate(() => this.onerror && this.onerror());
            }}
          }}
        }}
        global.Image = FakeImage;

        const elements = {{
          scanStatusMsg: {{ textContent: "" }},
          discoveryTableBody: {{ innerHTML: "" }},
          btnStartScan: {{ disabled: false }},
          scanSubnetInput: {{ value: "192.168.1" }}
        }};
        const document = {{
          getElementById(id) {{ return elements[id] || null; }}
        }};

        {fns}

        (async () => {{
          // 1. When permission stays "prompt" (prompt open or dismissed), only .1 is probed!
          await startDiscoveryScan();
          const countWhilePrompt = probedUrls.length;
          const statusWhilePrompt = elements.scanStatusMsg.textContent;

          // 2. When the user clicks Allow (permission transitions to "granted"), the rest of the subnet is scanned.
          probedUrls = [];
          permissionState = "granted";
          await startDiscoveryScan();
          const countWhenGranted = probedUrls.length;

          // 3. When permission is "denied", zero probes are sent.
          probedUrls = [];
          permissionState = "denied";
          await startDiscoveryScan();
          const countWhenDenied = probedUrls.length;

          console.log(JSON.stringify({{
            countWhilePrompt,
            statusWhilePrompt,
            countWhenGranted,
            countWhenDenied
          }}));
        }})();
        """
        result = self.run_node_json(script)
        self.assertEqual(
            result["countWhilePrompt"],
            1,
            "While permission is 'prompt', only a single host (.1) may be probed to avoid glitching the browser prompt",
        )
        self.assertIn("Waiting for Local Network permission", result["statusWhilePrompt"])
        self.assertEqual(result["countWhenGranted"], 35)
        self.assertEqual(result["countWhenDenied"], 0)


class TestPrivateNetworkAccessHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.server import OmniSightHandler

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), OmniSightHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_options_and_status_include_allow_private_network_header(self):
        req_opt = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/status",
            method="OPTIONS",
            headers={"Access-Control-Request-Private-Network": "true"},
        )
        with urllib.request.urlopen(req_opt, timeout=5) as resp:
            self.assertEqual(resp.headers.get("Access-Control-Allow-Private-Network"), "true")
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

        req_get = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/status")
        with urllib.request.urlopen(req_get, timeout=5) as resp:
            self.assertEqual(resp.headers.get("Access-Control-Allow-Private-Network"), "true")


if __name__ == "__main__":
    unittest.main(verbosity=2)
