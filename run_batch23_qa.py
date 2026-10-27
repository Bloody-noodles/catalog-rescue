import os
import sys
import traceback
import pandas as pd

from quality_checks import run_quality_checks
from cleaner import clean_catalog
from issue_analysis import analyze_issues
from action_report import build_action_report
from impact_report import build_impact_summary, calculate_review_items
from decision_engine import _count_automatic_items
import impact_report
import report
from unittest.mock import patch
from action_plan import (
    ACTION_AUTO_FIX,
    ACTION_REVIEW,
    ACTION_CRITICAL,
    classify_issue_action,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE_DIR, "sample_data", "adversarial")

TEST_FILES = [
    "01_missing_required_columns.csv",
    "02_empty_columns.csv",
    "03_empty_catalog.csv",
    "04_duplicate_heavy.csv",
    "05_garbage_values.csv",
    "06_weird_headers.csv",
    "07_minimal_valid.csv",
    "08_clean_catalog.csv",
    "09_mixed_types_display.csv",
    "10_boundary_values.csv",
]


def require(condition, message):
    """Raise a clear test failure when an assertion is violated."""
    if not condition:
        raise AssertionError(message)


def validate_action_report(report, filename):
    """Verify action counts and remediation safety."""
    automatic = report["automatic_instances"]
    review = report["review_instances"]
    critical = report["critical_instances"]

    require(
        all(isinstance(n, int) and n >= 0
            for n in [automatic, review, critical]),
        f"{filename}: action instance counts must be non-negative integers",
    )

    require(
        report["total_instances"] == automatic + review + critical,
        f"{filename}: action instance totals do not reconcile",
    )

    require(
        report["total_types"]
        == report["automatic_types"]
        + report["review_types"]
        + report["critical_types"],
        f"{filename}: distinct issue-type totals do not reconcile",
    )

    for issue in report["plan"]:
        action = issue["action"]
        severity = issue.get("severity", "Medium")
        auto_fix = issue.get("auto_fix", False)
        requires_review = issue.get("requires_review", True)

        if severity == "Critical":
            require(
                action == ACTION_CRITICAL,
                f"{filename}: Critical issue classified as {action!r}",
            )

        if action == ACTION_AUTO_FIX:
            require(
                auto_fix is True and requires_review is False,
                f"{filename}: automatic action lacks explicit approval",
            )
            require(
                severity != "Critical",
                f"{filename}: Critical issue cannot be auto-fixed",
            )

        require(
            action in {ACTION_AUTO_FIX, ACTION_REVIEW, ACTION_CRITICAL},
            f"{filename}: unexpected action classification {action!r}",
        )


def validate_classifier_safety():
    """Test the core safety policy independently of catalog fixtures."""
    cases = [
        (
            {
                "severity": "Critical",
                "auto_fix": True,
                "requires_review": False,
            },
            ACTION_CRITICAL,
        ),
        (
            {
                "severity": "Low",
                "auto_fix": True,
                "requires_review": False,
            },
            ACTION_AUTO_FIX,
        ),
        (
            {
                "severity": "Low",
                "auto_fix": True,
                "requires_review": True,
            },
            ACTION_REVIEW,
        ),
        (
            {
                "severity": "Medium",
                "auto_fix": False,
                "requires_review": False,
            },
            ACTION_REVIEW,
        ),
        (
            None,
            ACTION_REVIEW,
        ),
    ]

    for issue, expected in cases:
        actual = classify_issue_action(issue)
        require(
            actual == expected,
            f"Classifier expected {expected!r}, got {actual!r} for {issue!r}",
        )


def run_one(filename):
    path = os.path.join(TEST_DIR, filename)

    require(
        os.path.isfile(path),
        f"Test fixture not found: {path}",
    )

    df = pd.read_csv(path)

    before = run_quality_checks(df)
    cleaned, change_log = clean_catalog(df)
    after = run_quality_checks(cleaned)

    issues = analyze_issues(after)
    actions = build_action_report(issues)
    impact = build_impact_summary(before, after, change_log)

    # Record preservation: cleaning must not silently delete or add rows.
    require(
        len(cleaned) == len(df),
        f"{filename}: row count changed from {len(df)} to {len(cleaned)}",
    )

    # Health scores must stay inside their defined range.
    for label, results in [("before", before), ("after", after)]:
        score = results.get("health_score")
        require(
            isinstance(score, (int, float)) and 0 <= score <= 100,
            f"{filename}: invalid {label} health score {score!r}",
        )

    validate_action_report(actions, filename)

    # Cross-check independently generated issue totals.
    require(
        actions["total_instances"] == impact["issues_after"],
        (
            f"{filename}: action report has {actions['total_instances']} "
            f"issue instances but impact report has "
            f"{impact['issues_after']}"
        ),
    )

    # Stable expectations established by the existing baseline.
    if filename == "01_missing_required_columns.csv":
        require(
            actions["critical_instances"] >= 1,
            "Missing-required-columns fixture must retain a Critical action",
        )

    if filename in {
        "06_weird_headers.csv",
        "07_minimal_valid.csv",
        "08_clean_catalog.csv",
    }:
        require(
            impact["issues_after"] == 0,
            f"{filename}: expected zero issues after cleaning",
        )

    if filename == "03_empty_catalog.csv":
        require(
            len(cleaned) == 0,
            "Empty-catalog fixture unexpectedly gained rows",
        )
        require(
            after["health_score"] == 0,
            "Empty catalog should have a health score of zero",
        )

    return {
        "rows_before": len(df),
        "rows_after": len(cleaned),
        "before_score": before.get("health_score", 0),
        "after_score": after.get("health_score", 0),
        "issues_after": impact["issues_after"],
        "automatic_changes": len(change_log),
        "automatic_instances": actions["automatic_instances"],
        "review_instances": actions["review_instances"],
        "critical_instances": actions["critical_instances"],
        "assertions_passed": True,
    }


def validate_issue_counting_safety():
    """Verify automatic and human-review counters respect safety rules."""
    issues = [
        {
            "key": "safe_test",
            "count": 2,
            "severity": "Low",
            "auto_fix": True,
            "requires_review": False,
        },
        {
            "key": "review_test",
            "count": 3,
            "severity": "Medium",
            "auto_fix": False,
            "requires_review": True,
        },
        {
            "key": "critical_test",
            "count": 1,
            "severity": "Critical",
            "auto_fix": True,
            "requires_review": False,
        },
    ]

    # Critical issues must never count as automatic fixes.
    automatic = _count_automatic_items(issues)
    require(
        automatic == 2,
        f"Decision engine expected 2 automatic items, got {automatic}",
    )

    # Human-review count must include the three review-required instances.
    with patch.object(
        impact_report, "analyze_issues", return_value=issues
    ):
        review = calculate_review_items({})

    require(
        review == 3,
        f"Impact report expected 3 review items, got {review}",
    )

    # The quality report must apply the same automatic-fix safety rule.
    with patch.object(report, "analyze_issues", return_value=issues):
        summary = report.build_business_summary({
            "row_count": 5,
            "health_score": 70,
            "health_status": "Needs Attention",
        })

    quality_automatic = summary.get("automatic_instances")

    require(
        quality_automatic == 2,
        (
            "Quality report expected 2 automatic items, "
            f"got {quality_automatic}"
        ),
    )


def main():
    print("=" * 72)
    print("CATALOG RESCUE - BATCH 23 ASSERTION-BASED QA")
    print("=" * 72)

    passed = 0
    failed = 0

    print("\n[CORE REMEDIATION SAFETY]")

    try:
        validate_classifier_safety()
        print("  PASS: classifier safety assertions")
        passed += 1
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        failed += 1

    try:
        validate_issue_counting_safety()
        print("  PASS: issue-counting safety assertions")
        passed += 1
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3)
        failed += 1

    for filename in TEST_FILES:
        print(f"\n[{filename}]")

        try:
            result = run_one(filename)

            print(
                f"  Rows:             {result['rows_before']} "
                f"-> {result['rows_after']}"
            )
            print(
                f"  Health:           {result['before_score']} "
                f"-> {result['after_score']}"
            )
            print(f"  Issues remaining: {result['issues_after']}")
            print(f"  Safe changes:     {result['automatic_changes']}")
            print(f"  Automatic items:  {result['automatic_instances']}")
            print(f"  Human review:     {result['review_instances']}")
            print(f"  Critical:         {result['critical_instances']}")
            print("  ASSERTIONS: PASS")
            passed += 1

        except Exception as exc:
            print("  ASSERTIONS: FAIL")
            print(f"  Error: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            failed += 1

    print("\n" + "=" * 72)
    print(f"RESULT: {passed} passed / {failed} failed")
    print("=" * 72)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
