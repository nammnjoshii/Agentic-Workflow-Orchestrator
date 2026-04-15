import concurrent.futures
import logging
import os
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
CONTACT_THRESHOLD = int(os.environ.get("CONTACT_THRESHOLD", 70))
_SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
_HUNTER_KEY = os.environ.get("HUNTER_API_KEY", "")
_APOLLO_KEY = os.environ.get("APOLLO_API_KEY", "")
# v2: increased from 3 to 5 for higher contact coverage
_MAX_CONTACTS = 5

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_FIXTURE_CONTACTS = [
    {
        "name": "Jane Smith",
        "title": "Director of Data and Analytics",
        "linkedin_url": "https://www.linkedin.com/in/jane-smith-data",
        "email": "jsmith@example.org",
        "source": "linkedin",
    },
    {
        "name": "Robert Chen",
        "title": "VP Technology and Digital Innovation",
        "linkedin_url": "https://www.linkedin.com/in/robert-chen-vp",
        "email": None,
        "source": "hunter",
    },
    {
        "name": "Maria Lopez",
        "title": "Chief Data Officer",
        "linkedin_url": "https://www.linkedin.com/in/maria-lopez-cdo",
        "email": "mlopez@example.org",
        "source": "linkedin",
    },
    {
        "name": "David Kim",
        "title": "Manager, Data Engineering",
        "linkedin_url": "https://www.linkedin.com/in/david-kim-data",
        "email": None,
        "source": "linkedin",
    },
    {
        "name": "Sarah Thompson",
        "title": "Director of Digital Transformation",
        "linkedin_url": "https://www.linkedin.com/in/sarah-thompson-dt",
        "email": "sthompson@example.org",
        "source": "hunter",
    },
    {
        "name": "James Wilson",
        "title": "Assistant Deputy Minister, Digital Government",
        "linkedin_url": None,
        "email": None,
        "source": "website",
    },
]


def find_org_website(org_name):
    """Find the primary website for org_name. SerpAPI first, DuckDuckGo fallback."""
    if _SERPAPI_KEY:
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"q": org_name, "api_key": _SERPAPI_KEY, "num": 3},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            for result in data.get("organic_results", []):
                url = result.get("link", "")
                if url:
                    time.sleep(1)
                    return url
        except Exception as exc:
            logger.warning("[CONTACTS] SerpAPI failed for %s: %s — falling back to DDG", org_name, exc)
        time.sleep(1)

    # DuckDuckGo Instant Answer fallback
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": org_name, "format": "json", "no_redirect": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        url = data.get("AbstractURL") or data.get("Redirect") or ""
        time.sleep(1)
        return url if url else None
    except Exception as exc:
        logger.warning("[CONTACTS] DuckDuckGo failed for %s: %s", org_name, exc)
        time.sleep(1)
        return None


def _parse_linkedin_results(data):
    """Parse SerpAPI organic_results into contact dicts. Returns list."""
    contacts = []
    for result in data.get("organic_results", []):
        link = result.get("link", "")
        if "linkedin.com/in/" not in link:
            continue
        title_part = result.get("title", "")
        snippet = result.get("snippet", "")

        # SerpAPI title format: "Name - Title at Org | LinkedIn"
        name, role = "", ""
        if " - " in title_part:
            parts = title_part.split(" - ", 1)
            name = parts[0].strip()
            rest = parts[1]
            role = rest.split(" at ")[0].strip() if " at " in rest else rest.split(" | ")[0].strip()
        else:
            name = title_part.split("|")[0].strip()
            role = snippet[:80]

        if not name:
            continue
        contacts.append({
            "name": name,
            "title": role,
            "linkedin_url": link,
            "email": None,
            "source": "linkedin",
        })
        if len(contacts) >= _MAX_CONTACTS:
            break
    return contacts


def find_linkedin_contacts(org_name, location=""):
    """Search Google via SerpAPI for site:linkedin.com/in profiles at org_name."""
    if not _SERPAPI_KEY:
        logger.warning("[CONTACTS] SERPAPI_KEY unset — skipping LinkedIn search for %s", org_name)
        return []

    try:
        query = 'site:linkedin.com/in "{}"'.format(org_name)
        if location:
            query = '{} "{}"'.format(query, location)
        resp = requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": _SERPAPI_KEY, "num": 5},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1)
        return _parse_linkedin_results(data)
    except Exception as exc:
        logger.warning("[CONTACTS] LinkedIn search failed for %s: %s", org_name, exc)
        time.sleep(1)
        return []


def find_linkedin_contacts_by_role(org_name, location=""):
    """Second SerpAPI pass targeting decision-maker titles (v2).

    Queries for Director/VP/Chief/Manager at org_name in data/analytics context
    to surface contacts most likely to influence procurement decisions.
    """
    if not _SERPAPI_KEY:
        return []

    try:
        query = (
            'site:linkedin.com/in (Director OR VP OR Chief OR Manager) '
            '"data" "{}"'.format(org_name)
        )
        if location:
            query = '{} "{}"'.format(query, location)
        resp = requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": _SERPAPI_KEY, "num": 5},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1)
        return _parse_linkedin_results(data)
    except Exception as exc:
        logger.warning("[CONTACTS] role-targeted LinkedIn search failed for %s: %s", org_name, exc)
        time.sleep(1)
        return []


def find_emails(domain):
    """Hunter.io domain search — 1 credit per call. Returns [] if key unset."""
    if not _HUNTER_KEY:
        logger.warning("[CONTACTS] HUNTER_API_KEY unset — skipping email lookup for %s", domain)
        return []

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": _HUNTER_KEY, "limit": _MAX_CONTACTS},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1)

        contacts = []
        for person in data.get("data", {}).get("emails", []):
            first = person.get("first_name", "")
            last = person.get("last_name", "")
            name = "{} {}".format(first, last).strip()
            if not name:
                continue
            contacts.append({
                "name": name,
                "title": person.get("position", ""),
                "linkedin_url": person.get("linkedin", None),
                "email": person.get("value", None),
                "source": "hunter",
            })
        return contacts
    except Exception as exc:
        logger.warning("[CONTACTS] Hunter.io failed for %s: %s", domain, exc)
        time.sleep(1)
        return []


def _field_count(contact):
    """Count populated fields — used to prefer richer record on dedup."""
    return sum(1 for v in contact.values() if v)


def merge_contacts(linkedin, emails):
    """Deduplicate by first name + email, keep richer record. Cap at _MAX_CONTACTS.

    v2: also deduplicates by email address so Hunter.io and LinkedIn records
    for the same person are merged rather than duplicated.
    """
    seen_name = {}
    seen_email = {}

    for c in linkedin + emails:
        email = (c.get("email") or "").lower()

        # Email-based dedup: if we've already seen this email, keep richer record
        if email and email in seen_email:
            if _field_count(c) > _field_count(seen_email[email]):
                # Replace weaker record under same first-name key
                old = seen_email[email]
                old_first = (old.get("name") or "").split()[0].lower()
                seen_name[old_first] = c
                seen_email[email] = c
            continue

        first = (c.get("name") or "").split()[0].lower()
        if not first:
            continue
        if first not in seen_name or _field_count(c) > _field_count(seen_name[first]):
            seen_name[first] = c
        if email:
            seen_email[email] = seen_name[first]

    return list(seen_name.values())[:_MAX_CONTACTS]


def _parse_leadership_html(html: str) -> list:
    """Extract name+title pairs from a leadership page using BeautifulSoup.

    Heuristic: finds div/article/li/section elements with person-card class names,
    extracts h2/h3/h4 (name) + adjacent p/span (title). Fails gracefully.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        _PERSON_CLASSES = {"person", "member", "team-member", "executive", "bio", "card", "staff", "leader"}
        contacts = []
        for tag in soup.find_all(["div", "article", "li", "section"]):
            classes = set(" ".join(tag.get("class", [])).lower().split())
            if not (classes & _PERSON_CLASSES):
                continue
            name_tag = tag.find(["h2", "h3", "h4", "strong"])
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            if not name or len(name) > 80:
                continue
            title_tag = tag.find(["p", "span"])
            title = title_tag.get_text(strip=True) if title_tag else ""
            contacts.append({
                "name": name,
                "title": title,
                "email": None,
                "linkedin_url": None,
                "source": "website",
            })
            if len(contacts) >= _MAX_CONTACTS:
                break
        return contacts
    except Exception as exc:
        logger.debug("[CONTACTS] leadership HTML parse error: %s", exc)
        return []


def scrape_leadership_page(website_url: str) -> list:
    """Scrape the org's own website for leadership/team page contacts.

    Tries 11 common paths (/leadership, /about/team, etc.). Uses BeautifulSoup
    heuristic parsing. Contacts get source="website" → highest org affiliation
    confidence (90). Fails silently; never raises.
    """
    if not website_url:
        return []

    _PATHS = [
        "/leadership", "/leadership-team", "/executive-team",
        "/about/leadership", "/about/team", "/about/leadership-team",
        "/about-us/leadership", "/about-us/team", "/team",
        "/management", "/executives",
    ]

    try:
        parsed = urlparse(website_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return []

    for path in _PATHS:
        try:
            resp = requests.get(
                f"{base}{path}",
                headers={"User-Agent": _USER_AGENT},
                timeout=30,
            )
            if resp.status_code != 200:
                time.sleep(0.5)
                continue
            contacts = _parse_leadership_html(resp.text)
            if contacts:
                logger.info("[CONTACTS] found %d contacts on %s%s", len(contacts), base, path)
                time.sleep(1)
                return contacts[:_MAX_CONTACTS]
        except Exception as exc:
            logger.debug("[CONTACTS] leadership scrape failed at %s%s: %s", base, path, exc)
        time.sleep(0.5)

    return []


def find_apollo_contacts(domain: str, org_name: str) -> list:
    """Apollo.io People Search — returns contacts with LinkedIn URLs (no email in basic search).

    Complements Hunter.io (which returns emails). Apollo adds broader contact
    coverage and LinkedIn URLs. Source="apollo" → _org_affiliation_score=75.
    Fails silently; returns [] if APOLLO_API_KEY unset.
    """
    if not _APOLLO_KEY:
        logger.warning("[CONTACTS] APOLLO_API_KEY unset — skipping Apollo search for %s", org_name)
        return []

    try:
        payload = {
            "api_key": _APOLLO_KEY,
            "q_organization_name": org_name,
            "per_page": _MAX_CONTACTS,
        }
        if domain:
            payload["q_organization_domains"] = [domain]

        resp = requests.post(
            "https://api.apollo.io/api/v1/mixed_people/api_search",
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(1)

        contacts = []
        for person in data.get("people", []):
            name = person.get("name") or ""
            if not name:
                first = person.get("first_name") or ""
                last = person.get("last_name") or ""
                name = f"{first} {last}".strip()
            if not name:
                continue
            contacts.append({
                "name": name,
                "title": person.get("title") or "",
                "email": None,  # basic search does not return emails
                "linkedin_url": person.get("linkedin_url") or None,
                "source": "apollo",
            })
        return contacts
    except Exception as exc:
        logger.warning("[CONTACTS] Apollo search failed for %s: %s", org_name, exc)
        time.sleep(1)
        return []


def _extract_domain(url):
    if not url:
        return None
    try:
        host = urlparse(url).netloc
        return host.removeprefix("www.") if host else None
    except Exception:
        return None


def enrich_opportunity(org, title, exec_summary, suggested_angle, location=""):
    """Full enrichment pipeline (v2). Returns {} on complete failure — never raises.

    v2 changes:
    - Two LinkedIn passes: broad search + role-targeted (Director/VP/Chief/Manager)
    - Email-based deduplication in merge_contacts
    - All API timeouts raised to 30s
    - Contact cap raised to 5
    """
    try:
        website = find_org_website(org)
        domain = _extract_domain(website)

        # v3: four-source contact discovery for maximum coverage + org affiliation confidence
        website_contacts = scrape_leadership_page(website)  # source="website", affiliation=90
        linkedin_contacts = (                               # source="linkedin", affiliation=50
            find_linkedin_contacts(org, location=location)
            + find_linkedin_contacts_by_role(org, location=location)
        )
        email_contacts = find_emails(domain) if domain else []     # source="hunter", affiliation=75
        apollo_contacts = find_apollo_contacts(domain or "", org)  # source="apollo", affiliation=75

        contacts = merge_contacts(
            website_contacts + linkedin_contacts,
            email_contacts + apollo_contacts,
        )

        return {
            "website": website,
            "domain": domain,
            "contacts": contacts,
        }
    except Exception as exc:
        logger.warning("[CONTACTS] enrich_opportunity failed for %s: %s", org, exc)
        return {}


class StakeholderIntelligenceSpecialist:
    # v2: contact enrichment can take several minutes per org across two LinkedIn
    # passes + Hunter.io. Override via CONTACT_TIMEOUT_SECONDS env var.
    TIMEOUT_SECONDS = int(os.environ.get("CONTACT_TIMEOUT_SECONDS", 600))

    def run(self, state):
        state.setdefault("contacts", {})

        opportunities = [
            item for item in state.get("validated", [])
            if item.get("recommendation") in ("PURSUE", "CONSIDER")
        ]
        total = len(opportunities)

        for idx, item in enumerate(opportunities, start=1):
            org = item.get("org", "")
            logger.info("[CONTACTS] enriching org %d of %d: %s", idx, total, org)

            if DRY_RUN:
                enriched = {
                    "website": "https://www.example-org.ca",
                    "domain": "example-org.ca",
                    "contacts": list(_FIXTURE_CONTACTS),
                }
                logger.info(
                    "[CONTACTS] %d contacts found for %s (DRY_RUN)",
                    len(enriched["contacts"]), org,
                )
                state["contacts"][item["url"]] = enriched
                continue

            # Hard per-org timeout via ThreadPoolExecutor — prevents IPv6 SYN_SENT
            # hangs from blocking the entire pipeline (SIGALRM cannot interrupt
            # C-level socket operations on macOS).
            # NOTE: do NOT use `with` — ThreadPoolExecutor.__exit__ calls
            # shutdown(wait=True) which re-blocks on the stuck thread.
            _per_org_timeout = int(os.environ.get("CONTACT_ORG_TIMEOUT_SECONDS", 60))
            _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(
                enrich_opportunity,
                org=org,
                title=item.get("title", ""),
                exec_summary=item.get("exec_summary", ""),
                suggested_angle=item.get("suggested_angle", ""),
                location=item.get("location", ""),
            )
            try:
                enriched = _fut.result(timeout=_per_org_timeout)
                _ex.shutdown(wait=False)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[CONTACTS] org '%s' timed out after %ds — skipping",
                    org, _per_org_timeout,
                )
                _ex.shutdown(wait=False)  # abandon stuck thread — do NOT wait
                state["contacts"][item["url"]] = {"contacts": [], "website": None, "domain": None}
                continue

            n = len(enriched.get("contacts", []))
            logger.info("[CONTACTS] %d contacts found for %s", n, org)
            state["contacts"][item["url"]] = enriched

        return state
