import random
import pandas as pd


random.seed(2026)


# ==========================================================
# PRODUCT DATA
# ==========================================================

products = [
    {
        "sku": "SKU-001",
        "product_name": "iPhone 15",
        "price": 1250000,
        "category": "Phones",
        "description": "Apple iPhone 15 128GB",
        "email": "sales@example.com",
        "website": "https://example.com/iphone15",
        "phone": "08012345678",
    },
    {
        "sku": "SKU-002",
        "product_name": "Samsung Galaxy S24",
        "price": 1100000,
        "category": "Phones",
        "description": "Samsung Galaxy S24 smartphone",
        "email": "sales@example.com",
        "website": "https://example.com/s24",
        "phone": "08023456789",
    },
    {
        "sku": "SKU-003",
        "product_name": "HP EliteBook 840",
        "price": 850000,
        "category": "Laptops",
        "description": "Business laptop with Intel processor",
        "email": "support@example.com",
        "website": "https://example.com/hp840",
        "phone": "08034567890",
    },
    {
        "sku": "SKU-004",
        "product_name": "Dell Latitude 5420",
        "price": 720000,
        "category": "Laptops",
        "description": "Dell business laptop",
        "email": "support@example.com",
        "website": "https://example.com/dell5420",
        "phone": "08045678901",
    },
    {
        "sku": "SKU-005",
        "product_name": "Sony WH-1000XM5",
        "price": 450000,
        "category": "Audio",
        "description": "Wireless noise cancelling headphones",
        "email": "audio@example.com",
        "website": "https://example.com/sony",
        "phone": "08056789012",
    },
    {
        "sku": "SKU-006",
        "product_name": "Apple Watch Series 9",
        "price": 380000,
        "category": "Wearables",
        "description": "Apple smartwatch",
        "email": "wearables@example.com",
        "website": "https://example.com/watch",
        "phone": "08067890123",
    },
    {
        "sku": "SKU-007",
        "product_name": "JBL Flip 6",
        "price": 150000,
        "category": "Audio",
        "description": "Portable Bluetooth speaker",
        "email": "audio@example.com",
        "website": "https://example.com/jbl",
        "phone": "08078901234",
    },
    {
        "sku": "SKU-008",
        "product_name": "Logitech MX Master 3S",
        "price": 95000,
        "category": "Accessories",
        "description": "Wireless productivity mouse",
        "email": "sales@example.com",
        "website": "https://example.com/logitech",
        "phone": "08089012345",
    },
    {
        "sku": "SKU-009",
        "product_name": "Anker PowerCore 20K",
        "price": 65000,
        "category": "Accessories",
        "description": "20,000mAh portable power bank",
        "email": "sales@example.com",
        "website": "https://example.com/anker",
        "phone": "08090123456",
    },
    {
        "sku": "SKU-010",
        "product_name": "Nike Air Max",
        "price": 180000,
        "category": "Fashion",
        "description": "Nike running shoes",
        "email": "fashion@example.com",
        "website": "https://example.com/nike",
        "phone": "08101234567",
    },
]


# ==========================================================
# GENERATE BASE DATA
# ==========================================================

rows = []


for product in products:

    for copy_number in range(1, 6):

        row = product.copy()

        # Create a slightly different SKU
        row["sku"] = f"{product['sku']}-{copy_number}"

        rows.append(row)


# ==========================================================
# APPLY DATA QUALITY DAMAGE
# ==========================================================

for row in rows:

    damage_type = random.randint(
        1,
        20
    )


    # ------------------------------------------------------
    # WHITESPACE
    # ------------------------------------------------------

    if damage_type == 1:

        row["product_name"] = (
            "   "
            + row["product_name"]
            + "   "
        )


    # ------------------------------------------------------
    # RANDOM CASING
    # ------------------------------------------------------

    elif damage_type == 2:

        row["product_name"] = (
            row["product_name"].upper()
        )


    # ------------------------------------------------------
    # CATEGORY CASING
    # ------------------------------------------------------

    elif damage_type == 3:

        row["category"] = (
            row["category"].upper()
        )


    # ------------------------------------------------------
    # CATEGORY WHITESPACE
    # ------------------------------------------------------

    elif damage_type == 4:

        row["category"] = (
            " "
            + row["category"]
            + " "
        )


    # ------------------------------------------------------
    # CURRENCY FORMATTING
    # ------------------------------------------------------

    elif damage_type == 5:

        row["price"] = (
            f"₦{row['price']:,}"
        )


    # ------------------------------------------------------
    # DOLLAR FORMATTING
    # ------------------------------------------------------

    elif damage_type == 6:

        row["price"] = (
            f"${row['price']:,}"
        )


    # ------------------------------------------------------
    # COMMA FORMATTING
    # ------------------------------------------------------

    elif damage_type == 7:

        row["price"] = (
            f"{row['price']:,}"
        )


    # ------------------------------------------------------
    # NEGATIVE PRICE
    # ------------------------------------------------------

    elif damage_type == 8:

        row["price"] = -abs(
            row["price"]
        )


    # ------------------------------------------------------
    # MISSING PRICE
    # ------------------------------------------------------

    elif damage_type == 9:

        row["price"] = ""


    # ------------------------------------------------------
    # MISSING DESCRIPTION
    # ------------------------------------------------------

    elif damage_type == 10:

        row["description"] = ""


    # ------------------------------------------------------
    # MISSING SKU
    # ------------------------------------------------------

    elif damage_type == 11:

        row["sku"] = ""


    # ------------------------------------------------------
    # INVALID EMAIL
    # ------------------------------------------------------

    elif damage_type == 12:

        row["email"] = (
            "sales@@example"
        )


    # ------------------------------------------------------
    # INVALID WEBSITE
    # ------------------------------------------------------

    elif damage_type == 13:

        row["website"] = (
            "example.com/product"
        )


    # ------------------------------------------------------
    # BAD PHONE
    # ------------------------------------------------------

    elif damage_type == 14:

        row["phone"] = (
            "08012ABC789"
        )


    # ------------------------------------------------------
    # WEIRD WHITESPACE
    # ------------------------------------------------------

    elif damage_type == 15:

        row["description"] = (
            "  "
            + row["description"]
            + "   "
        )


    # ------------------------------------------------------
    # NULL DESCRIPTION
    # ------------------------------------------------------

    elif damage_type == 16:

        row["description"] = None


    # ------------------------------------------------------
    # SUSPICIOUS PRICE
    # ------------------------------------------------------

    elif damage_type == 17:

        row["price"] = 1


    # ------------------------------------------------------
    # EXTREME PRICE
    # ------------------------------------------------------

    elif damage_type == 18:

        row["price"] = 999999999


    # ------------------------------------------------------
    # CATEGORY TYPO
    # ------------------------------------------------------

    elif damage_type == 19:

        row["category"] = (
            row["category"][:-1]
        )


    # ------------------------------------------------------
    # SKU WHITESPACE
    # ------------------------------------------------------

    elif damage_type == 20:

        row["sku"] = (
            " "
            + row["sku"]
            + " "
        )


# ==========================================================
# ADD DUPLICATE SKU RECORDS
# ==========================================================

duplicate_rows = random.sample(
    rows,
    8
)


for row in duplicate_rows:

    duplicated = row.copy()

    rows.append(
        duplicated
    )


# ==========================================================
# ADD EXACT DUPLICATE ROWS
# ==========================================================

exact_duplicates = random.sample(
    rows,
    5
)


for row in exact_duplicates:

    rows.append(
        row.copy()
    )


# ==========================================================
# ADD COMPLETELY BROKEN ROWS
# ==========================================================

rows.append({
    "sku": "",
    "product_name": "",
    "price": "",
    "category": "",
    "description": "",
    "email": "",
    "website": "",
    "phone": "",
})


rows.append({
    "sku": "BROKEN-001",
    "product_name": "Mystery Product",
    "price": "not available",
    "category": "???",
    "description": None,
    "email": "broken-email",
    "website": "not-a-url",
    "phone": "abc",
})


# ==========================================================
# CREATE DATAFRAME
# ==========================================================

df = pd.DataFrame(
    rows
)


# ==========================================================
# SHUFFLE ROWS
# ==========================================================

df = df.sample(
    frac=1,
    random_state=2026
).reset_index(
    drop=True
)


# ==========================================================
# ADD EXTRA EMPTY COLUMN
# ==========================================================

df[""] = ""


# ==========================================================
# ADD WEIRD HEADER
# ==========================================================

df = df.rename(
    columns={
        "product_name": " Product Name ",
        "description": " Product Description ",
        "website": "Website URL",
    }
)


# ==========================================================
# SAVE
# ==========================================================

output_file = (
    "sample_data/"
    "torture_catalog.csv"
)


df.to_csv(
    output_file,
    index=False
)


print(
    f"Generated {len(df):,} rows."
)

print(
    f"Saved to: {output_file}"
)