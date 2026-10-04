"""
Tests for the dashboard's mixed-content guidance.

An HTTPS page (GitHub Pages) can never pull frames from a plain-http camera or
hub, and the escape hatches are wildly different per browser. The dashboard used
to tell everyone to "click the padlock > Site settings > Insecure content", which
is Chrome-only and simply does not exist in Safari or Firefox/Zen — so users on
those browsers were sent hunting for a setting that was never there.

These tests pin the corrected behaviour:

  1. The generic Chrome-only advice is gone from the blocked-camera banner.
  2. Both copies of the dashboard HTML ship the browser-aware help modal.
  3. Engine detection routes Zen/Firefox, Safari and Chromium correctly.
  4. Firefox/Zen and Safari are reported as having no site-level toggle, while
     Chromium points at the settings URL rather than the padlock popover.
  5. The README documents the same matrix.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(REPO_ROOT, "static", "js", "app.js")
README = os.path.join(REPO_ROOT, "README.md")
# index.html (GitHub Pages) and static/index.html (served by the hub) are kept
# byte-identical; the modal must be present in both or one surface breaks.
HTML_COPIES = [
    os.path.join(REPO_ROOT, "index.html"),
    os.path.join(REPO_ROOT, "static", "index.html"),
]

NODE = shutil.which("node")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_function(source, name):
    """Slice a top-level ``function name(...) {...}`` out of app.js by brace depth."""
    start = source.index("function %s(" % name)
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
                return source[start:offset + 1]
    raise AssertionError("unbalanced braces while extracting %s" % name)


class TestChromeOnlyAdviceRemoved(unittest.TestCase):
    def test_banner_no_longer_promises_a_padlock_toggle(self):
        source = read(APP_JS)
        banner = extract_function(source, "drawTacticalFallback")

        self.assertNotIn("Site settings", banner)
        self.assertNotIn("padlock", banner.lower())
        # The advice now lives behind a browser-aware help modal instead.
        self.assertIn("openMixedContentHelp", banner)

    def test_banner_links_the_real_hub_origin_not_hardcoded_localhost(self):
        source = read(APP_JS)
        banner = extract_function(source, "drawTacticalFallback")

        # A hardcoded http://localhost:8080 is wrong whenever the hub runs on
        # another machine (192.168.x.x, Tailscale, a tunnel).
        self.assertNotIn("http://localhost:8080", banner)
        self.assertIn("resolveHubOrigin()", banner)

    def test_hub_origin_prefers_a_saved_hub_over_localhost(self):
        source = read(APP_JS)
        resolver = extract_function(source, "resolveHubOrigin")

        self.assertIn("getSavedHubUrl()", resolver)
        self.assertIn("hubBaseUrl", resolver)
        # loopback remains the last-resort default
        self.assertIn("http://localhost:8080", resolver)


class TestHelpModalIsShipped(unittest.TestCase):
    def test_both_html_copies_carry_the_modal(self):
        for path in HTML_COPIES:
            with self.subTest(html=os.path.relpath(path, REPO_ROOT)):
                markup = read(path)
                self.assertIn('id="mixedContentModal"', markup)
                self.assertIn('id="btnCloseMixedContentModal"', markup)
                self.assertIn('id="mcBrowserSteps"', markup)
                self.assertIn('data-mc-hub-link', markup)
                self.assertIn('data-open-mixed-content-help', markup)

    def test_html_copies_stay_in_sync(self):
        digests = {hashlib.sha256(read(p).encode("utf-8")).hexdigest() for p in HTML_COPIES}
        self.assertEqual(len(digests), 1, "index.html and static/index.html have drifted apart")

    def test_modal_is_wired_to_open_and_close(self):
        source = read(APP_JS)
        self.assertIn('getElementById("btnCloseMixedContentModal")', source)
        self.assertIn("function openMixedContentHelp(", source)
        self.assertIn("function populateMixedContentHelp(", source)


@unittest.skipUnless(NODE, "node is required to execute the browser helpers")
class TestBrowserDetectionAndGuidance(unittest.TestCase):
    """Run the real helpers under node with stubbed browser globals."""

    USER_AGENTS = {
        # Zen Desktop is Firefox-based -> Gecko, no site permission exists.
        "zen": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0",
        "safari_macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        ),
        "safari_ios": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        ),
        # Firefox for iOS is WebKit under the hood: about:config does not exist.
        "firefox_ios": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) FxiOS/130.0 Mobile/15E148 Safari/605.1.15"
        ),
        "chrome": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "edge": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
        ),
        "brave": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Brave"
        ),
    }

    EXPECTED_ENGINE = {
        "zen": "gecko",
        "firefox": "gecko",
        "safari_macos": "webkit",
        "safari_ios": "webkit",
        "firefox_ios": "webkit",
        "chrome": "chromium",
        "edge": "chromium",
        "brave": "chromium",
    }

    def run_helpers(self, user_agent, saved_hub=""):
        source = read(APP_JS)
        helpers = "\n\n".join(
            extract_function(source, name)
            for name in ("detectBrowserEngine", "resolveHubOrigin", "mixedContentBrowserSteps")
        )
        script = (
            helpers
            + "\nconsole.log(JSON.stringify({"
            + "engine: detectBrowserEngine(),"
            + "hub: resolveHubOrigin(),"
            + "steps: mixedContentBrowserSteps()}));"
        )
        # Stub the browser globals the helpers touch, then dump their result.
        runner = (
            "const navigator = { userAgent: %r };\n"
            "const getSavedHubUrl = () => %r;\n"
            "let hubBaseUrl = '';\n" % (user_agent, saved_hub)
        ) + script

        with tempfile.TemporaryDirectory() as tmp:
            script_path = os.path.join(tmp, "helpers.js")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(runner)
            completed = subprocess.run(
                [NODE, script_path], capture_output=True, text=True, timeout=30
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        import json

        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_engine_detection(self):
        for label, user_agent in self.USER_AGENTS.items():
            with self.subTest(browser=label):
                result = self.run_helpers(user_agent)
                self.assertEqual(result["engine"], self.EXPECTED_ENGINE[label])

    def test_zen_and_safari_are_told_there_is_no_toggle(self):
        for label in ("zen", "safari_macos", "safari_ios", "firefox_ios"):
            with self.subTest(browser=label):
                steps = self.run_helpers(self.USER_AGENTS[label])["steps"]
                self.assertFalse(
                    steps["hasToggle"],
                    "%s has no 'Insecure content' site setting; guidance must not imply one" % label,
                )
                self.assertTrue(steps["steps"], "guidance must offer at least one actionable step")

    def test_zen_guidance_names_the_pref_that_actually_blocks_snapshots(self):
        steps = self.run_helpers(self.USER_AGENTS["zen"])["steps"]
        blob = " ".join(steps["steps"])
        # Firefox 127+ / Zen auto-upgrade http images to https and block them on
        # failure, so block_active_content alone does not fix a blank camera.
        self.assertIn("security.mixed_content.upgrade_display_content", blob)
        self.assertIn("security.mixed_content.block_active_content", blob)
        self.assertIn("about:config", blob)

    def test_safari_guidance_does_not_send_users_to_a_missing_setting(self):
        steps = self.run_helpers(self.USER_AGENTS["safari_macos"])["steps"]
        blob = " ".join(steps["steps"]) + steps["intro"]
        self.assertIn("no user-facing setting", blob.replace("<strong>", "").replace("</strong>", ""))
        # The reliable escape hatches must both be offered.
        self.assertIn("hub URL", blob)

    def test_chromium_guidance_gives_a_direct_settings_url(self):
        steps = self.run_helpers(self.USER_AGENTS["chrome"])["steps"]
        blob = " ".join(steps["steps"])
        self.assertTrue(steps["hasToggle"])
        # The padlock popover is exactly what users cannot find, so point at the
        # canonical settings page instead.
        self.assertIn("chrome://settings/content/insecureContent", blob)
        self.assertIn("siteDetails", blob)
        self.assertIn("unsafely-treat-insecure-origin-as-secure", blob)

    def test_saved_hub_beats_the_loopback_default(self):
        result = self.run_helpers(self.USER_AGENTS["chrome"], saved_hub="http://192.168.1.50:8080")
        self.assertEqual(result["hub"], "http://192.168.1.50:8080")

    def test_defaults_to_loopback_when_no_hub_is_saved(self):
        result = self.run_helpers(self.USER_AGENTS["chrome"])
        self.assertEqual(result["hub"], "http://localhost:8080")


class TestReadmeDocumentsTheMatrix(unittest.TestCase):
    def test_readme_covers_each_browser_family(self):
        text = read(README)
        self.assertRegex(text, r"####\s+Mixed content")

        for needle in (
            "Insecure content",
            "Zen Browser",
            "Safari",
            "chrome://settings/content/insecureContent",
            "security.mixed_content.upgrade_display_content",
            "security.mixed_content.block_active_content",
            "tailscale funnel",
            "trycloudflare.com",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_readme_explains_why_the_padlock_advice_fails(self):
        text = read(README)
        section = text.split("#### Mixed content", 1)[1]
        # Cut at the next heading so we only judge this section.
        section = re.split(r"\n####\s", section, maxsplit=1)[0]
        self.assertIn("Chrome-only", section)
        self.assertIn("does not exist in Safari", section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
