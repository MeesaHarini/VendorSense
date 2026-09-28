import os
import json
from dotenv import load_dotenv
from hindsight_client import Hindsight
from groq import Groq


# ============================================================
# VENDORSENSE
# AI ACCOUNTS PAYABLE AGENT
# Powered by Hindsight + Groq
# ============================================================


# ============================================================
# 1. LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not HINDSIGHT_API_KEY:
    raise ValueError(
        "HINDSIGHT_API_KEY is missing from your .env file."
    )

if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY is missing from your .env file."
    )


# ============================================================
# 2. CONFIGURATION
# ============================================================

BANK_ID = "vendorsense"

HINDSIGHT_BASE_URL = "https://api.hindsight.vectorize.io"

GROQ_MODEL = "openai/gpt-oss-120b"


# ============================================================
# 3. CREATE CLIENTS
# ============================================================

hindsight = Hindsight(
    base_url=HINDSIGHT_BASE_URL,
    api_key=HINDSIGHT_API_KEY
)

groq = Groq(
    api_key=GROQ_API_KEY
)


# ============================================================
# 4. CURRENT INVOICE
# ============================================================
#
# IMPORTANT:
#
# This invoice is intentionally using a DIFFERENT bank account
# from the one previously approved and remembered by Hindsight.
#
# Previous:
#     Bank ending: 7821
#
# Current:
#     Bank ending: 9143
#
# This should trigger HUMAN REVIEW.
# ============================================================

invoice = {
    "vendor": "Apex Industrial Supplies",
    "invoice_id": "INV-AIS-1048",
    "amount": 48620,
    "currency": "INR",
    "purchase_order": "AIS-2418",
    "payment_terms": "Net 30",
    "bank_account_last4": "9143",
    "bank_changed": True,
    "description": "Industrial pump components",
    "footer_format": "AIS standard footer"
}


# ============================================================
# 5. DISPLAY CURRENT INVOICE
# ============================================================

print("\n")
print("=" * 65)
print("                    VENDORSENSE")
print("              ACCOUNTS PAYABLE AGENT")
print("=" * 65)

print("\n📄 CURRENT INVOICE")
print("-" * 65)

print(f"Vendor              : {invoice['vendor']}")
print(f"Invoice ID          : {invoice['invoice_id']}")
print(f"Amount              : ₹{invoice['amount']:,}")
print(f"Purchase Order      : {invoice['purchase_order']}")
print(f"Payment Terms       : {invoice['payment_terms']}")
print(f"Bank Account        : XXXX{invoice['bank_account_last4']}")
print(f"Description         : {invoice['description']}")
print(f"Footer Format       : {invoice['footer_format']}")

print("-" * 65)


# ============================================================
# 6. SEARCH HINDSIGHT MEMORY
# ============================================================

print("\n🔎 Searching Hindsight memory...")

recall_query = f"""
Find relevant previous experience about this supplier and similar
accounts-payable invoices.

Current supplier:
{invoice['vendor']}

Current invoice:
{invoice['invoice_id']}

Current amount:
₹{invoice['amount']}

Current purchase order:
{invoice['purchase_order']}

Current payment terms:
{invoice['payment_terms']}

Current bank account ending:
{invoice['bank_account_last4']}

Current description:
{invoice['description']}

Current footer format:
{invoice['footer_format']}

Look for previous human-confirmed experience involving:

1. Previous invoices from this vendor.
2. Typical invoice amounts.
3. Typical payment terms.
4. Purchase order patterns.
5. Previously verified bank account information.
6. Previous human approval or rejection decisions.
7. Reasons for previous decisions.
8. Known invoice formatting patterns.
9. Previously identified exceptions.
10. Any previous bank-account changes.

Use the previous experience as evidence, not as absolute truth.
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
# 7. CONVERT HINDSIGHT RESULT TO TEXT
# ============================================================

if hasattr(recall_result, "model_dump"):

    memory_data = recall_result.model_dump()

    memory_text = json.dumps(
        memory_data,
        indent=2,
        default=str
    )

elif hasattr(recall_result, "dict"):

    memory_data = recall_result.dict()

    memory_text = json.dumps(
        memory_data,
        indent=2,
        default=str
    )

else:

    memory_text = str(recall_result)


# ============================================================
# 8. DISPLAY MEMORY
# ============================================================

print("\n🧠 HINDSIGHT MEMORY")
print("-" * 65)

print(memory_text)

print("-" * 65)


# ============================================================
# 9. GROQ AGENT INSTRUCTIONS
# ============================================================

system_prompt = """
You are VendorSense, an AI Accounts Payable decision-support agent.

Your purpose is to learn what "normal" looks like for each supplier
using previous human-confirmed experience stored in Hindsight.

You receive:

1. A current supplier invoice.
2. Relevant historical experience retrieved from Hindsight.

You must determine whether the invoice should:

AUTO_PROCESS

or

EXCEPTION

============================================================
DECISION RULES
============================================================

AUTO_PROCESS may be recommended when:

- The vendor is known.
- The invoice matches previously learned vendor patterns.
- The amount is consistent with previous invoices.
- Payment terms are consistent.
- Purchase order patterns are consistent.
- Bank information matches previously verified information.
- There are no meaningful conflicts.
- There is sufficient historical evidence.

EXCEPTION must be recommended when:

- The vendor is new.
- There is insufficient historical evidence.
- Important invoice information conflicts with previous experience.
- Bank details have changed.
- The purchase order cannot be reasonably validated.
- The invoice contains an unusual pattern requiring verification.
- The agent cannot confidently establish that the invoice is routine.

============================================================
BANK ACCOUNT SAFETY RULE
============================================================

A change in bank account information is ALWAYS an EXCEPTION.

Do NOT recommend AUTO_PROCESS when bank details have changed.

A changed bank account does NOT automatically mean fraud.

Instead, say that human verification is required.

============================================================
IMPORTANT
============================================================

Hindsight memory is evidence.

It is NOT absolute truth.

Never claim that an invoice is definitely fraudulent.

Never claim that an invoice is definitely safe.

Explain which evidence influenced your decision.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Use exactly this structure:

{
  "decision": "AUTO_PROCESS" or "EXCEPTION",
  "confidence": 0.0,
  "reason": "short explanation",
  "evidence": [
    "evidence item",
    "evidence item"
  ]
}

Confidence must be a number between 0 and 1.
"""


# ============================================================
# 10. BUILD GROQ REQUEST
# ============================================================

user_prompt = f"""
Analyze the following accounts-payable invoice.

CURRENT INVOICE:

{json.dumps(invoice, indent=2)}

HINDSIGHT EXPERIENCE:

{memory_text}

Determine whether this invoice should be automatically processed
or sent to a human exception queue.

Pay particular attention to whether the current bank account
matches previously verified vendor information.

Return ONLY valid JSON.
"""


# ============================================================
# 11. CALL GROQ
# ============================================================

print("\n🤖 VendorSense is reasoning over invoice + experience...")

try:

    completion = groq.chat.completions.create(

        model=GROQ_MODEL,

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
# 12. DISPLAY RAW AI RESPONSE
# ============================================================

print("\n📋 AI RESPONSE")
print("-" * 65)

print(ai_response)

print("-" * 65)


# ============================================================
# 13. PARSE JSON
# ============================================================

try:

    cleaned_response = (
        ai_response
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    decision = json.loads(cleaned_response)

except json.JSONDecodeError:

    print("\n❌ AI response was not valid JSON.")

    print("\nRaw response:")
    print(ai_response)

    raise


# ============================================================
# 14. HARD SAFETY CHECK
# ============================================================
#
# Even if the LLM makes a mistake, our application-level
# rule prevents automatic processing when bank details changed.
# ============================================================

if invoice["bank_changed"] is True:

    decision["decision"] = "EXCEPTION"

    decision["reason"] = (
        "Bank account details changed from previously verified "
        "vendor information. Human verification is required "
        "before processing."
    )

    evidence = decision.get("evidence", [])

    if not isinstance(evidence, list):
        evidence = []

    evidence.append(
        "Current bank account ending "
        f"{invoice['bank_account_last4']} differs from "
        "the previously verified vendor account."
    )

    decision["evidence"] = evidence


# ============================================================
# 15. NORMALIZE DECISION
# ============================================================

decision_value = str(
    decision.get("decision", "")
).upper().strip()

if decision_value not in [
    "AUTO_PROCESS",
    "EXCEPTION"
]:

    decision_value = "EXCEPTION"

    decision["decision"] = "EXCEPTION"

    decision["reason"] = (
        "The agent returned an invalid decision format. "
        "Human review is required."
    )


# ============================================================
# 16. DISPLAY FINAL RESULT
# ============================================================

print("\n")
print("=" * 65)
print("                 VENDORSENSE DECISION")
print("=" * 65)

print(f"\nVendor          : {invoice['vendor']}")
print(f"Invoice         : {invoice['invoice_id']}")
print(f"Amount          : ₹{invoice['amount']:,}")
print(f"Purchase Order  : {invoice['purchase_order']}")
print(
    f"Bank Account    : XXXX{invoice['bank_account_last4']}"
)

print("\nDecision        :", decision["decision"])

print(
    "Confidence      :",
    decision.get("confidence", "N/A")
)

print("\nReason:")
print(decision.get("reason", "No reason provided."))

print("\nEvidence:")

for item in decision.get("evidence", []):

    print(f"  • {item}")


print("\n" + "=" * 65)


# ============================================================
# 17. ACTION
# ============================================================

if decision["decision"] == "AUTO_PROCESS":

    print("🟢 ROUTINE INVOICE → AUTO-PROCESS")

    print(
        "\nVendorSense found sufficient evidence that "
        "this invoice matches learned vendor behavior."
    )

else:

    print("🟠 EXCEPTION → HUMAN REVIEW REQUIRED")

    print(
        "\nVendorSense detected an issue requiring "
        "human verification."
    )


print("=" * 65)


# ============================================================
# 18. DEMO EXPLANATION
# ============================================================

print("\n💡 LEARNING LOOP")

print("""
Invoice
   ↓
Hindsight Recall
   ↓
Previous Vendor Experience
   ↓
Groq Agent Reasoning
   ↓
Decision
   ├── 🟢 Routine → Auto-process
   │
   └── 🟠 Exception → Human Review
""")

print("=" * 65)
print("VendorSense completed the invoice analysis.")
print("=" * 65)