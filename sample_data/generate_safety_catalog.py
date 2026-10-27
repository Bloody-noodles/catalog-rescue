import os
import pandas as pd


OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__),
    "real_world"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)


rows = [
    # --------------------------------------------------------
    # SAFE FORMATTING CASES
    # --------------------------------------------------------

    {
        "sku": " SAFE-001 ",
        "product_name": "  Cotton T-Shirt  ",
        "price": "₦35,000",
        "category": " clothing ",
        "description": "Basic cotton t-shirt",
        "email": "sales@example.com",
        "website_url": "https://example.com/product/1",
        "phone": "08012345678",
        "stock": 25,
    },

    {
        "sku": "SAFE-002",
        "product_name": "Leather Shoes",
        "price": "35000",
        "category": "Clothing",
        "description": "Leather shoes",
        "email": "sales@example.com",
        "website_url": "https://example.com/product/2",
        "phone": "08012345678",
        "stock": 10,
    },

    # --------------------------------------------------------
    # SKU SAFETY CASES
    # --------------------------------------------------------

    {
        "sku": "ABC-001",
        "product_name": "Product A",
        "price": "₦20,000",
        "category": "Electronics",
        "description": "Test product",
        "email": "test@example.com",
        "website_url": "https://example.com/a",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": " ABC-002 ",
        "product_name": "Product B",
        "price": "₦25,000",
        "category": "Electronics",
        "description": "Test product",
        "email": "test@example.com",
        "website_url": "https://example.com/b",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "ABC 003",
        "product_name": "Product C",
        "price": "₦30,000",
        "category": "Electronics",
        "description": "SKU contains internal space",
        "email": "test@example.com",
        "website_url": "https://example.com/c",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "",
        "product_name": "Product D",
        "price": "₦40,000",
        "category": "Electronics",
        "description": "Missing SKU",
        "email": "test@example.com",
        "website_url": "https://example.com/d",
        "phone": "08012345678",
        "stock": 5,
    },

    # --------------------------------------------------------
    # PRICE SAFETY CASES
    # --------------------------------------------------------

    {
        "sku": "PRICE-001",
        "product_name": "Very Cheap Product",
        "price": "1",
        "category": "Misc",
        "description": "Price intentionally set to one",
        "email": "test@example.com",
        "website_url": "https://example.com/price1",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "PRICE-002",
        "product_name": "Extremely Expensive Product",
        "price": "999999999",
        "category": "Misc",
        "description": "Suspiciously high price",
        "email": "test@example.com",
        "website_url": "https://example.com/price2",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "PRICE-003",
        "product_name": "Negative Price Product",
        "price": "-5000",
        "category": "Misc",
        "description": "Invalid negative price",
        "email": "test@example.com",
        "website_url": "https://example.com/price3",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "PRICE-004",
        "product_name": "Zero Price Product",
        "price": "0",
        "category": "Misc",
        "description": "Zero price",
        "email": "test@example.com",
        "website_url": "https://example.com/price4",
        "phone": "08012345678",
        "stock": 5,
    },

    # --------------------------------------------------------
    # EMAIL SAFETY
    # --------------------------------------------------------

    {
        "sku": "EMAIL-001",
        "product_name": "Valid Email",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Valid email",
        "email": "sales@example.com",
        "website_url": "https://example.com/email1",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "EMAIL-002",
        "product_name": "Broken Email",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Invalid email",
        "email": "sales@@example.com",
        "website_url": "https://example.com/email2",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "EMAIL-003",
        "product_name": "Missing Email",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Missing email",
        "email": "",
        "website_url": "https://example.com/email3",
        "phone": "08012345678",
        "stock": 5,
    },

    # --------------------------------------------------------
    # URL SAFETY
    # --------------------------------------------------------

    {
        "sku": "URL-001",
        "product_name": "Valid URL",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Valid URL",
        "email": "test@example.com",
        "website_url": "https://example.com/product",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "URL-002",
        "product_name": "Missing Protocol",
        "price": "₦10,000",
        "category": "Misc",
        "description": "URL without protocol",
        "email": "test@example.com",
        "website_url": "example.com/product",
        "phone": "08012345678",
        "stock": 5,
    },

    # --------------------------------------------------------
    # PHONE SAFETY
    # --------------------------------------------------------

    {
        "sku": "PHONE-001",
        "product_name": "Valid Phone",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Valid phone",
        "email": "test@example.com",
        "website_url": "https://example.com/phone1",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "PHONE-002",
        "product_name": "Broken Phone",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Phone contains letters",
        "email": "test@example.com",
        "website_url": "https://example.com/phone2",
        "phone": "08012ABC789",
        "stock": 5,
    },

    {
        "sku": "PHONE-003",
        "product_name": "Short Phone",
        "price": "₦10,000",
        "category": "Misc",
        "description": "Phone too short",
        "email": "test@example.com",
        "website_url": "https://example.com/phone3",
        "phone": "123",
        "stock": 5,
    },

    # --------------------------------------------------------
    # STOCK SAFETY
    # --------------------------------------------------------

    {
        "sku": "STOCK-001",
        "product_name": "Zero Stock",
        "price": "₦10,000",
        "category": "Inventory",
        "description": "Zero stock may be intentional",
        "email": "test@example.com",
        "website_url": "https://example.com/stock1",
        "phone": "08012345678",
        "stock": 0,
    },

    {
        "sku": "STOCK-002",
        "product_name": "Negative Stock",
        "price": "₦10,000",
        "category": "Inventory",
        "description": "Negative stock should be reviewed",
        "email": "test@example.com",
        "website_url": "https://example.com/stock2",
        "phone": "08012345678",
        "stock": -5,
    },

    {
        "sku": "STOCK-003",
        "product_name": "Large Stock",
        "price": "₦10,000",
        "category": "Inventory",
        "description": "Large but potentially valid stock",
        "email": "test@example.com",
        "website_url": "https://example.com/stock3",
        "phone": "08012345678",
        "stock": 1000000,
    },

    # --------------------------------------------------------
    # CATEGORY CONSISTENCY
    # --------------------------------------------------------

    {
        "sku": "CAT-001",
        "product_name": "Category A",
        "price": "₦10,000",
        "category": "Shoes",
        "description": "Category test",
        "email": "test@example.com",
        "website_url": "https://example.com/cat1",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "CAT-002",
        "product_name": "Category B",
        "price": "₦10,000",
        "category": "shoes",
        "description": "Category test",
        "email": "test@example.com",
        "website_url": "https://example.com/cat2",
        "phone": "08012345678",
        "stock": 5,
    },

    {
        "sku": "CAT-003",
        "product_name": "Category C",
        "price": "₦10,000",
        "category": " SHOES ",
        "description": "Category test",
        "email": "test@example.com",
        "website_url": "https://example.com/cat3",
        "phone": "08012345678",
        "stock": 5,
    },
]


path = os.path.join(
    OUTPUT_DIR,
    "safety_test_catalog.csv"
)

df = pd.DataFrame(rows)

df.to_csv(
    path,
    index=False
)

print("=" * 60)
print("CATALOG RESCUE SAFETY TEST")
print("=" * 60)
print(f"Created: {path}")
print(f"Rows: {len(df)}")
print(f"Columns: {len(df.columns)}")
print("=" * 60)