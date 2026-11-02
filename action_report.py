"""
Catalog Rescue Action Report

Builds a structured summary of what Catalog Rescue can safely
automate versus what still requires human judgment.

This module does not modify catalog data.
It only organizes remediation decisions for reporting and UI.
"""

from action_plan import (
    ACTION_AUTO_FIX,
    ACTION_REVIEW,
    ACTION_CRITICAL,
    build_action_plan,
    summarize_actions,
    count_action_types,
)


# ============================================================
# ACTION REPORT
# ============================================================

def build_action_report(issues):
    """
    Build a complete remediation report from detected issues.
    """

    plan = build_action_plan(issues)

    instance_summary = summarize_actions(plan)

    type_summary = count_action_types(plan)

    automatic_instances = instance_summary.get(
        ACTION_AUTO_FIX,
        0,
    )

    review_instances = instance_summary.get(
        ACTION_REVIEW,
        0,
    )

    critical_instances = instance_summary.get(
        ACTION_CRITICAL,
        0,
    )

    automatic_types = type_summary.get(
        ACTION_AUTO_FIX,
        0,
    )

    review_types = type_summary.get(
        ACTION_REVIEW,
        0,
    )

    critical_types = type_summary.get(
        ACTION_CRITICAL,
        0,
    )

    total_instances = (
        automatic_instances
        + review_instances
        + critical_instances
    )

    total_types = (
        automatic_types
        + review_types
        + critical_types
    )

    return {
        "plan": plan,

        # Issue-instance totals
        "total_instances": total_instances,
        "automatic_instances": automatic_instances,
        "review_instances": review_instances,
        "critical_instances": critical_instances,

        # Distinct issue-type totals
        "total_types": total_types,
        "automatic_types": automatic_types,
        "review_types": review_types,
        "critical_types": critical_types,

        # Human-readable status
        "automation_status": (
            "Safe automatic remediation available."
            if automatic_instances > 0
            else "No automatic remediation required."
        ),

        "review_status": (
            f"{review_instances} issue instances require "
            "human review."
            if review_instances > 0
            else "No human review items remain."
        ),

        "critical_status": (
            f"{critical_instances} critical issue instances "
            "require immediate attention."
            if critical_instances > 0
            else "No critical remediation actions detected."
        ),
    }


# ============================================================
# ACTION FILTERS
# ============================================================

def get_automatic_actions(report):
    """
    Return issues that are approved for safe automation.
    """

    if not isinstance(report, dict):
        return []

    return [
        issue
        for issue in report.get("plan", [])
        if issue.get("action") == ACTION_AUTO_FIX
    ]


def get_review_actions(report):
    """
    Return issues that require human review.
    """

    if not isinstance(report, dict):
        return []

    return [
        issue
        for issue in report.get("plan", [])
        if issue.get("action") == ACTION_REVIEW
    ]


def get_critical_actions(report):
    """
    Return critical remediation issues.
    """

    if not isinstance(report, dict):
        return []

    return [
        issue
        for issue in report.get("plan", [])
        if issue.get("action") == ACTION_CRITICAL
    ]


# ============================================================
# EXPORT-FRIENDLY SUMMARY
# ============================================================

def build_action_summary_rows(report):
    """
    Convert the action report into simple rows suitable for
    CSV, Excel, tables, or future API responses.
    """

    if not isinstance(report, dict):
        return []

    return [
        {
            "Action": "Automatic Fix",
            "Issue Types": report.get(
                "automatic_types",
                0,
            ),
            "Issue Instances": report.get(
                "automatic_instances",
                0,
            ),
            "Requires Human Review": "No",
        },
        {
            "Action": "Human Review",
            "Issue Types": report.get(
                "review_types",
                0,
            ),
            "Issue Instances": report.get(
                "review_instances",
                0,
            ),
            "Requires Human Review": "Yes",
        },
        {
            "Action": "Critical Action",
            "Issue Types": report.get(
                "critical_types",
                0,
            ),
            "Issue Instances": report.get(
                "critical_instances",
                0,
            ),
            "Requires Human Review": "Yes",
        },
    ]


# ============================================================
# BUSINESS SAFETY STATEMENT
# ============================================================

def get_safety_statement(report):
    """
    Return the customer-facing explanation of the remediation
    boundary.
    """

    if not isinstance(report, dict):
        return (
            "Catalog Rescue uses conservative remediation rules "
            "and does not invent business data."
        )

    return (
        "Catalog Rescue automatically applies only deterministic "
        "formatting changes that are explicitly approved by its "
        "quality rules. Business decisions such as resolving "
        "duplicate SKU ownership, filling missing business data, "
        "or validating suspicious prices remain under human control."
    )