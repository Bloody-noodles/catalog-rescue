import pandas as pd


def clean_column_names(df):
    """
    Standardize column names and record changes.
    """

    df = df.copy()
    changes = []

    original_columns = list(df.columns)

    new_columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
    )

    for old, new in zip(original_columns, new_columns):

        if old != new:
            changes.append({
                "row": "HEADER",
                "field": str(old),
                "before": str(old),
                "after": str(new),
                "reason": "Standardized column name"
            })

    df.columns = new_columns

    return df, changes


def clean_text_columns(df):
    """
    Remove unnecessary whitespace from text fields.
    """

    df = df.copy()
    changes = []

    for column in df.columns:

        dtype = df[column].dtype
        if not (
            pd.api.types.is_object_dtype(dtype)
            or isinstance(dtype, pd.StringDtype)
        ):
            continue

        for index in df.index:

            original = df.at[index, column]

            if pd.isna(original):
                continue

            original_string = str(original)
            cleaned_string = original_string.strip()

            if original_string != cleaned_string:

                changes.append({
                    "row": int(index) + 2,
                    "field": column,
                    "before": original_string,
                    "after": cleaned_string,
                    "reason": "Removed unnecessary whitespace"
                })

                df.at[index, column] = cleaned_string

    return df, changes


def clean_price_column(df):
    """
    Normalize common currency-formatted prices.
    """

    df = df.copy()
    changes = []

    if "price" not in df.columns:
        return df, changes

    df["price"] = df["price"].astype(object)

    for index in df.index:

        original = df.at[index, "price"]

        if pd.isna(original):
            continue

        original_string = str(original).strip()

        cleaned_string = (
            original_string
            .replace(",", "")
            .replace("₦", "")
            .replace("$", "")
            .replace("£", "")
            .strip()
        )

        numeric_value = pd.to_numeric(
            cleaned_string,
            errors="coerce"
        )

        if pd.isna(numeric_value):
            continue

        if original_string != str(numeric_value):

            changes.append({
                "row": int(index) + 2,
                "field": "price",
                "before": original_string,
                "after": numeric_value,
                "reason": "Normalized price format"
            })

        df.at[index, "price"] = numeric_value

    return df, changes


def normalize_categories(df):
    """
    Standardize category capitalization and whitespace.
    """

    df = df.copy()
    changes = []

    if "category" not in df.columns:
        return df, changes

    for index in df.index:

        original = df.at[index, "category"]

        if pd.isna(original):
            continue

        original_string = str(original)

        cleaned_string = (
            original_string
            .strip()
            .title()
        )

        if original_string.lower() == "nan":
            cleaned_string = ""

        if original_string != cleaned_string:

            changes.append({
                "row": int(index) + 2,
                "field": "category",
                "before": original_string,
                "after": cleaned_string,
                "reason": "Standardized category formatting"
            })

            df.at[index, "category"] = cleaned_string

    return df, changes


def clean_catalog(df):
    """
    Run the complete catalog cleaning pipeline.

    Returns:
        cleaned dataframe
        change log
    """

    cleaned = df.copy()
    all_changes = []

    cleaned, changes = clean_column_names(cleaned)
    all_changes.extend(changes)

    cleaned, changes = clean_text_columns(cleaned)
    all_changes.extend(changes)

    cleaned, changes = clean_price_column(cleaned)
    all_changes.extend(changes)

    cleaned, changes = normalize_categories(cleaned)
    all_changes.extend(changes)

    return cleaned, all_changes