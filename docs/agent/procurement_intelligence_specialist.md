---
module: agent/procurement_intelligence_specialist
purpose: Define scrape sources, per-source strategy, listing schema, and deduplication contract
dependencies: src/agents/procurement_intelligence_specialist.py, src/database.py (is_duplicate)
last_updated: 2026-03-03 (updated same day: added SaskTenders + AlbertaPurchasing)
---

## Purpose

`ProcurementIntelligenceSpecialist` visits government procurement portals, extracts new RFP listings, filters duplicates via DB lookup, and writes to `state['listings']`. It is the first agent in the pipeline. The client operates in both **Canada and the USA** — all scrapers capture leads from both countries.

---

## Scope

- Covers eleven sources across Canada and USA: MERX, BidNet, RFPMart, CanadaBuys, BidsCanada, BidsAndTenders, CanadaTenders, GlobalTenders, SaskTenders, AlbertaPurchasing, TorontoBids.
- Excludes: BC Bid (CAPTCHA-blocked), scoring, contact discovery.
- Deduplication is URL-based only at this stage.

---

## Sources

| Source | URL | Method | Status | Notes |
|--------|-----|--------|--------|-------|
| MERX | `https://www.merx.com/public/solicitations/open` | Playwright | Active | Canada + USA; 26 listings/page; no login required |
| BidNet | `https://www.bidnetdirect.com/solicitations/open-bids` | Playwright | Active | Primarily USA; 26 listings/page; no login required |
| RFPMart | `https://www.rfpmart.com/data-research-analytics-rfp-government-contract.html` + IT category | requests+BS4 | Active | Canada + USA filtered; ~182 listings |
| CanadaBuys | `https://canadabuys.canada.ca/en/tender-opportunities?solr_document_type=tender_notice&status=0` | Playwright | Active | Canada only; JS-rendered table; ~50 listings |
| BidsCanada | `https://www.bidscanada.com/Default.CFM` (POST login → search) | requests+BS4 | Active (free tier) | Canada; 50 listings (free tier limit from 8,967 total); login via `BIDSCANADA_LOGIN` / `BIDSCANADA_PASSWORD` |
| BidsAndTenders | `https://metrovancouver.bidsandtenders.ca/Module/Tenders/en/Home/BidsHomepage` | Playwright | Active | Canada (Metro Vancouver); ~20 listings; login via `BIDS_AND_TENDERS_LOGIN` / `BIDS_AND_TENDERS_PASSWORD` |
| CanadaTenders | `https://www.canadatenders.com/tenders.php` | requests+BS4 | Subscription | Returns 0 without subscription; included for future use |
| GlobalTenders | `https://www.globaltenders.com/canada-tenders` | requests+BS4 | Subscription | Returns 0 without subscription; included for future use |
| SaskTenders | `https://sasktenders.ca/content/public/Search.aspx` | requests+BS4 | Active | Canada (SK); ~49 public listings; no login required |
| AlbertaPurchasing | `https://purchasing.alberta.ca/api/opportunity/search` | REST API (POST) | Active | Canada (AB); 16,365 total; returns 100 most-recent per call; no auth required |
| TorontoBids | `https://secure.toronto.ca/c3api_data/v2/DataAccess.svc/pmmd_solicitations/feis_solicitation_published` | REST API (GET, OData) | Active | Canada (Toronto); ~54 open solicitations; public, no auth; date-filtered dynamically |

**Evaluated but excluded:**

| Source | URL | Reason |
|--------|-----|--------|
| BC Bid | `bcbid.gov.bc.ca` | CAPTCHA bot-check blocks all automated access |
| Metro Vancouver | `metrovancouver.bidsandtenders.ca` | Covered via BidsAndTenders (same platform) |

---

## Key Decisions

- **Playwright for MERX, BidNet, CanadaBuys; requests+BS4 for others:** MERX, BidNet, and CanadaBuys render listings via JavaScript. Static HTTP is sufficient for RFPMart and the subscription-gated sites.
- **No country filtering on MERX/BidNet:** The client operates in both Canada and USA. OpportunityQualificationSpecialist handles relevance; ProcurementIntelligenceSpecialist captures all listings from these sources without geographic restriction.
- **RFPMart filtered to Canada + USA:** The `COUNTRIES = {"canada", "usa"}` set in `scrape_rfpmart()` enforces this. Other countries are excluded.
- **Per-source isolation:** Each scraper function runs in its own `try/except`. One failed source does not prevent others from running.
- **DRY_RUN bypass:** When `DRY_RUN=true`, `scrape_all()` returns five hardcoded fixture listings (MERX, CanadaBuys, BidNet, SaskTenders, AlbertaPurchasing) without any network calls.
- **User-Agent:** `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36` — set on all requests.

---

## Constraints

- `time.sleep(2)` required between page navigations on all Playwright flows.
- `scrape_all()` must return `[]` on complete failure — never raise.
- Each listing dict must contain all 7 required keys before being appended.
- Log format after each source: `[PROCUREMENT] {source}: found {n} listings`.

---

## Interfaces / Dependencies

**Listing schema (all keys required):**
```python
{
  "title":           str,   # RFP title as published
  "org":             str,   # Issuing organisation name
  "deadline":        str,   # ISO date string YYYY-MM-DD or raw text
  "value":           str,   # Contract value string or "Not specified"
  "url":             str,   # Canonical listing URL (used as dedup key)
  "source":          str,   # One of: MERX | BidNet | RFPMart | CanadaBuys | BidsCanada | BidsAndTenders | CanadaTenders | GlobalTenders | SaskTenders | AlbertaPurchasing | TorontoBids
  "raw_description": str,   # First 1000 chars of listing body text
}
```

**DB call:**
- `is_duplicate(url: str) -> bool` — called per listing before appending to state.

**State output:**
- `state['listings']`: list of listing dicts, all unique by URL.

---

## Risks / Considerations

- **Layout drift:** Portal HTML changes break CSS selectors silently — scraper returns 0 with no error. Add a minimum-results assertion in the weekly smoke test.
- **MERX selector:** `tr[class]` on `https://www.merx.com/public/solicitations/open`. Row text structure: `title / org / location / Published / date / Closing / date / ID`. Closing date is at index 6 of split lines.
- **CanadaBuys selector:** `table.eps-table tbody tr` with 5 cells: title+link / category / open-date / closing-date / org.
- **BidNet selector:** Same `tr[class]` pattern as MERX. Location at line index 1; closing date at index 5.
- **Playwright version lock:** Pin `playwright==1.44.0` in requirements.txt and re-run `playwright install chromium` after any upgrade.
- **Rate limiting:** `sleep(2)` is conservative; reduce only with evidence.
- **Subscription sources:** CanadaTenders, GlobalTenders return 0 without credentials. Activate by obtaining subscriptions.
- **BidsCanada auth flow:** GET login page → POST `Default.CFM` (UserName, Password, Page=250, PC=457DDD89) → extract `UID` and `SID` from redirect URL → POST search (Page=400, blank SearchTerms). Stable bid URL uses `BSID={bid_id}` from link href (not session-specific). Free tier returns 50 of 8,967 total listings.
- **BidsAndTenders auth flow:** Playwright login on `secure.bidsandtenders.ca` (fills `#Username`, `#Password`, clicks submit button) → cookies set on `.bidsandtenders.ca` domain → navigate to `metrovancouver.bidsandtenders.ca/Module/Tenders/en/Home/BidsHomepage`. Data rows contain `<td><strong>` title; action rows (next sibling) contain `/Tender/Detail/{uuid}` links. Session verifiable: URL should NOT contain `/Login` after submit.
- **BidsAndTenders scope:** Currently scrapes Metro Vancouver only (~20 listings). Extend by adding other `*.bidsandtenders.ca` subdomains (each buyer is a separate node). The same `secure.bidsandtenders.ca` session works across all nodes.
- **MERX (SOVRA):** The old URL `https://www.merx.com/English/SUPPLIER_Menu.cfm?WCI=PublicOpportunities` is dead. The new public URL requires no login.
- **SaskTenders row structure:** 7-cell `<tr>` rows: `[0]=sort-indicator, [1]=title, [2]=org, [3]=competition#, [4]=open-date, [5]=close-date, [6]=status`. Status values: `Open`, `Closed`, `Cancelled`. Print URLs (`print.aspx?competitionId=UUID`) appear in same DOM order as summary rows — zip them to get canonical URLs.
- **AlbertaPurchasing API:** POST to `https://purchasing.alberta.ca/api/opportunity/search` with JSON body. No auth header required; must include `Origin: https://purchasing.alberta.ca` and `Referer: https://purchasing.alberta.ca/search`. Response: `{values: [...], totalCount: N}`. Each item has `referenceNumber` (→ `/posting/{ref}` URL), `shortTitle`, `contractingOrganization`, `closeDateTime`, `projectDescription`.
- **AlbertaPurchasing pagination:** 16,365 total listings. Scraper fetches `limit=100, offset=0` (most recent 100) to keep pipeline manageable. Increase limit or add pagination if full coverage is needed.
- **BC Bid CAPTCHA:** `https://www.bcbid.gov.bc.ca` enforces a browser-check CAPTCHA. Even Playwright headless is blocked. Do not include until a CAPTCHA-solving service is integrated.
