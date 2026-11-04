import unittest

import numpy as np
import pandas as pd

from database.serialization import dataframe_to_payload, to_json_safe


class DatabaseSerializationTests(unittest.TestCase):
    def test_dataframe_payload_preserves_duplicate_column_names(self):
        frame = pd.DataFrame([["SKU-1", 12.5]], columns=["sku", "sku"])
        payload = dataframe_to_payload(frame)
        self.assertEqual(payload["columns"], ["sku", "sku"])
        self.assertEqual(payload["rows"], [["SKU-1", 12.5]])

    def test_nested_pandas_and_numpy_values_are_json_safe(self):
        value = {
            "count": np.int64(3),
            "score": np.float64(92.5),
            "missing": np.nan,
            "timestamp": pd.Timestamp("2026-11-03T12:00:00Z"),
            "frame": pd.DataFrame({"sku": ["A", None]}),
        }
        result = to_json_safe(value)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["score"], 92.5)
        self.assertIsNone(result["missing"])
        self.assertEqual(result["timestamp"], "2026-11-03T12:00:00+00:00")
        self.assertEqual(result["frame"]["rows"], [["A"], [None]])


if __name__ == "__main__":
    unittest.main()
