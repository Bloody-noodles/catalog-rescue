import hashlib
import math
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from api.auth import VerifiedIdentity, get_authenticated_identity
from catalog_engine import analyze_catalog
from catalog_ingestion import load_catalog
from database.job_lifecycle import JobTransitionError
from database.job_service import retry_failed_job
from database.models import AnalysisRun, Catalog, IdempotencyRecord
from database.ownership import (
    get_existing_user_id,
    persist_idempotency_record,
    resolve_user_for_write,
)
from database.serialization import dataframe_to_payload, to_json_safe
from database.session import get_api_db_session

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_FORMATS = {"csv", "xlsx", "xls"}


class QualityMetrics(BaseModel):
    completeness: float
    validity: float
    consistency: float
    uniqueness: float


class TopProblem(BaseModel):
    problem: str
    count: int
    message: str


class AnalysisSummary(BaseModel):
    decision: str
    quality_status: str
    recommendations: List[str]
    top_problems: List[TopProblem]


class CatalogAnalysisResponse(BaseModel):
    status: str
    catalog_id: UUID
    analysis_id: UUID
    records: int
    fields: int
    health_score: int
    issue_count: int
    cleaned_records: int
    affected_records: int
    quality_metrics: QualityMetrics
    summary: AnalysisSummary


class CatalogDetailResponse(BaseModel):
    id: UUID
    original_filename: str
    file_format: str
    row_count: int
    column_count: int
    column_names: List[str]
    created_at: datetime


class AnalysisHistoryItem(BaseModel):
    id: UUID
    catalog_id: UUID
    status: str
    completed_at: datetime
    health_score: int
    issue_count: int
    cleaned_record_count: int
    affected_record_count: int
    quality_metrics: Dict[str, Any]
    analysis_summary: Dict[str, Any]


class AsyncAnalysisHistoryItem(BaseModel):
    id: UUID
    catalog_id: UUID
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempt_count: int
    retryable: bool
    health_score: int
    issue_count: int
    cleaned_record_count: int
    affected_record_count: int
    quality_metrics: Dict[str, Any]
    analysis_summary: Dict[str, Any]


class AnalysisDetailResponse(AnalysisHistoryItem):
    cleaned_rows: Optional[Dict[str, Any]] = None
    analysis_report: Optional[Dict[str, Any]] = None


class SafeAnalysisError(BaseModel):
    code: str
    message: str


class AnalysisStatusResponse(BaseModel):
    analysis_id: UUID
    catalog_id: UUID
    status: str
    attempt_count: int
    created_at: datetime
    started_at: Optional[datetime] = None
    updated_at: datetime
    completed_at: Optional[datetime] = None
    retryable: bool
    error: Optional[SafeAnalysisError] = None
    result_url: Optional[str] = None


class AsyncSubmissionResponse(BaseModel):
    catalog_id: UUID
    analysis_id: UUID
    status: str
    status_url: str
    result_url: Optional[str] = None


class AnalysisRetryResponse(BaseModel):
    analysis_id: UUID
    status: str


app = FastAPI(title="Catalog Rescue API")

IDEMPOTENCY_CONSTRAINT = "uq_idempotency_records_owner_key"
SAFE_FAILURE_MESSAGE = "Analysis failed. See the status for retry information."
QUALITY_RESULT_FIELDS = {
    "row_count",
    "column_count",
    "has_data",
    "data_status",
    "missing_columns",
    "missing_values",
    "duplicate_skus",
    "duplicate_rows",
    "invalid_prices",
    "suspicious_prices",
    "blank_skus",
    "invalid_sku_formats",
    "category_variations",
    "missing_descriptions",
    "invalid_emails",
    "invalid_urls",
    "invalid_phones",
    "empty_columns",
    "completeness",
    "validity",
    "consistency",
    "uniqueness",
    "health_score",
    "health_status",
}
QUALITY_RESULT_TABLE_FIELDS = {
    "duplicate_skus",
    "duplicate_rows",
    "invalid_prices",
    "suspicious_prices",
    "blank_skus",
    "invalid_sku_formats",
    "missing_descriptions",
    "invalid_emails",
    "invalid_urls",
    "invalid_phones",
}
IMPACT_COUNT_FIELDS = {
    "total_records",
    "issues_before",
    "issues_after",
    "issues_resolved",
    "automatic_changes",
    "affected_records",
    "review_items",
    "critical_before",
    "high_before",
    "medium_before",
    "low_before",
    "critical_after",
    "high_after",
    "medium_after",
    "low_after",
}
EXPORT_METRIC_NAMES = (
    "Total Records",
    "Issues Before Cleaning",
    "Issues After Cleaning",
    "Issues Resolved",
    "Automatic Changes",
    "Records Affected",
    "Affected Percentage",
    "Items Requiring Review",
    "Health Score Before",
    "Health Score After",
    "Health Score Change",
    "Critical Issues After",
    "High Issues After",
    "Medium Issues After",
    "Low Issues After",
)


def _is_nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _has_keys(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and keys.issubset(value)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_table_payload(value: Any, columns: Optional[List[str]] = None) -> bool:
    if not _has_keys(value, {"columns", "rows"}):
        return False
    table_columns = value["columns"]
    rows = value["rows"]
    return (
        isinstance(table_columns, list)
        and all(isinstance(column, str) for column in table_columns)
        and (columns is None or table_columns == columns)
        and isinstance(rows, list)
        and all(
            isinstance(row, list) and len(row) == len(table_columns)
            for row in rows
        )
    )


def _valid_quality_results(results: Any) -> bool:
    if not _has_keys(results, QUALITY_RESULT_FIELDS):
        return False
    if not all(
        _is_nonnegative_integer(results[field])
        for field in ("row_count", "column_count")
    ):
        return False
    if (
        not isinstance(results["has_data"], bool)
        or results["has_data"] != (results["row_count"] > 0)
        or not isinstance(results["data_status"], str)
        or not isinstance(results["health_status"], str)
        or not _is_nonnegative_integer(results["health_score"])
        or results["health_score"] > 100
    ):
        return False
    if not all(
        _is_finite_number(results[field]) and 0 <= results[field] <= 100
        for field in ("completeness", "validity", "consistency", "uniqueness")
    ):
        return False
    if not _is_string_list(results["missing_columns"]):
        return False
    if not _is_string_list(results["empty_columns"]):
        return False
    if not isinstance(results["missing_values"], dict) or not all(
        isinstance(column, str) and _is_nonnegative_integer(count)
        for column, count in results["missing_values"].items()
    ):
        return False
    if not isinstance(results["category_variations"], dict) or not all(
        isinstance(category, str) and _is_string_list(variants)
        for category, variants in results["category_variations"].items()
    ):
        return False
    return all(
        _is_table_payload(results[field])
        for field in QUALITY_RESULT_TABLE_FIELDS
    )


def _quality_issue_instance_count(results: dict) -> int:
    return (
        len(results["missing_columns"])
        + sum(results["missing_values"].values())
        + len(results["category_variations"])
        + len(results["empty_columns"])
        + sum(len(results[field]["rows"]) for field in QUALITY_RESULT_TABLE_FIELDS)
    )


def _valid_analysis_result(analysis: AnalysisRun) -> bool:
    report = analysis.analysis_report
    report_fields = {
        "before_results",
        "after_results",
        "impact_summary",
        "quality_report",
        "business_decision",
        "issues",
        "action_report",
        "change_log",
        "issue_table",
        "export_report",
    }
    if analysis.completed_at is None or not _has_keys(report, report_fields):
        return False
    if not _is_table_payload(analysis.cleaned_rows):
        return False
    if not all(
        _is_nonnegative_integer(value)
        for value in (
            analysis.health_score,
            analysis.issue_count,
            analysis.cleaned_record_count,
            analysis.affected_record_count,
        )
    ) or analysis.health_score > 100:
        return False

    before = report["before_results"]
    after = report["after_results"]
    impact = report["impact_summary"]
    quality = report["quality_report"]
    decision = report["business_decision"]
    issues = report["issues"]
    action_report = report["action_report"]
    change_log = report["change_log"]
    if not _valid_quality_results(before) or not _valid_quality_results(after):
        return False
    if not _has_keys(
        impact,
        IMPACT_COUNT_FIELDS
        | {
            "affected_percentage",
            "before_score",
            "after_score",
            "score_change",
        },
    ):
        return False
    if (
        len(analysis.cleaned_rows["rows"]) != analysis.cleaned_record_count
        or len(analysis.cleaned_rows["columns"]) != after["column_count"]
        or after["row_count"] != analysis.cleaned_record_count
        or analysis.health_score != after["health_score"]
        or before["row_count"] != impact["total_records"]
    ):
        return False

    if not all(
        _is_nonnegative_integer(impact[field])
        for field in IMPACT_COUNT_FIELDS
    ) or not all(
        _is_nonnegative_integer(impact[field]) and impact[field] <= 100
        for field in ("before_score", "after_score")
    ):
        return False
    if (
        not type(impact["score_change"]) is int
        or not -100 <= impact["score_change"] <= 100
        or not _is_finite_number(impact["affected_percentage"])
        or not 0 <= impact["affected_percentage"] <= 100
        or not math.isclose(
            impact["affected_percentage"],
            (
                impact["affected_records"] / impact["total_records"] * 100
                if impact["total_records"] > 0
                else 0.0
            ),
        )
        or impact["affected_records"] != analysis.affected_record_count
        or impact["before_score"] != before["health_score"]
        or impact["after_score"] != after["health_score"]
        or impact["score_change"] != after["health_score"] - before["health_score"]
        or impact["issues_before"] != _quality_issue_instance_count(before)
        or impact["issues_after"] != _quality_issue_instance_count(after)
        or impact["issues_resolved"]
        != max(0, impact["issues_before"] - impact["issues_after"])
    ):
        return False

    if not isinstance(change_log, list) or not all(
        _has_keys(change, {"row", "field", "before", "after", "reason"})
        and (
            change["row"] == "HEADER"
            or _is_nonnegative_integer(change["row"])
        )
        and isinstance(change["field"], str)
        and isinstance(change["reason"], str)
        for change in change_log
    ):
        return False
    affected_rows = {
        change["row"] for change in change_log if change["row"] != "HEADER"
    }
    if (
        impact["automatic_changes"] != len(change_log)
        or impact["affected_records"] != len(affected_rows)
        or impact["affected_records"] > impact["total_records"]
    ):
        return False

    issue_fields = {
        "severity",
        "issue",
        "count",
        "impact",
        "key",
        "rule_id",
        "rule_name",
        "category",
        "auto_fix",
        "requires_review",
    }
    if not isinstance(issues, list) or not all(
        _has_keys(issue, issue_fields)
        and isinstance(issue["severity"], str)
        and issue["severity"] in {"Critical", "High", "Medium", "Low"}
        and all(
            isinstance(issue[field], str)
            for field in ("issue", "impact", "key", "rule_id", "rule_name", "category")
        )
        and _is_nonnegative_integer(issue["count"])
        and issue["count"] > 0
        and isinstance(issue["auto_fix"], bool)
        and isinstance(issue["requires_review"], bool)
        for issue in issues
    ):
        return False
    issue_instances = sum(issue["count"] for issue in issues)
    severity_counts = {
        severity: sum(
            issue["count"] for issue in issues if issue["severity"] == severity
        )
        for severity in ("Critical", "High", "Medium", "Low")
    }
    review_items = sum(
        issue["count"] for issue in issues if issue["requires_review"]
    )
    automatic_items = sum(
        issue["count"]
        for issue in issues
        if issue["auto_fix"]
        and not issue["requires_review"]
        and issue["severity"] != "Critical"
    )
    if (
        analysis.issue_count != issue_instances
        or impact["issues_after"] != issue_instances
        or impact["review_items"] != review_items
        or any(
            impact[f"{severity.lower()}_after"] != severity_counts[severity]
            for severity in severity_counts
        )
    ):
        return False

    if not _has_keys(
        quality,
        {
            "health_score",
            "status",
            "data_status",
            "has_data",
            "completeness",
            "consistency",
            "validity",
            "uniqueness",
            "dimensions",
            "top_problems",
            "recommendations",
            "business_summary",
            "row_count",
            "column_count",
        },
    ):
        return False
    if (
        not isinstance(quality["status"], str)
        or not isinstance(quality["data_status"], str)
        or not isinstance(quality["has_data"], bool)
        or not _is_nonnegative_integer(quality["row_count"])
        or not _is_nonnegative_integer(quality["column_count"])
        or not _is_nonnegative_integer(quality["health_score"])
        or quality["health_score"] > 100
        or not all(
            _is_finite_number(quality[field]) and 0 <= quality[field] <= 100
            for field in ("completeness", "consistency", "validity", "uniqueness")
        )
        or not _has_keys(
        quality["dimensions"],
        {"Completeness", "Consistency", "Validity", "Uniqueness"},
        )
        or not isinstance(quality["top_problems"], list)
        or not all(
        _has_keys(problem, {"problem", "count", "message"})
        and isinstance(problem["problem"], str)
        and _is_nonnegative_integer(problem["count"])
        and isinstance(problem["message"], str)
        for problem in quality["top_problems"]
        )
        or not _is_string_list(quality["recommendations"])
    ):
        return False
    dimension_map = {
        "Completeness": "completeness",
        "Consistency": "consistency",
        "Validity": "validity",
        "Uniqueness": "uniqueness",
    }
    if (
        quality["row_count"] != after["row_count"]
        or quality["column_count"] != after["column_count"]
        or quality["health_score"] != after["health_score"]
        or quality["status"] != after["health_status"]
        or quality["data_status"] != after["data_status"]
        or quality["has_data"] != after["has_data"]
        or any(
            not _is_finite_number(quality[key])
            or not math.isclose(quality[key], after[key])
            or not _is_finite_number(quality["dimensions"][label])
            or not math.isclose(quality["dimensions"][label], after[key])
            for label, key in dimension_map.items()
        )
    ):
        return False
    business_summary = quality["business_summary"]
    summary_fields = {
        "decision",
        "next_action",
        "issue_instances",
        "critical_instances",
        "high_instances",
        "medium_instances",
        "low_instances",
        "automatic_instances",
        "health_score",
        "status",
        "row_count",
        "affected_records",
        "affected_percentage",
        "issues_resolved",
    }
    if not _has_keys(business_summary, summary_fields):
        return False
    if (
        not all(
            isinstance(business_summary[field], str) and business_summary[field]
            for field in ("decision", "next_action", "status")
        )
        or not all(
            _is_nonnegative_integer(business_summary[field])
            for field in (
                "issue_instances",
                "critical_instances",
                "high_instances",
                "medium_instances",
                "low_instances",
                "automatic_instances",
                "health_score",
                "row_count",
                "affected_records",
                "issues_resolved",
            )
        )
        or not _is_finite_number(business_summary["affected_percentage"])
        or business_summary["affected_records"] != 0
        or business_summary["affected_percentage"] != 0
        or business_summary["issues_resolved"] != 0
        or business_summary["status"] != quality["status"]
        or business_summary["issue_instances"] != issue_instances
        or business_summary["health_score"] != after["health_score"]
        or business_summary["row_count"] != after["row_count"]
        or business_summary["automatic_instances"] != automatic_items
        or any(
            business_summary[f"{severity.lower()}_instances"]
            != severity_counts[severity]
            for severity in severity_counts
        )
    ):
        return False

    decision_fields = {
        "decision",
        "title",
        "explanation",
        "next_action",
        "health_score",
        "row_count",
        "issue_instances",
        "review_items",
        "automatic_items",
        "critical",
        "high",
        "medium",
        "low",
    }
    if not _has_keys(decision, decision_fields):
        return False
    if (
        not all(
            isinstance(decision[field], str) and decision[field]
            for field in ("decision", "title", "explanation", "next_action")
        )
        or not all(
            _is_nonnegative_integer(decision[field])
            for field in (
                "health_score",
                "row_count",
                "issue_instances",
                "review_items",
                "automatic_items",
                "critical",
                "high",
                "medium",
                "low",
            )
        )
        or decision["health_score"] > 100
        or decision["health_score"] != after["health_score"]
        or decision["row_count"] != after["row_count"]
        or decision["issue_instances"] != issue_instances
        or decision["review_items"] != review_items
        or decision["automatic_items"] != automatic_items
        or any(
            decision[severity.lower()] != severity_counts[severity]
            for severity in severity_counts
        )
    ):
        return False

    if not _has_keys(
        analysis.quality_metrics,
        {"completeness", "validity", "consistency", "uniqueness"},
    ) or not all(
        _is_finite_number(analysis.quality_metrics[key])
        and 0 <= analysis.quality_metrics[key] <= 100
        and math.isclose(analysis.quality_metrics[key], after[key])
        and math.isclose(analysis.quality_metrics[key], quality[key])
        for key in ("completeness", "validity", "consistency", "uniqueness")
    ):
        return False
    if not _has_keys(
        analysis.analysis_summary,
        {"decision", "quality_status", "recommendations", "top_problems"},
    ) or (
        not isinstance(analysis.analysis_summary["decision"], str)
        or not isinstance(analysis.analysis_summary["quality_status"], str)
        or not _is_string_list(analysis.analysis_summary["recommendations"])
        or not isinstance(analysis.analysis_summary["top_problems"], list)
        or analysis.analysis_summary["decision"] != decision["decision"]
        or analysis.analysis_summary["quality_status"] != quality["status"]
        or analysis.analysis_summary["recommendations"] != quality["recommendations"]
        or analysis.analysis_summary["top_problems"] != quality["top_problems"]
    ):
        return False

    if not _has_keys(
        action_report,
        {
            "plan",
            "total_instances",
            "automatic_instances",
            "review_instances",
            "critical_instances",
            "total_types",
            "automatic_types",
            "review_types",
            "critical_types",
            "automation_status",
            "review_status",
            "critical_status",
        },
    ):
        return False
    plan = action_report["plan"]
    if not isinstance(plan, list) or len(plan) != len(issues):
        return False
    action_numeric_fields = (
        "total_instances",
        "automatic_instances",
        "review_instances",
        "critical_instances",
        "total_types",
        "automatic_types",
        "review_types",
        "critical_types",
    )
    if not all(
        _is_nonnegative_integer(action_report[field])
        for field in action_numeric_fields
    ):
        return False
    action_counts = {
        "Automatic Fix": 0,
        "Human Review": 0,
        "Critical Action": 0,
    }
    action_types = dict.fromkeys(action_counts, 0)
    for issue, item in zip(issues, plan):
        expected_action = (
            "Critical Action"
            if issue["severity"] == "Critical"
            else "Automatic Fix"
            if issue["auto_fix"] and not issue["requires_review"]
            else "Human Review"
        )
        if not _has_keys(item, issue_fields | {"action"}) or any(
            item[field] != issue[field] for field in issue_fields
        ) or item["action"] != expected_action:
            return False
        action_counts[expected_action] += issue["count"]
        action_types[expected_action] += 1
    for action, suffix in (
        ("Automatic Fix", "automatic"),
        ("Human Review", "review"),
        ("Critical Action", "critical"),
    ):
        if (
            action_report[f"{suffix}_instances"] != action_counts[action]
            or action_report[f"{suffix}_types"] != action_types[action]
        ):
            return False
    if (
        action_report["total_instances"] != issue_instances
        or action_report["total_types"] != len(issues)
        or not all(
            isinstance(action_report[field], str) and action_report[field]
            for field in ("automation_status", "review_status", "critical_status")
        )
    ):
        return False

    issue_columns = [
        "Severity",
        "Category",
        "Issue",
        "Count",
        "Automatic Fix",
        "Human Review",
        "Business Impact",
    ]
    issue_rows = [
        [
            issue["severity"],
            issue["category"],
            issue["issue"],
            issue["count"],
            "Yes" if issue["auto_fix"] else "No",
            "Yes" if issue["requires_review"] else "No",
            issue["impact"],
        ]
        for issue in issues
    ]
    if not _is_table_payload(report["issue_table"], issue_columns):
        return False
    if report["issue_table"]["rows"] != issue_rows:
        return False

    export_values = {
        "Total Records": impact["total_records"],
        "Issues Before Cleaning": impact["issues_before"],
        "Issues After Cleaning": impact["issues_after"],
        "Issues Resolved": impact["issues_resolved"],
        "Automatic Changes": impact["automatic_changes"],
        "Records Affected": impact["affected_records"],
        "Affected Percentage": round(impact["affected_percentage"], 2),
        "Items Requiring Review": impact["review_items"],
        "Health Score Before": impact["before_score"],
        "Health Score After": impact["after_score"],
        "Health Score Change": impact["score_change"],
        "Critical Issues After": impact["critical_after"],
        "High Issues After": impact["high_after"],
        "Medium Issues After": impact["medium_after"],
        "Low Issues After": impact["low_after"],
    }
    export_report = report["export_report"]
    if (
        not _is_table_payload(export_report, ["Metric", "Value"])
        or len(export_report["rows"]) != len(EXPORT_METRIC_NAMES)
        or [row[0] for row in export_report["rows"]] != list(EXPORT_METRIC_NAMES)
        or any(
            not _is_finite_number(row[1])
            or not math.isclose(row[1], export_values[row[0]])
            for row in export_report["rows"]
        )
    ):
        return False
    return True


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/catalogs/analyze", response_model=CatalogAnalysisResponse)
def analyze_uploaded_catalog(
    file: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    if file is None:
        raise HTTPException(status_code=422, detail="A catalog file is required.")

    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED_FORMATS:
        file.file.close()
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload a CSV, XLSX, or XLS catalog.")

    try:
        file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        file.file.close()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded catalog exceeds the 10 MB limit.")

    try:
        source = BytesIO(file_bytes)
        source.name = filename
        dataframe = load_catalog(source)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read the uploaded catalog. Verify that it is a valid CSV or Excel file.",
        ) from exc
    try:
        result = analyze_catalog(dataframe)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Catalog analysis could not be completed.") from exc

    quality = result["quality_report"]
    after = result["after_results"]
    metrics = {
        "completeness": quality["completeness"],
        "validity": quality["validity"],
        "consistency": quality["consistency"],
        "uniqueness": quality["uniqueness"],
    }
    summary = {
        "decision": result["business_decision"]["decision"],
        "quality_status": quality["status"],
        "recommendations": quality["recommendations"],
        "top_problems": quality["top_problems"],
    }

    catalog = Catalog(
        original_filename=filename,
        file_format=suffix,
        row_count=len(dataframe),
        column_count=len(dataframe.columns),
        column_names=[str(column) for column in dataframe.columns],
        original_file=file_bytes,
        original_rows=dataframe_to_payload(dataframe),
    )
    report = {key: value for key, value in result.items() if key != "cleaned_df"}
    analysis = AnalysisRun(
        status="completed",
        completed_at=datetime.now(timezone.utc),
        health_score=int(quality["health_score"]),
        issue_count=sum(int(issue.get("count", 0)) for issue in result["issues"]),
        cleaned_record_count=len(result["cleaned_df"]),
        affected_record_count=int(result["impact_summary"]["affected_records"]),
        quality_metrics=to_json_safe(metrics),
        analysis_summary=to_json_safe(summary),
        cleaned_rows=dataframe_to_payload(result["cleaned_df"]),
        analysis_report=to_json_safe(report),
    )

    try:
        with db.begin():
            user = resolve_user_for_write(db, identity)
            catalog.owner_id = user.id
            db.add(catalog)
            db.flush()
            analysis.catalog_id = catalog.id
            db.add(analysis)
            db.flush()
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=500, detail="The analysis completed but could not be saved.") from exc

    return CatalogAnalysisResponse(
        status="completed",
        catalog_id=catalog.id,
        analysis_id=analysis.id,
        records=int(after["row_count"]),
        fields=int(after["column_count"]),
        health_score=int(quality["health_score"]),
        issue_count=analysis.issue_count,
        cleaned_records=len(result["cleaned_df"]),
        affected_records=analysis.affected_record_count,
        quality_metrics=metrics,
        summary=summary,
    )


def _is_idempotency_key_conflict(exc: IntegrityError) -> bool:
    original = exc.orig
    diagnostic = getattr(original, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == IDEMPOTENCY_CONSTRAINT:
        return True

    return (
        str(original)
        == "UNIQUE constraint failed: "
        "idempotency_records.owner_id, idempotency_records.key"
    )


def _set_async_response_headers(response: Response, analysis_id: UUID) -> str:
    status_url = f"/analyses/{analysis_id}/status"
    response.headers["Location"] = status_url
    response.headers["Retry-After"] = "2"
    return status_url


@app.post(
    "/v2/catalogs/analyze",
    response_model=AsyncSubmissionResponse,
    response_model_exclude_none=True,
    status_code=202,
)
def enqueue_catalog_analysis(
    response: Response,
    file: Optional[UploadFile] = File(default=None),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    if file is None:
        raise HTTPException(status_code=422, detail="A catalog file is required.")

    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 255:
            file.file.close()
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key must contain between 1 and 255 characters.",
            )

    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED_FORMATS:
        file.file.close()
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload a CSV, XLSX, or XLS catalog.")

    try:
        file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        file.file.close()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded catalog exceeds the 10 MB limit.")

    try:
        source = BytesIO(file_bytes)
        source.name = filename
        dataframe = load_catalog(source)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read the uploaded catalog. Verify that it is a valid CSV or Excel file.",
        ) from exc

    fingerprint = hashlib.sha256(file_bytes).hexdigest()
    catalog = Catalog(
        original_filename=filename,
        file_format=suffix,
        row_count=len(dataframe),
        column_count=len(dataframe.columns),
        column_names=[str(column) for column in dataframe.columns],
        original_file=file_bytes,
        original_rows=dataframe_to_payload(dataframe),
    )
    analysis = AnalysisRun(
        status="queued",
        attempt_count=0,
        retryable=False,
        health_score=0,
        issue_count=0,
        cleaned_record_count=0,
        affected_record_count=0,
        quality_metrics={},
        analysis_summary={},
        cleaned_rows=None,
        analysis_report=None,
    )

    try:
        with db.begin():
            user = resolve_user_for_write(db, identity)
            catalog.owner_id = user.id
            if idempotency_key is not None:
                existing = db.execute(
                    select(IdempotencyRecord, AnalysisRun)
                    .join(
                        AnalysisRun,
                        AnalysisRun.id == IdempotencyRecord.analysis_id,
                    )
                    .join(Catalog, Catalog.id == AnalysisRun.catalog_id)
                    .where(
                        IdempotencyRecord.owner_id == user.id,
                        IdempotencyRecord.key == idempotency_key,
                        Catalog.owner_id == user.id,
                    )
                ).one_or_none()
                if existing is not None:
                    record, existing_analysis = existing
                    if record.request_fingerprint != fingerprint:
                        raise HTTPException(
                            status_code=409,
                            detail="This Idempotency-Key was already used for different content.",
                        )
                    analysis_id = existing_analysis.id
                    catalog_id = existing_analysis.catalog_id
                    current_status = existing_analysis.status
                    return _async_submission_response(
                        response,
                        analysis_id,
                        catalog_id,
                        current_status,
                    )

            db.add(catalog)
            db.flush()
            analysis.catalog_id = catalog.id
            db.add(analysis)
            db.flush()
            if idempotency_key is not None:
                persist_idempotency_record(
                    db,
                    owner=user,
                    catalog=catalog,
                    analysis=analysis,
                    key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
    except IntegrityError as exc:
        if idempotency_key is None or not _is_idempotency_key_conflict(exc):
            raise HTTPException(
                status_code=503,
                detail="The analysis job could not be saved. Please try again.",
            ) from exc

        try:
            with db.begin():
                user_id = get_existing_user_id(db, identity)
                existing = None
                if user_id is not None:
                    existing = db.execute(
                        select(IdempotencyRecord, AnalysisRun)
                        .join(
                            AnalysisRun,
                            AnalysisRun.id == IdempotencyRecord.analysis_id,
                        )
                        .join(Catalog, Catalog.id == AnalysisRun.catalog_id)
                        .where(
                            IdempotencyRecord.owner_id == user_id,
                            IdempotencyRecord.key == idempotency_key,
                            Catalog.owner_id == user_id,
                        )
                    ).one_or_none()
                if existing is None:
                    raise HTTPException(
                        status_code=503,
                        detail="The analysis job could not be saved. Please try again.",
                    )
                record, existing_analysis = existing
                if record.request_fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="This Idempotency-Key was already used for different content.",
                    )
                analysis_id = existing_analysis.id
                catalog_id = existing_analysis.catalog_id
                current_status = existing_analysis.status
        except HTTPException:
            raise
        except SQLAlchemyError as lookup_exc:
            raise HTTPException(
                status_code=503,
                detail="The analysis job could not be saved. Please try again.",
            ) from lookup_exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="The analysis job could not be saved. Please try again.",
        ) from exc
    else:
        analysis_id = analysis.id
        catalog_id = catalog.id
        current_status = analysis.status

    return _async_submission_response(response, analysis_id, catalog_id, current_status)


def _async_submission_response(
    response: Response,
    analysis_id: UUID,
    catalog_id: UUID,
    current_status: str,
) -> AsyncSubmissionResponse:
    status_url = _set_async_response_headers(response, analysis_id)
    return AsyncSubmissionResponse(
        catalog_id=catalog_id,
        analysis_id=analysis_id,
        status=current_status,
        status_url=status_url,
        result_url=f"/analyses/{analysis_id}" if current_status == "completed" else None,
    )


def _owned_user_id(db: Session, identity: VerifiedIdentity) -> UUID:
    user_id = get_existing_user_id(db, identity)
    if user_id is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return user_id


def _owned_analysis(db: Session, analysis_id: UUID, owner_id: UUID) -> AnalysisRun:
    analysis = db.scalar(
        select(AnalysisRun)
        .join(Catalog, Catalog.id == AnalysisRun.catalog_id)
        .where(
            AnalysisRun.id == analysis_id,
            Catalog.owner_id == owner_id,
        )
    )
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return analysis


@app.post(
    "/analyses/{analysis_id}/retry",
    response_model=AnalysisRetryResponse,
    status_code=202,
)
def retry_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    _owned_analysis(db, analysis_id, _owned_user_id(db, identity))
    try:
        retry_failed_job(db, analysis_id)
        db.commit()
    except JobTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="The analysis job could not be retried. Please try again.",
        ) from exc
    return AnalysisRetryResponse(analysis_id=analysis_id, status="queued")


@app.get("/catalogs/{catalog_id}", response_model=CatalogDetailResponse)
def get_catalog(
    catalog_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    owner_id = _owned_user_id(db, identity)
    catalog = db.scalar(
        select(Catalog).where(
            Catalog.id == catalog_id,
            Catalog.owner_id == owner_id,
        )
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Catalog not found.")
    return catalog


@app.get("/catalogs/{catalog_id}/analyses", response_model=List[AnalysisHistoryItem])
def get_catalog_analyses(
    catalog_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    owner_id = _owned_user_id(db, identity)
    catalog = db.scalar(
        select(Catalog.id).where(
            Catalog.id == catalog_id,
            Catalog.owner_id == owner_id,
        )
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Catalog not found.")
    statement = (
        select(AnalysisRun)
        .where(AnalysisRun.catalog_id == catalog_id)
        .where(AnalysisRun.status == "completed")
        .order_by(AnalysisRun.completed_at.desc())
    )
    return list(db.scalars(statement).all())


@app.get(
    "/v2/catalogs/{catalog_id}/analyses",
    response_model=List[AsyncAnalysisHistoryItem],
)
def get_catalog_analysis_history_v2(
    catalog_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    owner_id = _owned_user_id(db, identity)
    catalog = db.scalar(
        select(Catalog.id).where(
            Catalog.id == catalog_id,
            Catalog.owner_id == owner_id,
        )
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Catalog not found.")
    statement = (
        select(AnalysisRun)
        .where(AnalysisRun.catalog_id == catalog_id)
        .order_by(AnalysisRun.created_at.desc())
    )
    return list(db.scalars(statement).all())


@app.get(
    "/analyses/{analysis_id}/status",
    response_model=AnalysisStatusResponse,
    response_model_exclude_none=True,
)
def get_analysis_status(
    analysis_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    analysis = _owned_analysis(db, analysis_id, _owned_user_id(db, identity))

    failed_error = None
    if analysis.status == "failed":
        failed_error = SafeAnalysisError(
            code="analysis_failed",
            message=SAFE_FAILURE_MESSAGE,
        )
    return AnalysisStatusResponse(
        analysis_id=analysis.id,
        catalog_id=analysis.catalog_id,
        status=analysis.status,
        attempt_count=analysis.attempt_count,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        updated_at=analysis.updated_at,
        completed_at=analysis.completed_at,
        retryable=analysis.retryable,
        error=failed_error,
        result_url=f"/analyses/{analysis.id}" if analysis.status == "completed" else None,
    )


@app.get("/analyses/{analysis_id}", response_model=AnalysisDetailResponse)
def get_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    analysis = _owned_analysis(db, analysis_id, _owned_user_id(db, identity))
    if analysis.status != "completed":
        detail: Dict[str, Any] = {
            "status": analysis.status,
            "status_url": f"/analyses/{analysis.id}/status",
        }
        if analysis.status == "failed":
            detail["error"] = {
                "code": "analysis_failed",
                "message": SAFE_FAILURE_MESSAGE,
                "retryable": analysis.retryable,
            }
        raise HTTPException(status_code=409, detail=detail)
    if not _valid_analysis_result(analysis):
        raise HTTPException(
            status_code=500,
            detail="The stored analysis result is invalid or incomplete.",
        )
    return analysis


@app.get("/catalogs/{catalog_id}/file")
def download_original_catalog(
    catalog_id: UUID,
    db: Session = Depends(get_api_db_session),
    identity: VerifiedIdentity = Depends(get_authenticated_identity),
):
    owner_id = _owned_user_id(db, identity)
    catalog = db.scalar(
        select(Catalog).where(
            Catalog.id == catalog_id,
            Catalog.owner_id == owner_id,
        )
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Catalog not found.")
    if catalog.original_file is None:
        raise HTTPException(status_code=404, detail="The original uploaded file is not available.")

    media_types = {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
    }
    return Response(
        content=catalog.original_file,
        media_type=media_types.get(catalog.file_format, "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(catalog.original_filename)}"
        },
    )
