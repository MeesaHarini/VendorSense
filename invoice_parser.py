import re
import json
from pypdf import PdfReader


def extract_pdf_text(pdf_path):
    """
    Extract all text from an invoice PDF.
    """
    reader = PdfReader(pdf_path)

    pages = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        pages.append(page_text)

    return "\n".join(pages)


def clean_text(value):
    """
    Clean extracted PDF text.
    """
    if value is None:
        return None

    value = value.replace("\xa0", " ")
    value = value.replace("\u2013", "-")
    value = value.replace("\u2014", "-")

    # Collapse repeated spaces but preserve newlines
    value = re.sub(r"[ \t]+", " ", value)

    return value.strip()


def parse_invoice(text):
    """
    Convert raw PDF text into a structured invoice dictionary.

    This parser intentionally does NOT make any business decision.
    Hindsight + the agent are responsible for deciding:
        EXCEPTION
        or
        AUTO-PROCESS
    """

    if not text:
        return {
            "vendor": None,
            "invoice_id": None,
            "invoice_date": None,
            "amount": None,
            "currency": "INR",
            "purchase_order": None,
            "payment_terms": None,
            "bank_account_last4": None,
            "description": None,
            "source": "PDF upload"
        }

    # ---------------------------------------------------------
    # Normalize extracted PDF text
    # ---------------------------------------------------------

    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    lines = []

    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            lines.append(line)

    normalized_text = "\n".join(lines)

    # ---------------------------------------------------------
    # VENDOR
    # ---------------------------------------------------------

    vendor = None

    # Expected structure:
    #
    # Supplier
    # Nova Office Systems
    #
    # or:
    #
    # Vendor
    # ABC Company
    #

    for i, line in enumerate(lines):

        if re.fullmatch(
            r"(Supplier|Vendor|Seller)",
            line,
            re.IGNORECASE
        ):

            if i + 1 < len(lines):

                candidate = lines[i + 1].strip()

                # Don't accidentally capture another label
                if not re.match(
                    r"^(GSTIN|Invoice|Invoice Date|PO|Payment|Currency|Bill To)$",
                    candidate,
                    re.IGNORECASE
                ):
                    vendor = candidate
                    break

    # Fallback:
    # Search for "Supplier: Company Name"
    if not vendor:

        match = re.search(
            r"(?:Supplier|Vendor|Seller)\s*[:\-]\s*([^\n]+)",
            normalized_text,
            re.IGNORECASE
        )

        if match:
            vendor = match.group(1).strip()

    # Remove accidental trailing labels
    if vendor:

        vendor = re.sub(
            r"\s+(GSTIN|Invoice|Invoice Date|PO|Payment Terms|Currency).*$",
            "",
            vendor,
            flags=re.IGNORECASE
        )

        vendor = clean_text(vendor)

    # ---------------------------------------------------------
    # INVOICE NUMBER
    # ---------------------------------------------------------

    invoice_id = None

    invoice_patterns = [
        r"Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
        r"Invoice\s*[:\-]\s*([A-Za-z0-9\-\/]+)"
    ]

    for pattern in invoice_patterns:

        match = re.search(
            pattern,
            normalized_text,
            re.IGNORECASE
        )

        if match:
            invoice_id = match.group(1).strip()
            break

    # ---------------------------------------------------------
    # INVOICE DATE
    # ---------------------------------------------------------

    invoice_date = None

    date_patterns = [
        r"Invoice\s*Date\s*[:\-]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"Invoice\s*Date\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4})",
        r"Date\s*[:\-]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"Date\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4})"
    ]

    for pattern in date_patterns:

        match = re.search(
            pattern,
            normalized_text,
            re.IGNORECASE
        )

        if match:
            invoice_date = match.group(1).strip()
            break

    # ---------------------------------------------------------
    # PURCHASE ORDER
    # ---------------------------------------------------------

    purchase_order = None

    po_patterns = [
        r"PO\s*(?:Number|No\.?|#)\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
        r"Purchase\s*Order\s*(?:Number|No\.?|#)?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)"
    ]

    for pattern in po_patterns:

        match = re.search(
            pattern,
            normalized_text,
            re.IGNORECASE
        )

        if match:
            purchase_order = match.group(1).strip()
            break

    # ---------------------------------------------------------
    # PAYMENT TERMS
    # ---------------------------------------------------------

    payment_terms = None

    match = re.search(
        r"Payment\s*Terms\s*[:\-]?\s*([^\n]+)",
        normalized_text,
        re.IGNORECASE
    )

    if match:
        payment_terms = match.group(1).strip()

    # ---------------------------------------------------------
    # CURRENCY
    # ---------------------------------------------------------

    currency = "INR"

    match = re.search(
        r"Currency\s*[:\-]?\s*([A-Za-z]{3})",
        normalized_text,
        re.IGNORECASE
    )

    if match:
        currency = match.group(1).upper()

    # ---------------------------------------------------------
    # BANK ACCOUNT LAST 4
    # ---------------------------------------------------------

    bank_account_last4 = None

    bank_patterns = [
        r"Account\s*[:\-]?\s*[Xx\*]*([0-9]{4})",
        r"Bank\s*Account\s*[:\-]?\s*[Xx\*]*([0-9]{4})",
        r"A\/C\s*(?:No\.?|Number)?\s*[:\-]?\s*[Xx\*]*([0-9]{4})"
    ]

    for pattern in bank_patterns:

        match = re.search(
            pattern,
            normalized_text,
            re.IGNORECASE
        )

        if match:
            bank_account_last4 = match.group(1)
            break

    # ---------------------------------------------------------
    # TOTAL AMOUNT
    # ---------------------------------------------------------

    amount = None

    # We prioritize Total Due because this is the amount
    # the AP agent should evaluate.

    amount_patterns = [

        # Total Due ₹255,470
        r"Total\s*Due\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d{1,2})?)",

        # Total Due
        # ₹255,470
        r"Total\s*Due\s*\n\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d{1,2})?)",

        # Total ₹255,470
        r"\bTotal\b\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d{1,2})?)",

        # Total
        # ₹255,470
        r"\bTotal\b\s*\n\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d{1,2})?)"
    ]

    for pattern in amount_patterns:

        match = re.search(
            pattern,
            normalized_text,
            re.IGNORECASE
        )

        if match:

            try:
                amount = float(
                    match.group(1).replace(",", "")
                )

                break

            except ValueError:
                pass

    # ---------------------------------------------------------
    # DESCRIPTION
    # ---------------------------------------------------------

    description = None

    # Try to identify invoice table rows.
    #
    # Example:
    #
    # 1 Ergonomic Executive Workstations 6 28,500 171,000

    description_pattern = re.compile(
        r"^\s*\d+\s+(.+?)\s+\d+\s+[\d,]+(?:\.\d{1,2})?\s+[\d,]+(?:\.\d{1,2})?\s*$"
    )

    for line in lines:

        match = description_pattern.match(line)

        if match:

            description = match.group(1).strip()
            break

    # ---------------------------------------------------------
    # FALLBACK DESCRIPTION
    # ---------------------------------------------------------

    if not description:

        # Look for the first line after "Description"
        for i, line in enumerate(lines):

            if re.fullmatch(
                r"Description",
                line,
                re.IGNORECASE
            ):

                if i + 1 < len(lines):

                    candidate = lines[i + 1].strip()

                    if candidate:
                        description = candidate

                break

    # ---------------------------------------------------------
    # FINAL CLEANUP
    # ---------------------------------------------------------

    vendor = clean_text(vendor)
    invoice_id = clean_text(invoice_id)
    invoice_date = clean_text(invoice_date)
    purchase_order = clean_text(purchase_order)
    payment_terms = clean_text(payment_terms)
    description = clean_text(description)

    # ---------------------------------------------------------
    # STRUCTURED INVOICE
    # ---------------------------------------------------------

    invoice = {
        "vendor": vendor,
        "invoice_id": invoice_id,
        "invoice_date": invoice_date,
        "amount": amount,
        "currency": currency,
        "purchase_order": purchase_order,
        "payment_terms": payment_terms,
        "bank_account_last4": bank_account_last4,
        "description": description,
        "source": "PDF upload"
    }

    return invoice


# =============================================================
# COMMAND LINE TEST
# =============================================================

if __name__ == "__main__":

    import os

    pdf_path = "sample_invoice_completely_different.pdf"

    print("\n========================================")
    print("       VENDORSENSE INVOICE PARSER")
    print("========================================\n")

    # Check file exists
    if not os.path.exists(pdf_path):

        print("ERROR: PDF file not found.")
        print()
        print("Expected file:")
        print(os.path.abspath(pdf_path))
        print()
        print("Put the PDF in your vendorsense project folder.")
        print()

        raise SystemExit(1)

    # Extract PDF text
    text = extract_pdf_text(pdf_path)

    print("========== EXTRACTED PDF TEXT ==========\n")
    print(text)

    # Parse invoice
    invoice = parse_invoice(text)

    print("\n========== PARSED INVOICE ==========\n")

    print(
        json.dumps(
            invoice,
            indent=2,
            ensure_ascii=False
        )
    )

    # Save parsed invoice
    with open(
        "parsed_invoice.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            invoice,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("\n========================================")
    print("Saved: parsed_invoice.json")
    print("========================================\n")