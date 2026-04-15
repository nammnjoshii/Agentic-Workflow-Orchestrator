"""Minimal BCBid test using nodriver (direct CDP, no Playwright layer).

Run: python scripts/test_nodriver_bcbid.py
Env: BCBID_SESSION (optional base64 storage_state JSON)

What this tests: nodriver connects directly to Chrome's DevTools Protocol without
any Playwright abstraction layer. Different fingerprint surface — BCBid's iV may
not recognise it as automation.

Note on async: nodriver is async-only. scripts/ is not part of the main pipeline
so async/await is permitted here (the no-async rule applies to src/ agents only).
"""
import asyncio
import base64
import json
import os

SEARCH_TERMS = ["data", "analytics"]
BASE = "https://www.bcbid.gov.bc.ca"
BROWSE_URL = f"{BASE}/page.aspx/en/rfp/request_browse_public"


def _load_session_cookies():
    session_env = os.environ.get("BCBID_SESSION", "").strip()
    if not session_env:
        return []
    try:
        state = json.loads(base64.b64decode(session_env).decode())
        return state.get("cookies", [])
    except Exception as e:
        print(f"[WARN] Could not parse BCBID_SESSION: {e}")
        return []


async def run():
    import nodriver  # installed only in test workflow, not main requirements.txt

    print("=== BCBid Nodriver Test ===")
    import shutil
    chrome_bin = (
        shutil.which("google-chrome-stable")
        or shutil.which("google-chrome")
        or shutil.which("chromium-browser")
        or shutil.which("chromium")
    )
    print(f"Chrome binary: {chrome_bin}")
    if not chrome_bin:
        print("ERROR: no Chrome binary found in PATH — cannot start nodriver")
        return
    browser = await nodriver.start(
        headless=True,
        sandbox=False,
        browser_executable_path=chrome_bin,
        browser_args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    try:
        tab = await browser.get(BASE)
        print(f"Home URL: {tab.url}")

        # Inject session cookies if available (nodriver doesn't support storage_state)
        cookies = _load_session_cookies()
        if cookies:
            for ck in cookies:
                await tab.set_cookie(
                    name=ck["name"],
                    value=ck["value"],
                    domain=ck.get("domain", ".bcbid.gov.bc.ca"),
                    path=ck.get("path", "/"),
                )
            print(f"Injected {len(cookies)} session cookies")
        else:
            print("No session cookies — cold start")

        await tab.get(BROWSE_URL)
        print(f"Browse URL: {tab.url}")

        if "browser_check" in tab.url:
            print("FAIL: stuck on browser_check gate — fingerprint not trusted")
            return

        # Wait for search box (up to 30s, 5s per attempt)
        search_box = None
        for attempt in range(6):
            try:
                search_box = await tab.find("input#body_x_txtQuery", timeout=5)
                print(f"SUCCESS: search box found (attempt {attempt + 1})")
                break
            except Exception:
                print(f"Attempt {attempt + 1}: search box not visible yet...")
                await asyncio.sleep(5)

        if search_box is None:
            print("FAIL: search box not found after 30s — iV overlay may still be active")
            return

        # Run 2 keyword searches
        for term in SEARCH_TERMS:
            await search_box.send_keys(term)
            await search_box.send_keys("\n")
            await asyncio.sleep(4)

            links = await tab.find_all("a[href*='process_manage_extranet']")
            print(f"'{term}': {len(links)} listing(s) found")

            # Reset for next search
            await tab.get(BROWSE_URL)
            await asyncio.sleep(2)
            try:
                search_box = await tab.find("input#body_x_txtQuery", timeout=15)
            except Exception:
                print(f"Search box lost after '{term}' search — stopping")
                break

        print("=== Done ===")

    finally:
        await browser.stop()


asyncio.run(run())
