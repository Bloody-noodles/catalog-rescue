# Catalog Rescue

Catalog Rescue is a Streamlit application for inspecting, cleaning and assessing product-catalog data before it is published or passed to downstream systems.

It is designed to make catalog-quality problems visible and to distinguish safe, deterministic cleanup from issues that still need a human decision.

## What it does

- Accepts a product catalog for analysis and provides a sample catalog for trying the workflow.
- Checks catalog structure and required fields, including SKU, product name, price and category.
- Identifies data-quality issues such as missing values, duplicate SKUs or rows, invalid prices and malformed contact or link fields where those fields are present.
- Applies conservative normalization and records the changes in a change log.
- Reports catalog health, issue severity, business-facing publication guidance and remaining review work.
- Keeps potentially ambiguous or business-sensitive issues in a human-review workflow rather than silently changing or deleting records.
- Exports the cleaned catalog and supporting reports.

The application is an analysis and remediation aid. Its quality checks are practical validation rules, not proof that every product record is factually correct or ready for every commerce platform.

## Application workflow

1. Load a catalog or use the included sample data.
2. Review the detected quality issues.
3. Run the analysis and safe cleanup.
4. Compare the original and cleaned catalog.
5. Inspect the change log, unresolved issues and recommended actions.
6. Export the cleaned catalog and reports for further review.

## Tech stack

- Python
- Streamlit
- pandas
- openpyxl

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/Bloody-noodles/catalog-rescue.git
cd catalog-rescue
```

### 2. Create and activate a virtual environment

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Run the application

```bash
streamlit run app.py
```

Streamlit will print a local URL in the terminal, usually `http://localhost:8501`.

## Sample data

The `sample_data/` directory contains sample catalog files and generators used during development. The included `sample_data/messy_catalog.csv` demonstrates common catalog issues such as missing SKUs, inconsistent text formatting, duplicate records and problematic prices.

Use sample data to explore the workflow before uploading business data.

## Project structure

```text
catalog-rescue/
├── app.py                  # Streamlit user interface and workflow
├── cleaner.py              # Conservative cleanup and change logging
├── quality_checks.py       # Catalog quality checks
├── validators.py           # Field-level validation helpers
├── rules.py                # Quality-rule registry
├── rule_engine.py          # Rule metadata and issue enrichment
├── issue_analysis.py       # Issue analysis and review classification
├── action_plan.py          # Remediation action classification
├── action_report.py        # Remediation summaries
├── decision_engine.py      # Business-facing publication decision
├── report.py               # Quality report generation
├── impact_report.py        # Before/after impact and export reports
├── sample_data/            # Sample catalogs and data generators
├── tests/                  # Automated tests
└── requirements.txt        # Python dependencies
```

## Run tests

The repository includes unit tests using Python's standard `unittest` framework.

```bash
python -m unittest discover -s tests -v
```

## Data handling and review notes

- Work with a copy of important source catalogs and retain your own backups outside the application repository.
- Review the change log and unresolved issues before using an exported catalog.
- Duplicate SKUs and other ambiguous records should be checked against the source system; they should not be assumed to represent disposable duplicates.
- Do not upload confidential, personal or commercially sensitive catalog data unless you are authorised to do so and understand the environment in which the app is running.

## Current scope

Catalog Rescue is an evolving project. The current repository provides a local Streamlit workflow for catalog inspection, conservative cleanup, quality reporting and export. Integrations with commerce platforms, production deployment, authentication, multi-user access and automated synchronization are not documented as supported features.

## License

No license is currently specified. All rights remain with the repository owner unless a license is added.
