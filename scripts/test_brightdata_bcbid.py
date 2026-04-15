"""Minimal BCBid test using Bright Data Scraping Browser (cloud Playwright via CDP WebSocket).

Run: python scripts/test_brightdata_bcbid.py
Env: BRIGHT_DATA_WS_CDP (required), BCBID_SESSION (optional)
     BRIGHT_DATA_WS_CDP format: wss://brd-customer-{ID}-zone-{ZONE}:{PASS}@brd.superproxy.io:9222

What this tests: Bright Data's Scraping Browser runs Chromium entirely in their
cloud infrastructure with their own residential IPs and managed fingerprinting.
Connecting via connect_over_cdp() means zero local browser — the browser fingerprint
and IP both come from Bright Data, not from the GitHub Actions runner.

How it differs from test_proxy_bcbid.py: the proxy test runs Chromium locally
through a proxy (runner fingerprint + residential IP). This test uses Bright Data's
own browser (their fingerprint + their IP).

Pre-requisite: Bright Data account → create a "Scraping Browser" zone →
copy the WebSocket CDP endpoint URL → add as BRIGHT_DATA_WS_CDP GitHub Actions secret.
"""
import base64
import os
import tempfile

from playwright.sync_api import sync_playwright  # standard Playwright, not patchright

SEARCH_TERMS = ["data", "analytics"]
BASE = "https://www.bcbid.gov.bc.ca"
BROWSE_URL = f"{BASE}/page.aspx/en/rfp/request_browse_public"


def _load_session():
    session_env = os.environ.get("BCBID_SESSION", "").strip()
    if not session_env:
        return None
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    tf.write(base64.b64decode(session_env).decode())
    tf.close()
    return tf.name


def run():
    ws_cdp = os.environ.get("BRIGHT_DATA_WS_CDP", "").strip()
    if not ws_cdp:
        print("ERROR: BRIGHT_DATA_WS_CDP env var not set — skipping test")
        print("Set up a Scraping Browser zone at brightdata.com and add the WS endpoint as a secret.")
        return

    session_path = _load_session()

    # Log endpoint host only — never log credentials
    safe_endpoint = ws_cdp.split("@")[-1] if "@" in ws_cdp else ws_cdp
    print("=== BCBid Bright Data Scraping Browser Test ===")
    print(f"Endpoint: {safe_endpoint}")
    print(f"Session: {'loaded' if session_path else 'none (cold start)'}")

    with sync_playwright() as pw:
        # connect_over_cdp replaces launch() — browser runs in Bright Data's cloud
        browser = pw.chromium.connect_over_cdp(ws_cdp)
        ctx_kwargs = {}
        if session_path:
            # Bright Data supports storage_state injection via new_context()
            ctx_kwargs["storage_state"] = session_path

        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        print("Navigating to home page...")
        page.goto(BASE, timeout=60000)
        print(f"Home URL: {page.url}")
        if "browser_check" in page.url:
            print("FAIL: browser_check gate on home page — Bright Data fingerprint not trusted by BCBid")
            browser.close()
            return

        print("Navigating to browse page...")
        page.goto(BROWSE_URL, timeout=60000)
        print(f"Browse URL: {page.url}")
        if "browser_check" in page.url:
            print("FAIL: browser_check gate on browse page")
            browser.close()
            return

        print("Waiting for iV overlay to clear...")
        try:
            page.wait_for_selector("body:not([aria-busy='true'])", timeout=30000)
            page.wait_for_selector("input#body_x_txtQuery", state="visible", timeout=30000)
            print("SUCCESS: search box visible — iV cleared")
        except Exception as e:
            print(f"FAIL: search box not found — {e}")
            browser.close()
            return

        for term in SEARCH_TERMS:
            try:
                page.fill("input#body_x_txtQuery", term)
                page.keyboard.press("Enter")
                page.wait_for_selector("a[href*='process_manage_extranet']", timeout=15000)
                links = page.query_selector_all("a[href*='process_manage_extranet']")
                print(f"'{term}': {len(links)} listing(s)")
            except Exception as e:
                print(f"'{term}': FAIL — {e}")
            page.goto(BROWSE_URL, timeout=60000)
            page.wait_for_timeout(2000)

        browser.close()
    print("=== Done ===")


run()
