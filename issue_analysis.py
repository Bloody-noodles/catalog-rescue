import pandas as pd

from rule_engine import enrich_issues


# ============================================================
# ISSUE DEFINITIONS
# ============================================================

ISSUE_DEFINITIONS = [
    {
        "key": "missing_columns",
        "severity": "Critical",
        "issue": "Missing required columns",
        "impact": "Catalog structure may be incompatible with downstream systems.",
    },
    {
        "key": "invalid_prices",
        "severity": "High",
        "issue": "Invalid prices",
        "impact": "Products may display incorrect or unusable pricing.",
    },
    {
        "key": "duplicate_skus",
        "severity": "High",
        "issue": "Duplicate SKUs",
        "impact": "Products may be duplicated or incorrectly matched.",
    },
    {
        "key": "blank_skus",
        "severity": "High",
        "issue": "Blank SKUs",
        "impact": "Products may be difficult to identify or synchronize.",
    },
    {
        "key": "invalid_emails",
        "severity": "High",
        "issue": "Invalid email addresses",
        "impact": "Customer or operational communications may fail.",
    },
    {
        "key": "invalid_urls",
        "severity": "High",
        "issue": "Invalid website URLs",
        "impact": "Product or business links may fail when published.",
    },
    {
        "key": "invalid_phones",
        "severity": "High",
        "issue": "Invalid phone numbers",
        "impact": "Customers or staff may be unable to contact the business.",
    },
    {
        "key": "missing_values",
        "severity": "Medium",
        "issue": "Missing values",
        "impact": "Incomplete product information may affect catalog quality.",
    },
    {
        "key": "missing_descriptions",
        "severity": "Medium",
        "issue": "Missing product descriptions",
        "impact": "Products may lack useful information for customers or marketplace listings.",
    },
    {
        "key": "duplicate_rows",
        "severity": "Medium",
        "issue": "Duplicate rows",
        "impact": "Repeated records can create catalog clutter and reporting errors.",
    },
    {
        "key": "category_variations",
        "severity": "Medium",
        "issue": "Category inconsistencies",
        "impact": "Inconsistent categories can affect filtering and reporting.",
    },
    {
        "key": "suspicious_prices",
        "severity": "Medium",
        "issue": "Suspicious prices",
        "impact": "Unusual prices may require business verification before publication.",
    },
    {
        "key": "invalid_sku_formats",
        "severity": "Medium",
        "issue": "Invalid SKU formats",
        "impact": "Inconsistent identifiers may cause matching or synchronization problems.",
    },
    {
        "key": "empty_columns",
        "severity": "Low",
        "issue": "Empty columns",
        "impact": "Unused columns can create unnecessary catalog structure and processing noise.",
    },
]


# ============================================================
# HELPERS
# ============================================================

def _count_result(value):
    """
    Safely count the number of detected issue records.
    """

    if isinstance(value, dict):
        return len(value)

    if isinstance(value, list):
        return len(value)

    if isinstance(value, pd.DataFrame):
        return len(value)

    return 0


# ============================================================
# ISSUE ANALYSIS
# ============================================================

def analyze_issues(results):
    """
    Convert raw quality-check results into structured issues.

    Each issue is subsequently enriched using the central
    rule registry.
    """

    issues = []

    for definition in ISSUE_DEFINITIONS:

        key = definition["key"]

        value = results.get(key, {})

        count = _count_result(value)

        # Missing values are stored as:
        #
        # {
        #     "price": 4,
        #     "category": 2
        # }
        #
        # Therefore their count must be the total number
        # of missing cells rather than the number of columns.
        if key == "missing_values":
            if isinstance(value, dict):
                count = sum(value.values())
            else:
                count = 0

        if count <= 0:
            continue

        issues.append(
            {
                "severity": definition["severity"],
                "issue": definition["issue"],
                "count": count,
                "impact": definition["impact"],
                "key": key,
            }
        )

    # --------------------------------------------------------
    # Attach centralized rule metadata.
    # --------------------------------------------------------

    return enrich_issues(issues)


# ============================================================
# IMPACT SUMMARY
# ============================================================

def calculate_impact_summary(issues):

    summary = {
        "Critical": 0,
        "High": 0,
        "Medium": 0,
        "Low": 0,
    }

    for issue in issues:

        severity = issue.get("severity")

        count = issue.get("count", 0)

        if severity in summary:
            summary[severity] += int(count)

    return summary


# ============================================================
# ISSUE DATAFRAME
# ============================================================

def build_issue_dataframe(issues):

    if not issues:
        return pd.DataFrame(
            columns=[
                "Severity",
                "Category",
                "Issue",
                "Count",
                "Automatic Fix",
                "Human Review",
                "Business Impact",
            ]
        )

    rows = []

    for issue in issues:

        rows.append(
            {
                "Severity": issue.get("severity", ""),
                "Category": issue.get("category", ""),
                "Issue": issue.get("issue", ""),
                "Count": issue.get("count", 0),
                "Automatic Fix": (
                    "Yes"
                    if issue.get("auto_fix", False)
                    else "No"
                ),
                "Human Review": (
                    "Yes"
                    if issue.get("requires_review", True)
                    else "No"
                ),
                "Business Impact": issue.get(
                    "impact",
                    "",
                ),
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# TOTAL ISSUE INSTANCES
# ============================================================

def calculate_total_issue_instances(results):

    issues = analyze_issues(results)

    return sum(
        issue["count"]
        for issue in issues
    )