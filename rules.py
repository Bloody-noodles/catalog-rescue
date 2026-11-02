"""
Catalog Rescue Rule Registry

Central definition of the quality rules used by the engine.

The registry describes WHAT each rule means.
The actual detection logic remains in quality_checks.py.

This separation lets Catalog Rescue grow without turning
the quality engine into an unmanageable collection of hard-coded
business decisions.
"""


# ============================================================
# RULE REGISTRY
# ============================================================

RULES = [

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    {
        "id": "missing_columns",
        "name": "Missing Required Columns",
        "category": "Structure",
        "severity": "Critical",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Required catalog fields are missing from the dataset."
        ),
        "business_impact": (
            "The catalog may be incompatible with downstream systems."
        ),
    },

    # --------------------------------------------------------
    # COMPLETENESS
    # --------------------------------------------------------

    {
        "id": "missing_values",
        "name": "Missing Values",
        "category": "Completeness",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "One or more catalog fields contain missing values."
        ),
        "business_impact": (
            "Incomplete product information may affect publishing "
            "and customer experience."
        ),
    },

    {
        "id": "missing_descriptions",
        "name": "Missing Product Descriptions",
        "category": "Completeness",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Products are missing descriptions."
        ),
        "business_impact": (
            "Products may lack useful information for customers "
            "or marketplace listings."
        ),
    },

    # --------------------------------------------------------
    # UNIQUENESS
    # --------------------------------------------------------

    {
        "id": "duplicate_skus",
        "name": "Duplicate SKUs",
        "category": "Uniqueness",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Multiple records share the same SKU."
        ),
        "business_impact": (
            "Products may be duplicated or incorrectly matched "
            "during synchronization."
        ),
    },

    {
        "id": "duplicate_rows",
        "name": "Duplicate Rows",
        "category": "Uniqueness",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Identical records appear more than once."
        ),
        "business_impact": (
            "Repeated records can create catalog clutter "
            "and reporting errors."
        ),
    },

    {
        "id": "blank_skus",
        "name": "Blank SKUs",
        "category": "Uniqueness",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Products do not have a usable SKU."
        ),
        "business_impact": (
            "Products may be difficult to identify or synchronize."
        ),
    },

    # --------------------------------------------------------
    # VALIDITY
    # --------------------------------------------------------

    {
        "id": "invalid_prices",
        "name": "Invalid Prices",
        "category": "Validity",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Prices are missing, non-numeric, or non-positive."
        ),
        "business_impact": (
            "Products may display incorrect or unusable pricing."
        ),
    },

    {
        "id": "suspicious_prices",
        "name": "Suspicious Prices",
        "category": "Validity",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Prices appear unusually low or unusually high."
        ),
        "business_impact": (
            "Unusual prices may require business verification "
            "before publication."
        ),
    },

    {
        "id": "invalid_sku_formats",
        "name": "Invalid SKU Formats",
        "category": "Validity",
        "severity": "Medium",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "SKU values do not follow the expected format."
        ),
        "business_impact": (
            "Inconsistent identifiers may cause matching "
            "or synchronization problems."
        ),
    },

    {
        "id": "invalid_emails",
        "name": "Invalid Email Addresses",
        "category": "Validity",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Email addresses fail basic structural validation."
        ),
        "business_impact": (
            "Customer or operational communications may fail."
        ),
    },

    {
        "id": "invalid_urls",
        "name": "Invalid Website URLs",
        "category": "Validity",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Website URLs fail basic URL validation."
        ),
        "business_impact": (
            "Product or business links may fail when published."
        ),
    },

    {
        "id": "invalid_phones",
        "name": "Invalid Phone Numbers",
        "category": "Validity",
        "severity": "High",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Phone numbers contain invalid characters or lengths."
        ),
        "business_impact": (
            "Customers or staff may be unable to contact the business."
        ),
    },

    # --------------------------------------------------------
    # CONSISTENCY
    # --------------------------------------------------------

    {
        "id": "category_variations",
        "name": "Category Inconsistencies",
        "category": "Consistency",
        "severity": "Medium",
        "auto_fix": True,
        "requires_review": False,
        "description": (
            "The same category appears in inconsistent formatting."
        ),
        "business_impact": (
            "Inconsistent categories can affect filtering and reporting."
        ),
    },

    {
        "id": "empty_columns",
        "name": "Empty Columns",
        "category": "Structure",
        "severity": "Low",
        "auto_fix": False,
        "requires_review": True,
        "description": (
            "Columns contain no usable values."
        ),
        "business_impact": (
            "Unused columns can create unnecessary catalog structure "
            "and processing noise."
        ),
    },

    # --------------------------------------------------------
    # DATA NORMALIZATION
    # --------------------------------------------------------

    {
        "id": "whitespace_normalization",
        "name": "Whitespace Normalization",
        "category": "Formatting",
        "severity": "Low",
        "auto_fix": True,
        "requires_review": False,
        "description": (
            "Leading and trailing whitespace is removed "
            "from catalog values."
        ),
        "business_impact": (
            "Reduces formatting inconsistencies and improves matching."
        ),
    },

    {
        "id": "column_name_normalization",
        "name": "Column Name Normalization",
        "category": "Formatting",
        "severity": "Low",
        "auto_fix": True,
        "requires_review": False,
        "description": (
            "Column names are normalized into a consistent format."
        ),
        "business_impact": (
            "Improves compatibility with catalog processing systems."
        ),
    },

    {
        "id": "currency_normalization",
        "name": "Currency Formatting Normalization",
        "category": "Formatting",
        "severity": "Low",
        "auto_fix": True,
        "requires_review": False,
        "description": (
            "Safe currency formatting inconsistencies are normalized."
        ),
        "business_impact": (
            "Improves consistency without changing the underlying price."
        ),
    },
]


# ============================================================
# LOOKUP HELPERS
# ============================================================

RULE_MAP = {
    rule["id"]: rule
    for rule in RULES
}


def get_rule(rule_id):
    """
    Return a single rule definition by ID.
    """
    return RULE_MAP.get(rule_id)


def get_all_rules():
    """
    Return all registered rules.
    """
    return RULES.copy()


def get_rules_by_category(category):
    """
    Return rules belonging to a quality category.
    """
    return [
        rule
        for rule in RULES
        if rule["category"].lower() == category.lower()
    ]


def get_rules_by_severity(severity):
    """
    Return rules matching a severity level.
    """
    return [
        rule
        for rule in RULES
        if rule["severity"].lower() == severity.lower()
    ]


def get_auto_fix_rules():
    """
    Return rules that are approved for automatic cleanup.
    """
    return [
        rule
        for rule in RULES
        if rule["auto_fix"]
    ]


def get_review_rules():
    """
    Return rules that require human review.
    """
    return [
        rule
        for rule in RULES
        if rule["requires_review"]
    ]


def get_rule_summary():
    """
    Return high-level registry statistics.
    """

    return {
        "total_rules": len(RULES),
        "automatic_rules": len(get_auto_fix_rules()),
        "review_rules": len(get_review_rules()),
        "critical_rules": len(
            get_rules_by_severity("Critical")
        ),
        "high_rules": len(
            get_rules_by_severity("High")
        ),
        "medium_rules": len(
            get_rules_by_severity("Medium")
        ),
        "low_rules": len(
            get_rules_by_severity("Low")
        ),
    }