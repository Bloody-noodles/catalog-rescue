# Catalog Rescue — Product & Architecture Master Plan

**Status:** Prototype/MVP → Production SaaS transition  
**Date:** November 1, 2026

## Vision

Catalog Rescue is not intended to remain a CSV cleaner or Streamlit demo.

The long-term product is a **catalog-data quality and governance platform** that helps organizations detect, understand, safely remediate, and continuously monitor product-data problems.

Core promise:

> Catalog Rescue helps organizations find catalog-data problems before those problems propagate into storefronts, marketplaces, feeds, PIMs, ERP systems, and internal operations.

Core principles:

- Never silently delete business records.
- Never invent business information.
- Never guess a correct price, SKU, brand, or product attribute without an explicit rule or trusted source.
- Separate safe normalization from human review.
- Audit every automated change.
- Give customers control over retention and deletion.
- Treat customer data as customer-owned.

## Current State

Live prototype: https://catalog-rescue.streamlit.app/  
GitHub repository: https://github.com/Bloody-noodles/catalog-rescue  
Local project: `C:\Users\PC\Desktop\catalog_rescue`

Local run:

```bash
streamlit run app.py
```

Current QA:

```bash
python run_batch23_qa.py
```

Current stack:

- Python
- Streamlit
- pandas
- openpyxl
- CSV/XLSX/XLS
- Existing validation, cleaning, rule, scoring, issue-analysis and reporting modules

Current capabilities:

- CSV/Excel upload
- Missing-data detection
- Duplicate detection
- Duplicate-SKU detection
- Invalid-value detection
- Formatting inconsistency detection
- Safe formatting corrections
- Quality metrics
- Issue analysis
- Reports
- Cleaned exports
- Change/audit information
- Built-in stress-test catalog

### Important status

The current Streamlit application is an **MVP/demo**, not yet an enterprise SaaS platform.

Do not market the current version as providing enterprise-grade security, compliance, availability, tenant isolation, or large-scale processing.

For sensitive production data, use anonymized/test data until the production security architecture is implemented.

---

# Target Product

The final product should be a **catalog-data quality and governance platform**, not merely an Excel cleaner.

Long-term positioning:

> **Detect, remediate and monitor product-catalog quality issues before they reach your sales channels.**

Potential customers:

1. Ecommerce distributors and wholesalers
2. Ecommerce implementation agencies
3. Mid-sized retailers with large catalogs
4. Multi-brand retailers
5. Manufacturers with substantial online catalogs
6. Marketplace operators
7. B2B suppliers
8. Large marketplace sellers

Ideal customer:

> Too much product data for reliable manual spreadsheet maintenance, but not large enough to already have a highly mature data-quality platform.

---

# Problems Solved

## Completeness

- Missing descriptions
- Missing prices
- Missing SKUs
- Missing brands
- Missing categories
- Missing product attributes
- Incomplete variants

## Consistency

- Naming inconsistencies
- Unit inconsistencies
- Formatting differences
- Capitalization differences
- Variant inconsistencies
- Category inconsistencies

## Validity

- Invalid prices
- Malformed identifiers
- Invalid field values
- Unexpected types
- Invalid formats

## Duplication

- Duplicate rows
- Duplicate SKUs
- Duplicate products
- Near-duplicate records

## Operational problems

- Supplier spreadsheets requiring manual cleanup
- Failed imports
- Marketplace-feed problems
- Catalog migration problems
- Catalog-quality regressions
- Repeated manual cleanup work

---

# Production Architecture

The Streamlit prototype should eventually become a thin client/demo layer over a real backend.

```text
                    CATALOG RESCUE
                         |
              +----------+----------+
              |                     |
        Web Application          Public API
              |                     |
              +----------+----------+
                         |
                   Authentication
                         |
                  Tenant / Workspace
                         |
              +----------+----------+
              |                     |
        File Ingestion          API Ingestion
              |                     |
              +----------+----------+
                         |
                    Object Storage
                         |
                    Job / Queue
                         |
              +----------+----------+
              |                     |
        Analysis Workers       Validation Workers
              |                     |
              +----------+----------+
                         |
                   Results Database
                         |
        +----------------+----------------+
        |                |                |
    Dashboard         Reports          Exports
        |                |                |
        +----------------+----------------+
                         |
                     Audit Log
```

---

# Architecture Layers

## 1. Frontend

Eventually a proper web application.

Responsibilities:

- Authentication
- Organization/workspace selection
- Catalog upload
- Job status
- Progress
- Catalog history
- Issue exploration
- Reports
- Review workflow
- Export
- Settings
- Team management
- Billing

Streamlit may remain useful for internal testing during migration.

## 2. API

The backend should expose controlled operations such as:

```text
POST /catalogs
POST /catalogs/{id}/analyze
GET  /catalogs/{id}/status
GET  /catalogs/{id}/report
GET  /catalogs/{id}/issues
POST /catalogs/{id}/review
POST /catalogs/{id}/export
DELETE /catalogs/{id}
```

Exact endpoint names may change during implementation.

## 3. Catalog Engine

The existing logic in:

- `cleaner.py`
- `quality_checks.py`
- `validators.py`
- `rules.py`
- `rule_engine.py`
- `issue_analysis.py`
- `decision_engine.py`
- `report.py`
- `action_report.py`
- `impact_report.py`
- `action_plan.py`

is valuable domain logic.

Extract it from Streamlit so it can run independently.

The engine should not depend on whether the caller is Streamlit, a web frontend, an API, a worker, or a CLI.

---

# Large-Data Strategy

Do not process giant catalogs inside normal HTTP requests.

Target:

```text
Upload
  ↓
Object storage
  ↓
Create job
  ↓
Queue
  ↓
Worker
  ↓
Inspect file
  ↓
Select processing strategy
  ↓
Process in chunks/partitions
  ↓
Run rules
  ↓
Aggregate results
  ↓
Persist results
  ↓
Generate report/export
  ↓
Notify frontend
```

Processing evolution:

### Small files

Pandas/Polars-style processing.

### Large files

Chunked/bounded-memory processing.

### Very large workloads

Parallel/distributed workers only when measurement justifies them.

Do not introduce Spark/Kubernetes/etc. simply because they sound enterprise-grade.

---

# Job System

Every analysis becomes a durable job:

```text
QUEUED
  ↓
PROCESSING
  ↓
VALIDATING
  ↓
REPORTING
  ↓
COMPLETED
```

Failure:

```text
FAILED
```

A job should record:

- job ID
- tenant ID
- catalog ID
- input version
- status
- progress
- worker information
- start time
- completion time
- error information
- retry count

Support:

- retries
- failure handling
- cancellation where feasible
- job prioritization
- per-tenant resource limits

---

# Multi-Tenancy

Organizations must be isolated.

```text
Organization A
 ├── Users
 ├── Catalogs
 ├── Jobs
 ├── Reports
 └── Audit events

Organization B
 ├── Users
 ├── Catalogs
 ├── Jobs
 ├── Reports
 └── Audit events
```

Every customer-owned object must have a tenant/organization relationship.

Tenant isolation must be enforced server-side and at the data layer, not only by frontend filtering.

Potential progression:

- Standard SaaS: strong logical tenant isolation and database authorization.
- Enterprise: dedicated database/schema, storage and/or processing resources.
- High-security: private/dedicated deployment.

---

# Database

PostgreSQL is the intended relational foundation.

Core entities:

```text
organizations
users
memberships
catalogs
catalog_versions
jobs
issues
issue_instances
rules
changes
reports
exports
audit_events
api_keys
subscriptions
```

Relationships must preserve organization ownership, catalog history, job history, issue history, automated changes, and user actions.

---

# Catalog Versioning

Catalogs should have versions:

```text
Catalog
 ├── v1
 ├── v2
 ├── v3
 └── v4
```

This enables:

- upload comparison
- quality trends
- regression detection
- historical reporting
- rollback/reference

Example:

```text
Health score:
67 → 72 → 81 → 89
```

---

# Continuous Quality Monitoring

Long-term, Catalog Rescue should monitor catalog quality over time.

Metrics:

- Completeness
- Consistency
- Validity
- Uniqueness
- Issue count
- Critical issue count
- Safe-change count
- Review-required count
- Health score

Example:

```text
Previous catalog: 91/100
New catalog:      74/100

Regression: -17

New problems:
42 missing attributes
13 duplicate SKUs
9 invalid values
```

---

# Safe Cleaning / Decision Engine

Automated changes must be rule-driven.

Every change should contain:

```text
catalog_version
record_id
field
original_value
new_value
rule_id
reason
classification
timestamp
actor
```

Classes:

```text
SAFE_AUTOMATION
REVIEW_REQUIRED
DO_NOT_CHANGE
```

Never manufacture business truth.

---

# Security

Security is a product requirement.

Required foundations:

- HTTPS/TLS
- Encryption at rest
- Secure secrets management
- Strong authentication
- Authorization
- Tenant isolation
- Role-based access control
- Secure file handling
- Input validation
- Rate limiting
- Audit logging
- Monitoring
- Backup/recovery
- Deletion controls
- Incident response procedures

Uploaded files must never be assumed trustworthy.

---

# Retention and Deletion

Eventually customers should control retention.

Possible policies:

```text
Delete after analysis
7 days
30 days
90 days
Custom
```

Deletion must account for:

- Original uploads
- Processed files
- Exports
- Cached results
- Database records
- Replicas
- Backups according to documented policy

---

# Authentication and Authorization

Organization roles:

```text
Owner
Admin
Catalog Manager
Analyst
Viewer
```

Potential permissions:

- Upload
- Analyze
- View issues
- Approve changes
- Export
- Delete
- Manage users
- Manage organization
- Manage billing
- API access

Enterprise evolution:

- MFA
- SSO
- SAML/OIDC
- SCIM
- Session controls

---

# Audit Trail

Example:

```text
2026-11-15 09:31
John uploaded catalog v18

2026-11-15 09:32
Analysis started

2026-11-15 09:47
Analysis completed

2026-11-15 09:49
Jane viewed report

2026-11-15 10:03
John approved 42 safe changes

2026-11-15 10:06
Clean catalog exported
```

---

# API and Integrations

Long-term integrations:

- CSV
- XLSX
- REST API
- SFTP
- Shopify
- WooCommerce
- BigCommerce
- Magento/Adobe Commerce
- PIM systems
- ERP systems
- Scheduled supplier feeds

Potential webhooks:

```text
catalog.analysis.started
catalog.analysis.completed
catalog.analysis.failed
catalog.export.completed
catalog.review.required
```

---

# AI Position

AI is optional.

Core reliability must not depend on an LLM being correct.

Deterministic rules handle deterministic problems.

AI may later assist with:

- Anomaly explanation
- Semantic duplicate detection
- Category mapping
- Attribute classification
- Suggested normalization
- Review prioritization

Model:

```text
DETERMINISTIC
    ↓
SAFE AUTOMATION

AI / HEURISTIC
    ↓
SUGGESTION
    ↓
HUMAN REVIEW
```

Never silently convert AI guesses into business truth.

---

# Commercial Evolution

The architecture should support a service-led start without locking the product into manual work.

```text
Free/sample audit
        ↓
Paid catalog audit
        ↓
Paid catalog cleanup
        ↓
Recurring catalog QA
        ↓
Catalog Rescue SaaS
        ↓
Enterprise / dedicated deployment
```

---

# Cost Strategy

The project starts from zero budget.

## $0 development phase

Use:

- Local development
- Local database
- Local workers
- Open-source software
- Existing GitHub repository
- Existing computer

Goal: build and prove the architecture locally.

## Low-cost hosted phase

Only deploy when needed.

Free tiers are useful for experimentation but are not equivalent to production enterprise capacity.

Example current Supabase free limits include a 500 MB database, 1 GB file storage, and project pausing after inactivity. Pro currently starts at $25/month. Treat these as development/early-stage constraints, not enterprise guarantees.

## Commercial phase

Once real customers exist, revenue should fund:

- Compute
- Storage
- Database
- Backups
- Monitoring
- Email
- Domain
- Security tooling
- Support

## Enterprise phase

Potential additional costs:

- Dedicated infrastructure
- Larger compute
- Stronger backups
- Security testing
- Compliance programs
- SSO/SCIM
- Dedicated environments
- Regional infrastructure

Rule:

> Do not pay for enterprise infrastructure before the product or customer requirement justifies it.

---

# Hosting Note

Vercel's current Hobby plan is $0/month but is intended for personal, non-commercial use. Pro is currently listed at $20/month and is intended for professional/business usage.

Therefore, do not assume Vercel Hobby is the final commercial hosting plan.

---

# Enterprise Readiness Roadmap

## Stage 0 — Prototype

Current:

```text
Streamlit
Python
pandas
CSV/XLSX
```

Goal: prove the engine.

## Stage 1 — Production Engine

Build:

- Independent catalog engine
- Backend API
- PostgreSQL
- Object-storage abstraction
- Job model
- Worker model
- Automated tests

Goal: separate the brain from the UI.

## Stage 2 — SaaS Foundation

Build:

- Frontend
- Authentication
- Organizations
- Tenant isolation
- Roles
- Catalog storage
- Catalog versions
- Jobs
- Reports
- Exports
- Audit logs

Goal: multiple customers can safely use the system.

## Stage 3 — Scale

Build:

- Chunked processing
- Queue
- Worker scaling
- Retries
- Resource limits
- Large-file handling
- Observability
- Performance testing

Goal: large catalogs become an engineering problem the system is designed to handle.

## Stage 4 — Security

Build:

- Hardened authentication
- RBAC
- MFA
- Secure file processing
- Encryption
- Retention/deletion
- Backups
- Disaster recovery
- Security logging
- Vulnerability management
- Incident response

Goal: make the platform defensible.

## Stage 5 — Enterprise

Build:

- SSO
- SCIM
- Dedicated environments
- Configurable retention
- Enterprise audit controls
- Security questionnaires
- Penetration testing
- Compliance readiness
- SLA capability

Goal: become a credible enterprise vendor.

## Stage 6 — Ecosystem

Build:

- APIs
- Webhooks
- Ecommerce integrations
- PIM integrations
- ERP integrations
- Supplier-feed automation
- Scheduled monitoring

Goal: become catalog-quality infrastructure rather than merely a catalog-cleaning application.

---

# Testing Strategy

## Unit tests

Rules, validators, cleaners, scoring.

## Integration tests

Database, storage, API, workers.

## Security tests

Authorization and tenant-isolation tests.

## Data tests

Known catalogs with expected outcomes.

## Regression tests

Every bug becomes a regression test.

## Load tests

Progressively test:

- 10k records
- 100k
- 500k
- 1M
- Larger datasets as infrastructure permits

Measure:

- Processing time
- Memory
- CPU
- Storage
- Failure rate

Never claim a scale limit without testing it.

---

# Observability

Production needs visibility into:

- Request latency
- Job duration
- Queue depth
- Worker failures
- Memory
- CPU
- Database performance
- Storage usage
- Error rates
- Tenant-level resource usage

Failures should be diagnosable without unnecessarily exposing customer data.

---

# November 2026 Objective

The goal is not to finish the enterprise product in November.

The goal is to move from:

```text
Streamlit MVP
```

toward:

```text
Production-oriented SaaS foundation
```

Priority:

### Week 1
Architecture specification, repository cleanup, engine boundaries.

### Week 2
Backend/API foundation and database models.

### Week 3
Catalog ingestion, object-storage abstraction, job/worker architecture.

### Week 4
Organizations, authentication, tenant isolation, catalog versions, reporting and hardening.

If time becomes constrained, prioritize the architecture and engine extraction over rushing incomplete enterprise features.

---

# Rules for Coding Agents

Any coding agent working on Catalog Rescue must read this file before modifying the project.

The agent must:

1. Understand the architecture before changing code.
2. Inspect the repository before replacing files.
3. Preserve working functionality.
4. Prefer incremental, testable changes.
5. Run existing QA/tests after meaningful changes.
6. Add regression tests for bugs.
7. Never claim enterprise readiness without evidence.
8. Never claim compliance certifications that do not exist.
9. Never weaken tenant isolation for convenience.
10. Never introduce secrets into source control.
11. Never expose customer data in logs.
12. Never silently change business data.
13. Explain architectural decisions affecting scalability.
14. Avoid unnecessary dependencies.
15. Avoid rewriting the entire application when targeted extraction is sufficient.

---

# Definition of Done — Production SaaS Foundation

The foundation is not complete until:

- The analysis engine runs independently of Streamlit.
- API and engine are separated.
- Large files are processed asynchronously.
- Jobs survive normal request lifecycle boundaries.
- Catalog data is stored outside application memory.
- Organizations/tenants exist.
- Tenant authorization is enforced server-side.
- Catalog versions exist.
- Results are persisted.
- Changes are auditable.
- Deletion is controllable.
- Authentication exists.
- RBAC exists.
- Critical rules have automated tests.
- Load testing establishes measured processing limits.
- Errors are observable.
- Secrets are managed securely.
- Production deployment is reproducible.
- Documentation explains data handling.

Only after this should strong enterprise-facing claims be made.

---

# Long-Term Destination

Catalog Rescue should evolve from:

> Upload an Excel file and get a cleaned Excel file.

into:

> **The quality-control layer between product-data sources and the systems that depend on them.**

Potential future flow:

```text
SUPPLIERS
    |
    +-- CSV
    +-- XLSX
    +-- API
    +-- SFTP
          |
          v
    CATALOG RESCUE
          |
     +----+----+
     |    |    |
   Detect Fix Monitor
     |    |    |
     +----+----+
          |
          v
       PIM / ERP
          |
          v
 Ecommerce / Marketplaces
```

Catalog Rescue is being evolved, not restarted.

The existing MVP is evidence that the core concept works.

The next objective is to turn the prototype's analysis engine into reliable, secure, scalable infrastructure.
