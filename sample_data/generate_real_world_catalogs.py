import os
import random
import pandas as pd


OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__),
    "real_world"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

random.seed(42)


# ============================================================
# HELPERS
# ============================================================

def save_catalog(filename, rows):
    path = os.path.join(OUTPUT_DIR, filename)
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f"Created: {path}")
    print(f"Rows: {len(df)} | Columns: {len(df.columns)}")
    print("-" * 60)


# ============================================================
# 1. FASHION STORE
# ============================================================

fashion_products = [
    {
        "SKU": "TSH-001",
        "Product Name": "Classic Cotton T-Shirt",
        "Category": "Clothing",
        "Size": "M",
        "Color": "Black",
        "Price": "₦18,500",
        "Stock": 24,
        "Description": "Classic cotton crew-neck t-shirt."
    },
    {
        "SKU": "TSH-002 ",
        "Product Name": "Classic Cotton T-Shirt",
        "Category": "clothing",
        "Size": "L",
        "Color": "Black",
        "Price": "18,500",
        "Stock": 15,
        "Description": "Classic cotton crew-neck t-shirt."
    },
    {
        "SKU": "TSH-003",
        "Product Name": "Classic Cotton T-Shirt",
        "Category": " CLOTHING ",
        "Size": "XL",
        "Color": "black",
        "Price": "₦18,500",
        "Stock": "",
        "Description": ""
    },
    {
        "SKU": "JEAN-001",
        "Product Name": "Slim Fit Denim Jeans",
        "Category": "Men",
        "Size": "32",
        "Color": "Blue",
        "Price": "₦45,000",
        "Stock": 8,
        "Description": "Slim fit stretch denim."
    },
    {
        "SKU": "JEAN-002",
        "Product Name": "Slim Fit Denim Jeans",
        "Category": "men ",
        "Size": "34",
        "Color": "Blue",
        "Price": "45000",
        "Stock": -3,
        "Description": "Slim fit stretch denim."
    },
    {
        "SKU": "",
        "Product Name": "Leather Sneakers",
        "Category": "Footwear",
        "Size": "42",
        "Color": "White",
        "Price": "₦72,000",
        "Stock": 5,
        "Description": "Premium leather sneakers."
    },
    {
        "SKU": "SNK-002",
        "Product Name": "Leather Sneakers",
        "Category": "footwear",
        "Size": "43",
        "Color": "White",
        "Price": "₦72,000",
        "Stock": 3,
        "Description": "Premium leather sneakers."
    },
    {
        "SKU": "SNK-002",
        "Product Name": "Leather Sneakers",
        "Category": "footwear",
        "Size": "43",
        "Color": "White",
        "Price": "₦72,000",
        "Stock": 3,
        "Description": "Premium leather sneakers."
    },
]


# ============================================================
# 2. ELECTRONICS STORE
# ============================================================

electronics_products = [
    {
        "sku": "IPH15-128",
        "product_name": "iPhone 15",
        "brand": "Apple",
        "category": "Smartphones",
        "price": "₦1,250,000",
        "stock": "12",
        "warranty": "12 months",
        "website_url": "https://example.com/iphone15"
    },
    {
        "sku": "IPH15-256",
        "product_name": "iPhone 15",
        "brand": "apple",
        "category": "smartphones",
        "price": "₦1,450,000",
        "stock": "8",
        "warranty": "12 Months",
        "website_url": "https://example.com/iphone15"
    },
    {
        "sku": "SAMS-S24",
        "product_name": "Samsung Galaxy S24",
        "brand": "Samsung",
        "category": "Smart Phone",
        "price": "₦1,100,000",
        "stock": "7",
        "warranty": "1 year",
        "website_url": "example.com/s24"
    },
    {
        "sku": "LAP-001",
        "product_name": "HP Pavilion 15",
        "brand": "HP",
        "category": "Laptops",
        "price": "₦950,000",
        "stock": "4",
        "warranty": "12 months",
        "website_url": "https://example.com/hp"
    },
    {
        "sku": "LAP-002",
        "product_name": "Dell Inspiron 15",
        "brand": "Dell",
        "category": "Laptops",
        "price": "-500000",
        "stock": "2",
        "warranty": "12 months",
        "website_url": "https://example.com/dell"
    },
    {
        "sku": "HEAD-001",
        "product_name": "Wireless Headphones",
        "brand": "Sony",
        "category": "Audio",
        "price": "1",
        "stock": "18",
        "warranty": "",
        "website_url": "https://example.com/sony"
    },
    {
        "sku": "HEAD-001",
        "product_name": "Wireless Headphones",
        "brand": "Sony",
        "category": "Audio",
        "price": "₦120,000",
        "stock": "18",
        "warranty": "",
        "website_url": "https://example.com/sony"
    },
]


# ============================================================
# 3. GROCERY STORE
# ============================================================

grocery_products = [
    {
        "sku": "RICE-001",
        "product_name": "Premium Long Grain Rice",
        "category": "Grains",
        "unit": "10kg",
        "price": "₦22,500",
        "quantity": 40,
        "supplier_email": "sales@groceryhub.com",
        "expiry_date": "2027-05-10"
    },
    {
        "sku": "RICE-002",
        "product_name": "Premium Long Grain Rice",
        "category": "grains",
        "unit": "5 kg",
        "price": "₦12,000",
        "quantity": 25,
        "supplier_email": "sales@@groceryhub.com",
        "expiry_date": "2027-05-10"
    },
    {
        "sku": "MILK-001",
        "product_name": "Full Cream Milk",
        "category": "Dairy",
        "unit": "1L",
        "price": "₦4,500",
        "quantity": -7,
        "supplier_email": "orders@groceryhub.com",
        "expiry_date": ""
    },
    {
        "sku": "MILK-002",
        "product_name": "Full Cream Milk",
        "category": " dairy ",
        "unit": "1 litre",
        "price": "₦4,500",
        "quantity": 16,
        "supplier_email": "orders@groceryhub.com",
        "expiry_date": "2026-01-10"
    },
    {
        "sku": "",
        "product_name": "Tomato Paste",
        "category": "Canned Foods",
        "unit": "400g",
        "price": "₦2,100",
        "quantity": 50,
        "supplier_email": "supplier@groceryhub.com",
        "expiry_date": "2027-02-20"
    },
    {
        "sku": "TOM-002",
        "product_name": "",
        "category": "Canned Foods",
        "unit": "400g",
        "price": "",
        "quantity": 20,
        "supplier_email": "",
        "expiry_date": ""
    },
]


# ============================================================
# 4. AUTO PARTS BUSINESS
# ============================================================

auto_parts = [
    {
        "part_number": "TOY-BRK-001",
        "product_name": "Toyota Corolla Brake Pad",
        "brand": "Toyota",
        "category": "Brake Parts",
        "price": "₦85,000",
        "vehicle_model": "Corolla",
        "year": "2015-2019",
        "phone": "08031234567"
    },
    {
        "part_number": "TOY-BRK-002 ",
        "product_name": "Toyota Corolla Brake Pad",
        "brand": "TOYOTA",
        "category": "brake parts",
        "price": "85000",
        "vehicle_model": "Corolla",
        "year": "2015-2019",
        "phone": "08031234567"
    },
    {
        "part_number": "HON-OIL-001",
        "product_name": "Honda Civic Oil Filter",
        "brand": "Honda",
        "category": "Filters",
        "price": "₦15,500",
        "vehicle_model": "Civic",
        "year": "2016-2020",
        "phone": "0803ABC4567"
    },
    {
        "part_number": "",
        "product_name": "Lexus RX350 Air Filter",
        "brand": "Lexus",
        "category": "Filters",
        "price": "₦22,000",
        "vehicle_model": "RX350",
        "year": "2018-2022",
        "phone": "08061234567"
    },
    {
        "part_number": "LEX-AIR-002",
        "product_name": "Lexus RX350 Air Filter",
        "brand": "Lexus",
        "category": "Filters",
        "price": "₦999999999",
        "vehicle_model": "RX350",
        "year": "2018-2022",
        "phone": "08061234567"
    },
]


# ============================================================
# 5. MARKETPLACE IMPORT
# ============================================================

marketplace_products = [
    {
        " Product Name ": "Bluetooth Speaker",
        "SKU": "SPK-001",
        "Price": "₦35,000",
        "Category": "Electronics",
        "Description": "Portable bluetooth speaker",
        "Email": "seller@example.com",
        "Website URL": "https://shop.example.com/spk001",
        "Phone": "08012345678"
    },
    {
        " Product Name ": "Bluetooth Speaker ",
        "SKU": "SPK-001",
        "Price": "35000",
        "Category": "electronics",
        "Description": "",
        "Email": "seller@@example.com",
        "Website URL": "shop.example.com/spk001",
        "Phone": "08012345678"
    },
    {
        " Product Name ": "Wireless Mouse",
        "SKU": "",
        "Price": "₦18,000",
        "Category": "Computer Accessories",
        "Description": "Wireless optical mouse",
        "Email": "seller@example.com",
        "Website URL": "https://shop.example.com/mouse",
        "Phone": "123"
    },
    {
        " Product Name ": "USB Keyboard",
        "SKU": "KB-001",
        "Price": "-25000",
        "Category": "Computer accessories",
        "Description": "",
        "Email": "",
        "Website URL": "",
        "Phone": ""
    },
    {
        " Product Name ": "Laptop Stand",
        "SKU": "STAND-01",
        "Price": "1",
        "Category": "Accessories",
        "Description": "Adjustable laptop stand",
        "Email": "seller@example.com",
        "Website URL": "https://shop.example.com/stand",
        "Phone": "08012345678"
    },
]


# ============================================================
# CREATE FILES
# ============================================================

save_catalog(
    "fashion_store.csv",
    fashion_products
)

save_catalog(
    "electronics_store.csv",
    electronics_products
)

save_catalog(
    "grocery_store.csv",
    grocery_products
)

save_catalog(
    "auto_parts.csv",
    auto_parts
)

save_catalog(
    "marketplace_import.csv",
    marketplace_products
)


print()
print("=" * 60)
print("REAL-WORLD CATALOG TEST LAB READY")
print("=" * 60)
print(f"Output directory: {OUTPUT_DIR}")