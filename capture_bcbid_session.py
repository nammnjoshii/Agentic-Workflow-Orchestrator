"""capture_bcbid_session.py — One-shot helper to save a valid BCBid browser session.

BCBid deploys an IntelligenceView (iV) fingerprinting gate that blocks headless
Chromium even with patchright's automation-signal masking.  Running with a
visible (headful) browser passes the gate naturally, because iV cannot
distinguish a real Chrome window from automation in that mode.

This script:
  1. Launches a headful patchright Chromium window.
  2. Warms up the session on BCBid's home page (sets fingerprint cookies).
  3. Navigates to the browse page to ensure full session state is captured.
  4. Writes the browser context's storage_state (cookies + localStorage) to
     bcbid_session.json at the project root.

The existing scrape_bcbid() function in procurement_intelligence_specialist.py
automatically loads bcbid_session.json when present (lines 1132-1137), so no
scraper changes are needed.  The session typically stays valid for days.

Usage:
    python3 capture_bcbid_session.py

Output:
    bcbid_session.json  (project root)

After running, re-execute the pipeline:
    DRY_RUN=false python3 main.py
"""

import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE = "https://www.bcbid.gov.bc.ca"
BROWSE_URL = f"{BASE}/page.aspx/en/rfp/request_browse_public"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "bcbid_session.json")


def main():
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        logger.error("patchright not installed. Run: pip3 install patchright && python3 -m patchright install chromium")
        sys.exit(1)

    logger.info("Launching headful Chromium (a browser window will open)…")

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
        )
        page = ctx.new_page()

        # Step 1: Home page warm-up — BCBid sets initial fingerprint cookies here.
        logger.info("Navigating to BCBid home page…")
        try:
            page.goto(BASE, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as exc:
            logger.warning("Home page load did not reach networkidle: %s", exc)

        if "browser_check" in page.url:
            logger.info("browser_check gate on home page — waiting for it to pass (up to 90s)…")
            try:
                page.wait_for_url(lambda u: "browser_check" not in u, timeout=90000)
                page.wait_for_load_state("networkidle", timeout=15000)
                logger.info("browser_check cleared → %s", page.url)
            except Exception:
                logger.warning("browser_check did not clear on home page — continuing anyway")

        logger.info("Home page loaded: %s", page.url)
        time.sleep(2)

        # Step 2: Browse page — ensures the search session state is captured too.
        logger.info("Navigating to BCBid browse (search) page…")
        try:
            page.goto(BROWSE_URL, timeout=45000)
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as exc:
            logger.warning("Browse page load did not reach networkidle: %s", exc)

        if "browser_check" in page.url:
            logger.info("browser_check gate on browse page — waiting up to 90s…")
            try:
                page.wait_for_url(lambda u: "browser_check" not in u, timeout=90000)
                page.wait_for_load_state("networkidle", timeout=15000)
                logger.info("browser_check cleared → %s", page.url)
            except Exception:
                logger.warning("browser_check did not clear on browse page — continuing anyway")

        logger.info("Browse page loaded: %s", page.url)
        time.sleep(2)

        # Step 3: Save storage state (cookies + localStorage).
        ctx.storage_state(path=SESSION_PATH)
        browser.close()

    logger.info("Session saved to: %s", SESSION_PATH)
    logger.info("You can now run the full pipeline:")
    logger.info("  DRY_RUN=false python3 main.py")


if __name__ == "__main__":
    main()
