import html
import io
import os
import textwrap

import pandas as pd
import streamlit as st

from catalog_engine import analyze_catalog
from catalog_ingestion import load_catalog


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Catalog Rescue — Product Catalog Quality Checker",
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
    "analysis_result": None,
    "analyzed": False,
    "demo_mode": False,
    "uploaded_signature": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def reset_analysis():
    """Clear results when a new source catalog is loaded."""
    st.session_state.cleaned_df = None
    st.session_state.before_results = None
    st.session_state.after_results = None
    st.session_state.change_log = []
    st.session_state.impact_summary = None
    st.session_state.analysis_result = None
    st.session_state.analyzed = False


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
        .stButton > button,
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

def dataframe_for_display(df):
    """
    Return a display-only copy with consistent string column types.

    This prevents Streamlit/PyArrow from failing when a column mixes
    values such as integers, text, and missing values. The original
    dataframe remains unchanged for quality checks and exports.
    """
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    display_df = df.copy()
    for column in display_df.columns:
        display_df[column] = display_df[column].astype("string")
    return display_df


def dataframe_to_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cleaned Catalog")
    return output.getvalue()


def change_log_dataframe(change_log):
    """Convert cleaner change-log entries to a consistent export/display schema."""
    columns = ["Row", "Column", "Original Value", "New Value"]

    if not change_log:
        return pd.DataFrame(columns=columns)

    rows = []
    for change in change_log:
        rows.append(
            {
                # Header changes use "HEADER"; data changes use row numbers.
                # String conversion avoids mixed-type Arrow serialization errors.
                "Row": str(change.get("row", "")),
                "Column": str(
                    change.get("field", change.get("column", ""))
                ),
                "Original Value": _safe_cell_value(
                    change.get("before", change.get("old_value", ""))
                ),
                "New Value": _safe_cell_value(
                    change.get("after", change.get("new_value", ""))
                ),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _safe_cell_value(value):
    """Make change-log values readable and safe for CSV/dataframe display."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def severity_metric(summary, severity):
    return int(summary.get(severity, 0) or 0)


def render_business_decision(decision):
    """Render the customer-facing publication decision."""
    if not isinstance(decision, dict):
        st.warning("The publication decision could not be generated.")
        return

    decision_type = decision.get("decision", "Insufficient Data")
    title = decision.get("title", "Review Required")
    explanation = decision.get(
        "explanation",
        "The catalog requires further review.",
    )
    next_action = decision.get(
        "next_action",
        "Review the catalog before continuing.",
    )

    health_score = decision.get("health_score", 0)
    issue_instances = decision.get("issue_instances", 0)
    review_items = decision.get("review_items", 0)
    automatic_items = decision.get("automatic_items", 0)

    styles = {
        "Safe to Publish": {
            "background": "#ecfdf5",
            "border": "#10b981",
            "icon": "OK",
        },
        "Publish After Review": {
            "background": "#fffbeb",
            "border": "#f59e0b",
            "icon": "!",
        },
        "Do Not Publish Yet": {
            "background": "#fef2f2",
            "border": "#ef4444",
            "icon": "X",
        },
        "Insufficient Data": {
            "background": "#f8fafc",
            "border": "#64748b",
            "icon": "-",
        },
    }

    style = styles.get(decision_type, styles["Insufficient Data"])

    # Escape text inserted into HTML so catalog-derived strings cannot
    # inject markup into this presentation block.
    safe_title = html.escape(str(title))
    safe_explanation = html.escape(str(explanation))
    safe_next_action = html.escape(str(next_action))

    card_html = textwrap.dedent(
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
                    font-size:16px;
                    font-weight:800;
                ">{style['icon']}</div>
                <div>
                    <div style="
                        font-size:13px;
                        font-weight:700;
                        letter-spacing:.08em;
                        text-transform:uppercase;
                        color:#64748b;
                    ">Publication Decision</div>
                    <div style="
                        font-size:28px;
                        font-weight:800;
                        color:#0f172a;
                        line-height:1.2;
                    ">{safe_title}</div>
                </div>
            </div>
            <div style="
                font-size:16px;
                line-height:1.6;
                color:#334155;
                margin-bottom:18px;
            ">{safe_explanation}</div>
            <div style="
                background:rgba(255,255,255,.65);
                border-radius:10px;
                padding:14px 16px;
                color:#0f172a;
            ">
                <strong>Recommended next action:</strong><br>
                {safe_next_action}
            </div>
        </div>
        """
    )

    st.markdown(card_html, unsafe_allow_html=True)
    st.markdown("### Business Snapshot")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "Health Score",
            "-" if decision_type == "Insufficient Data" else f"{health_score}/100",
        )
    with col2:
        st.metric("Issue Instances", issue_instances)
    with col3:
        st.metric("Human Review", review_items)
    with col4:
        st.metric("Automatic Actions", automatic_items)


def show_dataframe(df, **kwargs):
    """Render a display-safe copy while preserving the source dataframe."""
    st.dataframe(dataframe_for_display(df), width="stretch", **kwargs)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <div class="brand">🛡️ Catalog Rescue</div>
        <div class="brand-subtitle">Data Quality Intelligence</div>
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
    demo_path = os.path.join("sample_data", "torture_catalog.csv")
    if st.button("🧪 Load Demo Catalog", width="stretch"):
        if os.path.exists(demo_path):
            try:
                st.session_state.catalog_df = load_catalog(demo_path)
                st.session_state.demo_mode = True
                st.session_state.uploaded_signature = None
                reset_analysis()
                st.rerun()
            except Exception as exc:
                st.error(f"Could not load the demo dataset: {exc}")
        else:
            st.error("Demo dataset not found.")


# ============================================================
# READ UPLOAD
# ============================================================

if uploaded_file is not None:
    try:
        file_signature = (uploaded_file.name, uploaded_file.size)
        previous_signature = st.session_state.get("uploaded_signature")

        if file_signature != previous_signature:
            uploaded_file.seek(0)
            df_uploaded = load_catalog(uploaded_file)

            st.session_state.catalog_df = df_uploaded
            st.session_state.uploaded_signature = file_signature
            st.session_state.demo_mode = False
            reset_analysis()

    except Exception as exc:
        st.error(
            "Could not read this file. Check that it is a valid CSV or Excel "
            f"file and try again. Details: {exc}"
        )


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
        show_dataframe(df.head(20), hide_index=True)

    if st.button(
        "🔎 Analyze Catalog",
        type="primary",
        width="stretch",
    ):
        with st.spinner("Analyzing catalog quality..."):
            try:
                analysis_result = analyze_catalog(df)

                st.session_state.analysis_result = analysis_result
                st.session_state.before_results = analysis_result["before_results"]
                st.session_state.after_results = analysis_result["after_results"]
                st.session_state.cleaned_df = analysis_result["cleaned_df"]
                st.session_state.change_log = analysis_result["change_log"]
                st.session_state.impact_summary = analysis_result["impact_summary"]
                st.session_state.analyzed = True

                st.success("Catalog analysis complete.")
            except Exception as exc:
                reset_analysis()
                st.error(
                    "Analysis could not be completed. Your uploaded catalog "
                    f"has not been exported or overwritten. Details: {exc}"
                )


# ============================================================
# RESULTS
# ============================================================

if st.session_state.analyzed:
    analysis_result = st.session_state.analysis_result
    before_results = st.session_state.before_results
    after_results = st.session_state.after_results
    cleaned_df = st.session_state.cleaned_df
    change_log = st.session_state.change_log
    impact = st.session_state.impact_summary
    df = st.session_state.catalog_df

    report = analysis_result["quality_report"]
    business_decision = analysis_result["business_decision"]
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

    score_col, metrics_col = st.columns([1, 2.2])
    with score_col:
        st.markdown(
            f"""
            <div class="status-box">
                <div class="metric-label">Health Score</div>
                <div class="status-number">{report["health_score"]}</div>
                <div class="status-label">{report["status"]}</div>
                <div class="small-muted">Score after safe automatic cleanup</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with metrics_col:
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Completeness", f'{report["completeness"]:.1f}%')
        with m2:
            st.metric("Validity", f'{report["validity"]:.1f}%')
        with m3:
            st.metric("Consistency", f'{report["consistency"]:.1f}%')
        with m4:
            st.metric("Uniqueness", f'{report["uniqueness"]:.1f}%')

    # --------------------------------------------------------
    # CLEANING IMPACT
    # --------------------------------------------------------

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
        st.metric("Before", impact["before_score"])
    with i2:
        st.metric("After", impact["after_score"], delta=f'{impact["score_change"]:+d}')
    with i3:
        st.metric("Safe Changes", impact["automatic_changes"])
    with i4:
        st.metric("Records Affected", impact["affected_records"])
    with i5:
        st.metric("Issues Resolved", impact["issues_resolved"])

    st.caption(
        f'{impact["affected_percentage"]:.1f}% of records were touched by automatic cleanup. '
        "Only deterministic formatting and normalization rules are applied automatically."
    )

    # --------------------------------------------------------
    # REMAINING SEVERITY
    # --------------------------------------------------------

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
        st.metric("Critical", severity_metric(impact, "critical_after"))
    with s2:
        st.metric("High", severity_metric(impact, "high_after"))
    with s3:
        st.metric("Medium", severity_metric(impact, "medium_after"))
    with s4:
        st.metric("Low", severity_metric(impact, "low_after"))

    # --------------------------------------------------------
    # TOP PROBLEMS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">What needs attention</div>',
        unsafe_allow_html=True,
    )
    top_problems = report.get("top_problems", [])
    if top_problems:
        problem_df = pd.DataFrame(
            [
                {
                    "Problem": item.get("problem", ""),
                    "Count": item.get("count", 0),
                    "Details": item.get("message", ""),
                }
                for item in top_problems
            ]
        )
        show_dataframe(problem_df, hide_index=True)
    else:
        st.success("No major unresolved quality problems were detected.")

    # --------------------------------------------------------
    # RECOMMENDATIONS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">Recommended actions</div>',
        unsafe_allow_html=True,
    )
    for recommendation in report.get("recommendations", []):
        st.markdown(f"- {recommendation}")

    # --------------------------------------------------------
    # HUMAN REVIEW QUEUE
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">Human review queue</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-copy">These issues were intentionally not changed automatically because they may require business context.</div>',
        unsafe_allow_html=True,
    )
    st.metric("Items requiring review", impact.get("review_items", 0))

    # --------------------------------------------------------
    # DUPLICATE SKU INVESTIGATION
    # --------------------------------------------------------

    duplicate_skus = after_results.get("duplicate_skus", pd.DataFrame())
    if isinstance(duplicate_skus, pd.DataFrame) and not duplicate_skus.empty:
        with st.expander(
            f"🔍 Investigate duplicate SKUs ({len(duplicate_skus)} records)",
            expanded=False,
        ):
            st.warning(
                "Duplicate SKUs are not automatically deleted. "
                "Confirm whether the records represent the same product."
            )
            show_dataframe(duplicate_skus, hide_index=True)

    # --------------------------------------------------------
    # DETAILED ISSUE ANALYSIS
    # --------------------------------------------------------

    analyzed_issues = analysis_result["issues"]
    action_report = analysis_result["action_report"]
    issue_table = analysis_result["issue_table"]

    # These values are retained for compatibility with the existing
    # action-report module; they are not used to alter the source results.
    automatic_instances = action_report.get("automatic_instances", 0)
    review_instances = action_report.get("review_instances", 0)
    critical_instances = action_report.get("critical_instances", 0)

    st.markdown(
        '<div class="section-title">Detailed issue analysis</div>',
        unsafe_allow_html=True,
    )
    if isinstance(issue_table, pd.DataFrame) and not issue_table.empty:
        show_dataframe(issue_table, hide_index=True)
    else:
        st.success("No unresolved issues found.")

    # --------------------------------------------------------
    # FIELD-LEVEL VALIDATION
    # --------------------------------------------------------

    with st.expander("🧩 Field-level validation", expanded=False):
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
            value = after_results.get(key, [])
            if isinstance(value, dict):
                count = len(value)
            elif isinstance(value, (list, pd.DataFrame, pd.Series)):
                count = len(value)
            else:
                count = 0

            validation_rows.append(
                {
                    "Check": label,
                    "Records": count,
                    "Status": "Needs review" if count > 0 else "Clear",
                }
            )

        show_dataframe(pd.DataFrame(validation_rows), hide_index=True)

    # --------------------------------------------------------
    # AUTOMATIC CLEANUP LOG
    # --------------------------------------------------------

    with st.expander(
        f"✨ Automatic cleanup ({len(change_log)} changes)",
        expanded=False,
    ):
        if change_log:
            changes_df = change_log_dataframe(change_log)
            show_dataframe(changes_df, hide_index=True)
        else:
            st.info("No automatic changes were required.")

    # --------------------------------------------------------
    # BEFORE / AFTER
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">Before and after</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-copy">Inspect the rescued catalog before exporting it.</div>',
        unsafe_allow_html=True,
    )

    before_tab, after_tab = st.tabs(["Original catalog", "Rescued catalog"])
    with before_tab:
        show_dataframe(df.head(30), hide_index=True)
    with after_tab:
        show_dataframe(cleaned_df.head(30), hide_index=True)

    # --------------------------------------------------------
    # EXPORTS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">Export your rescued catalog</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-copy">Download the cleaned catalog, change log and quality report for your records.</div>',
        unsafe_allow_html=True,
    )

    export_report = analysis_result["export_report"]
    csv_data = dataframe_to_csv(cleaned_df)
    excel_data = dataframe_to_excel(cleaned_df)
    changes_data = dataframe_to_csv(change_log_dataframe(change_log))
    report_data = dataframe_to_csv(export_report)

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
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
    st.info("Upload a catalog above or load the demo catalog to begin.")


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
