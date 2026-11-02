import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app


ROOT_DIR = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


class CatalogApiTests(unittest.TestCase):
    def test_health(self):
        response = CLIENT.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_openapi_docs_routes_are_available(self):
        self.assertEqual(CLIENT.get("/openapi.json").status_code, 200)
        self.assertEqual(CLIENT.get("/docs").status_code, 200)

    def test_missing_upload_returns_validation_error(self):
        response = CLIENT.post("/catalogs/analyze")

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("Traceback", response.text)

    def test_csv_analysis_returns_json_safe_summary(self):
        fixture_path = (
            ROOT_DIR
            / "sample_data"
            / "adversarial"
            / "08_clean_catalog.csv"
        )
        response = CLIENT.post(
            "/catalogs/analyze",
            files={
                "file": (
                    "catalog.csv",
                    fixture_path.read_bytes(),
                    "text/csv",
                )
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["records"], 5)
        self.assertEqual(payload["fields"], 8)
        self.assertEqual(payload["cleaned_records"], 5)
        self.assertGreaterEqual(payload["health_score"], 0)
        self.assertLessEqual(payload["health_score"], 100)
        self.assertIsInstance(payload["issue_count"], int)
        self.assertEqual(
            set(payload["quality_metrics"]),
            {"completeness", "validity", "consistency", "uniqueness"},
        )
        self.assertIn("decision", payload["summary"])
        self.assertIn("top_problems", payload["summary"])

    def test_xlsx_analysis_succeeds(self):
        catalog = pd.DataFrame(
            {
                "sku": ["XLSX-1"],
                "product_name": ["Widget"],
                "price": [12.5],
                "category": ["Tools"],
            }
        )
        content = io.BytesIO()
        catalog.to_excel(content, index=False, engine="openpyxl")

        response = CLIENT.post(
            "/catalogs/analyze",
            files={
                "file": (
                    "catalog.xlsx",
                    content.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["records"], 1)
        self.assertEqual(response.json()["fields"], 4)

    def test_unsupported_file_returns_safe_error(self):
        private_value = "PRIVATE_CATALOG_CONTENT"
        response = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.txt", private_value.encode(), "text/plain")},
        )

        self.assertEqual(response.status_code, 415)
        self.assertNotIn(private_value, response.text)
        self.assertNotIn("Traceback", response.text)

    def test_malformed_csv_returns_safe_error(self):
        private_value = "PRIVATE_CATALOG_CONTENT"
        response = CLIENT.post(
            "/catalogs/analyze",
            files={
                "file": (
                    "catalog.csv",
                    b"\xff" + private_value.encode(),
                    "text/csv",
                )
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(private_value, response.text)
        self.assertNotIn("Traceback", response.text)

    def test_analysis_failure_returns_safe_error(self):
        with patch("api.main.analyze_catalog", side_effect=RuntimeError("secret detail")):
            response = CLIENT.post(
                "/catalogs/analyze",
                files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
            )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret detail", response.text)
        self.assertNotIn("Traceback", response.text)

    def test_api_import_does_not_add_fastapi_dependency_to_engine(self):
        script = (
            "import sys; "
            "import catalog_engine; "
            "import catalog_ingestion; "
            "assert 'fastapi' not in sys.modules; "
            "assert 'streamlit' not in sys.modules"
        )
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT_DIR,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
