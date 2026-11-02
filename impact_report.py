import pandas as pd

from issue_analysis import (
    analyze_issues,
    calculate_impact_summary,
)


# ==================================================
# RECORDS AFFECTED BY AUTOMATIC CLEANING
# ==================================================

def count_records_affected(change_log):

    if not isinstance(
        change_log,
        list
    ):

        return 0

    affected_rows = set()

    for change in change_log:

        if not isinstance(
            change,
            dict
        ):

            continue

        row = change.get(
            "row"
        )

        # Header changes are not catalog records.
        if row == "HEADER":
            continue

        if row is not None:

            affected_rows.add(
                row
            )

    return len(
        affected_rows
    )


# ==================================================
# ISSUE INSTANCE COUNT
# ==================================================

def count_result_items(results):

    issues = analyze_issues(
        results
    )

    return sum(
        issue.get(
            "count",
            0
        )
        for issue in issues
    )


# ==================================================
# ISSUE COUNT
# ==================================================

def calculate_issue_count(results):

    return count_result_items(
        results
    )


# ==================================================
# HUMAN REVIEW ITEMS
# ==================================================

def calculate_review_items(results):
    """
    Count issue instances that explicitly require human review.
    One record may require review for multiple independent issues.
    """
    issues = analyze_issues(results)

    return sum(
        int(issue.get("count", 0))
        for issue in issues
        if issue.get("requires_review", True)
    )

# ==================================================
# AFFECTED RECORD PERCENTAGE
# ==================================================

def calculate_affected_percentage(
    affected_records,
    total_records
):

    if total_records <= 0:
        return 0.0

    return (
        affected_records
        /
        total_records
    ) * 100


# ==================================================
# SCORE CHANGE
# ==================================================

def calculate_score_change(
    before_score,
    after_score
):

    return int(
        after_score
        -
        before_score
    )


# ==================================================
# BUILD IMPACT SUMMARY
# ==================================================

def build_impact_summary(
    before_results,
    after_results,
    change_log
):

    # ----------------------------------------------
    # BASIC RECORD COUNTS
    # ----------------------------------------------

    total_records = (
        before_results.get(
            "row_count",
            0
        )
    )

    # ----------------------------------------------
    # ISSUE COUNTS
    # ----------------------------------------------

    issues_before = (
        count_result_items(
            before_results
        )
    )

    issues_after = (
        count_result_items(
            after_results
        )
    )

    issues_resolved = max(
        0,
        issues_before
        -
        issues_after
    )

    # ----------------------------------------------
    # AUTOMATIC CLEANUP
    # ----------------------------------------------

    affected_records = (
        count_records_affected(
            change_log
        )
    )

    affected_percentage = (
        calculate_affected_percentage(
            affected_records,
            total_records
        )
    )

    automatic_changes = (
        len(change_log)
        if isinstance(
            change_log,
            list
        )
        else 0
    )

    # ----------------------------------------------
    # HUMAN REVIEW
    # ----------------------------------------------

    review_items = (
        calculate_review_items(
            after_results
        )
    )

    # ----------------------------------------------
    # HEALTH SCORES
    # ----------------------------------------------

    before_score = int(
        before_results.get(
            "health_score",
            0
        )
    )

    after_score = int(
        after_results.get(
            "health_score",
            0
        )
    )

    score_change = (
        calculate_score_change(
            before_score,
            after_score
        )
    )

    # ----------------------------------------------
    # SEVERITY DISTRIBUTION
    # ----------------------------------------------

    before_issues = analyze_issues(
        before_results
    )

    after_issues = analyze_issues(
        after_results
    )

    before_impact = (
        calculate_impact_summary(
            before_issues
        )
    )

    after_impact = (
        calculate_impact_summary(
            after_issues
        )
    )

    # ----------------------------------------------
    # RETURN SUMMARY
    # ----------------------------------------------

    return {

        "total_records":
            total_records,

        "issues_before":
            issues_before,

        "issues_after":
            issues_after,

        "issues_resolved":
            issues_resolved,

        "automatic_changes":
            automatic_changes,

        "affected_records":
            affected_records,

        "affected_percentage":
            affected_percentage,

        "review_items":
            review_items,

        "before_score":
            before_score,

        "after_score":
            after_score,

        "score_change":
            score_change,

        # ------------------------------------------
        # BEFORE SEVERITY
        # ------------------------------------------

        "critical_before":
            before_impact["Critical"],

        "high_before":
            before_impact["High"],

        "medium_before":
            before_impact["Medium"],

        "low_before":
            before_impact["Low"],

        # ------------------------------------------
        # AFTER SEVERITY
        # ------------------------------------------

        "critical_after":
            after_impact["Critical"],

        "high_after":
            after_impact["High"],

        "medium_after":
            after_impact["Medium"],

        "low_after":
            after_impact["Low"],

    }


# ==================================================
# EXPORT REPORT
# ==================================================

def build_export_report(
    before_results,
    after_results,
    impact_summary
):

    rows = [

        {
            "Metric":
                "Total Records",

            "Value":
                impact_summary[
                    "total_records"
                ],
        },

        {
            "Metric":
                "Issues Before Cleaning",

            "Value":
                impact_summary[
                    "issues_before"
                ],
        },

        {
            "Metric":
                "Issues After Cleaning",

            "Value":
                impact_summary[
                    "issues_after"
                ],
        },

        {
            "Metric":
                "Issues Resolved",

            "Value":
                impact_summary[
                    "issues_resolved"
                ],
        },

        {
            "Metric":
                "Automatic Changes",

            "Value":
                impact_summary[
                    "automatic_changes"
                ],
        },

        {
            "Metric":
                "Records Affected",

            "Value":
                impact_summary[
                    "affected_records"
                ],
        },

        {
            "Metric":
                "Affected Percentage",

            "Value":
                round(
                    impact_summary[
                        "affected_percentage"
                    ],
                    2
                ),
        },

        {
            "Metric":
                "Items Requiring Review",

            "Value":
                impact_summary[
                    "review_items"
                ],
        },

        {
            "Metric":
                "Health Score Before",

            "Value":
                impact_summary[
                    "before_score"
                ],
        },

        {
            "Metric":
                "Health Score After",

            "Value":
                impact_summary[
                    "after_score"
                ],
        },

        {
            "Metric":
                "Health Score Change",

            "Value":
                impact_summary[
                    "score_change"
                ],
        },

        {
            "Metric":
                "Critical Issues After",

            "Value":
                impact_summary[
                    "critical_after"
                ],
        },

        {
            "Metric":
                "High Issues After",

            "Value":
                impact_summary[
                    "high_after"
                ],
        },

        {
            "Metric":
                "Medium Issues After",

            "Value":
                impact_summary[
                    "medium_after"
                ],
        },

        {
            "Metric":
                "Low Issues After",

            "Value":
                impact_summary[
                    "low_after"
                ],
        },
    ]

    return pd.DataFrame(
        rows
    )