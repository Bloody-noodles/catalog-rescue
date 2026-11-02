import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal


ROOT_DIR = Path(__file__).resolve().parents[1]


class CatalogIngestionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = pd.DataFrame(
            {
                "SKU": ["SKU-1", "SKU-2"],
                "Product Name": ["Widget", "Gadget"],
                "Price": [12.5, 25.0],
                "Category": ["Tools", "Electronics"],
            }
        )

    def test_csv_ingestion_returns_the_same_dataframe(self):
        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.csv"
            self.catalog.to_csv(path, index=False)

            actual = load_catalog(path)

        assert_frame_equal(actual, self.catalog)

    def test_xlsx_ingestion_returns_the_same_dataframe(self):
        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.xlsx"
            self.catalog.to_excel(path, index=False, engine="openpyxl")

            actual = load_catalog(path)

        assert_frame_equal(actual, self.catalog)

    def test_xls_follows_existing_excel_reader_path_when_engine_is_available(self):
        if (
            importlib.util.find_spec("xlrd") is None
            or importlib.util.find_spec("xlwt") is None
        ):
            self.skipTest(
                "No existing XLS fixture or reader/writer dependencies are available"
            )

        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.xls"
            self.catalog.to_excel(path, index=False, engine="xlwt")

            actual = load_catalog(path)

        assert_frame_equal(actual, self.catalog)

    def test_demo_catalog_preserves_shape_and_values(self):
        from catalog_ingestion import load_catalog

        path = ROOT_DIR / "sample_data" / "torture_catalog.csv"
        actual = load_catalog(path)
        expected = pd.read_csv(path, low_memory=False)

        self.assertEqual(actual.shape, (65, 9))
        assert_frame_equal(actual, expected)

    def test_import_does_not_import_streamlit(self):
        script = (
            "import sys; "
            "import catalog_ingestion; "
            "assert 'streamlit' not in sys.modules"
        )
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT_DIR,
            check=True,
        )

    def test_invalid_excel_file_propagates_reader_error(self):
        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.xlsx"
            path.write_text("not an Excel workbook", encoding="utf-8")

            with self.assertRaises((ValueError, OSError)):
                load_catalog(path)

    def test_csv_ingestion_output_can_be_analyzed(self):
        from catalog_engine import analyze_catalog
        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.csv"
            self.catalog.to_csv(path, index=False)

            result = analyze_catalog(load_catalog(path))

        self.assertEqual(len(result["cleaned_df"]), len(self.catalog))
        self.assertIn("health_score", result["after_results"])
        self.assertIn("health_score", result["quality_report"])

    def test_xlsx_ingestion_output_can_be_analyzed(self):
        from catalog_engine import analyze_catalog
        from catalog_ingestion import load_catalog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.xlsx"
            self.catalog.to_excel(path, index=False, engine="openpyxl")

            result = analyze_catalog(load_catalog(path))

        self.assertEqual(len(result["cleaned_df"]), len(self.catalog))
        self.assertIn("health_score", result["after_results"])


if __name__ == "__main__":
    unittest.main()
