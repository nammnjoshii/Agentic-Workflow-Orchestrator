"""Minimal BCBid test using patchright + residential proxy.

Run: python scripts/test_proxy_bcbid.py
Env: BCBID_SESSION (optional), BCBID_PROXY_URL (required for proxy path)
     BCBID_PROXY_URL format: http://user:pass@host:port

What this tests: whether the existing patchright fingerprint passes BCBid's gates
when requests originate from a residential IP instead of a GitHub Actions AWS
datacenter IP. If this passes but the regular bcbid_scrape.yml fails, the blocker
is IP reputation rather than browser fingerprinting.

Pre-requisite: add BCBID_PROXY_URL as a GitHub Actions secret.
Webshare (webshare.io) offers a free 1 GB/month residential proxy tier.
"""
import base64
import os
import tempfile

from patchright.sync_api import sync_playwright

SEARCH_TERMS = ["data", "analytics"]
BASE = "https://www.bcbid.gov.bc.ca"
BROWSE_URL = f"{BASE}/page.aspx/en/rfp/request_browse_public"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _load_session():
    session_env = os.environ.get("BCBID_SESSION", "").strip()
    if not session_env:
        return None
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    tf.write(base64.b64decode(session_env).decode())
    tf.close()
    return tf.name


def run():
    proxy_url = os.environ.get("BCBID_PROXY_URL", "").strip()
    session_path = _load_session()

    print("=== BCBid Proxy+Patchright Test ===")
    # Log proxy host only — never log credentials
    if proxy_url:
        proxy_host = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        print(f"Proxy: {proxy_host}")
    else:
        print("Proxy: NONE (direct connection — no BCBID_PROXY_URL set)")
    print(f"Session: {'loaded' if session_path else 'none (cold start)'}")

    ctx_kwargs = {"viewport": {"width": 1366, "height": 768}, "user_agent": USER_AGENT}
    if session_path:
        ctx_kwargs["storage_state"] = session_path
    if proxy_url:
        ctx_kwargs["proxy"] = {"server": proxy_url}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        print("Navigating to home page...")
        page.goto(BASE, timeout=30000)
        print(f"Home URL: {page.url}")
        if "browser_check" in page.url:
            print("FAIL: browser_check gate on home page — patchright CDP patches not working")
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
            page.goto(BROWSE_URL, timeout=30000)
            page.wait_for_timeout(2000)

        browser.close()
    print("=== Done ===")


run()
