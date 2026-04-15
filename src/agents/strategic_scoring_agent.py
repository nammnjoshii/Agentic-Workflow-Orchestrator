import json
import logging
import os
import re
import time
from datetime import date, datetime

import anthropic
import requests

from src.database import has_score, get_scored_opportunity
from src.agents.extraction_utils import extract_rfp_content, parse_rfp_metadata
from src.config import CLIENT_NAME as _CLIENT_NAME, CLIENT_DESCRIPTION as _CLIENT_DESCRIPTION

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
_MODEL = "claude-sonnet-4-6"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "tests", "fixtures", "sample_scored.json"
)

CLIENT_PROFILE = f"""{_CLIENT_NAME} is {_CLIENT_DESCRIPTION} specialising in end-to-end data lifecycle services:

PRIMARY CAPABILITIES (weight heavily):
- Data Collection: APIs, REST, GraphQL, ETL connectors, Kafka, Kinesis, Fivetran, batch ingestion, streaming ingestion, CDC, change data capture, NiFi
- Data Engineering: Spark, PySpark, Databricks, Airflow, dbt, Delta Lake, Parquet, Iceberg, pipeline CI/CD, schema evolution, data quality checks
- Data Storage: Snowflake, BigQuery, Redshift, PostgreSQL, MySQL, S3, ADLS, GCS, warehouse architecture, lakehouse architecture
- Data Processing: Spark SQL, DAG orchestration, semantic modeling, cost-optimized compute, ELT transformation pipelines
- Analytics & BI: Power BI, Tableau, Looker, dashboards, KPI modeling, analytics engineering, semantic layers
- ML / AI: MLflow, supervised learning, unsupervised learning, NLP, LLM integration, embeddings, vector databases, feature stores, inference pipelines, model tuning
- Deployment (MLOps / DataOps): CI/CD, GitHub Actions, Azure DevOps, Terraform, Docker, Kubernetes, model deployment APIs, batch inference, streaming inference
- Monitoring & Observability: model drift detection, data quality monitoring, metrics, logs, tracing, alerting systems
- Security: IAM, RBAC, encryption at rest, encryption in transit, secrets management, Key Vault, Secret Manager, PII handling
- Governance: lineage, catalogs, metadata management, SOC2, ISO27001, compliance controls
- Cloud Infrastructure: Azure, AWS, GCP, Infrastructure-as-Code, landing zones, VPC, VNet, cloud IAM, security scanning, cost optimization, FinOps

SECONDARY CAPABILITIES (weight moderately):
- AI/ML implementation: LLM integration, RAG systems, model deployment
- Digital transformation strategy and roadmaps
- Indigenous data sovereignty frameworks
- Public sector reporting and compliance

IDEAL CLIENT PROFILE:
- Canadian government (federal, provincial, municipal) or Crown corporations
- US federal, state, or municipal government agencies
- Private sector in Canada or USA in regulated industries (energy, financial services, healthcare, public utilities)
- Contract value $100K–$5M
- Engagement duration 6–24 months
- Requires both strategy and technical delivery

DISQUALIFIERS (recommend SKIP regardless of score):
- Civil engineering, construction, or physical infrastructure
- Hardware procurement or physical asset management
- Medical devices or clinical healthcare delivery
- Legal services or court administration
- Staffing-only engagements with no deliverable output"""

# Flat capability keyword list used by extraction_utils for semantic segmentation
CAPABILITY_KEYWORDS: list[str] = [
    # Data Collection
    "APIs", "REST", "GraphQL", "ETL connectors", "Kafka", "Kinesis", "Fivetran",
    "batch ingestion", "streaming ingestion", "CDC", "change data capture", "NiFi",
    # Data Engineering
    "Spark", "PySpark", "Databricks", "Airflow", "dbt", "Delta Lake", "Parquet",
    "Iceberg", "pipeline", "schema evolution", "data quality",
    # Data Storage
    "Snowflake", "BigQuery", "Redshift", "PostgreSQL", "MySQL", "S3", "ADLS", "GCS",
    "warehouse", "lakehouse",
    # Analytics & BI
    "Power BI", "Tableau", "Looker", "dashboard", "KPI", "analytics engineering",
    # ML / AI
    "MLflow", "NLP", "LLM", "embeddings", "vector database", "feature store",
    "inference", "model deployment", "model tuning",
    # Deployment
    "Terraform", "Docker", "Kubernetes", "DevOps", "CI/CD",
    # Monitoring
    "drift detection", "data quality monitoring", "observability", "alerting",
    # Security
    "IAM", "RBAC", "encryption", "PII", "Key Vault", "secrets management",
    # Governance
    "lineage", "catalog", "metadata", "SOC2", "ISO27001", "compliance",
    # Cloud
    "Azure", "AWS", "GCP", "cloud", "FinOps", "Infrastructure-as-Code",
    # Procurement
    "RFP", "RFQ", "RFI", "Statement of Work", "evaluation criteria",
]

# System prompt: static company profile — eligible for prompt caching across repeated calls.
_SYSTEM_PROMPT = (
    "You are evaluating procurement opportunities for " + _CLIENT_NAME + ", " + _CLIENT_DESCRIPTION + ".\n\n"
    "Use the following company profile to assess RFP relevance:\n\n"
    + CLIENT_PROFILE
)

# User prompt: dynamic per-RFP content only.
_SCORING_USER_PROMPT = """\
Evaluate the following RFP opportunity and return a JSON object with exactly these 9 keys:
{{
  "relevance_score":  integer 0-100,
  "recommendation":   "PURSUE" | "CONSIDER" | "SKIP",
  "score_rationale":  string (2 sentences max),
  "capability_match": [list of matched company profile items],
  "risks":            [list of disqualifying or limiting factors],
  "estimated_effort": "S" | "M" | "L" | "XL",
  "exec_summary":     string (3 sentences max, suitable for email digest),
  "suggested_angle":  string (1 sentence positioning statement),
  "decision_log":     []
}}

Score bands: 75-100 = PURSUE, 50-74 = CONSIDER, 0-49 = SKIP.
If any disqualifier is present, set recommendation to SKIP regardless of score.
Reply with valid JSON only — no markdown fences, no explanation.

RFP CONTENT:
{rfp_text}"""

_REQUIRED_KEYS = {
    "relevance_score", "recommendation", "score_rationale",
    "capability_match", "risks", "estimated_effort",
    "exec_summary", "suggested_angle", "decision_log",
}


# ---------------------------------------------------------------------------
# Priority score helpers (deterministic — no API call)
# ---------------------------------------------------------------------------

def _rfp_type_score(title: str, source: str) -> int:
    """Score 0–100 based on procurement type detected in title or source."""
    text = f"{title} {source}".upper()
    if "RFP" in text or "REQUEST FOR PROPOSAL" in text:
        return 100
    if "RFQ" in text or "REQUEST FOR QUOTATION" in text:
        return 70
    if "RFI" in text or "REQUEST FOR INFORMATION" in text:
        return 50
    return 30


def _value_score(value_str: str) -> int:
    """Score 0–100 based on estimated contract value."""
    if not value_str:
        return 50
    text = str(value_str).upper().replace(",", "")
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return 50
    amount = float(nums[0])
    if "M" in text or "MILLION" in text:
        amount *= 1_000_000
    elif "K" in text or "THOUSAND" in text:
        amount *= 1_000
    if amount >= 1_000_000:
        return 100
    if amount >= 500_000:
        return 80
    if amount >= 100_000:
        return 60
    return 20


def _time_left_score(deadline_str: str) -> int:
    """Score 0–100 based on days remaining until deadline."""
    if not deadline_str:
        return 50
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y"]
    for fmt in formats:
        try:
            deadline = datetime.strptime(deadline_str.strip(), fmt).date()
            days_left = (deadline - date.today()).days
            if days_left > 60:
                return 100
            if days_left >= 30:
                return 70
            if days_left >= 14:
                return 40
            return 20
        except ValueError:
            continue
    return 50


# Primary capability keywords — extracted from the PRIMARY CAPABILITIES section of CLIENT_PROFILE.
# Used by _capability_quality_score to distinguish primary vs generic matches.
_PRIMARY_CAPABILITY_KEYWORDS: frozenset = frozenset({
    # Data Collection
    "api", "rest", "graphql", "etl", "kafka", "kinesis", "fivetran",
    "ingestion", "cdc", "nifi",
    "pubsub", "eventhub", "streaming", "batch", "web scraping", "connectors",
    "change data capture",
    # Data Engineering
    "spark", "pyspark", "databricks", "airflow", "dbt", "delta lake",
    "parquet", "iceberg", "pipeline", "schema evolution", "data quality",
    "apache flink", "apache beam", "confluent", "prefect", "dagster",
    # Data Processing / ELT (full sub-domain)
    "spark sql", "dag", "orchestration", "semantic modeling", "elt",
    "data transformation", "data processing", "cost optimization",
    # Data Storage
    "snowflake", "bigquery", "redshift", "postgresql", "mysql", "s3",
    "adls", "gcs", "warehouse", "lakehouse",
    "azure synapse", "azure data factory", "microsoft fabric",
    # Analytics & BI
    "power bi", "tableau", "looker", "dashboard", "kpi", "analytics engineering",
    "semantic layer", "reporting", "visualization", "business intelligence",
    # ML / AI
    "mlflow", "nlp", "llm", "embeddings", "vector database", "feature store",
    "inference", "model deployment", "model tuning",
    "supervised learning", "unsupervised learning", "rag", "retrieval augmented",
    "batch inference", "streaming inference", "machine learning",
    "artificial intelligence", "deep learning", "generative ai",
    "databricks unity catalog", "dbt cloud", "great expectations",
    # Deployment (MLOps / DataOps)
    "terraform", "docker", "kubernetes", "devops", "ci/cd",
    "github actions", "azure devops", "model serving", "mlops", "dataops",
    # Monitoring & Observability
    "drift detection", "data quality monitoring", "observability", "alerting",
    "metrics", "logs", "tracing", "monitoring",
    # Security
    "iam", "rbac", "encryption", "pii", "key vault", "secrets management",
    "secret manager", "encryption at rest", "encryption in transit",
    "data masking", "tokenization",
    # Governance
    "lineage", "catalog", "metadata", "soc2", "iso27001", "compliance",
    # Cloud Infrastructure
    "azure", "aws", "gcp", "finops", "infrastructure-as-code",
    "landing zone", "vpc", "vnet", "security scanning", "cloud migration",
    "modernization",
    # Data Management (practical RFP language)
    "data mesh", "data fabric", "data lake", "data lakehouse",
    "data integration", "data migration", "master data", "mdm",
    "data catalog", "data lineage", "open data", "data sharing",
    "data architecture", "data governance", "data strategy",
    # Secondary / Strategic
    "digital transformation", "public sector", "indigenous data",
    "data sovereignty", "microservices", "serverless", "real-time",
    # NoSQL / Modern Databases
    "mongodb", "redis", "elasticsearch", "opensearch", "dynamodb",
    "cassandra", "cosmosdb", "couchdb", "neo4j", "influxdb",
    # Legacy / Enterprise ETL (modernisation RFPs name the tool being replaced)
    "talend", "informatica", "ssis", "matillion", "airbyte",
    "boomi", "mulesoft", "pentaho", "stitch",
    # Cloud ML Platforms
    "sagemaker", "azure machine learning", "vertex ai", "kubeflow",
    "metaflow", "bentoml", "seldon", "ray",
    # Data Catalog / Governance Platforms
    "collibra", "alation", "microsoft purview", "azure purview",
    "datahub", "apache atlas", "amundsen", "openmetadata",
    # Query Engines
    "hive", "trino", "presto", "athena", "aws glue", "aws emr",
    "databricks sql",
    # Monitoring / Observability Tools
    "grafana", "prometheus", "datadog", "splunk", "elastic",
    "elk stack", "new relic", "dynatrace",
    # Privacy / Regulatory (mandatory in Canadian/US gov RFPs)
    "gdpr", "pipeda", "hipaa", "fedramp", "privacy",
    "data residency", "data localization", "privacy by design",
    # Identity / Auth
    "active directory", "okta", "sso", "saml", "ldap", "oauth",
    "zero trust", "identity management",
    # Analytics Domain Patterns
    "predictive analytics", "prescriptive analytics", "descriptive analytics",
    "geospatial", "gis", "spatial analytics", "self-service analytics",
    "data platform", "analytics platform", "data hub", "data exchange",
    "medallion architecture", "data products", "data contracts",
    "event-driven", "event sourcing",
    # Integration / Middleware
    "api management", "api gateway", "service mesh", "integration platform",
    "interoperability", "message queue", "message broker",
    # Data Engineering Frameworks (Python stack)
    "dask", "polars", "pandas", "numpy",
    # Cloud Services (named in RFPs)
    "aws lambda", "aws emr", "azure functions", "google cloud run",
    "cloud run", "serverless functions",
    # Data Fundamentals (common in all data RFPs)
    "data analytics", "data warehouse", "data science", "data modeling",
    "data modelling", "information management", "data modernization",
    "cloud data platform", "enterprise data platform", "database development",
    "data lifecycle", "data lifecycle management",
    # Cloud — expanded terms
    "amazon web services", "google dataflow", "logic apps",
    "hybrid cloud", "cloud security", "cloud-first", "cloud hosting",
    "secure data sharing", "sql analytics", "performance optimization",
    # ML / AI — expanded
    "forecasting", "model governance", "data science services",
    "classification models", "regression models", "time series",
    # Security / Gov — expanded
    "phi", "cybersecurity", "audit log", "audit logging",
    "data classification", "security assessment",
    # Government program language
    "shared services", "digital acceleration", "im/it",
    "enterprise architecture", "solution architecture",
    # Project / org descriptors (high-value indicators)
    "enterprise data program", "center of excellence",
    "analytics center of excellence", "analytics modernization",
    "reporting modernization", "ai adoption", "data-driven",
    # Roles that signal a data project (appear in scope descriptions)
    "data engineer", "data architect", "data scientist", "ml engineer",
    "bi developer", "analytics consultant", "database administrator",
    "information management specialist",
})

# Core data-analytics terms — used by _core_da_score to directly boost pure DA opportunities.
_CORE_DA_TERMS: frozenset = frozenset({
    "data analytics", "data analysis", "analytics services",
    "data and analytics", "analytics platform", "data platform",
    "data science", "business intelligence", "data warehouse",
    "information management", "data management", "data engineering",
    "analytics consulting", "data strategy", "data modernization",
})

# Hard disqualifier patterns — risks containing these text patterns warrant a hard penalty.
_HARD_RISK_PATTERNS: tuple = (
    "civil engineering", "construction", "physical infrastructure",
    "hardware procurement", "physical asset", "medical device",
    "clinical healthcare", "legal services", "court administration",
    "staffing-only", "staffing only",
)

# ---------------------------------------------------------------------------
# Geographic affinity patterns (v2) — West Coast Canada + USA priority
# ---------------------------------------------------------------------------

# British Columbia — highest priority market
_GEO_WEST_COAST_BC: tuple = (
    "british columbia", " bc ", "bcgov", "city of vancouver",
    "city of surrey", "city of burnaby", "city of richmond", "city of kelowna",
    "city of victoria", "city of abbotsford", "city of coquitlam",
    "metro vancouver", "translink", "bc hydro", "bc transit",
    "province of british columbia",
)

# Washington, Oregon, California — co-equal priority with BC
_GEO_WEST_COAST_US: tuple = (
    "washington state", "state of washington", "seattle", "tacoma", "spokane",
    "portland", "state of oregon", "oregon department",
    "california", "san francisco", "los angeles", "san jose", "san diego",
    "sacramento", "california department",
)

# Other Canadian or US regions — still relevant, lower priority than west coast
_GEO_CANADA_OR_US: tuple = (
    "canada", "ontario", "alberta", "quebec", "nova scotia", "new brunswick",
    "manitoba", "saskatchewan", "newfoundland", "yukon", "nunavut",
    "government of canada", "united states", "federal",
    "state of ", "city of ", "county of ",
)


def _capability_quality_score(capability_match: list) -> int:
    """Score 0–100 based on capability quality (PRIMARY vs generic match).

    3+ primary matches → 100, 2 primary → 85, 1 primary → 60,
    matches but none primary → 30, no matches → 0.
    """
    if not capability_match:
        return 0
    matches_lower = [m.lower() for m in capability_match]
    primary_hits = sum(
        1 for m in matches_lower
        if any(pk in m or m in pk for pk in _PRIMARY_CAPABILITY_KEYWORDS)
    )
    if primary_hits >= 3:
        return 100
    if primary_hits == 2:
        return 85
    if primary_hits == 1:
        return 60
    return 30  # has matches but none are primary capabilities


def _risk_profile_score(risks: list) -> int:
    """Score 0–100 inversely proportional to risks, with severity weighting.

    Hard disqualifier patterns count as maximum severity.
    0 risks → 100, 1 soft → 70, 2 soft → 40, 1 hard or 3+ soft → 20.
    """
    if not risks:
        return 100
    risk_text = " ".join(risks).lower()
    if any(p in risk_text for p in _HARD_RISK_PATTERNS):
        return 20
    n = len(risks)
    if n == 1:
        return 70
    if n == 2:
        return 40
    return 20


def _description_richness_score(listing: dict) -> int:
    """Score 0–100 based on how much metadata is available for this listing.

    More available metadata → higher confidence in the computed priority score.
    Points awarded (1 each): title, org, non-empty contract value, deadline, long description.
    Mapping: 5→100, 4→80, 3→60, 2→40, 0-1→10.
    """
    points = 0
    if listing.get("title"):
        points += 1
    if listing.get("org"):
        points += 1
    v = (listing.get("value") or "").strip().lower()
    if v and v != "not specified":
        points += 1
    if listing.get("deadline"):
        points += 1
    desc = listing.get("raw_description") or listing.get("description") or ""
    if len(desc) > 200:
        points += 1
    return {5: 100, 4: 80, 3: 60, 2: 40}.get(points, 10)


def _geo_affinity_score(listing: dict) -> int:
    """Score 0–100 reflecting geographic priority (v2).

    West Coast Canada (BC) or USA (WA/OR/CA) = 100.
    Other Canadian or US region = 50.
    Unknown / international = 30.
    BCBid source is an unconditional BC signal (score=100).
    """
    source = (listing.get("source") or "").lower()
    if source == "bcbid":
        return 100

    text = " ".join([
        listing.get("title") or "",
        listing.get("org") or "",
        listing.get("location") or "",
        (listing.get("raw_description") or "")[:500],
    ]).lower()

    for pattern in _GEO_WEST_COAST_BC:
        if pattern in text:
            return 100

    for pattern in _GEO_WEST_COAST_US:
        if pattern in text:
            return 100

    for pattern in _GEO_CANADA_OR_US:
        if pattern in text or pattern in source:
            return 50

    return 30


def _core_da_score(listing: dict, scored: dict) -> int:
    """Score 0–100 reflecting how directly this is a core data-analytics opportunity.

    Title or capability_match containing a core DA term → 100.
    Description only → 60.
    No match → 10.
    """
    title = (listing.get("title") or "").lower()
    cap_matches = [m.lower() for m in (scored.get("capability_match") or [])]
    for term in _CORE_DA_TERMS:
        if term in title or any(term in m for m in cap_matches):
            return 100
    desc = ((listing.get("raw_description") or listing.get("description") or "")[:300]).lower()
    for term in _CORE_DA_TERMS:
        if term in desc:
            return 60
    return 10


def compute_priority_score(listing: dict, scored: dict) -> int:
    """Compute opportunity_priority_score (0–100 int) from listing metadata + scored fields.

    Weights (v4 — 6 components, core DA boost replaces time_left):
      relevance_score               35%  (primary fit signal from Claude)
      capability_quality_score      20%  (strongest concrete fit evidence)
      geographic_affinity_score     15%  (BC/WA/OR/CA = full score — primary markets)
      core_da_score                 10%  (direct data-analytics title/match bonus)
      estimated_contract_value      10%  (raised from 5% — $5M vs $50K is a real decision)
      risk_profile_score            10%  (raised from 5% — hard disqualifiers need more weight)
    Removed: time_left_score (urgency is implicit in deadline — less important than fit signal)
    """
    relevance = int(scored.get("relevance_score") or 0)
    value = _value_score(listing.get("value", ""))
    cap_quality = _capability_quality_score(scored.get("capability_match", []))
    risk = _risk_profile_score(scored.get("risks", []))
    geo = _geo_affinity_score(listing)
    core_da = _core_da_score(listing, scored)

    raw = (
        relevance * 0.35
        + value * 0.10
        + core_da * 0.10
        + cap_quality * 0.20
        + risk * 0.10
        + geo * 0.15
    )
    return int(round(min(100.0, raw)))


# ---------------------------------------------------------------------------
# Document fetch + section extraction
# ---------------------------------------------------------------------------

def _fetch_rfp_text(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _load_from_db(url: str):
    return get_scored_opportunity(url)


# ---------------------------------------------------------------------------
# ScoringAgent
# ---------------------------------------------------------------------------

class StrategicScoringAgent:
    def __init__(self):
        self._client = anthropic.Anthropic()

    def _score_listing(self, listing: dict) -> dict:
        raw_desc = (listing.get("raw_description") or "").strip()

        # Fetch live URL — fall back gracefully on auth walls / network errors.
        # BCBid requires Camoufox; plain requests.get returns iV challenge HTML —
        # skip URL fetch entirely and rely on raw_description from the scraper.
        rfp_html = ""
        metadata = {}
        if listing.get("source") != "BCBid":
            try:
                rfp_html = _fetch_rfp_text(listing["url"])
                metadata = parse_rfp_metadata(rfp_html)
            except Exception as exc:
                logger.warning("[SCORER] URL fetch failed for %s: %s — using raw_description", listing["url"], exc)

        # Enrich listing value from parsed budget if not already specified
        if metadata.get("budget"):
            existing = (listing.get("value") or "").strip().lower()
            if not existing or existing == "not specified":
                listing["value"] = metadata["budget"]

        relevant = extract_rfp_content(
            text=rfp_html,
            title=listing.get("title", ""),
            source=listing.get("source", ""),
            capabilities=CAPABILITY_KEYWORDS,
        ) if rfp_html else ""

        # Supplement with raw_description when extracted content is sparse
        # (happens when the portal requires auth or uses JS rendering)
        word_count = len(relevant.split())
        if word_count < 150 and raw_desc:
            logger.info(
                "[SCORER] extracted %d words — supplementing with raw_description (%d chars)",
                word_count, len(raw_desc),
            )
            header = "Title: {}\nOrg: {}\n\n".format(
                listing.get("title", ""), listing.get("org", "")
            )
            relevant = (header + raw_desc + ("\n\n" + relevant if relevant else "")).strip()

        # Prepend structured metadata header so Sonnet sees labeled fields first
        if metadata:
            meta_lines = []
            if "budget" in metadata:
                meta_lines.append("Budget/Value: " + metadata["budget"])
            if "duration" in metadata:
                meta_lines.append("Contract Duration: " + metadata["duration"])
            if "department" in metadata:
                meta_lines.append("Issuing Department: " + metadata["department"])
            if "closing_date" in metadata:
                meta_lines.append("Closing Date: " + metadata["closing_date"])
            if meta_lines:
                relevant = (
                    "STRUCTURED METADATA:\n"
                    + "\n".join(meta_lines)
                    + "\n\n"
                    + relevant
                )

        user_content = _SCORING_USER_PROMPT.format(rfp_text=relevant)
        message = self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            temperature=0,
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        usage = getattr(message, "usage", None)
        raw = _strip_fences(message.content[0].text)
        scored = json.loads(raw)

        if not _REQUIRED_KEYS.issubset(scored.keys()):
            missing = _REQUIRED_KEYS - scored.keys()
            raise ValueError(f"Scored response missing keys: {missing}")

        scored["opportunity_priority_score"] = compute_priority_score(listing, scored)
        return scored, usage

    def run(self, state: dict) -> dict:
        state.setdefault("scored", [])
        tokens_in = 0
        tokens_out = 0

        for listing in state.get("filtered", []):
            url = listing["url"]
            title = listing.get("title", url)

            # Cache hit — load from DB, skip API call
            if has_score(url):
                cached = _load_from_db(url)
                if cached:
                    if "opportunity_priority_score" not in cached:
                        cached["opportunity_priority_score"] = compute_priority_score(listing, cached)
                    logger.info(
                        "[SCORER] cache hit %s → %s %s",
                        title, cached.get("relevance_score"), cached.get("recommendation"),
                    )
                    state["scored"].append({**listing, **cached})
                    continue

            # DRY_RUN — return fixture
            if DRY_RUN:
                with open(_FIXTURE_PATH) as f:
                    scored = json.load(f)
                scored["opportunity_priority_score"] = compute_priority_score(listing, scored)
                logger.info(
                    "[SCORER] scored %s → %s %s (DRY_RUN)",
                    title, scored["relevance_score"], scored["recommendation"],
                )
                state["scored"].append({**listing, **scored})
                continue

            scored = None
            for attempt in range(3):
                try:
                    scored, usage = self._score_listing(listing)
                    if usage:
                        tokens_in += getattr(usage, "input_tokens", 0)
                        tokens_out += getattr(usage, "output_tokens", 0)
                    break
                except anthropic.RateLimitError:
                    wait = 2 ** attempt
                    logger.warning("[SCORER] rate limited — waiting %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                except Exception as exc:
                    logger.warning("[SCORER] failed on %s: %s", title, exc)
                    scored = None
                    break
            else:
                logger.warning("[SCORER] failed on %s after max retries", title)
                scored = None
            if scored is None:
                continue

            logger.info(
                "[SCORER] scored %s → %s %s",
                title, scored["relevance_score"], scored["recommendation"],
            )
            state["scored"].append({**listing, **scored})

        state.setdefault("token_usage", {})[self.__class__.__name__] = {
            "input": tokens_in,
            "output": tokens_out,
        }
        return state

