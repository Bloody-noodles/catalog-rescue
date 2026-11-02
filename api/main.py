from io import BytesIO
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from catalog_engine import analyze_catalog
from catalog_ingestion import load_catalog


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
    records: int
    fields: int
    health_score: int
    issue_count: int
    cleaned_records: int
    affected_records: int
    quality_metrics: QualityMetrics
    summary: AnalysisSummary


app = FastAPI(title="Catalog Rescue API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/catalogs/analyze", response_model=CatalogAnalysisResponse)
def analyze_uploaded_catalog(
    file: Optional[UploadFile] = File(default=None),
):
    if file is None:
        raise HTTPException(status_code=422, detail="A catalog file is required.")

    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"csv", "xlsx", "xls"}:
        file.file.close()
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a CSV, XLSX, or XLS catalog.",
        )

    try:
        catalog_file = BytesIO(file.file.read())
        catalog_file.name = filename
        dataframe = load_catalog(catalog_file)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read the uploaded catalog. Verify that it is a valid CSV or Excel file.",
        ) from exc
    finally:
        file.file.close()

    try:
        result = analyze_catalog(dataframe)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Catalog analysis could not be completed.",
        ) from exc

    quality_report = result["quality_report"]
    after_results = result["after_results"]
    return CatalogAnalysisResponse(
        status="completed",
        records=after_results["row_count"],
        fields=after_results["column_count"],
        health_score=quality_report["health_score"],
        issue_count=sum(int(issue.get("count", 0)) for issue in result["issues"]),
        cleaned_records=len(result["cleaned_df"]),
        affected_records=result["impact_summary"]["affected_records"],
        quality_metrics=QualityMetrics(
            completeness=quality_report["completeness"],
            validity=quality_report["validity"],
            consistency=quality_report["consistency"],
            uniqueness=quality_report["uniqueness"],
        ),
        summary=AnalysisSummary(
            decision=result["business_decision"]["decision"],
            quality_status=quality_report["status"],
            recommendations=quality_report["recommendations"],
            top_problems=quality_report["top_problems"],
        ),
    )
