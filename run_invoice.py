import json
import os

from dotenv import load_dotenv
from hindsight_client import Hindsight
from groq import Groq


# ============================================================
# VENDORSENSE — PDF TO AI AGENT
# ============================================================

load_dotenv()

HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not HINDSIGHT_API_KEY:
    raise ValueError("HINDSIGHT_API_KEY is missing from .env")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing from .env")


# ============================================================
# CONFIGURATION
# ============================================================

BANK_ID = "vendorsense"

hindsight = Hindsight(
    base_url="https://api.hindsight.vectorize.io",
    api_key=HINDSIGHT_API_KEY
)

groq = Groq(
    api_key=GROQ_API_KEY
)


# ============================================================
# 1. LOAD PARSED INVOICE
# ============================================================

print("\n" + "=" * 65)
print("             VENDORSENSE INVOICE AGENT")
print("=" * 65)

print("\n📦 Loading parsed invoice...")

try:

    with open(
        "parsed_invoice.json",
        "r",
        encoding="utf-8"
    ) as file:

        invoice = json.load(file)

except FileNotFoundError:

    print("\n❌ parsed_invoice.json not found.")

    print(
        "\nRun this first:"
    )

    print(
        "python invoice_parser.py"
    )

    raise SystemExit


print("✅ Invoice data loaded.")


# ============================================================
# 2. DISPLAY INVOICE
# ============================================================

print("\n📄 INVOICE")

print("-" * 65)

print(f"Vendor          : {invoice.get('vendor')}")
print(f"Invoice ID      : {invoice.get('invoice_id')}")
print(f"Amount          : ₹{invoice.get('amount'):,}")
print(f"Purchase Order  : {invoice.get('purchase_order')}")
print(f"Payment Terms   : {invoice.get('payment_terms')}")
print(
    f"Bank Account    : XXXX{invoice.get('bank_account_last4')}"
)
print(f"Description     : {invoice.get('description')}")

print("-" * 65)


# ============================================================
# 3. SEARCH HINDSIGHT
# ============================================================

print("\n🔎 Searching Hindsight memory...")

recall_query = f"""
Find previous human-confirmed experience about this vendor.

Vendor:
{invoice.get('vendor')}

Current invoice:
{invoice.get('invoice_id')}

Amount:
₹{invoice.get('amount')}

Purchase order:
{invoice.get('purchase_order')}

Payment terms:
{invoice.get('payment_terms')}

Bank account ending:
{invoice.get('bank_account_last4')}

Description:
{invoice.get('description')}

Look for:

- previous invoices from this vendor
- typical invoice amounts
- payment terms
- purchase order patterns
- previously verified bank information
- previous human approval or rejection
- reasons for previous decisions
- previously identified exceptions

Use the memories as evidence, not absolute truth.
"""

try:

    recall_result = hindsight.recall(
        bank_id=BANK_ID,
        query=recall_query,
        max_tokens=2000,
        budget="mid"
    )

    print("✅ Hindsight memory retrieved.")

except Exception as e:

    print("\n❌ Hindsight recall failed.")
    print(f"Error: {e}")

    raise


# ============================================================
# 4. CONVERT MEMORY TO TEXT
# ============================================================

if hasattr(recall_result, "model_dump"):

    memory_text = json.dumps(
        recall_result.model_dump(),
        indent=2,
        default=str
    )

elif hasattr(recall_result, "dict"):

    memory_text = json.dumps(
        recall_result.dict(),
        indent=2,
        default=str
    )

else:

    memory_text = str(recall_result)


# ============================================================
# 5. DISPLAY MEMORY
# ============================================================

print("\n🧠 HINDSIGHT EXPERIENCE")

print("-" * 65)

print(memory_text)

print("-" * 65)


# ============================================================
# 6. AI AGENT
# ============================================================

system_prompt = """
You are VendorSense, an AI Accounts Payable agent.

Your job is to analyze supplier invoices using previous
human-confirmed vendor experience retrieved from Hindsight.

The objective is to determine whether an invoice is routine
enough to be automatically processed or whether it requires
human review.

DECISION OPTIONS:

AUTO_PROCESS
EXCEPTION

AUTO_PROCESS can be used when:

- The vendor is known.
- Previous experience exists.
- The invoice matches learned vendor patterns.
- Amount is consistent.
- Payment terms are consistent.
- Purchase order pattern is consistent.
- Bank information matches previously verified information.
- No meaningful deviation is present.

EXCEPTION must be used when:

- There is insufficient experience.
- The vendor is new.
- Important information conflicts with previous experience.
- Bank details changed.
- The invoice has a meaningful unusual pattern.

IMPORTANT:

A changed bank account is ALWAYS an EXCEPTION.

A changed bank account does NOT automatically mean fraud.

It means human verification is required.

Hindsight memories are evidence, not absolute truth.

Never claim an invoice is definitely fraudulent.

Return ONLY valid JSON.

Format:

{
  "decision": "AUTO_PROCESS" or "EXCEPTION",
  "confidence": 0.0,
  "reason": "short explanation",
  "evidence": [
    "evidence item",
    "evidence item"
  ]
}
"""


user_prompt = f"""
CURRENT INVOICE:

{json.dumps(invoice, indent=2)}

HINDSIGHT EXPERIENCE:

{memory_text}

Analyze the invoice.

Return only valid JSON.
"""


# ============================================================
# 7. GROQ REASONING
# ============================================================

print("\n🤖 VendorSense is analyzing the invoice...")

try:

    completion = groq.chat.completions.create(

        model="openai/gpt-oss-120b",

        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],

        temperature=0.1,

        max_tokens=500
    )

    ai_response = (
        completion
        .choices[0]
        .message
        .content
        .strip()
    )

except Exception as e:

    print("\n❌ Groq request failed.")
    print(f"Error: {e}")

    raise


# ============================================================
# 8. PARSE AI RESPONSE
# ============================================================

cleaned_response = (
    ai_response
    .replace("```json", "")
    .replace("```", "")
    .strip()
)

try:

    decision = json.loads(cleaned_response)

except json.JSONDecodeError:

    print("\n❌ AI returned invalid JSON.")

    print("\nRaw response:")
    print(ai_response)

    raise


# ============================================================
# 9. APPLICATION SAFETY CHECK
# ============================================================

# Our MVP deliberately treats a changed bank account
# as requiring human verification.

# For the current synthetic invoice, the bank account
# is the previously verified account XXXX7821.

known_bank = "7821"

if invoice.get("bank_account_last4") != known_bank:

    decision["decision"] = "EXCEPTION"

    decision["reason"] = (
        "Bank account details differ from the previously "
        "verified vendor account. Human verification is required."
    )

    evidence = decision.get("evidence", [])

    if not isinstance(evidence, list):
        evidence = []

    evidence.append(
        "Current bank account differs from previously "
        "verified vendor information."
    )

    decision["evidence"] = evidence


# ============================================================
# 10. FINAL RESULT
# ============================================================

print("\n")
print("=" * 65)
print("                 VENDORSENSE DECISION")
print("=" * 65)

print(
    f"\nVendor          : {invoice.get('vendor')}"
)

print(
    f"Invoice         : {invoice.get('invoice_id')}"
)

print(
    f"Amount          : ₹{invoice.get('amount'):,}"
)

print(
    f"Purchase Order  : {invoice.get('purchase_order')}"
)

print(
    f"Bank Account    : XXXX{invoice.get('bank_account_last4')}"
)

print(
    f"\nDecision        : {decision.get('decision')}"
)

print(
    f"Confidence      : {decision.get('confidence')}"
)

print("\nReason:")

print(
    decision.get(
        "reason",
        "No reason provided."
    )
)

print("\nEvidence:")

for item in decision.get("evidence", []):

    print(f"  • {item}")


print("\n" + "=" * 65)


if decision.get("decision") == "AUTO_PROCESS":

    print("🟢 AUTO-PROCESS")

    print(
        "\nThis invoice matches the learned vendor pattern."
    )

else:

    print("🟠 EXCEPTION")

    print(
        "\nHuman review is required."
    )


print("=" * 65)
print("\n✅ PDF → AGENT → HINDSIGHT → GROQ → DECISION COMPLETE")
print("=" * 65)