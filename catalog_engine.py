import pandas as pd

from action_report import build_action_report
from cleaner import clean_catalog
from decision_engine import build_business_decision
from impact_report import build_export_report, build_impact_summary
from issue_analysis import analyze_issues, build_issue_dataframe
from quality_checks import run_quality_checks
from report import build_quality_report


def analyze_catalog(df):
    """Run the existing catalog analysis workflow without a UI dependency."""
    before_results = run_quality_checks(df)
    cleaned_df, change_log = clean_catalog(df.copy())
    after_results = run_quality_checks(cleaned_df)
    impact_summary = build_impact_summary(
        before_results,
        after_results,
        change_log,
    )

    quality_report = build_quality_report(after_results)
    business_decision = build_business_decision(after_results)
    issues = analyze_issues(after_results)
    action_report = build_action_report(issues)
    issue_table = build_issue_dataframe(issues)
    export_report = build_export_report(
        before_results,
        after_results,
        impact_summary,
    )

    return {
        "before_results": before_results,
        "cleaned_df": cleaned_df,
        "change_log": change_log,
        "after_results": after_results,
        "impact_summary": impact_summary,
        "quality_report": quality_report,
        "business_decision": business_decision,
        "issues": issues,
        "action_report": action_report,
        "issue_table": issue_table,
        "export_report": export_report,
    }
