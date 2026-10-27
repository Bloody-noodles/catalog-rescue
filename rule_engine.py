"""
Catalog Rescue Rule Engine

Provides a thin layer between the quality-check results
and the central rule registry.
"""

from rules import (
    get_rule,
    get_all_rules,
)


def get_rule_metadata(rule_id):
    """
    Return metadata for a rule.

    If a rule is not registered, return a safe fallback.
    """

    rule = get_rule(rule_id)

    if rule is not None:
        return rule

    return {
        "id": rule_id,
        "name": rule_id.replace("_", " ").title(),
        "category": "Other",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": "Unregistered quality issue.",
        "business_impact": (
            "This issue should be reviewed before publication."
        ),
    }


def enrich_issue(issue):
    """
    Add registry metadata to an existing issue dictionary.
    """

    rule_id = issue.get("key", "")

    metadata = get_rule_metadata(rule_id)

    enriched = issue.copy()

    enriched["rule_id"] = rule_id
    enriched["rule_name"] = metadata["name"]
    enriched["category"] = metadata["category"]
    enriched["severity"] = metadata["severity"]
    enriched["auto_fix"] = metadata["auto_fix"]
    enriched["requires_review"] = metadata["requires_review"]

    if not enriched.get("impact"):
        enriched["impact"] = metadata["business_impact"]

    return enriched


def enrich_issues(issues):
    """
    Enrich a list of detected issues with rule metadata.
    """

    return [
        enrich_issue(issue)
        for issue in issues
        if isinstance(issue, dict)
    ]


def summarize_registry():
    """
    Return a compact registry summary.
    """

    rules = get_all_rules()

    return {
        "total_rules": len(rules),
        "automatic_rules": sum(
            1
            for rule in rules
            if rule["auto_fix"]
        ),
        "review_rules": sum(
            1
            for rule in rules
            if rule["requires_review"]
        ),
    }