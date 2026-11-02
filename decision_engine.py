from issue_analysis import analyze_issues


DECISION_SAFE = "Safe to Publish"
DECISION_REVIEW = "Publish After Review"
DECISION_BLOCKED = "Do Not Publish Yet"
DECISION_INSUFFICIENT = "Insufficient Data"


def _count_by_severity(issues, severity):
    return sum(
        int(issue.get("count", 0))
        for issue in issues
        if issue.get("severity") == severity
    )


def _count_review_items(issues):
    return sum(
        int(issue.get("count", 0))
        for issue in issues
        if issue.get("requires_review", True)
    )



def _count_automatic_items(issues):
    return sum(
        int(issue.get("count", 0))
        for issue in issues
        if issue.get("auto_fix", False)
        and not issue.get("requires_review", True)
        and issue.get("severity") != "Critical"
    )


def determine_business_decision(results):
    """
    Converts technical quality results into a business-facing
    publication decision.

    This layer does not modify the catalog.
    It only interprets the existing quality results.
    """

    row_count = int(results.get("row_count", 0))
    health_score = int(results.get("health_score", 0))

    if row_count <= 0:
        return DECISION_INSUFFICIENT

    issues = analyze_issues(results)

    critical = _count_by_severity(issues, "Critical")
    high = _count_by_severity(issues, "High")
    review_items = _count_review_items(issues)

    # Critical issues always block publication.
    if critical > 0:
        return DECISION_BLOCKED

    # A very low health score or significant high-severity risk
    # means the catalog should not be published yet.
    if health_score < 60 or high >= max(5, row_count // 3):
        return DECISION_BLOCKED

    # Remaining review items mean publication should happen
    # only after those issues are checked.
    if review_items > 0:
        return DECISION_REVIEW

    return DECISION_SAFE


def get_decision_title(decision):
    titles = {
        DECISION_SAFE: "Safe to Publish",
        DECISION_REVIEW: "Publish After Review",
        DECISION_BLOCKED: "Do Not Publish Yet",
        DECISION_INSUFFICIENT: "Insufficient Data",
    }
    return titles.get(decision, "Review Required")


def get_decision_explanation(decision):
    explanations = {
        DECISION_SAFE: (
            "No unresolved quality issues currently require human review. "
            "The catalog can proceed to publication."
        ),
        DECISION_REVIEW: (
            "The catalog has unresolved issues that should be reviewed "
            "before publication."
        ),
        DECISION_BLOCKED: (
            "The catalog contains significant quality risks. "
            "Resolve or verify the flagged issues before publication."
        ),
        DECISION_INSUFFICIENT: (
            "There are not enough catalog records to make a meaningful "
            "quality or publication decision."
        ),
    }
    return explanations.get(
        decision,
        "The catalog requires further review."
    )


def get_recommended_next_action(decision):
    actions = {
        DECISION_SAFE: (
            "Proceed with your catalog upload or publishing workflow."
        ),
        DECISION_REVIEW: (
            "Review the remaining flagged records, resolve business-data "
            "issues, then run Catalog Rescue again."
        ),
        DECISION_BLOCKED: (
            "Resolve the highest-severity issues first, then re-run "
            "the analysis before publishing."
        ),
        DECISION_INSUFFICIENT: (
            "Upload a catalog containing at least one product record."
        ),
    }
    return actions.get(
        decision,
        "Review the catalog before continuing."
    )


def build_business_decision(results):
    """
    Return a complete business-facing decision payload.
    """

    decision = determine_business_decision(results)

    issues = analyze_issues(results)

    critical = _count_by_severity(issues, "Critical")
    high = _count_by_severity(issues, "High")
    medium = _count_by_severity(issues, "Medium")
    low = _count_by_severity(issues, "Low")

    review_items = _count_review_items(issues)
    automatic_items = _count_automatic_items(issues)

    row_count = int(results.get("row_count", 0))
    health_score = int(results.get("health_score", 0))

    return {
        "decision": decision,
        "title": get_decision_title(decision),
        "explanation": get_decision_explanation(decision),
        "next_action": get_recommended_next_action(decision),
        "health_score": health_score,
        "row_count": row_count,
        "issue_instances": sum(
            int(issue.get("count", 0))
            for issue in issues
        ),
        "review_items": review_items,
        "automatic_items": automatic_items,
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
    }