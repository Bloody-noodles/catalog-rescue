import unittest

import pandas as pd

from cleaner import clean_catalog


class CleanCatalogTests(unittest.TestCase):
    def test_string_dtype_catalog_with_large_numeric_price(self):
        catalog = pd.DataFrame(
            {
                "sku": pd.Series(["SKU-1"], dtype="string"),
                "product_name": pd.Series(["  Widget  "], dtype="string"),
                "price": pd.Series(["999999999"], dtype="string"),
                "category": pd.Series(["Tools"], dtype="string"),
            }
        )

        cleaned, _ = clean_catalog(catalog)

        self.assertEqual(cleaned.loc[0, "product_name"], "Widget")
        self.assertEqual(cleaned.loc[0, "price"], 999999999)


if __name__ == "__main__":
    unittest.main()
