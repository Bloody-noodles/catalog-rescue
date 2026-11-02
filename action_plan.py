"""
Catalog Rescue Action Planning

Transforms detected quality issues into clear remediation
actions.

The purpose is to answer:

1. What can Catalog Rescue safely fix?
2. What requires human review?
3. What is critical?
"""


# ============================================================
# ACTION TYPES
# ============================================================

ACTION_AUTO_FIX = "Automatic Fix"

ACTION_REVIEW = "Human Review"

ACTION_CRITICAL = "Critical Action"


# ============================================================
# ACTION CLASSIFICATION
# ============================================================

def classify_issue_action(issue):
    """
    Determine the appropriate action for a detected issue.
    """

    if not isinstance(issue, dict):
        return ACTION_REVIEW

    severity = issue.get("severity", "Medium")
    auto_fix = issue.get("auto_fix", False)
    requires_review = issue.get("requires_review", True)

    # Critical problems always require intervention.
    if severity == "Critical":
        return ACTION_CRITICAL

    # Registry explicitly approves automatic remediation.
    if auto_fix and not requires_review:
        return ACTION_AUTO_FIX

    # Everything else remains under human control.
    return ACTION_REVIEW


# ============================================================
# ENRICH ISSUE
# ============================================================

def add_action_to_issue(issue):
    """
    Add an explicit remediation action to an issue.
    """

    enriched = issue.copy()

    enriched["action"] = classify_issue_action(issue)

    return enriched


def build_action_plan(issues):
    """
    Convert detected issues into an actionable remediation plan.
    """

    if not isinstance(issues, list):
        return []

    return [
        add_action_to_issue(issue)
        for issue in issues
        if isinstance(issue, dict)
    ]


# ============================================================
# ACTION SUMMARY
# ============================================================

def summarize_actions(issues):
    """
    Count issues by remediation action.
    """

    summary = {
        ACTION_AUTO_FIX: 0,
        ACTION_REVIEW: 0,
        ACTION_CRITICAL: 0,
    }

    for issue in issues:

        action = issue.get(
            "action",
            classify_issue_action(issue),
        )

        count = int(
            issue.get("count", 0)
        )

        if action in summary:
            summary[action] += count

    return summary


# ============================================================
# RECORD-LEVEL SUMMARY
# ============================================================

def count_action_types(issues):
    """
    Count the number of distinct issue types by action.
    """

    summary = {
        ACTION_AUTO_FIX: 0,
        ACTION_REVIEW: 0,
        ACTION_CRITICAL: 0,
    }

    for issue in issues:

        action = issue.get(
            "action",
            classify_issue_action(issue),
        )

        if action in summary:
            summary[action] += 1

    return summary