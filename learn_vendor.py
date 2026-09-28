import os
from dotenv import load_dotenv
from hindsight_client import Hindsight

# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY")

if not HINDSIGHT_API_KEY:
    raise ValueError("HINDSIGHT_API_KEY is missing from .env")


# ============================================================
# HINDSIGHT
# ============================================================

hindsight = Hindsight(
    base_url="https://api.hindsight.vectorize.io",
    api_key=HINDSIGHT_API_KEY
)

BANK_ID = "vendorsense"


# ============================================================
# HUMAN-VERIFIED EXPERIENCE
# ============================================================

experience = """
Vendor: Apex Industrial Supplies

Invoice reviewed:
Invoice ID: INV-AIS-1047
Amount: ₹48,620
Purchase Order: AIS-2417
Payment Terms: Net 30
Bank Account Ending: 7821
Description: Industrial pump components
Footer Format: AIS standard footer

Human decision: APPROVED

Human verification:
- Invoice was verified against the purchase order.
- Amount was considered valid for this vendor.
- Net 30 payment terms are acceptable.
- Bank account ending 7821 was verified.
- AIS standard footer formatting was confirmed as legitimate.

Vendor pattern learned:
Apex Industrial Supplies commonly sends invoices for industrial
pump components in the approximate ₹40,000–₹60,000 range.
Their invoices commonly use AIS purchase order formatting,
Net 30 payment terms, and the AIS standard footer.

Important:
This memory represents a previous human-confirmed decision.
It should be used as evidence for future invoices, not treated
as absolute truth.
"""


# ============================================================
# RETAIN EXPERIENCE
# ============================================================

print("\n🧠 Teaching VendorSense...")

try:
    result = hindsight.retain(
        bank_id=BANK_ID,
        content=experience
    )

    print("\n✅ EXPERIENCE STORED IN HINDSIGHT")
    print("-" * 60)
    print(result)
    print("-" * 60)

except Exception as e:
    print("\n❌ Failed to store experience.")
    print(f"Error: {e}")
    raise


print("\n🎓 VendorSense has learned from a human-approved invoice.")
print("Now run vendor_agent.py again.")