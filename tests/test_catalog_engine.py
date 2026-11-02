import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from action_report import build_action_report
from cleaner import clean_catalog
from decision_engine import build_business_decision
from impact_report import build_export_report, build_impact_summary
from issue_analysis import analyze_issues, build_issue_dataframe
from quality_checks import run_quality_checks
from report import build_quality_report


ROOT_DIR = Path(__file__).resolve().parents[1]


class CatalogEngineTests(unittest.TestCase):
    def test_imports_without_streamlit(self):
        script = (
            "import sys; "
            "import catalog_engine; "
            "assert 'streamlit' not in sys.modules"
        )
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT_DIR,
            check=True,
        )

    def test_analyzes_dataframe_and_returns_application_results(self):
        from catalog_engine import analyze_catalog

        catalog = pd.DataFrame(
            {
                "SKU": ["SKU-1", "SKU-2"],
                "Product Name": ["Widget", "Gadget"],
                "Price": ["12.50", "25"],
                "Category": ["Tools", "Electronics"],
            }
        )

        result = analyze_catalog(catalog)

        self.assertEqual(
            set(result),
            {
                "before_results",
                "cleaned_df",
                "change_log",
                "after_results",
                "impact_summary",
                "quality_report",
                "business_decision",
                "issues",
                "action_report",
                "issue_table",
                "export_report",
            },
        )
        self.assertEqual(len(result["cleaned_df"]), len(catalog))
        self.assertGreaterEqual(result["after_results"]["health_score"], 0)
        self.assertLessEqual(result["after_results"]["health_score"], 100)
        self.assertIsInstance(result["change_log"], list)
        self.assertTrue(
            all(isinstance(change, dict) for change in result["change_log"])
        )
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["action_report"], dict)
        self.assertIsInstance(result["business_decision"], dict)
        self.assertIsInstance(result["quality_report"], dict)
        self.assertIsInstance(result["issue_table"], pd.DataFrame)
        self.assertIsInstance(result["export_report"], pd.DataFrame)

    def test_matches_direct_orchestration_for_adversarial_fixture(self):
        from catalog_engine import analyze_catalog

        fixture_path = (
            ROOT_DIR
            / "sample_data"
            / "adversarial"
            / "05_garbage_values.csv"
        )
        catalog = pd.read_csv(fixture_path)

        expected_before = run_quality_checks(catalog)
        expected_cleaned, expected_change_log = clean_catalog(catalog.copy())
        expected_after = run_quality_checks(expected_cleaned)
        expected_impact = build_impact_summary(
            expected_before,
            expected_after,
            expected_change_log,
        )
        expected_issues = analyze_issues(expected_after)
        expected = {
            "before_results": expected_before,
            "cleaned_df": expected_cleaned,
            "change_log": expected_change_log,
            "after_results": expected_after,
            "impact_summary": expected_impact,
            "quality_report": build_quality_report(expected_after),
            "business_decision": build_business_decision(expected_after),
            "issues": expected_issues,
            "action_report": build_action_report(expected_issues),
            "issue_table": build_issue_dataframe(expected_issues),
            "export_report": build_export_report(
                expected_before,
                expected_after,
                expected_impact,
            ),
        }

        actual = analyze_catalog(catalog)
        self.assertEqual(set(actual), set(expected))
        for key in expected:
            with self.subTest(result=key):
                self.assert_equivalent(expected[key], actual[key])
        self.assertEqual(len(actual["cleaned_df"]), len(catalog))

    def assert_equivalent(self, expected, actual):
        if isinstance(expected, pd.DataFrame):
            assert_frame_equal(expected, actual)
        elif isinstance(expected, dict):
            self.assertEqual(set(expected), set(actual))
            for key in expected:
                self.assert_equivalent(expected[key], actual[key])
        elif isinstance(expected, (list, tuple)):
            self.assertEqual(len(expected), len(actual))
            for expected_item, actual_item in zip(expected, actual):
                self.assert_equivalent(expected_item, actual_item)
        else:
            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
