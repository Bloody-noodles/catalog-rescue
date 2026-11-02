import os

import pandas as pd


def load_catalog(file_or_path):
    """Read a CSV or Excel catalog into a DataFrame using pandas defaults."""
    filename = getattr(file_or_path, "name", None)
    if filename is None:
        filename = os.fspath(file_or_path)

    if str(filename).lower().endswith(".csv"):
        return pd.read_csv(file_or_path, low_memory=False)

    return pd.read_excel(file_or_path)
