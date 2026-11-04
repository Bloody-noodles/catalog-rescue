import math
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import numpy as np
import pandas as pd


def dataframe_to_payload(dataframe: pd.DataFrame) -> dict:
    """Preserve column order and duplicate column names in JSON storage."""
    return {
        "columns": [to_json_safe(column) for column in dataframe.columns.tolist()],
        "rows": [
            [to_json_safe(value) for value in row]
            for row in dataframe.itertuples(index=False, name=None)
        ],
    }


def to_json_safe(value):
    """Convert Pandas, NumPy and common Python values to JSON-safe values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.DataFrame):
        return dataframe_to_payload(value)
    if isinstance(value, pd.Series):
        return [to_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, set):
        return [to_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
