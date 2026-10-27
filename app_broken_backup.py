import io
import os
import textwrap
import pandas as pd
import streamlit as st

from cleaner import clean_catalog
from quality_checks import run_quality_checks
from action_report import build_action_report
from decision_engine import build_business_decision
from report import build_quality_report
from issue_analysis import (
    build_issue_dataframe,
    analyze_issues,
)
from impact_report import (
    build_impact_summary,
    build_export_report,
)
from rules import get_all_rules, get_rule_summary


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Catalog Rescue",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "catalog_df": None,
    "cleaned_df": None,
    "before_results": None,
    "after_results": None,
    "change_log": [],
    "impact_summary": None,
    "analyzed": False,
    "demo_mode": False,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# STYLING
# ============================================================

    st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1450px;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(128,128,128,0.18);
        }

        .brand {
            font-size: 1.65rem;
            font-weight: 800;
            letter-spacing: -0.04em;
            margin-bottom: 0.15rem;
        }

        .brand-subtitle {
            font-size: 0.78rem;
            opacity: 0.65;
            margin-bottom: 1.5rem;
        }

        .eyebrow {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            opacity: 0.6;
            margin-bottom: 0.35rem;
        }

        .hero-title {
            font-size: 3rem;
            line-height: 1.05;
            font-weight: 850;
            letter-spacing: -0.055em;
            margin: 0;
        }

        .hero-copy {
            font-size: 1.05rem;
            line-height: 1.65;
            max-width: 850px;
            opacity: 0.72;
            margin-top: 0.8rem;
        }

        .section-title {
            font-size: 1.35rem;
            font-weight: 800;
            letter-spacing: -0.025em;
            margin-top: 2rem;
            margin-bottom: 0.25rem;
        }

        .section-copy {
            opacity: 0.65;
            margin-bottom: 1rem;
        }

        .metric-card {
            padding: 1.15rem 1.2rem;
            border: 1px solid rgba(128,128,128,0.2);
            border-radius: 14px;
            min-height: 118px;
        }

        .metric-label {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            opacity: 0.58;
            font-weight: 700;
        }

        .metric-value {
            font-size: 2rem;
            font-weight: 850;
            letter-spacing: -0.04em;
            margin-top: 0.3rem;
        }

        .metric-note {
            font-size: 0.8rem;
            opacity: 0.58;
            margin-top: 0.2rem;
        }

        .status-box {
            padding: 1.2rem;
            border: 1px solid rgba(128,128,128,0.2);
            border-radius: 14px;
        }

        .status-number {
            font-size: 4rem;
            line-height: 1;
            font-weight: 900;
            letter-spacing: -0.06em;
        }

        .status-label {
            font-size: 1rem;
            font-weight: 750;
            margin-top: 0.35rem;
        }

        .small-muted {
            font-size: 0.82rem;
            opacity: 0.6;
        }

        .review-box {
            padding: 1rem 1.1rem;
            border: 1px solid rgba(128,128,128,0.2);
            border-radius: 12px;
            margin-bottom: 0.7rem;
        }

        .footer {
            margin-top: 4rem;
            padding-top: 1.5rem;
            border-top: 1px solid rgba(128,128,128,0.18);
            text-align: center;
            opacity: 0.55;
            font-size: 0.78rem;
        }

        div[data-testid="stMetric"] {
            padding: 0.4rem 0;
        }

        .stButton > button {
            border-radius: 10px;
            font-weight: 700;
        }

        .stDownloadButton > button {
            border-radius: 10px;
            font-weight: 700;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPERS
# ============================================================

def dataframe_to_csv(df):
    return df.to_csv(index=False).encode("utf-8")


def dataframe_to_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cleaned Catalog")

    return output.getvalue()


def safe_display_dataframe(df):
    """
    Prepare a dataframe for Streamlit display without changing the
    underlying catalog data.

    Streamlit/Arrow can reject columns that contain mixed Python types,
    such as numeric prices mixed with text like "not available", or a
    change-log Row column containing both integers and "HEADER".
    Only mixed-type object columns are converted to strings for display.
    """
    if not isinstance(df, pd.DataFrame):
        return df

    display_df = df.copy()

    for column in display_df.columns:
        series = display_df[column]

        if not pd.api.types.is_object_dtype(series.dtype):
            continue

        non_null_values = series.dropna()

        if non_null_values.empty:
            continue

        value_types = {type(value) for value in non_null_values}

        if len(value_types) > 1:
            display_df[column] = series.map(
                lambda value: "" if pd.isna(value) else str(value)
            )

    return display_df


def display_dataframe(df, **kwargs):
    """Render a dataframe safely in Streamlit."""
    st.dataframe(
        safe_display_dataframe(df),
        **kwargs,
    )


def change_log_dataframe(change_log):
    if not change_log:
        return pd.DataFrame(
            columns=["Row", "Column", "Original Value", "New Value"]
        )

    rows = []

    for change in change_log:
        rows.append(
            {
                "Row": change.get("row", ""),
                "Column": change.get("column", ""),
                "Original Value": change.get("old_value", ""),
                "New Value": change.get("new_value", ""),
            }
        )

    return pd.DataFrame(rows)


def severity_metric(summary, severity):
    return int(summary.get(severity, 0))


def rule_registry_dataframe():
    rows = []

    for rule in get_all_rules():
        rows.append(
            {
                "Rule": rule.get("name", ""),
                "Category": rule.get("category", ""),
                "Severity": rule.get("severity", ""),
                "Automatic Fix": "Yes" if rule.get("auto_fix", False) else "No",
                "Human Review": "Yes" if rule.get("requires_review", True) else "No",
                "Description": rule.get("description", ""),
                "Business Impact": rule.get("business_impact", ""),
            }
        )

    return pd.DataFrame(rows)


def render_business_decision(decision):
    """
    Render the customer-facing business decision prominently.
    """

    if not isinstance(decision, dict):
        return

    decision_type = decision.get("decision", "Insufficient Data")
    title = decision.get("title", "Review Required")
    explanation = decision.get(
        "explanation",
        "The catalog requires further review."
    )
    next_action = decision.get(
        "next_action",
        "Review the catalog before continuing."
    )

    health_score = decision.get("health_score", 0)
    issue_instances = decision.get("issue_instances", 0)
    review_items = decision.get("review_items", 0)
    automatic_items = decision.get("automatic_items", 0)

    styles = {
        "Safe to Publish": {
            "background": "#ecfdf5",
            "border": "#10b981",
            "icon": "✓",
        },
        "Publish After Review": {
            "background": "#fffbeb",
            "border": "#f59e0b",
            "icon": "!",
        },
        "Do Not Publish Yet": {
            "background": "#fef2f2",
            "border": "#ef4444",
            "icon": "×",
        },
        "Insufficient Data": {
            "background": "#f8fafc",
            "border": "#64748b",
            "icon": "—",
        },
    }

    style = styles.get(
        decision_type,
        styles["Insufficient Data"]
    )

    st.markdown(
        textwrap.dedent(
            f"""
        <div style="
            background:{style['background']};
            border:1px solid {style['border']};
            border-left:6px solid {style['border']};
            border-radius:14px;
            padding:24px;
            margin:10px 0 24px 0;
        ">
            <div style="
                display:flex;
                align-items:center;
                gap:14px;
                margin-bottom:10px;
            ">
                <div style="
                    width:42px;
                    height:42px;
                    border-radius:50%;
                    background:{style['border']};
                    color:white;
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    font-size:24px;
                    font-weight:700;
                ">
                    {style['icon']}
                </div>

                <div>
                    <div style="
                        font-size:13px;
                        font-weight:700;
                        letter-spacing:.08em;
                        text-transform:uppercase;
                        color:#64748b;
                    ">
                        Publication Decision
                    </div>

                    <div style="
                        font-size:28px;
                        font-weight:800;
                        color:#0f172a;
                        line-height:1.2;
                    ">
                        {title}
                    </div>
                </div>
            </div>

            <div style="
                font-size:16px;
                line-height:1.6;
                color:#334155;
                margin-bottom:18px;
            ">
                {explanation}
            </div>

            <div style="
                background:rgba(255,255,255,.65);
                border-radius:10px;
                padding:14px 16px;
                color:#0f172a;
            ">
                <strong>Recommended next action:</strong><br>
                {next_action}
            </div>
        </div>
                 """
        ),
        unsafe_allow_html=True,
    )
    st.markdown("### Business Snapshot")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if decision_type == "Insufficient Data":
            st.metric("Health Score", "—")
        else:
            st.metric("Health Score", f"{health_score}/100")

    with col2:
        st.metric(
            "Issues",
            f"{issue_instances:,}"
        )

    with col3:
        st.metric(
            "Needs Review",
            f"{review_items:,}"
        )

    with col4:
        st.metric(
            "Safe Changes",
            f"{automatic_items:,}"
        )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        """
        <div class="brand">🛡️ Catalog Rescue</div>
        <div class="brand-subtitle">
            Data Quality Intelligence
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Workflow")

    st.markdown(
        """
        **01 · Upload**  
        Bring in your messy catalog.

        **02 · Analyze**  
        Detect quality risks.

        **03 · Rescue**  
        Apply safe deterministic cleanup.

        **04 · Review**  
        Separate unresolved issues.

        **05 · Export**  
        Download the cleaned catalog.
        """
    )

    st.divider()

    st.markdown("### What gets checked")

    st.markdown(
        """
        - Missing values
        - Duplicate SKUs
        - Duplicate rows
        - Invalid prices
        - SKU formats
        - Categories
        - Descriptions
        - Emails
        - URLs
        - Phone numbers
        - Empty columns
        """
    )

    st.divider()

    st.caption("Catalog Rescue MVP")
    st.caption("Built for practical catalog data quality.")


# ============================================================
# HERO
# ============================================================

    st.markdown(
    '<div class="eyebrow">DATA QUALITY INTELLIGENCE</div>',
    unsafe_allow_html=True,
)

    st.markdown(
    '<h1 class="hero-title">Turn messy product data into a catalog you can trust.</h1>',
    unsafe_allow_html=True,
)

    st.markdown(
    """
    <div class="hero-copy">
        Catalog Rescue analyzes product catalogs for missing data,
        duplicates, invalid fields, inconsistent formatting and other
        quality risks — then safely fixes what can be fixed without
        silently changing business information.
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")


# ============================================================
# UPLOAD AREA
# ============================================================

    st.markdown(
    '<div class="section-title">Start with your catalog</div>',
    unsafe_allow_html=True,
)

    st.markdown(
    '<div class="section-copy">Upload a CSV or Excel product catalog, or use the built-in stress-test dataset.</div>',
    unsafe_allow_html=True,
)

upload_col, demo_col = st.columns([2.2, 1])

with upload_col:

    uploaded_file = st.file_uploader(
        "Upload catalog",
        type=["csv", "xlsx", "xls"],
        label_visibility="collapsed",
    )

with demo_col:

    demo_path = os.path.join(
        "sample_data",
        "torture_catalog.csv",
    )

    if st.button(
        "🧪 Load Demo Catalog",
        width="stretch",
    ):
        if os.path.exists(demo_path):
            st.session_state.catalog_df = pd.read_csv(demo_path)
            st.session_state.demo_mode = True
            st.session_state.analyzed = False
            st.session_state.cleaned_df = None
            st.session_state.before_results = None
            st.session_state.after_results = None
            st.session_state.change_log = []
            st.session_state.impact_summary = None
            st.rerun()
        else:
            st.error("Demo dataset not found.")


# ============================================================
# READ UPLOAD
# ============================================================

if uploaded_file is not None:
    try:

        file_signature = (
            uploaded_file.name,
            uploaded_file.size,
        )

        previous_signature = st.session_state.get(
            "uploaded_signature"
        )

        if file_signature != previous_signature:

            if uploaded_file.name.lower().endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            st.session_state.catalog_df = df
            st.session_state.uploaded_signature = file_signature
            st.session_state.demo_mode = False
            st.session_state.analyzed = False
            st.session_state.cleaned_df = None
            st.session_state.before_results = None
            st.session_state.after_results = None
            st.session_state.change_log = []
            st.session_state.impact_summary = None

    except Exception as exc:
        st.error(f"Could not read this file: {exc}")

# ============================================================
# CATALOG READY
# ============================================================

if st.session_state.catalog_df is not None:

    df = st.session_state.catalog_df

    if st.session_state.demo_mode:
        st.info(
            "Demo mode: this catalog intentionally contains messy data "
            "so you can see how Catalog Rescue behaves under pressure."
        )

    meta_col1, meta_col2, meta_col3 = st.columns(3)

    with meta_col1:
    st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Records</div>
                <div class="metric-value">{len(df):,}</div>
                <div class="metric-note">Rows detected</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with meta_col2:
    st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Fields</div>
                <div class="metric-value">{len(df.columns):,}</div>
                <div class="metric-note">Columns detected</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with meta_col3:
    st.markdown(
            """
            <div class="metric-card">
                <div class="metric-label">Engine</div>
                <div class="metric-value">Safe</div>
                <div class="metric-note">Deterministic cleanup</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    with st.expander("Preview source catalog", expanded=False):
        display_dataframe(
            df.head(20),
            width="stretch",
            hide_index=True,
        )

    if st.button(
        "🔎 Analyze Catalog",
        type="primary",
        width="stretch",
    ):

        with st.spinner("Analyzing catalog quality..."):

            before_results = run_quality_checks(df)

            cleaned_df, change_log = clean_catalog(df)

            after_results = run_quality_checks(cleaned_df)

            impact_summary = build_impact_summary(
                before_results,
                after_results,
                change_log,
            )

            st.session_state.before_results = before_results
            st.session_state.after_results = after_results
            st.session_state.cleaned_df = cleaned_df
            st.session_state.change_log = change_log
            st.session_state.impact_summary = impact_summary
            st.session_state.analyzed = True

            st.success("Catalog analysis complete.")

# ============================================================
# RESULTS
# ============================================================

if st.session_state.analyzed:

    before_results = st.session_state.before_results
    after_results = st.session_state.after_results
    cleaned_df = st.session_state.cleaned_df
    change_log = st.session_state.change_log
    impact = st.session_state.impact_summary

    report = build_quality_report(after_results, impact)
    business_decision = build_business_decision(after_results)

    render_business_decision(business_decision)

    st.divider()

    st.markdown(
        '<div class="eyebrow">CATALOG HEALTH</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-title">Your catalog health at a glance</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">A quality snapshot based on the cleaned dataset and unresolved issues.</div>',
        unsafe_allow_html=True,
    )

    has_data = report["has_data"]
    score_display = report["health_score"] if has_data else "—"
    dimension_display = (
        lambda value: f"{value:.1f}%" if has_data else "—"
    )

    score_col, metrics_col = st.columns([1, 2.2])

    with score_col:

    st.markdown(
            f"""
            <div class="status-box">
                <div class="metric-label">Health Score</div>
                <div class="status-number">{score_display}</div>
                <div class="status-label">{report["status"]}</div>
                <div class="small-muted">
                    Score after safe automatic cleanup
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with metrics_col:

        m1, m2, m3, m4 = st.columns(4)

        with m1:
            st.metric(
                "Completeness",
                dimension_display(report["completeness"]),
            )

        with m2:
            st.metric(
                "Validity",
                dimension_display(report["validity"]),
            )

        with m3:
            st.metric(
                "Consistency",
                dimension_display(report["consistency"]),
            )

        with m4:
            st.metric(
                "Uniqueness",
                dimension_display(report["uniqueness"]),
            )

    # ========================================================
    # BUSINESS DECISION
    # ========================================================

    business = report["business_summary"]

    st.markdown(
        '<div class="section-title">Business decision</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">A plain-language summary of what the current catalog quality means operationally.</div>',
        unsafe_allow_html=True,
    )

    if not has_data:
        st.warning(
            "This catalog contains no product records. Catalog Rescue cannot assess catalog quality yet. "
            "Upload a file containing at least one product row to continue."
        )
    elif business["critical_instances"] > 0:
        st.error(business["next_action"])
    elif business["high_instances"] > 0:
        st.warning(business["next_action"])
    elif business["issue_instances"] > 0:
        st.info(business["next_action"])
    else:
        st.success(business["next_action"])

    b1, b2, b3, b4 = st.columns(4)

    with b1:
        st.metric(
            "Open Issues",
            business["issue_instances"],
        )

    with b2:
        st.metric(
            "High + Critical",
            business["high_instances"] + business["critical_instances"],
        )

    with b3:
        st.metric(
            "Safe Auto-Fixes",
            business["automatic_instances"],
        )

    with b4:
        st.metric(
            "Records Affected",
            business["affected_records"],
        )

    st.caption(
        f'Next action: {business["next_action"]}'
    )

    st.write("")

    # ========================================================
    # IMPACT
    # ========================================================

    st.markdown(
        '<div class="section-title">Cleaning impact</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">What changed between the original catalog and the rescued version.</div>',
        unsafe_allow_html=True,
    )

    i1, i2, i3, i4, i5 = st.columns(5)

    with i1:
        st.metric(
            "Before",
            impact["before_score"],
        )

    with i2:
        st.metric(
            "After",
            impact["after_score"],
            delta=f'{impact["score_change"]:+d}',
        )

    with i3:
        st.metric(
            "Safe Changes",
            impact["automatic_changes"],
        )

    with i4:
        st.metric(
            "Records Affected",
            impact["affected_records"],
        )

    with i5:
        st.metric(
            "Issues Resolved",
            impact["issues_resolved"],
        )

    if report["has_data"]:
        st.caption(
            f'{impact["affected_percentage"]:.1f}% of records were touched by automatic cleanup. '
            "Only deterministic formatting and normalization rules are applied automatically."
        )
    else:
        st.caption(
            "No product records were available, so cleaning impact is not meaningfully assessed."
        )

    # ========================================================
    # SEVERITY
    # ========================================================

    st.markdown(
        '<div class="section-title">Remaining risk</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">Issues still present after safe automatic cleanup.</div>',
        unsafe_allow_html=True,
    )

    s1, s2, s3, s4 = st.columns(4)

    with s1:
        st.metric(
            "Critical",
            severity_metric(
                impact,
                "critical_after",
            ),
        )

    with s2:
        st.metric(
            "High",
            severity_metric(
                impact,
                "high_after",
            ),
        )

    with s3:
        st.metric(
            "Medium",
            severity_metric(
                impact,
                "medium_after",
            ),
        )

    with s4:
        st.metric(
            "Low",
            severity_metric(
                impact,
                "low_after",
            ),
        )

    # ========================================================
    # TOP PROBLEMS
    # ========================================================

    st.markdown(
        '<div class="section-title">What needs attention</div>',
        unsafe_allow_html=True,
    )

    top_problems = report["top_problems"]

    if top_problems:

        problem_df = pd.DataFrame(
            [
                {
                    "Problem": item["problem"],
                    "Count": item["count"],
                    "Details": item["message"],
                }
                for item in top_problems
            ]
        )

        display_dataframe(
            problem_df,
            width="stretch",
            hide_index=True,
        )

    else:

        st.success(
            "No major unresolved quality problems were detected."
        )

    # ========================================================
    # RECOMMENDATIONS
    # ========================================================

    st.markdown(
        '<div class="section-title">Recommended actions</div>',
        unsafe_allow_html=True,
    )

    for recommendation in report["recommendations"]:
    st.markdown(
            f"- {recommendation}"
        )

    # ========================================================
    # REVIEW QUEUE
    # ========================================================

    st.markdown(
        '<div class="section-title">Human review queue</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">These issues were intentionally not changed automatically because they may require business context.</div>',
        unsafe_allow_html=True,
    )

    st.metric(
        "Items requiring review",
        impact["review_items"],
    )

    # ========================================================
    # DUPLICATE SKU INVESTIGATION
    # ========================================================

    duplicate_skus = after_results.get(
        "duplicate_skus",
        pd.DataFrame(),
    )

    if isinstance(duplicate_skus, pd.DataFrame) and not duplicate_skus.empty:

        with st.expander(
            f"🔍 Investigate duplicate SKUs ({len(duplicate_skus)} records)",
            expanded=False,
        ):

            st.warning(
                "Duplicate SKUs are not automatically deleted. "
                "Confirm whether the records represent the same product."
            )

            display_dataframe(
                duplicate_skus,
                width="stretch",
                hide_index=True,
            )

    # ========================================================
    # DETAILED ISSUE ANALYSIS
    # ========================================================

    analyzed_issues = analyze_issues(
        after_results
    )

    action_report = build_action_report(analyzed_issues)    

    issue_table = build_issue_dataframe(
        analyzed_issues
    )

    automatic_instances = action_report["automatic_instances"]
    review_instances = action_report["review_instances"]
    critical_instances = action_report["critical_instances"]

    st.markdown(
        '<div class="section-title">Detailed issue analysis</div>',
        unsafe_allow_html=True,
    )

    if not issue_table.empty:

        display_dataframe(
            issue_table,
            width="stretch",
            hide_index=True,
        )

    else:

        st.success(
            "No unresolved issues found."
        )

    # ========================================================
    # RULE GOVERNANCE
    # ========================================================

    st.markdown(
        '<div class="section-title">Rule governance</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">The quality engine uses a registered set of explicit rules to determine what can be automated and what stays under human control.</div>',
        unsafe_allow_html=True,
    )

    rule_summary = get_rule_summary()
    r1, r2, r3, r4 = st.columns(4)

    with r1:
        st.metric("Registered Rules", rule_summary.get("total_rules", 0))

    with r2:
        st.metric("Automatic Rules", rule_summary.get("automatic_rules", 0))

    with r3:
        st.metric("Human Review Rules", rule_summary.get("review_rules", 0))

    with r4:
        st.metric("Critical Rules", rule_summary.get("critical_rules", 0))

    with st.expander("View rule registry", expanded=False):
        st.dataframe(
            rule_registry_dataframe(),
            width="stretch",
            hide_index=True,
        )

    # ========================================================
    # FIELD VALIDATION
    # ========================================================

    with st.expander(
        "🧩 Field-level validation",
        expanded=False,
    ):

        validation_rows = []

        validation_map = {
            "Invalid Prices": "invalid_prices",
            "Invalid SKU Formats": "invalid_sku_formats",
            "Invalid Emails": "invalid_emails",
            "Invalid URLs": "invalid_urls",
            "Invalid Phones": "invalid_phones",
            "Missing Descriptions": "missing_descriptions",
            "Blank SKUs": "blank_skus",
            "Suspicious Prices": "suspicious_prices",
        }

        for label, key in validation_map.items():

            value = after_results.get(
                key,
                [],
            )

            if isinstance(value, dict):
                count = len(value)
            elif isinstance(value, list):
                count = len(value)
            elif isinstance(value, pd.DataFrame):
                count = len(value)
            else:
                count = 0

            validation_rows.append(
                {
                    "Check": label,
                    "Records": count,
                    "Status": (
                        "Needs review"
                        if count > 0
                        else "Clear"
                    ),
                }
            )

        validation_df = pd.DataFrame(
            validation_rows
        )

        display_dataframe(
            validation_df,
            width="stretch",
            hide_index=True,
        )

    # ========================================================
    # AUTOMATIC CLEANUP
    # ========================================================

    with st.expander(
        f"✨ Automatic cleanup ({len(change_log)} changes)",
        expanded=False,
    ):

        if change_log:

            changes_df = change_log_dataframe(
                change_log
            )

            display_dataframe(
                changes_df,
                width="stretch",
                hide_index=True,
            )

        else:

            st.info(
                "No automatic changes were required."
            )

    # ========================================================
    # BEFORE / AFTER
    # ========================================================

    st.markdown(
        '<div class="section-title">Before and after</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">Inspect the rescued catalog before exporting it.</div>',
        unsafe_allow_html=True,
    )

    before_tab, after_tab = st.tabs(
        [
            "Original catalog",
            "Rescued catalog",
        ]
    )

    with before_tab:

        display_dataframe(
            df.head(30),
            width="stretch",
            hide_index=True,
        )

    with after_tab:

        display_dataframe(
            cleaned_df.head(30),
            width="stretch",
            hide_index=True,
        )

    # ========================================================
    # EXPORT
    # ========================================================

    st.markdown(
        '<div class="section-title">Export your rescued catalog</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-copy">Download the cleaned catalog, change log and quality report for your records.</div>',
        unsafe_allow_html=True,
    )

    export_report = build_export_report(
        before_results,
        after_results,
        impact,
    )

    csv_data = dataframe_to_csv(
        cleaned_df
    )

    excel_data = dataframe_to_excel(
        cleaned_df
    )

    changes_data = dataframe_to_csv(
        change_log_dataframe(change_log)
    )

    report_data = dataframe_to_csv(
        export_report
    )

    e1, e2, e3, e4 = st.columns(4)

    with e1:

        st.download_button(
            "⬇️ Cleaned CSV",
            data=csv_data,
            file_name="catalog_rescue_cleaned.csv",
            mime="text/csv",
            width="stretch",
        )

    with e2:

        st.download_button(
            "⬇️ Cleaned Excel",
            data=excel_data,
            file_name="catalog_rescue_cleaned.xlsx",
            mime=(
                "application/"
                "vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            width="stretch",
        )

    with e3:

        st.download_button(
            "⬇️ Change Log",
            data=changes_data,
            file_name="catalog_rescue_change_log.csv",
            mime="text/csv",
            width="stretch",
        )

    with e4:

        st.download_button(
            "⬇️ Quality Report",
            data=report_data,
            file_name="catalog_rescue_quality_report.csv",
            mime="text/csv",
            width="stretch",
        )


# ============================================================
# EMPTY STATE
# ============================================================

else:

    st.write("")

    empty_col1, empty_col2, empty_col3 = st.columns(3)

    with empty_col1:

    st.markdown(
            """
            ### 🔎 Detect
            Find missing values, duplicates,
            invalid fields and inconsistent
            catalog structures.
            """
        )

    with empty_col2:

    st.markdown(
            """
            ### 🧹 Clean
            Apply safe, deterministic
            normalization without silently
            changing business data.
            """
        )

    with empty_col3:

    st.markdown(
            """
            ### 📊 Report
            Understand catalog health,
            unresolved risks and the changes
            made before export.
            """
        )

    st.write("")

    st.info(
        "Upload a catalog above or load the demo catalog to begin."
    )


# ============================================================
# FOOTER
# ============================================================

    st.markdown(
    """
    <div class="footer">
        Catalog Rescue · Data Quality Intelligence · MVP
        <br>
        Safe cleanup. Transparent changes. Human review where it matters.
    </div>
    """,
    unsafe_allow_html=True,
)
