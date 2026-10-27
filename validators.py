import re


def is_missing(value):
    """
    Determine whether a value is genuinely missing or empty.
    """

    if value is None:
        return True

    text = str(value).strip()

    return text == "" or text.lower() in {
        "nan",
        "none",
        "null"
    }


def is_valid_email(value):
    """
    Perform a practical email-format validation.

    This checks structure only. It does not verify
    whether the mailbox actually exists.
    """

    if is_missing(value):
        return False

    email = str(value).strip()

    pattern = (
        r"^[A-Za-z0-9._%+-]+"
        r"@[A-Za-z0-9.-]+\."
        r"[A-Za-z]{2,}$"
    )

    return re.match(
        pattern,
        email
    ) is not None


def is_valid_url(value):
    """
    Validate basic HTTP/HTTPS URL structure.
    """

    if is_missing(value):
        return False

    url = str(value).strip()

    pattern = (
        r"^https?://"
        r"[A-Za-z0-9.-]+"
        r"(?::\d+)?"
        r"(?:/.*)?$"
    )

    return re.match(
        pattern,
        url,
        flags=re.IGNORECASE
    ) is not None


def is_valid_phone(value):
    """
    Perform practical phone-number validation.

    Allows common international and local formats.
    """

    if is_missing(value):
        return False

    phone = str(value).strip()

    digits = re.sub(
        r"\D",
        "",
        phone
    )

    # Reject values containing alphabetic characters.
    if re.search(
        r"[A-Za-z]",
        phone
    ):
        return False

    # Basic length protection.
    if len(digits) < 7:
        return False

    if len(digits) > 15:
        return False

    return True


def is_valid_sku_format(value):
    """
    Validate basic SKU formatting.

    This does not enforce one universal SKU convention,
    because different businesses use different formats.
    """

    if is_missing(value):
        return False

    sku = str(value).strip()

    # A SKU should contain at least one useful character.
    if len(sku) < 2:
        return False

    # Reject values containing obvious whitespace internally.
    if re.search(
        r"\s",
        sku
    ):
        return False

    return True


def is_suspicious_price(value):
    """
    Identify prices that may deserve human review.

    Suspicious does not mean invalid.
    """

    if is_missing(value):
        return False

    text = (
        str(value)
        .replace(",", "")
        .replace("₦", "")
        .replace("$", "")
        .replace("£", "")
        .strip()
    )

    try:

        price = float(text)

    except (ValueError, TypeError):

        return False

    # These values may be legitimate, but deserve review.
    if price == 1:
        return True

    if price >= 100_000_000:
        return True

    return False