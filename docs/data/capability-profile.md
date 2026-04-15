# Client Capability Profile

> Configure this file for your organization before deploying the pipeline.
> The scoring agents load this profile to evaluate RFP-capability fit.

---
module: data/capability-profile
purpose: Define CLIENT_PROFILE constant and the scoring rubric used by ScoringAgent
dependencies: src/agents/scoring_agent.py
last_updated: 2026-03-03
---

## Purpose

Single source of truth for the client's capability profile. `CLIENT_PROFILE` is copied verbatim into `src/agents/scoring_agent.py`. No other file defines or duplicates this content.

---

## Scope

- Covers capability definition, score band thresholds, and disqualifier rules.
- Excludes: prompt template (in `agent/scorer.md`), critic validation logic (in `agent/scorer.md`).
- Editing this file requires simultaneous update to `scoring_agent.py` and a changelog entry.

---

## Key Decisions

- **Capabilities are ranked.** Primary listed first (weighted heavily), secondary follow (weighted moderately).
- **Disqualifiers are binary.** Any disqualifier present → `recommendation` must be `SKIP` regardless of score. ScoringCritic enforces this.
- **Score bands are fixed.** Changes require simultaneous updates to `agent/filter.md` and `operation/antipatterns.md`.
- **Full lifecycle taxonomy.** Covers all 12 domains from data collection through procurement/risk language — keywords feed extraction segmentation, capability match count, strategic fit score, and risk profile score.

---

## Constraints

- `CLIENT_PROFILE` must be a single Python string constant.
- Do not add client names or proprietary project details to this file — it may be committed to a shared repo.
- Maximum profile length: 600 words. Longer profiles inflate prompt tokens on every scoring call.

---

## Interfaces / Dependencies

**CLIENT_PROFILE (copy verbatim into scoring_agent.py):**

```
The client is a Canadian data and analytics consultancy specialising in end-to-end data lifecycle services:

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

PROCUREMENT / RFP DOMAIN LANGUAGE:
- RFP, RFQ, RFI, Statement of Work, mandatory requirements, rated criteria, contract value, submission deadline, public sector, evaluation committee

RISK LANGUAGE:
- vendor lock-in, integration risk, data migration risk, security risk, compliance risk, performance SLA, technical debt

DISQUALIFIERS (recommend SKIP regardless of score):
- Civil engineering, construction, or physical infrastructure
- Hardware procurement or physical asset management
- Medical devices or clinical healthcare delivery
- Legal services or court administration
- Staffing-only engagements with no deliverable output
```

**Score band thresholds:**

| Score | Recommendation | Meaning |
|-------|---------------|---------|
| 75–100 | PURSUE | Strong capability match, ideal client profile |
| 50–74 | CONSIDER | Partial match or non-ideal but winnable |
| 0–49 | SKIP | Weak match or disqualifier present |

---

## Capability Keywords (for extraction segmentation)

All terms below feed `extraction_utils.extract_rfp_content()` capability scoring and semantic segmentation:

**Data Collection:** APIs, REST, GraphQL, web scraping, batch ingestion, streaming ingestion, CDC, change data capture, connectors, ETL connectors, Kafka, Kinesis, PubSub, EventHub, NiFi, Fivetran

**Data Engineering:** Spark, PySpark, Databricks, Airflow, dbt, data quality checks, schema evolution, pipeline CI/CD, Delta Lake, Parquet, Iceberg

**Data Storage:** Snowflake, BigQuery, Redshift, PostgreSQL, MySQL, S3, ADLS, GCS, warehouse architecture, lakehouse architecture

**Data Processing / ELT:** Spark SQL, DAG orchestration, semantic modeling, cost-optimized compute, data transformation pipelines

**Analytics & BI:** Tableau, Power BI, Looker, dashboards, KPI modeling, analytics engineering, semantic layers

**ML / AI:** MLflow, supervised learning, unsupervised learning, NLP, LLM integration, embeddings, vector databases, feature stores, inference pipelines, model tuning

**Deployment (MLOps / DataOps):** CI/CD, GitHub Actions, Azure DevOps, Terraform, Docker, Kubernetes, model deployment APIs, batch inference, streaming inference

**Monitoring & Observability:** model drift detection, data quality monitoring, metrics, logs, tracing, alerting systems

**Security:** IAM, RBAC, encryption at rest, encryption in transit, secrets management, Key Vault, Secret Manager, PII handling

**Governance:** lineage, catalogs, metadata management, SOC2, ISO27001, compliance controls

**Cloud Infrastructure:** Azure, AWS, GCP, Terraform, Infrastructure-as-Code, landing zones, VPC, VNet, cloud IAM, security scanning, cost optimization, FinOps

**Procurement / RFP Domain Language:** RFP, RFQ, RFI, Statement of Work, mandatory requirements, rated criteria, contract value, submission deadline, public sector, evaluation committee

**Risk Language:** vendor lock-in, integration risk, data migration risk, security risk, compliance risk, performance SLA, technical debt

---

## Risks / Considerations

- **Profile staleness:** Update within the same sprint as any capability change. Stale profiles degrade scoring silently.
- **Disqualifier gaps:** Review after every false-positive PURSUE recommendation.
- **Score band note:** `FILTER_THRESHOLD=60` sits between SKIP and CONSIDER. Listings 50–59 are dropped before deep scoring by design.
