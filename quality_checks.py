import pandas as pd
from validators import (
    is_missing,
    is_valid_email,
    is_valid_url,
    is_valid_phone,
    is_valid_sku_format,
    is_suspicious_price,
)

REQUIRED_COLUMNS = ["sku", "product_name", "price", "category"]


def normalize_column_names(df):
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
    )
    return df


def check_required_columns(df):
    return [column for column in REQUIRED_COLUMNS if column not in df.columns]


def check_missing_values(df):
    missing = {}
    for column in df.columns:
        count = sum(is_missing(value) for value in df[column])
        if count > 0:
            missing[column] = count
    return missing


def check_duplicate_skus(df):
    if "sku" not in df.columns:
        return pd.DataFrame()
    sku = df["sku"].astype(str).str.strip()
    valid_sku = ~sku.str.lower().isin(["", "nan", "none", "null"])
    return df[valid_sku & sku.duplicated(keep=False)]


def check_duplicate_rows(df):
    return df[df.duplicated(keep=False)]


def check_invalid_prices(df):
    if "price" not in df.columns:
        return pd.DataFrame()
    prices = (
        df["price"].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₦", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("£", "", regex=False)
        .str.strip()
    )
    numeric_prices = pd.to_numeric(prices, errors="coerce")
    invalid = numeric_prices.isna() | (numeric_prices <= 0)
    return df[invalid]


def check_suspicious_prices(df):
    if "price" not in df.columns:
        return pd.DataFrame()
    return df[df["price"].apply(is_suspicious_price)]


def check_blank_skus(df):
    if "sku" not in df.columns:
        return pd.DataFrame()
    return df[df["sku"].apply(is_missing)]


def check_invalid_sku_formats(df):
    if "sku" not in df.columns:
        return pd.DataFrame()
    mask = ~df["sku"].apply(is_missing) & ~df["sku"].apply(is_valid_sku_format)
    return df[mask]


def check_category_variations(df):
    if "category" not in df.columns:
        return {}
    categories = df["category"].dropna().astype(str).str.strip()
    normalized = categories.str.lower()
    groups = {}
    for value in normalized.unique():
        original_values = sorted(categories[normalized == value].unique())
        if len(original_values) > 1:
            groups[value] = original_values
    return groups


def check_missing_descriptions(df):
    if "product_description" in df.columns:
        column = "product_description"
    elif "description" in df.columns:
        column = "description"
    else:
        return pd.DataFrame()
    return df[df[column].apply(is_missing)]


def check_invalid_emails(df):
    if "email" not in df.columns:
        return pd.DataFrame()
    mask = ~df["email"].apply(is_missing) & ~df["email"].apply(is_valid_email)
    return df[mask]


def check_invalid_urls(df):
    if "website_url" in df.columns:
        column = "website_url"
    elif "website" in df.columns:
        column = "website"
    else:
        return pd.DataFrame()
    mask = ~df[column].apply(is_missing) & ~df[column].apply(is_valid_url)
    return df[mask]


def check_invalid_phones(df):
    if "phone" not in df.columns:
        return pd.DataFrame()
    mask = ~df["phone"].apply(is_missing) & ~df["phone"].apply(is_valid_phone)
    return df[mask]


def check_empty_columns(df):
    empty_columns = []
    for column in df.columns:
        if all(is_missing(value) for value in df[column]):
            empty_columns.append(column)
    return empty_columns


def calculate_completeness(df, results):
    if len(df) <= 0:
        return 0.0

    total_cells = len(df) * len(df.columns)
    if total_cells <= 0:
        return 0.0

    missing_cells = sum(results.get("missing_values", {}).values())
    score = (1 - (missing_cells / total_cells)) * 100
    missing_columns = len(results.get("missing_columns", []))
    if missing_columns:
        score -= min(missing_columns * 5, 20)
    return round(max(0, min(score, 100)), 1)


def calculate_validity(results):
    row_count = results.get("row_count", 0)
    if row_count <= 0:
        return 0.0

    invalid_counts = [
        len(results.get("invalid_prices", [])),
        len(results.get("invalid_emails", [])),
        len(results.get("invalid_urls", [])),
        len(results.get("invalid_phones", [])),
        len(results.get("invalid_sku_formats", [])),
    ]
    total_invalid = sum(invalid_counts)
    penalty = min((total_invalid / row_count) * 100, 100)
    return round(max(0, 100 - penalty), 1)


def calculate_consistency(results):
    row_count = results.get("row_count", 0)
    if row_count <= 0:
        return 0.0

    duplicate_rows = len(results.get("duplicate_rows", []))
    category_variations = len(results.get("category_variations", {}))
    invalid_sku_formats = len(results.get("invalid_sku_formats", []))
    duplicate_sku_records = len(results.get("duplicate_skus", []))
    affected = duplicate_rows + duplicate_sku_records + invalid_sku_formats
    row_penalty = min((affected / row_count) * 60, 60)
    category_penalty = min(category_variations * 5, 40)
    score = 100 - (row_penalty + category_penalty)
    return round(max(0, min(score, 100)), 1)


def calculate_uniqueness(results):
    row_count = results.get("row_count", 0)
    if row_count <= 0:
        return 0.0

    duplicate_skus = len(results.get("duplicate_skus", []))
    duplicate_rows = len(results.get("duplicate_rows", []))
    blank_skus = len(results.get("blank_skus", []))
    affected = duplicate_skus + duplicate_rows + blank_skus
    penalty = min((affected / row_count) * 100, 100)
    return round(max(0, 100 - penalty), 1)


def calculate_health_score(completeness, validity, consistency, uniqueness):
    score = (
        completeness * 0.30
        + validity * 0.35
        + consistency * 0.20
        + uniqueness * 0.15
    )
    return round(max(0, min(score, 100)))


def get_health_status(score, row_count=None):
    if row_count is not None and row_count <= 0:
        return "Insufficient Data"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs Attention"
    if score >= 40:
        return "Poor"
    return "Critical"


def run_quality_checks(df):
    df = normalize_column_names(df)
    results = {}
    results["row_count"] = len(df)
    results["column_count"] = len(df.columns)
    results["has_data"] = len(df) > 0
    results["data_status"] = "Ready for assessment" if len(df) > 0 else "Insufficient Data"

    results["missing_columns"] = check_required_columns(df)
    results["missing_values"] = check_missing_values(df)
    results["duplicate_skus"] = check_duplicate_skus(df)
    results["duplicate_rows"] = check_duplicate_rows(df)
    results["invalid_prices"] = check_invalid_prices(df)
    results["suspicious_prices"] = check_suspicious_prices(df)
    results["blank_skus"] = check_blank_skus(df)
    results["invalid_sku_formats"] = check_invalid_sku_formats(df)
    results["category_variations"] = check_category_variations(df)
    results["missing_descriptions"] = check_missing_descriptions(df)
    results["invalid_emails"] = check_invalid_emails(df)
    results["invalid_urls"] = check_invalid_urls(df)
    results["invalid_phones"] = check_invalid_phones(df)
    results["empty_columns"] = check_empty_columns(df)

    results["completeness"] = calculate_completeness(df, results)
    results["validity"] = calculate_validity(results)
    results["consistency"] = calculate_consistency(results)
    results["uniqueness"] = calculate_uniqueness(results)
    results["health_score"] = calculate_health_score(
        results["completeness"],
        results["validity"],
        results["consistency"],
        results["uniqueness"],
    )
    results["health_status"] = get_health_status(
        results["health_score"],
        row_count=results["row_count"],
    )

    return results
