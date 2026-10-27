import csv
import random
from pathlib import Path


OUTPUT_FILE = Path(__file__).parent / "messy_catalog.csv"


products = [
    ("SKU-001", "Samsung Galaxy S24", 850000, "Phones"),
    ("SKU-002", "iPhone 15", 1200000, "Phones"),
    ("SKU-003", "Tecno Camon 30", 420000, "Phones"),
    ("SKU-004", "Infinix Note 40", 380000, "Phones"),
    ("SKU-005", "Redmi Note 13", 310000, "Phones"),
    ("SKU-006", "HP EliteBook 840", 950000, "Laptops"),
    ("SKU-007", "Dell Latitude 5420", 780000, "Laptops"),
    ("SKU-008", "MacBook Air M2", 1450000, "Laptops"),
    ("SKU-009", "Lenovo ThinkPad T14", 880000, "Laptops"),
    ("SKU-010", "ASUS VivoBook 15", 690000, "Laptops"),
    ("SKU-011", "Sony WH-1000XM5", 620000, "Audio"),
    ("SKU-012", "AirPods Pro 2", 430000, "Audio"),
    ("SKU-013", "JBL Flip 6", 210000, "Audio"),
    ("SKU-014", "Oraimo FreePods 4", 75000, "Audio"),
    ("SKU-015", "Anker Soundcore Q20", 145000, "Audio"),
    ("SKU-016", "Samsung 55 Inch Smart TV", 890000, "Televisions"),
    ("SKU-017", "LG 55 Inch OLED TV", 1350000, "Televisions"),
    ("SKU-018", "Hisense 50 Inch TV", 620000, "Televisions"),
    ("SKU-019", "TCL 55 Inch Smart TV", 710000, "Televisions"),
    ("SKU-020", "Bruhm 43 Inch TV", 410000, "Televisions"),
    ("SKU-021", "Nike Air Max 270", 180000, "Fashion"),
    ("SKU-022", "Adidas Ultraboost", 220000, "Fashion"),
    ("SKU-023", "Puma RS-X", 165000, "Fashion"),
    ("SKU-024", "New Balance 574", 190000, "Fashion"),
    ("SKU-025", "Nike Air Force 1", 175000, "Fashion"),
]


categories = [
    "Phones",
    "phones",
    "PHONES",
    " Phone ",
    "Laptops",
    "laptops",
    "LAPTOPS",
    "Audio",
    "audio",
    "AUDIO",
    "Televisions",
    "televisions",
    "TV",
    "Fashion",
    "fashion",
    "FASHION",
]


def create_row(index):
    sku, name, price, category = random.choice(products)

    # Introduce deliberate data-quality problems
    problem = random.randint(1, 10)

    if problem == 1:
        sku = sku + " "

    elif problem == 2:
        sku = ""

    elif problem == 3:
        name = "  " + name + "  "

    elif problem == 4:
        price = ""

    elif problem == 5:
        price = "₦" + f"{price:,}"

    elif problem == 6:
        price = -price

    elif problem == 7:
        category = random.choice(categories)

    elif problem == 8:
        category = " " + category + " "

    elif problem == 9:
        name = name.upper()

    elif problem == 10:
        # Leave row mostly valid
        pass

    return [
        sku,
        name,
        price,
        category,
    ]


def main():

    random.seed(42)

    rows = []

    # Generate 200 records
    for i in range(200):
        rows.append(create_row(i))

    # Deliberately add duplicate products/SKUs
    rows.append([
        "SKU-001",
        "Samsung Galaxy S24",
        850000,
        "Phones",
    ])

    rows.append([
        "SKU-002",
        "iPhone 15",
        1200000,
        "Phones",
    ])

    rows.append([
        "SKU-006",
        "HP EliteBook 840",
        950000,
        "Laptops",
    ])

    # Deliberately add completely duplicated rows
    rows.append(rows[10])
    rows.append(rows[25])
    rows.append(rows[50])

    # Write CSV
    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "SKU",
            "Product Name",
            "Price",
            "Category",
        ])

        writer.writerows(rows)

    print()
    print("====================================")
    print(" Catalog Rescue Test Data Generated")
    print("====================================")
    print()
    print(f"File: {OUTPUT_FILE}")
    print(f"Records: {len(rows)}")
    print()
    print("Open the CSV and inspect it if you want.")
    print()


if __name__ == "__main__":
    main()