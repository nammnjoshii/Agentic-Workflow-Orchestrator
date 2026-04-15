import concurrent.futures
import io
import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from src.database import filter_new_urls, filter_hash_duplicates, upsert_raw_listings

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Keywords used to filter relevant opportunities on portals that require keyword search
_PROCUREMENT_KEYWORDS = [
    "data analytics", "data science", "business intelligence",
    "machine learning", "artificial intelligence", "analytics platform",
    "data engineering", "data governance", "data integration",
    "cloud data", "data warehouse", "reporting platform", "ETL",
]

_FIXTURE_LISTINGS = [
    {
        "title": "Data Analytics Platform Modernisation",
        "org": "BC Hydro",
        "deadline": "2026-06-01",
        "value": "$500,000",
        "url": "https://fixture.example.com/rfp/1",
        "source": "MERX",
        "raw_description": "Seeking a vendor to modernise the enterprise data analytics platform using Snowflake and Power BI.",
    },
    {
        "title": "Business Intelligence Dashboard Development",
        "org": "City of Vancouver",
        "deadline": "2026-05-15",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/2",
        "source": "CanadaBuys",
        "raw_description": "Development of BI dashboards using Tableau or Power BI for city operations reporting.",
    },
    {
        "title": "Data Science and Analytics Services",
        "org": "State of California",
        "deadline": "2026-05-30",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/3",
        "source": "BidNet",
        "raw_description": "Seeking data science and analytics consulting services for state government agencies.",
    },
    {
        "title": "Enterprise Data Governance and Analytics Platform",
        "org": "SaskBuilds and Procurement",
        "deadline": "2026-06-15",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/4",
        "source": "SaskTenders",
        "raw_description": "RFP for enterprise data governance framework and analytics platform implementation.",
    },
    {
        "title": "Data Integration and Business Intelligence Services",
        "org": "Government of Alberta",
        "deadline": "2026-06-30",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/5",
        "source": "AlbertaPurchasing",
        "raw_description": "Seeking vendor for data integration, ETL pipeline development, and BI dashboard services.",
    },
    {
        "title": "Data Analytics and Reporting Platform for Public Services",
        "org": "Unknown",
        "deadline": "2026-07-15",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/6",
        "source": "TendersOnTime",
        "raw_description": "Government procurement notice for Canada. RFP for data analytics and reporting platform.",
    },
    {
        "title": "RFP for Data and Analytics Services for City Operations",
        "org": "City of Toronto",
        "deadline": "2026-08-01",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/7",
        "source": "TorontoBids",
        "raw_description": "RFP from City of Toronto for data analytics services. Category: Information Technology.",
    },
    {
        "title": "Data Analytics and Reporting Platform — BC Public Service",
        "org": "BC Ministry of Finance",
        "deadline": "2026-07-30",
        "value": "Not specified",
        "url": "https://fixture.example.com/rfp/8",
        "source": "BCBid",
        "raw_description": "RFP for enterprise data analytics and reporting platform for BC Public Service. Scope: data warehouse, BI dashboards, ETL pipelines. Purchaser: BC Ministry of Finance.",
    },
]


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _block_resources(route):
    """Abort non-essential resource types (images, CSS, fonts, media) to speed up Playwright loads."""
    if route.request.resource_type in {"image", "stylesheet", "font", "media"}:
        route.abort()
    else:
        route.continue_()


def scrape_merx(browser=None):  # noqa: ARG001 — browser arg kept for API compat; camoufox manages its own context
    """Scrape MERX public solicitations — Canada and USA (no login required).

    Uses camoufox (Firefox + anti-fingerprint) to bypass bot-detection that blocks
    standard Playwright/Chromium on datacenter IPs such as GitHub Actions runners.
    """
    from camoufox.sync_api import Camoufox

    results = []
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        try:
            page.goto("https://www.merx.com/public/solicitations/open", timeout=30000)
            page.wait_for_selector("tr[class]", timeout=10000)

            rows = page.query_selector_all("tr[class]")
            if not rows:
                logger.warning("[SCRAPER] MERX: page loaded but 0 rows found — possible layout change")
            for row in rows:
                try:
                    link = row.query_selector("a")
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    url = href if href.startswith("http") else f"https://www.merx.com{href}"
                    if not url or url == "https://www.merx.com":
                        continue

                    text = link.inner_text().strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if len(lines) < 3:
                        continue

                    title = lines[0] or "Untitled"
                    org = lines[1] if len(lines) > 1 else "Unknown"
                    location = lines[2] if len(lines) > 2 else ""
                    # closing date: line structure is title/org/loc/Published/date/Closing/date/ID
                    deadline = lines[6] if len(lines) > 6 else ""

                    raw_description = (
                        f"{title}. Procurement issued by {org} in {location}."
                    )

                    results.append({
                        "title": title,
                        "org": org,
                        "location": location,
                        "deadline": deadline,
                        "value": "Not specified",
                        "url": url,
                        "source": "MERX",
                        "raw_description": raw_description,
                    })
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("[SCRAPER] MERX: page load/selector failed: %s", exc)
        finally:
            page.close()

    logger.info("[SCRAPER] MERX: found %d listings", len(results))
    return results


def scrape_bidnet(browser=None):  # noqa: ARG001 — browser arg kept for API compat; camoufox manages its own context
    """Scrape BidNet Direct open solicitations — USA and Canada.

    Uses camoufox (Firefox + anti-fingerprint) to bypass bot-detection that blocks
    standard Playwright/Chromium on datacenter IPs such as GitHub Actions runners.
    """
    from camoufox.sync_api import Camoufox

    results = []
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        try:
            page.goto(
                "https://www.bidnetdirect.com/solicitations/open-bids",
                timeout=30000,
            )
            page.wait_for_selector("tr[class]", timeout=10000)

            rows = page.query_selector_all("tr[class]")
            if not rows:
                logger.warning("[SCRAPER] BidNet: page loaded but 0 rows found — possible layout change")
            for row in rows:
                try:
                    link = row.query_selector("a")
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    url = href if href.startswith("http") else f"https://www.bidnetdirect.com{href}"
                    if not url or url == "https://www.bidnetdirect.com":
                        continue

                    text = link.inner_text().strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if len(lines) < 2:
                        continue

                    title = lines[0] or "Untitled"
                    location = lines[1] if len(lines) > 1 else ""
                    deadline = lines[5] if len(lines) > 5 else ""
                    org = f"Government of {location}" if location else "Unknown"

                    raw_description = (
                        f"{title}. Procurement issued by {org} in {location}."
                    )

                    results.append({
                        "title": title,
                        "org": org,
                        "location": location,
                        "deadline": deadline,
                        "value": "Not specified",
                        "url": url,
                        "source": "BidNet",
                        "raw_description": raw_description,
                    })
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("[SCRAPER] BidNet: page load/selector failed: %s", exc)
        finally:
            page.close()

    logger.info("[SCRAPER] BidNet: found %d listings", len(results))
    return results


def scrape_rfpmart():
    """Scrape RFPMart active RFPs for Canada and USA from IT and Data Analytics categories."""
    CATEGORY_URLS = [
        "https://www.rfpmart.com/data-research-analytics-rfp-government-contract.html",
        "https://www.rfpmart.com/it-services-computer-maintenance-and-technical-services-rfp-government-contract.html",
    ]
    COUNTRIES = {"canada", "usa"}
    # Link text pattern: "SKU-Country (Region) - Title"
    NAME_RE = re.compile(r'^[A-Z0-9]+-\d+-([A-Za-z ]+?)\s*\(([^)]+)\)\s*-\s*(.*)', re.DOTALL)
    BASE = "https://www.rfpmart.com"

    results = []
    seen_urls = set()
    session = _session()

    for cat_url in CATEGORY_URLS:
        try:
            resp = session.get(cat_url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("[SCRAPER] RFPMart category failed %s: %s", cat_url, exc)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # Listings are <a> tags whose href ends in -rfp.html (not the generic individual-rfp.html)
        for a in soup.find_all("a", href=re.compile(r'^\d+-.+-rfp\.html$')):
            try:
                href = a.get("href", "")
                url = href if href.startswith("http") else f"{BASE}/{href}"
                if url in seen_urls:
                    continue

                label = a.get_text(strip=True)
                m = NAME_RE.match(label)
                if not m:
                    continue

                country = m.group(1).strip()
                region = m.group(2).strip()
                raw_title = m.group(3).strip()

                if country.lower() not in COUNTRIES:
                    continue

                # Extract embedded deadline: "Title- Deadline March 10,2026"
                deadline_match = re.search(r"-\s*Deadline\s+(.+)$", raw_title, re.IGNORECASE)
                if deadline_match:
                    deadline = deadline_match.group(1).strip()
                    title = raw_title[:deadline_match.start()].strip().rstrip("-").strip()
                else:
                    deadline = ""
                    title = raw_title

                org = f"Government of {region}, {country}"
                raw_description = f"{title}. Procurement issued by {org}."

                seen_urls.add(url)
                results.append({
                    "title": title,
                    "org": org,
                    "deadline": deadline,
                    "value": "Not specified",
                    "url": url,
                    "source": "RFPMart",
                    "raw_description": raw_description,
                })
            except Exception:
                continue

        time.sleep(2)

    logger.info("[SCRAPER] RFPMart: found %d listings", len(results))
    return results


def scrape_canadabuys(browser=None):
    """Scrape CanadaBuys using Playwright (JavaScript-rendered table)."""
    from playwright.sync_api import sync_playwright

    _pw = None
    _own_browser = browser is None
    results = []
    BASE = "https://canadabuys.canada.ca"

    if _own_browser:
        _pw = sync_playwright().start()
        browser = _pw.chromium.launch(headless=True)

    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    page.route("**/*", _block_resources)
    try:
        page.goto(
            f"{BASE}/en/tender-opportunities?solr_document_type=tender_notice&status=0",
            timeout=30000,
        )
        page.wait_for_selector("table.eps-table tbody tr", timeout=10000)

        rows = page.query_selector_all("table.eps-table tbody tr")
        for row in rows:
            try:
                cells = row.query_selector_all("td")
                if len(cells) < 5:
                    continue

                link = cells[0].query_selector("a")
                if not link:
                    continue

                title = link.inner_text().strip() or "Untitled"
                href = link.get_attribute("href") or ""
                url = href if href.startswith("http") else f"{BASE}{href}"

                category = cells[1].inner_text().strip()
                deadline = cells[3].inner_text().strip()
                org = cells[4].inner_text().strip() or "Unknown"

                raw_description = (
                    f"{title}. Category: {category}. Procurement issued by {org}."
                )

                results.append({
                    "title": title,
                    "org": org,
                    "deadline": deadline,
                    "value": "Not specified",
                    "url": url,
                    "source": "CanadaBuys",
                    "raw_description": raw_description,
                })
            except Exception:
                continue
    finally:
        context.close()
        if _own_browser:
            browser.close()
            if _pw:
                _pw.stop()

    logger.info("[SCRAPER] CanadaBuys: found %d listings", len(results))
    return results


def scrape_bidscanada():
    """Scrape BidsCanada open RFPs using authenticated session. Returns up to 50 listings (free tier)."""
    from urllib.parse import urlparse, parse_qs, quote as url_quote

    login = os.environ.get("BIDSCANADA_LOGIN", "")
    password = os.environ.get("BIDSCANADA_PASSWORD", "")
    if not login or not password:
        logger.info("[SCRAPER] BidsCanada: found 0 listings (BIDSCANADA_LOGIN/PASSWORD not set)")
        return []

    results = []
    session = _session()
    PC = "457DDD89"
    try:
        # Step 1: GET the login page to initialise session cookies
        session.get(
            f"https://www.bidscanada.com/Default.CFM?Page=240&LogIn=Yes&PageRequested=260&PC={PC}&UID=%2D&SID=%2D&BSID=0",
            timeout=20,
        )
        # Step 2: POST login — response URL contains UID and SID session tokens
        login_resp = session.post(
            "https://www.bidscanada.com/Default.CFM",
            data={
                "UserName": login, "Password": password,
                "Page": "250", "PageRequested": "260", "ActionType": "",
                "PC": PC, "UID": "-", "BSID": "0", "Submit": "Submit",
            },
            allow_redirects=True, timeout=20,
        )
        login_resp.raise_for_status()
        params = parse_qs(urlparse(login_resp.url).query)
        uid = params.get("UID", ["-"])[0]
        sid = params.get("SID", ["-"])[0]
        if uid in ("-", "%2D"):
            logger.warning("[SCRAPER] BidsCanada login failed — invalid credentials or site change")
            return []

        # Step 3: POST blank search to get all results (free tier returns 50)
        search_resp = session.post(
            "https://www.bidscanada.com/Default.CFM",
            data={
                "Page": "400", "PC": PC,
                "UID": uid, "SID": sid, "BSID": "0",
                "SearchTerms": "", "Stemming": "Heavy",
                "MaxToDisplay": "50", "ActionType": "Search",
            },
            timeout=20,
        )
        search_resp.raise_for_status()
        soup = BeautifulSoup(search_resp.text, "html.parser")

        # Each result row has 5 cells; cell[0] has <b>Reference:</b> + ref_num, then <a> with title
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 5:
                continue
            cell0 = cells[0]
            ref_tag = cell0.find("b")
            if not ref_tag or "Reference" not in ref_tag.get_text():
                continue
            # Reference number is the text sibling after <b>Reference:</b>
            ref = ref_tag.parent.get_text(strip=True).replace("Reference:", "").strip()
            # Title is the <a> link text; split on "---" to remove French bilingual duplicate
            link = cell0.find("a")
            if not link:
                continue
            title_raw = link.get_text(" ", strip=True)
            title = title_raw.split("---")[0].strip()
            if not title or len(title) < 5:
                continue
            # Closing date is cells[2]; take text up to the "(" note
            closing = re.sub(r"\(.*", "", cells[2].get_text(strip=True)).strip()
            # Stable URL: extract BSID from link href (unique bid identifier)
            href = link.get("href", "")
            bsid_match = re.search(r"BSID=(\d+)", href)
            if bsid_match and bsid_match.group(1) != "0":
                url = f"https://www.bidscanada.com/Default.CFM?PC={PC}&BSID={bsid_match.group(1)}&Page=410"
            else:
                # Fallback: use reference as stable key
                ref_clean = re.sub(r"[^a-zA-Z0-9-]", "-", ref).strip("-")
                url = f"https://www.bidscanada.com/Default.CFM?PC={PC}&BidRef={ref_clean}"
            results.append({
                "title": title,
                "org": "Unknown",
                "deadline": closing,
                "value": "Not specified",
                "url": url,
                "source": "BidsCanada",
                "raw_description": f"{title}. Reference: {ref}.",
            })
    except Exception as exc:
        logger.warning("[SCRAPER] BidsCanada failed: %s", exc)

    logger.info("[SCRAPER] BidsCanada: found %d listings", len(results))
    return results


def scrape_bidsandtenders(browser=None):
    """Scrape BidsAndTenders (Metro Vancouver portal) using authenticated Playwright session."""
    from playwright.sync_api import sync_playwright

    login = os.environ.get("BIDS_AND_TENDERS_LOGIN", "")
    password = os.environ.get("BIDS_AND_TENDERS_PASSWORD", "")
    if not login or not password:
        logger.info("[SCRAPER] BidsAndTenders: found 0 listings (BIDS_AND_TENDERS_LOGIN/PASSWORD not set)")
        return []

    _pw = None
    _own_browser = browser is None
    results = []
    BASE = "https://metrovancouver.bidsandtenders.ca"

    if _own_browser:
        _pw = sync_playwright().start()
        browser = _pw.chromium.launch(headless=True)

    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    # BidsAndTenders JS grid requires stylesheets to render all rows — allow them through
    page.route("**/*", lambda r: r.abort() if r.request.resource_type in {"image", "font", "media"} else r.continue_())
    try:
        # Step 1: Login on the main secure portal (cookies are set on .bidsandtenders.ca domain)
        page.goto("https://secure.bidsandtenders.ca/Module/Tenders/en/Login/Index/", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=10000)
        page.fill("#Username", login)
        page.fill("#Password", password)
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=20000)

        # Verify login succeeded (URL should change from login page)
        if "/Login" in page.url:
            logger.warning("[SCRAPER] BidsAndTenders login failed — credentials invalid or page changed")
            return []

        # Step 2: Navigate to Metro Vancouver bid listing (session cookies carry over)
        page.goto(f"{BASE}/Module/Tenders/en/Home/BidsHomepage", timeout=30000)
        page.wait_for_selector("tr", timeout=10000)

        # Step 3: Extract listings from alternating row structure
        # Data rows: <td><strong>{bid_num} - {title}</strong></td><td>status</td><td>closing</td>...
        # Action rows: colspan=4, contain Tender/Terms/{uuid} links (registration + detail)
        rows = page.query_selector_all("tr")
        seen_uuids = set()

        for i, row in enumerate(rows):
            strong = row.query_selector("td strong")
            if not strong:
                continue
            title = strong.inner_text().strip()
            cells = row.query_selector_all("td")
            closing_raw = cells[2].inner_text().strip() if len(cells) > 2 else ""
            # Normalise date: "Wed Mar 11, 2026 2:00:00 PM (PDT)" → "Mar 11, 2026"
            date_match = re.search(r"(\w{3} \d+, \d{4})", closing_raw)
            deadline = date_match.group(1) if date_match else closing_raw[:20]

            # Detail/register link is in the next sibling row under /Tender/Terms/{uuid}
            if i + 1 < len(rows):
                next_row = rows[i + 1]
                # Portal uses /Tender/Terms/ for registration; extract UUID for stable URL
                detail_a = next_row.query_selector("a[href*='/Tender/Terms/']") or \
                           next_row.query_selector("a[href*='/Tender/Detail/']")
                if detail_a:
                    href = detail_a.get_attribute("href") or ""
                    uuid_match = re.search(r"/Tender/(?:Terms|Detail)/([a-f0-9\-]{36})", href)
                    if uuid_match:
                        uuid = uuid_match.group(1)
                        if uuid not in seen_uuids:
                            seen_uuids.add(uuid)
                            results.append({
                                "title": title,
                                "org": "Metro Vancouver",
                                "deadline": deadline,
                                "value": "Not specified",
                                "url": f"{BASE}/Module/Tenders/en/Tender/Terms/{uuid}",
                                "source": "BidsAndTenders",
                                "raw_description": f"{title}. Procurement by Metro Vancouver.",
                            })
    except Exception as exc:
        logger.warning("[SCRAPER] BidsAndTenders failed: %s", exc)
    finally:
        context.close()
        if _own_browser:
            browser.close()
            if _pw:
                _pw.stop()

    logger.info("[SCRAPER] BidsAndTenders: found %d listings", len(results))
    return results


def scrape_canadatenders():
    """Scrape CanadaTenders with login + keyword search + detail page extraction.

    Strategy:
      1. Authenticate with CanadaTenders_LOGIN / CanadaTenders_PASSWORD (if set).
      2. Search each procurement keyword; collect unique detail-page URLs.
      3. Fetch each detail page and extract: title, org, deadline, summary.
      4. Fall back to public listing scrape if keyword search returns nothing.
    """
    login = os.environ.get("CanadaTenders_LOGIN", "")
    password = os.environ.get("CanadaTenders_PASSWORD", "")
    BASE = "https://www.canadatenders.com"
    _SKIP_TITLES = {
        "contract award", "advance search", "view details", "view detail",
        "login", "register", "subscribe", "contact us", "about us",
        "search", "home", "tenders", "news",
    }
    TENDER_HREF_RE = re.compile(r"/tender/[a-z0-9-]+\.php", re.IGNORECASE)

    results = []
    seen_urls = set()
    session = _session()

    # --- Step 1: Login ---
    if login and password:
        try:
            login_page = session.get(f"{BASE}/login.php", timeout=20)
            soup_lp = BeautifulSoup(login_page.text, "html.parser")
            post_data = {"email": login, "password": password}
            # Carry any hidden CSRF / token fields
            for inp in soup_lp.find_all("input", {"type": "hidden"}):
                name = inp.get("name", "")
                val = inp.get("value", "")
                if name:
                    post_data[name] = val
            auth = session.post(f"{BASE}/login.php", data=post_data,
                                allow_redirects=True, timeout=20)
            body_lower = auth.text.lower()
            if "logout" in body_lower or "my account" in body_lower or "dashboard" in body_lower:
                logger.info("[SCRAPER] CanadaTenders: login succeeded")
            else:
                logger.info("[SCRAPER] CanadaTenders: login attempted (outcome uncertain)")
        except Exception as exc:
            logger.warning("[SCRAPER] CanadaTenders login failed: %s", exc)

    # --- Step 2: Keyword search ---
    def _collect_links(soup):
        links = []
        for a in soup.find_all("a", href=TENDER_HREF_RE):
            href = a.get("href", "")
            url = href if href.startswith("http") else f"{BASE}{href}"
            if url not in seen_urls:
                seen_urls.add(url)
                links.append(url)
        return links

    candidate_urls = []
    for kw in _PROCUREMENT_KEYWORDS:
        try:
            resp = session.get(f"{BASE}/tenders.php",
                               params={"keywords": kw, "status": "open"},
                               timeout=20)
            resp.raise_for_status()
            candidate_urls.extend(_collect_links(BeautifulSoup(resp.text, "html.parser")))
            time.sleep(0.8)
        except Exception as exc:
            logger.warning("[SCRAPER] CanadaTenders kw='%s' failed: %s", kw, exc)

    # --- Step 3: Detail pages ---
    for url in candidate_urls[:40]:          # cap to 40 to stay within time budget
        detail = _fetch_canadatenders_detail(session, url, BASE)
        if detail:
            results.append(detail)
        time.sleep(0.5)

    # --- Step 4: Fallback — public listing page ---
    if not results:
        try:
            resp = session.get(f"{BASE}/tenders.php", timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=TENDER_HREF_RE):
                href = a.get("href", "")
                full_url = href if href.startswith("http") else f"{BASE}{href}"
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                title = a.get_text(strip=True)
                if not title or title.lower() in _SKIP_TITLES or len(title) < 10:
                    slug = re.search(r"/tender/(.+?)(?:-[a-f0-9]+)?\.php", href)
                    title = slug.group(1).replace("-", " ").title() if slug else None
                    if not title:
                        continue
                results.append({
                    "title": title, "org": "Unknown", "deadline": "",
                    "value": "Not specified", "url": full_url,
                    "source": "CanadaTenders",
                    "raw_description": f"{title}. Listed on CanadaTenders.",
                })
        except Exception as exc:
            logger.warning("[SCRAPER] CanadaTenders fallback listing failed: %s", exc)

    logger.info("[SCRAPER] CanadaTenders: found %d listings", len(results))
    return results


def _fetch_canadatenders_detail(session, url, base_url):
    """Fetch a CanadaTenders detail page and extract structured fields.

    Extracts: title, Purchaser/Owner (org), Deadline, Summary/Description.
    Returns a listing dict or None on failure.
    """
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Title: prefer h1, fall back to h2, then page <title>
        h = soup.find("h1") or soup.find("h2")
        title = h.get_text(strip=True) if h else ""
        if not title:
            pt = soup.find("title")
            title = pt.get_text(strip=True) if pt else ""
        if len(title) < 5:
            return None

        org, deadline, value = "Unknown", "", "Not specified"
        summary_parts = []

        # Table rows: label | value
        _LABEL_ORG = re.compile(r"purchaser|owner|organization|buyer|issuer|entity", re.I)
        _LABEL_DL = re.compile(r"deadline|closing|due date|close date|expir", re.I)
        _LABEL_VAL = re.compile(r"value|budget|amount|contract value|estimated", re.I)
        _LABEL_SUM = re.compile(r"summary|description|scope|overview|details", re.I)

        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            lbl = cells[0].get_text(strip=True)
            val = cells[1].get_text(" ", strip=True)
            if _LABEL_ORG.search(lbl):
                org = val or org
            elif _LABEL_DL.search(lbl):
                deadline = val or deadline
            elif _LABEL_VAL.search(lbl):
                value = val or value
            elif _LABEL_SUM.search(lbl) and val:
                summary_parts.append(val)

        # Also scan labeled divs/spans
        for elem in soup.find_all(["div", "p", "li"]):
            text = elem.get_text(" ", strip=True)
            if ":" not in text or len(text) > 300:
                continue
            lbl, _, val = text.partition(":")
            val = val.strip()
            if not val:
                continue
            if _LABEL_ORG.search(lbl):
                org = val
            elif _LABEL_DL.search(lbl):
                deadline = val
            elif _LABEL_VAL.search(lbl):
                value = val
            elif _LABEL_SUM.search(lbl):
                summary_parts.append(val[:400])

        raw = (f"{title}. Purchaser: {org}. " + " ".join(summary_parts))[:1000]
        return {
            "title": title, "org": org, "deadline": deadline,
            "value": value, "url": url,
            "source": "CanadaTenders",
            "raw_description": raw,
        }
    except Exception as exc:
        logger.warning("[SCRAPER] CanadaTenders detail %s failed: %s", url, exc)
        return None



def _extract_pdf_text(content: bytes, max_pages: int = 6) -> str:
    """Extract plain text from PDF bytes using pypdf. Returns up to max_pages pages."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        texts = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            texts.append(page.extract_text() or "")
        return " ".join(texts)[:4000]
    except Exception as exc:
        logger.warning("[SCRAPER] BCBid PDF extraction failed: %s", exc)
        return ""


def scrape_bcbid(browser=None):  # noqa: ARG001 — browser arg kept for API compat; patchright manages its own context
    """Scrape BC Bid public RFP listings via patchright (patched Chromium stealth).

    BCBid deploys an iV (IntelligenceView) browser-fingerprinting challenge plus a
    /en/bas/browser_check JS gate that blocks standard Playwright/Chromium.
    patchright patches Chromium's CDP signals (navigator.webdriver, automation flags,
    etc.) to present as a real browser — same sync Playwright API, no camoufox dependency.

    Flow:
      1. For each keyword in SEARCH_TERMS, fill BCBid's built-in search box
         (searches Description, ID, Summary, Commodity — not just title).
         This replaces the old paginate-all-pages approach and correctly finds
         listings like 156482 / 224915 / RFQ254DBC01 that appear on pages 40-60+.
      2. Collect unique listing rows across all searches (deduplicated by URL).
      3. For each match fetch the detail page:
         - Extract Termination Date (BCBid's name for closing/deadline date),
           Issue Date, contact email, submission method, and contract value.
         - Download up to 3 RFx documents (PDF or Word/docx) and extract text.
    """
    from patchright.sync_api import sync_playwright

    results = []
    BASE = "https://www.bcbid.gov.bc.ca"
    BROWSE_URL = f"{BASE}/page.aspx/en/rfp/request_browse_public"

    # BCBid's search box queries Description + ID + Summary + Commodity.
    # Using targeted terms keeps result counts manageable while covering
    # Client capability profile (data/analytics, ML, cloud, GIS).
    SEARCH_TERMS = [
        "data",                    # data analytics, systems, entry, governance, collection
        "analytics",               # analytics platforms not already caught by "data"
        "reporting",               # reporting tools, BI reports
        "intelligence",            # business intelligence, artificial intelligence
        "digital",                 # digital platforms, adoption, transformation
        "information technology",  # IT consulting and services
        "Snowflake",               # specific platform
        "Power BI",                # specific platform
        "dashboard",               # BI dashboards
        "informatics",             # health / geospatial informatics
        "machine learning",        # ML / AI projects
        "artificial intelligence", # AI strategy, implementation
        "cloud",                   # cloud migration, Azure, AWS, GCP
        "Azure",                   # Microsoft Azure deployments
        "data warehouse",          # DWH / Snowflake projects
        "ETL",                     # extract-transform-load pipelines
        "geospatial",              # GIS / spatial analytics
        "GIS",                     # geographic information systems
        "database",                # DB administration, migration, design
        "managed services",        # IT managed services contracts
        "Microsoft",               # Microsoft 365, Azure, Power Platform
        "software",                # software development / implementation
    ]

    # Opportunity types to skip — construction/timber/goods-heavy, not services.
    # Based on BC Bid Appendix - Opportunity Type Groupings.
    _SKIP_OPP_TYPES = {
        "timber auction",
        "invitation to tender",
        "invitation to tender (bps)",
        "invitation to tender (simplified)",
        "mot itt",
        "notice of sale",
    }

    def _parse_listing_table(soup):
        """Return candidate rows from the main listings table (index 5)."""
        tables = soup.find_all("table")
        if len(tables) < 6:
            return []
        rows = tables[5].find_all("tr")
        candidates = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            desc = cells[2].get_text(strip=True)
            commodities = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            deadline = cells[6].get_text(strip=True) if len(cells) > 6 else ""
            org = cells[10].get_text(strip=True) if len(cells) > 10 else "BC Government"
            link = row.find("a")
            href = link.get("href", "") if link else ""
            url = href if href.startswith("http") else (BASE + href if href else "")
            candidates.append({
                "title": desc, "org": org, "deadline": deadline,
                "commodities": commodities, "detail_url": url,
            })
        return candidates

    def _paginate_current_results(page):
        """Paginate the current search results and return all listing rows."""
        rows = []
        seen = set()
        for _pg in range(20):  # cap: 300 results per search term
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for r in _parse_listing_table(soup):
                if r["detail_url"] and r["detail_url"] not in seen:
                    seen.add(r["detail_url"])
                    rows.append(r)
            next_btn = page.query_selector('button[aria-label="Next page"]')
            if not next_btn:
                break
            btn_class = next_btn.get_attribute("class") or ""
            if "disabled" in btn_class:
                break
            # Wait for iV overlay to clear before paginating — overlay intercepts
            # pointer events and causes ElementHandle.click to fail with "not attached".
            # JS evaluate bypasses pointer-event restrictions entirely.
            _wait_for_iv_challenge(page, timeout_ms=15000)
            page.locator('button[aria-label="Next page"]').evaluate("el => el.click()")
            page.wait_for_timeout(2000)
        return rows

    def _extract_doc_text(doc_url, doc_name, page_req):
        """Download a document (PDF or Word) and return extracted text."""
        text = ""
        try:
            resp = page_req.get(doc_url, timeout=15000)
            if not resp.ok:
                return text
            body = resp.body()
            # Detect by filename first, then by magic bytes
            is_pdf = doc_name.lower().endswith(".pdf") or body[:4] == b"%PDF"
            is_docx = doc_name.lower().endswith(".docx") or body[:2] == b"PK"
            if is_pdf:
                try:
                    import pypdf, io as _io
                    reader = pypdf.PdfReader(_io.BytesIO(body))
                    text = " ".join(
                        (p.extract_text() or "") for p in reader.pages[:6]
                    ).strip()
                except Exception:
                    pass
            if not text and is_docx:
                try:
                    import docx as _docx, io as _io
                    doc = _docx.Document(_io.BytesIO(body))
                    text = " ".join(p.text for p in doc.paragraphs if p.text.strip())
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("[SCRAPER] BCBid doc extract failed %s: %s", doc_url, exc)
        return text[:2000]

    def _handle_browser_check_page(page):
        """Attempt to pass BCBid's /en/bas/browser_check gate.

        BCBid's browser_check page runs JS to fingerprint the browser.  If the
        fingerprint passes, it sets a session cookie and redirects back to the
        original page.  Some implementations also require at least one real user
        interaction (mouse move + click) before they issue the redirect cookie.

        Strategy:
          1. Simulate human-like mouse movement and a click at the page centre.
          2. Wait up to 60s for the URL to leave browser_check.
          3. If still stuck, log a warning and return — the caller's
             _wait_for_iv_challenge will then raise RuntimeError (visible in logs).
        """
        logger.info("[SCRAPER] BCBid: browser_check gate detected — simulating interaction…")
        try:
            # Move to the page centre then click — some gating JS requires an
            # interaction event before it considers the session trustworthy.
            page.mouse.move(760, 400)
            page.wait_for_timeout(500)
            page.mouse.click(760, 400)
            page.wait_for_timeout(1000)
        except Exception as _mc_exc:
            logger.debug("[SCRAPER] BCBid: mouse interaction on browser_check failed: %s", _mc_exc)

        try:
            page.wait_for_url(
                lambda u: "browser_check" not in u, timeout=60000
            )
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            logger.info("[SCRAPER] BCBid: left browser_check → %s", page.url)
        except Exception:
            logger.warning(
                "[SCRAPER] BCBid: browser_check did not redirect after 60s "
                "(URL: %s) — proceeding; next step will surface the real error",
                page.url,
            )

    def _wait_for_iv_challenge(page, timeout_ms=30000):
        """Wait for the iV fingerprinting overlay to clear before interacting.

        BCBid deploys an IntelligenceView (iV) bot-detection overlay that covers
        the page during fingerprint validation.  The overlay CSS selector may
        change across BCBid releases, so we use a 3-layer strategy:

          Layer 1: Try multiple overlay selectors (5s each).  If one becomes
                   hidden, the challenge likely cleared.  Continue to Layer 3
                   regardless — overlay hiding alone is not definitive.
          Layer 2: Quick page content check.  If real-browse-page markers are
                   already present in the HTML, shorten remaining timeout to 8s
                   so keywords that load cleanly are not penalised.
          Layer 3: Probe fallback search-box selectors with wait_for_selector.
                   The search box appearing is the definitive signal that the
                   real browse page is loaded.  Returns the working selector
                   string so the caller can use it directly for fill().

        Raises RuntimeError if no search box becomes visible within timeout_ms,
        so the keyword retry loop can catch it and re-navigate.
        """
        # Layer 1 — try multiple overlay selectors.
        # 5s per selector; if BCBid renamed the overlay class, the exception is
        # caught and we move to the next candidate without consuming timeout_ms.
        for _overlay_sel in (
            "div.iv-block-overlay",
            "div.iv-overlay",
            "#iv-block-overlay",
            "div[class*='iv-block']",
            "div[class*='overlay'][class*='block']",
        ):
            try:
                page.wait_for_selector(_overlay_sel, state="hidden", timeout=5000)
                break
            except Exception:
                continue

        # Layer 2 — quick page-content marker check.
        # Strings that are ONLY present in the real browse page HTML.
        # If any match, the page is already real and we can shorten the wait.
        _BROWSE_MARKERS = ("body_x_txtQuery", "request_browse_public", "BC Bid - Search")
        try:
            if any(m in page.content() for m in _BROWSE_MARKERS):
                timeout_ms = min(timeout_ms, 8000)
        except Exception:
            pass

        # Layer 3 — probe for the search box (definitive signal).
        # Returns the first selector that becomes visible within timeout_ms.
        for _sb_sel in (
            "input#body_x_txtQuery",
            "input[id$='txtQuery']",
            "input[name*='txtQuery']",
            "input[placeholder*='Search']",
            "input[placeholder*='search']",
            "input[type='text'][id*='Query']",
            "input[type='search']",
            "form input[type='text']:first-of-type",
        ):
            try:
                page.wait_for_selector(_sb_sel, state="visible", timeout=timeout_ms)
                logger.debug("[SCRAPER] BCBid: search box ready via selector '%s'", _sb_sel)
                return _sb_sel
            except Exception:
                continue

        # All probes exhausted — emit diagnostics then raise so the retry loop acts.
        _log_bcbid_page_state(page)
        raise RuntimeError(
            "BCBid: no search box became visible after %dms — "
            "iV challenge may still be active or DOM changed" % timeout_ms
        )

    def _log_bcbid_page_state(page):
        """Emit URL, title and body preview for diagnosing BCBid page failures."""
        try:
            logger.warning(
                "[SCRAPER] BCBid page state — URL: %s | Title: %s | Body[:200]: %s",
                page.url,
                page.title(),
                page.content()[:200].replace("\n", " "),
            )
        except Exception as _diag_exc:
            logger.warning("[SCRAPER] BCBid page state diagnostic failed: %s", _diag_exc)

    # Phrases present on every real BCBid opportunity detail page.
    # If NONE of these appear after page load, we got the iV challenge
    # page instead of the actual opportunity — retry.
    _DETAIL_REAL_MARKERS = (
        "Termination Date",
        "Opportunity Type",
        "RFx General",
        "Open Date",
        "process_manage_extranet",
    )

    def _is_real_detail_page(html):
        return any(m in html for m in _DETAIL_REAL_MARKERS)

    def _read_detail_page_content(page, url, max_retries=4):
        """Navigate to a BCBid detail URL and return the page HTML.

        BCBid detail pages use a JS-redirect iV challenge (not the overlay used
        on browse pages).  The sequence is:
          1. goto(url) → browser loads iV challenge page
          2. iV JS fingerprints the browser → passes → triggers JS redirect back
             to the same URL (or with a session token)
          3. Real opportunity page loads

        Key insight: we must navigate ONCE with wait_until="networkidle" so
        Playwright waits through the JS-redirect chain.  Re-navigating on each
        retry restarts the challenge from zero — that is why the previous loop
        approach (4 × page.goto) never worked.

        After the initial navigate, poll the already-loaded page content without
        re-navigating.  We check up to max_retries times with 10s between checks.
        """
        html = ""
        # Single navigation — wait_until="networkidle" captures the JS redirect +
        # subsequent real-page load in one call.
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:
            pass  # timeout OK; page may still have content

        for attempt in range(max_retries):
            page.wait_for_timeout(3000)          # brief settle
            html = page.content()
            if _is_real_detail_page(html):
                return html
            logger.debug(
                "[SCRAPER] BCBid detail page not ready (attempt %d/%d): %s",
                attempt + 1, max_retries, url,
            )
            if attempt < max_retries - 1:
                # Poll without re-navigating — wait for in-flight JS activity
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(7000)

        logger.warning(
            "[SCRAPER] BCBid detail page never returned real content: %s", url
        )
        return html

    # Load persisted BCBid session if available.
    # BCBID_SESSION env var (base64-encoded storage_state JSON) takes precedence
    # over a local bcbid_session.json file.  Either is written/decoded before
    # the browser is launched so the context starts with valid cookies — BCBid's
    # browser_check gate is skipped entirely for trusted sessions.
    import base64 as _b64
    _session_path = None
    _session_env = os.environ.get("BCBID_SESSION", "").strip()
    if _session_env:
        import tempfile as _tmp
        _tf = _tmp.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="bcbid_session_"
        )
        _tf.write(_b64.b64decode(_session_env).decode())
        _tf.close()
        _session_path = _tf.name
        logger.info("[SCRAPER] BCBid: loaded session from BCBID_SESSION env var")
    else:
        _local = os.path.join(
            os.path.dirname(__file__), "..", "..", "bcbid_session.json"
        )
        if os.path.exists(_local):
            _session_path = os.path.abspath(_local)
            logger.info("[SCRAPER] BCBid: loaded session from %s", _session_path)

    try:
        with sync_playwright() as _pw:
            _browser = _pw.chromium.launch(headless=True)
            _ctx_kwargs = {
                "viewport": {"width": 1366, "height": 768},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
            if _session_path:
                _ctx_kwargs["storage_state"] = _session_path
            _ctx = _browser.new_context(**_ctx_kwargs)
            page = _ctx.new_page()

            # Session warm-up: visit BCBid home page before the search loop.
            # BCBid sets session/fingerprint cookies on the home page; establishing
            # them before hitting BROWSE_URL can prevent the browser_check redirect
            # on the first search entirely.
            try:
                logger.info("[SCRAPER] BCBid: warming up session via home page…")
                page.goto(BASE, timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                # If warm-up itself lands on browser_check, run the interaction
                # sequence immediately so the session cookie is set before searches.
                if "browser_check" in page.url:
                    _handle_browser_check_page(page)
                logger.info("[SCRAPER] BCBid: session warm-up done (URL: %s)", page.url)
            except Exception as _wu_exc:
                logger.warning("[SCRAPER] BCBid: session warm-up failed: %s", _wu_exc)

            # --- Step 1: Keyword searches — navigate fresh per term, wait for iV ---
            # Per-navigation approach: each search starts from BROWSE_URL so the
            # results table is in a known state.  _wait_for_iv_challenge() ensures
            # the overlay is gone before we interact (avoids click-intercept failures).
            all_rows: dict[str, dict] = {}  # keyed by detail_url for dedup

            for term in SEARCH_TERMS:
                _search_succeeded = False
                for _attempt in range(2):  # one initial try + one retry
                    try:
                        logger.debug(
                            "[SCRAPER] BCBid search '%s' attempt %d/2", term, _attempt + 1
                        )
                        page.goto(BROWSE_URL, timeout=60000)
                        # networkidle can hang on slow pages; _wait_for_iv_challenge
                        # is the definitive readiness check so we allow this to fail.
                        try:
                            page.wait_for_load_state("networkidle", timeout=20000)
                        except Exception:
                            pass
                        # BCBid may route through /en/bas/browser_check — a JS-based
                        # browser compatibility gate that fingerprints the browser and
                        # redirects back to BROWSE_URL once it passes.
                        if "browser_check" in page.url:
                            _handle_browser_check_page(page)
                        # _wait_for_iv_challenge returns the working selector string
                        # or raises RuntimeError if no search box becomes visible.
                        _working_sel = _wait_for_iv_challenge(page, timeout_ms=30000)
                        # BCBid sets aria-busy="true" on <body> during JS initialisation
                        # (ivBaseHtmlControl.initAsync).  Inputs are locked until it clears.
                        # wait_for_selector with :not([aria-busy="true"]) blocks until the
                        # DOM finishes loading — without this fill() times out even though
                        # the search box is visible.
                        try:
                            page.wait_for_selector(
                                'body:not([aria-busy="true"])', timeout=30000
                            )
                        except Exception:
                            pass  # proceed anyway — fill will surface any real blockage
                        page.wait_for_timeout(500)  # brief stabilisation after DOM ready
                        # Belt-and-suspenders: explicit visibility confirm before fill.
                        page.wait_for_selector(_working_sel, state="visible", timeout=5000)
                        page.fill(_working_sel, term)
                        # Press Enter to submit — avoids stale ElementHandle from .first.click()
                        # which can detach when BCBid's iV system mutates the DOM mid-click.
                        page.keyboard.press("Enter")
                        # Wait for at least one opportunity link to appear before parsing.
                        # Fixed wait (3s) caused 0-result reads when AJAX rendered slower.
                        try:
                            page.wait_for_selector(
                                "a[href*='process_manage_extranet']",
                                state="visible", timeout=10000,
                            )
                        except Exception:
                            page.wait_for_timeout(5000)  # fallback: 5s if no links appear
                        term_rows = _paginate_current_results(page)
                        new_count = 0
                        for r in term_rows:
                            if r["detail_url"] and r["detail_url"] not in all_rows:
                                all_rows[r["detail_url"]] = r
                                new_count += 1
                        logger.info(
                            "[SCRAPER] BCBid search '%s': %d results, %d new unique",
                            term, len(term_rows), new_count,
                        )
                        _search_succeeded = True
                        break  # keyword done — exit retry loop
                    except Exception as exc:
                        logger.warning(
                            "[SCRAPER] BCBid search '%s' attempt %d/2 failed: %s",
                            term, _attempt + 1, exc,
                        )
                        if _attempt == 0:
                            logger.info(
                                "[SCRAPER] BCBid retrying '%s' with fresh navigation...", term
                            )
                            page.wait_for_timeout(3000)  # brief back-off before retry

                if not _search_succeeded:
                    logger.warning(
                        "[SCRAPER] BCBid search '%s' failed after 2 attempts — skipping", term
                    )

            logger.info("[SCRAPER] BCBid: %d unique listings to inspect", len(all_rows))

            # --- Pre-filter: skip obviously irrelevant listings before fetching detail pages ---
            # Regex pre-screen on title + commodities (free, no API).
            # Conservative: uncertain titles are kept; Haiku decides later.
            # Skipping ~40-60% of listings reduces BCBid scrape time by ~20 min.
            _BCBID_KEEP = re.compile(
                r"data|analytic|reporting|intelligence|digital|information.?technology|"
                r"software|cloud|azure|aws|gcp|machine.?learning|artificial.?intelligence|"
                r"dashboard|informatics|database|ETL|snowflake|power.?bi|microsoft|"
                r"managed.?service|cyber|security|GIS|geospatial|ICT|"
                r"system|platform|application|solution|technology|network|"
                r"CRM|ERP|SCADA|LLM|\bAI\b|\bIT\b", re.I
            )
            _BCBID_SKIP = re.compile(
                r"\broad\b|bridge|highway|pavement|asphalt|culvert|water.?main|watermain|"
                r"pump.?station|sewer|hydrant|timber|silviculture|tree.?plant|"
                r"brushing|reforestation|harvest|logging|catering|food.?service|"
                r"janitorial|cleaning|custodial|grass.?cut|landscaping|"
                r"\bpark\b|playground|arena|recreation|sports.?field|tennis|soccer|"
                r"structural.?engineer|civil.?engineer|mechanical|electrical.?maint|"
                r"roofing|renovation|construction|demolition|excavat|paving|"
                r"fire.?hall|ambulance|emergency.?generat|propane|gravel|"
                r"fence|guardrail|sign.?install|traffic.?control|flagging|"
                r"\bboat\b|vessel|aircraft|\bvehicle\b|\bfleet\b|equipment.?supply|"
                r"move.?management|furniture|caretaker|pest.?control|"
                r"accommodation|food.?bank|\bmeal\b|silviculture|planting", re.I
            )

            def _is_relevant_bcbid_listing(title, commodities):
                text = (title or "") + " " + (commodities or "")
                if _BCBID_SKIP.search(text):
                    return False
                if _BCBID_KEEP.search(text):
                    return True
                return True  # uncertain — keep; Haiku decides later

            _pre_filtered = {
                url: r for url, r in all_rows.items()
                if _is_relevant_bcbid_listing(r["title"], r.get("commodities", ""))
            }
            _skipped_count = len(all_rows) - len(_pre_filtered)
            logger.info(
                "[SCRAPER] BCBid pre-filter: %d kept, %d skipped (irrelevant titles)",
                len(_pre_filtered), _skipped_count,
            )

            # --- Step 2: Fetch detail pages, extract structured fields ---
            _total_detail = len(_pre_filtered)
            _kept_count = 0
            for _detail_idx, (detail_url, row_data) in enumerate(_pre_filtered.items(), start=1):
                _kept_count += 1
                logger.info(
                    "[SCRAPER] BCBid detail page %d/%d — %s",
                    _detail_idx, _total_detail, row_data.get("title", "")[:60],
                )
                title = row_data["title"]
                raw_description = "%s. Procurement by %s." % (title, row_data["org"])
                doc_text = ""
                value = "Not specified"
                deadline = row_data.get("deadline", "")
                contact_email = ""
                submission_method = ""
                opportunity_type = ""
                commodity_codes = row_data.get("commodities", "")

                try:
                    detail_html = _read_detail_page_content(page, detail_url)
                    detail_soup = BeautifulSoup(detail_html, "html.parser")
                    detail_text = detail_soup.get_text(" ", strip=True)

                    # --- Structured field extraction from RFx General Information ---

                    # Opportunity Type — used to filter out construction/timber/goods types.
                    # Listed prominently in RFx General Information section.
                    opp_type_m = re.search(
                        r"Opportunity Type\s+([A-Za-z][^\n\r]{3,80}?)(?:\s{2,}|\d{4}-|\Z)",
                        detail_text, re.I,
                    )
                    if opp_type_m:
                        opportunity_type = opp_type_m.group(1).strip()
                        if opportunity_type.lower() in _SKIP_OPP_TYPES:
                            logger.debug(
                                "[SCRAPER] BCBid skipping %s (type: %s)",
                                title[:60], opportunity_type,
                            )
                            continue  # skip construction/timber listings entirely

                    # Commodity Codes — more structured on detail page than listing table
                    comm_m = re.search(
                        r"Commodity Codes?\s+([A-Z0-9 ,;/\-\(\)]{5,300})",
                        detail_text, re.I,
                    )
                    if comm_m:
                        commodity_codes = comm_m.group(1).strip()[:300]

                    # Termination Date = BCBid's name for the closing/deadline date
                    term_m = re.search(
                        r"Termination Date\s+([\d]{4}-[\d]{2}-[\d]{2}(?:\s+[\d:]+\s*[APM]*)?)",
                        detail_text, re.I,
                    )
                    if term_m:
                        deadline = term_m.group(1).strip()

                    # Issue Date
                    issue_m = re.search(
                        r"Issue Date\s+([\d]{4}-[\d]{2}-[\d]{2})", detail_text, re.I,
                    )

                    # Contact email — check Overview tab first, then navigate to Opportunity
                    # Details tab (Official Contact Information section per supplier guide p.32).
                    _EMAIL_RE = re.compile(
                        r"\b[A-Za-z0-9._%+-]+@(?:gov\.bc\.ca|bchydro\.com|phsa\.ca|"
                        r"fraserhealth\.ca|viha\.ca|vch\.ca|[A-Za-z0-9.-]+\.bc\.ca|"
                        r"[A-Za-z0-9.-]+\.ca|[A-Za-z0-9.-]+\.com)\b"
                    )
                    email_m = _EMAIL_RE.search(detail_text)
                    if email_m:
                        contact_email = email_m.group(0)

                    # If no email found on Overview, navigate to Opportunity Details tab.
                    # BCBid left-nav link text is "Opportunity Details" (supplier guide p.32).
                    if not contact_email:
                        try:
                            opp_details_link = page.locator(
                                'a:has-text("Opportunity Details")'
                            ).first
                            if opp_details_link.count():
                                opp_details_link.click()
                                page.wait_for_load_state("networkidle", timeout=8000)
                                od_text = BeautifulSoup(
                                    page.content(), "html.parser"
                                ).get_text(" ", strip=True)
                                email_m2 = _EMAIL_RE.search(od_text)
                                if email_m2:
                                    contact_email = email_m2.group(0)
                        except Exception:
                            pass

                    # Submission method (email / electronic / in-person)
                    sub_m = re.search(
                        r"(Submissions?\s+(?:must\s+be\s+submitted|by\s+email|"
                        r"electronically|through\s+BC\s+Bid)[^.]{0,150})",
                        detail_text, re.I,
                    )
                    if sub_m:
                        submission_method = sub_m.group(1).strip()[:200]

                    # Contract / estimated value
                    val_m = re.search(
                        r"(?:Contract|Estimated|Budget|Upset)\s+(?:Value|Amount|Price)"
                        r"[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)",
                        detail_text, re.I,
                    )
                    if val_m:
                        value = "$" + val_m.group(1)

                    # Summary/description text from section headings
                    _SECT_RE = re.compile(
                        r"summary|description|scope|overview|background|purpose|objective",
                        re.I,
                    )
                    for elem in detail_soup.find_all(["p", "div", "section", "td"]):
                        heading = elem.find(["h2", "h3", "h4", "strong", "b", "th"])
                        if heading and _SECT_RE.search(heading.get_text()):
                            raw_description += " " + elem.get_text(" ", strip=True)[:600]
                            break

                    # Include opportunity type and commodity codes in description for scoring
                    if opportunity_type:
                        raw_description = ("Type: %s. " % opportunity_type) + raw_description
                    if commodity_codes:
                        raw_description += " Commodity Codes: %s." % commodity_codes

                    # RFx document download skipped — BCBid requires auth for downloads,
                    # returning HTML redirects that cause long timeouts per listing.
                    # RFx General Information (type, deadline, commodity codes, contact,
                    # summary text) extracted from the HTML detail page is sufficient for scoring.

                except Exception as exc:
                    logger.warning("[SCRAPER] BCBid detail page failed %s: %s", detail_url, exc)

                combined_desc = (raw_description + " " + doc_text).strip()[:3000]
                results.append({
                    "title": title,
                    "org": row_data["org"],
                    "deadline": deadline,
                    "value": value,
                    "opportunity_type": opportunity_type,
                    "commodity_codes": commodity_codes,
                    "contact_email": contact_email,
                    "submission_method": submission_method,
                    "url": detail_url or BROWSE_URL,
                    "source": "BCBid",
                    "raw_description": combined_desc,
                })
                # Batch-save every 50 listings so progress is never lost on timeout
                if len(results) % 50 == 0:
                    upsert_raw_listings(results[-50:])

    except Exception as exc:
        logger.warning("[SCRAPER] BCBid failed: %s", exc)
    finally:
        # Clean up temp session file written from BCBID_SESSION env var
        if _session_env and _session_path and os.path.exists(_session_path):
            try:
                os.unlink(_session_path)
            except Exception:
                pass

    upsert_raw_listings(results)  # final flush — idempotent (INSERT OR REPLACE)
    logger.info("[SCRAPER] BCBid: found %d listings", len(results))
    return results


def scrape_sasktenders():
    """Scrape SaskTenders public search page. Returns ~50 open competitions (no login needed)."""
    results = []
    BASE = "https://sasktenders.ca/content/public/"
    session = _session()
    try:
        resp = session.get(BASE + "Search.aspx", timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Collect print URLs (unique per competition, appear in same order as summary rows)
        print_urls = [
            BASE + a.get("href")
            for a in soup.find_all("a", href=re.compile(r"print\.aspx\?competitionId=", re.I))
        ]
        # Summary rows: 7 cells, col[6]=status, col[1]=title, col[2]=org, col[3]=comp#, col[5]=close
        idx = 0
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 7:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            title, org, comp_num, close_date, status = (
                texts[1], texts[2], texts[3], texts[5], texts[6]
            )
            if (
                status in ("Open", "Closed", "Cancelled")
                and len(title) > 10
                and "PDF" not in texts[0]
                and not title.startswith("Competition Name")
            ):
                url = print_urls[idx] if idx < len(print_urls) else f"{BASE}Search.aspx#{comp_num}"
                idx += 1
                deadline = re.sub(r"\d{2}:\d{2}.*", "", close_date).strip()
                results.append({
                    "title": title,
                    "org": org,
                    "deadline": deadline,
                    "value": "Not specified",
                    "url": url,
                    "source": "SaskTenders",
                    "raw_description": f"{title}. Procurement by {org}. Competition #{comp_num}.",
                })
    except Exception as exc:
        logger.warning("[SCRAPER] SaskTenders failed: %s", exc)

    logger.info("[SCRAPER] SaskTenders: found %d listings", len(results))
    return results


def scrape_alberta_purchasing():
    """Scrape Alberta Purchasing Connection via public REST API. Returns 100 most-recent listings."""
    results = []
    try:
        payload = {
            "query": "",
            "queryMode": "standard",
            "includeEnhancedMatchIds": True,
            "filter": {
                "solicitationNumber": "",
                "categories": [],
                "statuses": [],
                "agreementTypes": [],
                "solicitationTypes": [],
                "opportunityTypes": [],
                "deliveryRegions": [],
                "deliveryRegion": "",
                "organizations": [],
                "unspsc": [],
                "postDateRange": "$$custom",
                "closeDateRange": "$$custom",
                "onlyBookmarked": False,
                "onlyInterestExpressed": False,
            },
            "limit": 100,
            "offset": 0,
            "sortOptions": [{"field": "PostDateTime", "direction": "desc"}],
        }
        resp = requests.post(
            "https://purchasing.alberta.ca/api/opportunity/search",
            json=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": "https://purchasing.alberta.ca/search",
                "Origin": "https://purchasing.alberta.ca",
            },
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("values", []):
            ref = item.get("referenceNumber", "")
            title = item.get("shortTitle", "") or item.get("title", "")
            if not title or not ref:
                continue
            org = item.get("contractingOrganization", "Unknown")
            deadline = (item.get("closeDateTime") or "")[:10]
            desc = item.get("projectDescription", "")
            results.append({
                "title": title,
                "org": org,
                "deadline": deadline,
                "value": "Not specified",
                "url": f"https://purchasing.alberta.ca/posting/{ref}",
                "source": "AlbertaPurchasing",
                "raw_description": f"{title}. {desc}"[:1000],
            })
    except Exception as exc:
        logger.warning("[SCRAPER] AlbertaPurchasing failed: %s", exc)

    logger.info("[SCRAPER] AlbertaPurchasing: found %d listings", len(results))
    return results


def scrape_toronto_bids():
    """Scrape Toronto Bids Portal via public OData API (no auth required). Returns all open solicitations."""
    from datetime import date as date_

    results = []
    today = date_.today().isoformat()
    BASE_PAGE = (
        "https://www.toronto.ca/business-economy/doing-business-with-the-city/"
        "searching-bidding-on-city-contracts/toronto-bids-portal/"
    )
    try:
        api_url = (
            "https://secure.toronto.ca/c3api_data/v2/DataAccess.svc/pmmd_solicitations/feis_solicitation_published"
            "?$format=application/json;odata.metadata=none"
            "&$count=true&$skip=0&$top=200"
            f"&$filter=Ready_For_Posting%20eq%20%27Yes%27%20and%20Status%20eq%20%27Open%27"
            f"%20and%20Closing_Date%20ge%20{today}"
            "&$orderby=Closing_Date%20desc,Issue_Date%20desc"
        )
        session = _session()
        session.headers.update({"Accept": "application/json", "Referer": BASE_PAGE})
        resp = session.get(api_url, timeout=20)
        resp.raise_for_status()

        for item in resp.json().get("value", []):
            title = item.get("Posting_Title", "").strip()
            uuid = item.get("id", "")
            if not title or not uuid:
                continue
            org_list = item.get("Client_Division", [])
            org = org_list[0] if org_list else "City of Toronto"
            deadline = item.get("Closing_Date", "")
            rfx_type = item.get("Solicitation_Document_Type", "")
            category = item.get("High_Level_Category", "")
            desc = (item.get("Solicitation_Document_Description", "") or "")[:500]
            results.append({
                "title": title,
                "org": org or "City of Toronto",
                "deadline": deadline,
                "value": "Not specified",
                "url": f"{BASE_PAGE}#all/{uuid}",
                "source": "TorontoBids",
                "raw_description": (
                    f"{title}. {rfx_type} from City of Toronto ({org}). Category: {category}. {desc}"
                )[:1000],
            })
    except Exception as exc:
        logger.warning("[SCRAPER] TorontoBids failed: %s", exc)

    logger.info("[SCRAPER] TorontoBids: found %d listings", len(results))
    return results



def scrape_all(skip_bcbid=False):
    """Call all scrapers, isolating failures per source. Returns [] on complete failure.

    Playwright scrapers (CanadaBuys, BidsAndTenders) run sequentially with a shared
    Chromium browser — sync_playwright() C-extensions are not thread-safe across
    instances, but a single browser can be safely reused across sequential scrapers.

    camoufox scrapers (MERX, BidNet, BCBid) use Firefox + anti-fingerprint to bypass
    bot-detection on datacenter IPs (e.g. GitHub Actions). They run after the
    sync_playwright() block closes — camoufox manages its own event loop and conflicts
    with an open sync_playwright() context.

    Requests-based scrapers (RFPMart, BidsCanada, CanadaTenders, GlobalTenders,
    SaskTenders, AlbertaPurchasing, TorontoBids) run in parallel via ThreadPoolExecutor.
    Each creates its own requests.Session() internally — no shared state.

    skip_bcbid: if True, omit BCBid (camoufox) — used when daily_scrape.yml sets
    SKIP_BCBID=true so the 713 MB Firefox binary is never triggered in the main pipeline.
    """
    if DRY_RUN:
        logger.info("[SCRAPER] DRY_RUN=true — returning fixture listings")
        return list(_FIXTURE_LISTINGS)

    from playwright.sync_api import sync_playwright

    all_listings = []

    # --- Playwright scrapers: sequential, shared browser (C-extensions not thread-safe) ---
    # MERX, BidNet, and BCBid are excluded here — they use camoufox (own event loop)
    # which conflicts with the sync_playwright() context. They run after this block.
    t_playwright = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for fn, name in [
                (scrape_canadabuys, "CanadaBuys"),
                (scrape_bidsandtenders, "BidsAndTenders"),
            ]:
                t0 = time.monotonic()
                logger.info("[SCRAPER] starting %s ...", name)
                try:
                    result = fn(browser)
                    all_listings.extend(result)
                    logger.info("[SCRAPER] %s: %.1fs — %d listing(s)", name, time.monotonic() - t0, len(result))
                except Exception as exc:
                    logger.warning("[SCRAPER] %s scrape failed: %s", name, exc)
        finally:
            browser.close()
    logger.info("[SCRAPER] Playwright block: %.1fs total", time.monotonic() - t_playwright)

    # --- All remaining scrapers: run in parallel after sync_playwright() closes ---
    # MERX and BidNet use camoufox (Firefox, own event loop per thread).
    # BCBid uses patchright (own Chromium, own sync_playwright context per thread).
    # Requests-based scrapers use independent sessions — already proven thread-safe.
    # All are independent and safe to run concurrently in separate threads.
    _parallel_scrapers = [
        (scrape_merx, "MERX"),
        (scrape_bidnet, "BidNet"),
        (scrape_rfpmart, "RFPMart"),
        (scrape_bidscanada, "BidsCanada"),
        (scrape_canadatenders, "CanadaTenders"),
        (scrape_sasktenders, "SaskTenders"),
        (scrape_alberta_purchasing, "AlbertaPurchasing"),
        (scrape_toronto_bids, "TorontoBids"),
    ]
    if not skip_bcbid:
        _parallel_scrapers.append((scrape_bcbid, "BCBid"))
    else:
        logger.info("[SCRAPER] BCBid skipped (SKIP_BCBID=true)")

    t_parallel = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_parallel_scrapers)) as executor:
        futures = {executor.submit(fn): name for fn, name in _parallel_scrapers}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            t0 = time.monotonic()
            try:
                results = future.result()
                all_listings.extend(results)
                upsert_raw_listings(results)  # persist immediately — safe on timeout
                logger.info("[SCRAPER] %s completed — %d listing(s)", name, len(results))
            except Exception as exc:
                logger.warning("[SCRAPER] %s scrape failed: %s", name, exc)
    logger.info("[SCRAPER] parallel block: %.1fs total", time.monotonic() - t_parallel)

    return all_listings


class ProcurementIntelligenceSpecialist:
    # v2: scraping can take 20+ min across 12 portals — use long timeout so
    # accuracy is not sacrificed. Override via SCRAPER_TIMEOUT_SECONDS env var.
    TIMEOUT_SECONDS = int(os.environ.get("SCRAPER_TIMEOUT_SECONDS", 3600))

    def run(self, state: dict) -> dict:
        state.setdefault("listings", [])
        skip_bcbid = os.environ.get("SKIP_BCBID", "false").lower() == "true"
        raw = scrape_all(skip_bcbid=skip_bcbid)

        # Step 1: URL-based dedup against DB (existing behaviour)
        all_urls = [l["url"] for l in raw]
        new_url_set = set(filter_new_urls(all_urls))
        url_deduped = [l for l in raw if l["url"] in new_url_set]

        # Step 2: Content-hash dedup — drops cross-source duplicates
        # (same RFP appearing on MERX and CanadaBuys under different URLs)
        new_listings = filter_hash_duplicates(url_deduped)

        state["listings"].extend(new_listings)
        logger.info(
            "[SCRAPER] %d new listings after dedup (scraped %d, url-new %d, hash-deduped %d)",
            len(new_listings),
            len(raw),
            len(url_deduped),
            len(url_deduped) - len(new_listings),
        )
        return state



class BCBidOnlyProcurementSpecialist(ProcurementIntelligenceSpecialist):
    """Variant used by the dedicated BCBid weekly workflow.

    Calls scrape_bcbid() directly — skips scrape_all() and all other portals.
    DRY_RUN returns only the BCBid fixture listing so tests stay offline.
    """

    def run(self, state: dict) -> dict:
        state.setdefault("listings", [])
        if DRY_RUN:
            raw = [l for l in _FIXTURE_LISTINGS if l.get("source") == "BCBid"]
        else:
            raw = scrape_bcbid()

        all_urls = [l["url"] for l in raw]
        new_url_set = set(filter_new_urls(all_urls))
        url_deduped = [l for l in raw if l["url"] in new_url_set]
        new_listings = filter_hash_duplicates(url_deduped)
        state["listings"].extend(new_listings)
        logger.info(
            "[SCRAPER] BCBid-only: %d new listings after dedup (scraped %d)",
            len(new_listings), len(raw),
        )
        return state
