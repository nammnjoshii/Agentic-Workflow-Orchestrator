"""One-time local script to capture a valid BCBid browser session.

Run this locally (NOT in CI) when BCBid's browser_check starts blocking the
automated scraper.  It opens a headed browser so you can watch the check pass,
then saves the resulting cookies and storage state to bcbid_session.json.

Usage
-----
    python scripts/capture_bcbid_session.py

After it exits, two things happen:
  1. bcbid_session.json is written in the repo root (git-ignored).
  2. A base64-encoded string is printed to the terminal.

Copy that base64 string and paste it as the value of the GitHub Actions secret
named BCBID_SESSION (Settings → Secrets and variables → Actions → New secret).

The session typically lasts 7–30 days.  Re-run this script when the scraper
starts failing with browser_check again.
"""

import base64
import json
import os
import sys

BCBID_BROWSE = "https://www.bcbid.gov.bc.ca/page.aspx/en/rfp/request_browse_public"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "bcbid_session.json")


def main():
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: patchright not installed. Run: pip install patchright && python -m patchright install chromium")
        sys.exit(1)

    print("Launching headed browser — BCBid will open in a new window.")
    print("Wait for the browser_check to pass automatically (the page will redirect).")
    print("Once you see the BC Bid search page, press Enter here to save the session.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            no_viewport=True,
        )
        page = ctx.new_page()

        print(f"Navigating to: {BCBID_BROWSE}")
        try:
            page.goto(BCBID_BROWSE, timeout=120000)
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass  # timeout OK — user may still be watching

        current = page.url
        if "browser_check" in current:
            print(f"\nBrowser check detected ({current}).")
            print("Waiting for it to redirect automatically…")
            try:
                page.wait_for_url(lambda u: "browser_check" not in u, timeout=120000)
                page.wait_for_load_state("networkidle", timeout=15000)
                print(f"Redirected to: {page.url}")
            except Exception:
                print("Did not auto-redirect. You may need to interact with the page.")

        input("\nPress Enter to save the session and exit…")

        # Save storage state (cookies + localStorage)
        session_path = os.path.abspath(SESSION_FILE)
        ctx.storage_state(path=session_path)
        print(f"\nSession saved to: {session_path}")

        browser.close()

    # Read and base64-encode for GitHub secret
    with open(session_path, "r") as f:
        raw = f.read()

    encoded = base64.b64encode(raw.encode()).decode()
    print("\n" + "=" * 60)
    print("BCBID_SESSION GitHub secret value (copy everything below):")
    print("=" * 60)
    print(encoded)
    print("=" * 60)
    print("\nPaste this as the BCBID_SESSION secret in:")
    print("GitHub → Settings → Secrets and variables → Actions → New secret")
    print("\nDone.")


if __name__ == "__main__":
    main()
