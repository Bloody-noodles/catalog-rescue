import pandas as pd

from issue_analysis import analyze_issues


def get_quality_status(score, row_count=None):
    if row_count is not None and row_count <= 0:
        return "Insufficient Data"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs Attention"
    if score >= 40:
        return "Poor"
    return "Critical"


def calculate_quality_dimensions(results):
    return {
        "Completeness": float(results.get("completeness", 0)),
        "Consistency": float(results.get("consistency", 0)),
        "Validity": float(results.get("validity", 0)),
        "Uniqueness": float(results.get("uniqueness", 0)),
    }


def get_top_problems(results, limit=6):
    problems = []

    missing_values = results.get("missing_values", {})
    if isinstance(missing_values, dict):
        count = sum(missing_values.values())
        if count > 0:
            problems.append(
                {
                    "problem": "Missing values",
                    "count": count,
                    "message": f"{count} missing values detected",
                }
            )

    problem_sources = [
        ("duplicate_skus", "Duplicate SKU records", "records affected by duplicate SKUs"),
        ("duplicate_rows", "Duplicate rows", "duplicate rows detected"),
        ("invalid_prices", "Invalid prices", "invalid price records detected"),
        ("suspicious_prices", "Suspicious prices", "prices require verification"),
        ("blank_skus", "Blank SKUs", "records have blank SKUs"),
        ("invalid_sku_formats", "Invalid SKU formats", "records have invalid SKU formats"),
        ("missing_descriptions", "Missing descriptions", "products are missing descriptions"),
        ("invalid_emails", "Invalid emails", "invalid email records detected"),
        ("invalid_urls", "Invalid URLs", "invalid website URLs detected"),
        ("invalid_phones", "Invalid phone numbers", "invalid phone records detected"),
        ("category_variations", "Category inconsistencies", "category consistency issues detected"),
        ("empty_columns", "Empty columns", "completely empty columns detected"),
    ]

    for key, title, description in problem_sources:
        value = results.get(key, {})
        if isinstance(value, dict):
            count = len(value)
        elif isinstance(value, list):
            count = len(value)
        elif isinstance(value, pd.DataFrame):
            count = len(value)
        else:
            count = 0

        if count <= 0:
            continue

        problems.append(
            {
                "problem": title,
                "count": count,
                "message": f"{count} {description}",
            }
        )

    problems.sort(key=lambda item: item["count"], reverse=True)
    return problems[:limit]


def build_recommendations(results):
    recommendations = []

    if results.get("row_count", 0) <= 0:
        return [
            "Upload a catalog containing at least one product record before assessing quality."
        ]

    missing_values = results.get("missing_values", {})
    if isinstance(missing_values, dict) and sum(missing_values.values()) > 0:
        recommendations.append(
            "Review missing product fields before publishing the catalog."
        )

    if len(results.get("duplicate_skus", [])) > 0:
        recommendations.append(
            "Review duplicate SKUs and confirm which records represent the same product."
        )

    if len(results.get("duplicate_rows", [])) > 0:
        recommendations.append(
            "Remove or consolidate exact duplicate records after verification."
        )

    if len(results.get("invalid_prices", [])) > 0:
        recommendations.append(
            "Verify invalid or non-positive prices before publishing."
        )

    if len(results.get("blank_skus", [])) > 0:
        recommendations.append(
            "Assign or verify SKUs for products that currently have none."
        )

    if len(results.get("invalid_emails", [])) > 0:
        recommendations.append(
            "Correct malformed email addresses before using the catalog operationally."
        )

    if len(results.get("invalid_urls", [])) > 0:
        recommendations.append(
            "Verify website URLs before publishing product or business links."
        )

    if len(results.get("invalid_phones", [])) > 0:
        recommendations.append(
            "Verify malformed phone numbers before customer-facing use."
        )

    if len(results.get("missing_descriptions", [])) > 0:
        recommendations.append(
            "Add product descriptions where marketplace or customer-facing listings require them."
        )

    if len(results.get("suspicious_prices", [])) > 0:
        recommendations.append(
            "Manually verify unusually low or high prices before publication."
        )

    if len(results.get("invalid_sku_formats", [])) > 0:
        recommendations.append(
            "Review SKU formatting for consistency before synchronization or marketplace upload."
        )

    if len(results.get("category_variations", {})) > 0:
        recommendations.append(
            "Standardize inconsistent category names before publishing or reporting."
        )

    if len(results.get("empty_columns", [])) > 0:
        recommendations.append(
            "Review completely empty columns and remove them if they are not required."
        )

    if not recommendations:
        recommendations.append(
            "No major remediation actions are currently required."
        )

    return recommendations


def _count_result(value):
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, pd.DataFrame):
        return len(value)
    return 0


def _issue_instance_count(results):
    try:
        return sum(issue.get("count", 0) for issue in analyze_issues(results))
    except Exception:
        return 0


def build_business_summary(results, impact_summary=None):
    row_count = int(results.get("row_count", 0))
    score = int(results.get("health_score", 0))
    status = results.get(
        "health_status",
        get_quality_status(score, row_count=row_count),
    )

    issues = analyze_issues(results)
    issue_instances = sum(int(issue.get("count", 0)) for issue in issues)

    severity = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for issue in issues:
        level = issue.get("severity", "Medium")
        if level in severity:
            severity[level] += int(issue.get("count", 0))

    
    automatic_instances = sum(
        int(issue.get("count", 0))
        for issue in issues
        if issue.get("auto_fix", False)
        and not issue.get("requires_review", True)
        and issue.get("severity") != "Critical"
    )


    if row_count <= 0:
        next_action = (
            "Provide a catalog containing at least one product record so quality can be assessed."
        )
        decision = "Not assessable yet"
    elif severity["Critical"] > 0:
        next_action = "Resolve critical structural issues before publication or synchronization."
        decision = "Block until critical issues are resolved"
    elif severity["High"] > 0:
        next_action = "Prioritize high-severity issues before publication or synchronization."
        decision = "Review high-risk issues before publishing"
    elif issue_instances > 0:
        next_action = "Work through the human review queue before final publication."
        decision = "Review remaining issues"
    else:
        next_action = "Catalog passes the current quality checks and is ready for normal publishing checks."
        decision = "Ready for normal publishing checks"

    summary = {
        "decision": decision,
        "next_action": next_action,
        "issue_instances": issue_instances,
        "critical_instances": severity["Critical"],
        "high_instances": severity["High"],
        "medium_instances": severity["Medium"],
        "low_instances": severity["Low"],
        "automatic_instances": automatic_instances,
        "health_score": score,
        "status": status,
        "row_count": row_count,
    }

    if isinstance(impact_summary, dict):
        summary["affected_records"] = int(impact_summary.get("affected_records", 0))
        summary["affected_percentage"] = float(
            impact_summary.get("affected_percentage", 0)
        )
        summary["issues_resolved"] = int(impact_summary.get("issues_resolved", 0))
    else:
        summary["affected_records"] = 0
        summary["affected_percentage"] = 0.0
        summary["issues_resolved"] = 0

    return summary


def build_quality_report(results, impact_summary=None):
    completeness = float(results.get("completeness", 0))
    consistency = float(results.get("consistency", 0))
    validity = float(results.get("validity", 0))
    uniqueness = float(results.get("uniqueness", 0))
    score = int(results.get("health_score", 0))
    row_count = int(results.get("row_count", 0))
    status = results.get(
        "health_status",
        get_quality_status(score, row_count=row_count),
    )

    top_problems = get_top_problems(results)
    recommendations = build_recommendations(results)
    dimensions = {
        "Completeness": completeness,
        "Consistency": consistency,
        "Validity": validity,
        "Uniqueness": uniqueness,
    }

    return {
        "health_score": score,
        "status": status,
        "data_status": results.get("data_status", "Ready for assessment"),
        "has_data": bool(results.get("has_data", row_count > 0)),
        "completeness": completeness,
        "consistency": consistency,
        "validity": validity,
        "uniqueness": uniqueness,
        "dimensions": dimensions,
        "top_problems": top_problems,
        "recommendations": recommendations,
        "business_summary": build_business_summary(results, impact_summary),
        "row_count": row_count,
        "column_count": results.get("column_count", 0),
    }


def build_report_dataframe(results):
    dimensions = calculate_quality_dimensions(results)
    rows = [
        {"Dimension": dimension, "Score": score}
        for dimension, score in dimensions.items()
    ]
    return pd.DataFrame(rows)
