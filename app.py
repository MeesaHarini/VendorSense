import os
import re
import json
import hashlib
import base64
import secrets
import shutil
from pathlib import Path
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader
from groq import Groq
from hindsight_client import Hindsight


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LEGACY_BANK_ID = "vendorsense"
BANK_ID = None
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_VISION_MODEL = "qwen/qwen3.8-27b"


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="VendorSense",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CHECK API KEYS
# ============================================================

if not HINDSIGHT_API_KEY:
    st.error("HINDSIGHT_API_KEY is missing from your .env file.")
    st.stop()

if not GROQ_API_KEY:
    st.error("GROQ_API_KEY is missing from your .env file.")
    st.stop()



# ============================================================
# API CLIENTS
# ============================================================

groq_client = Groq(
    api_key=GROQ_API_KEY
)

hindsight = Hindsight(
    base_url="https://api.hindsight.vectorize.io",
    api_key=HINDSIGHT_API_KEY,
)


# ============================================================
# MULTI-USER AUTHENTICATION
# ============================================================

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

USERS_PATH = os.path.join(
    APP_ROOT,
    "vendorsense_users.json",
)

USERS_ROOT = os.path.join(
    APP_ROOT,
    "users",
)

os.makedirs(USERS_ROOT, exist_ok=True)


def load_users():
    if not os.path.exists(USERS_PATH):
        return {}

    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_users(users):
    temp_path = USERS_PATH + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    os.replace(temp_path, USERS_PATH)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    ).hex()


def make_password_record(password):
    salt = secrets.token_hex(16)
    return {
        "salt": salt,
        "password_hash": password_hash(password, salt),
    }


def verify_password(password, record):
    try:
        candidate = password_hash(
            password,
            record["salt"],
        )
        return secrets.compare_digest(
            candidate,
            record["password_hash"],
        )
    except Exception:
        return False


def normalize_recovery_answer(answer):
    return " ".join(
        str(answer or "").strip().casefold().split()
    )


def make_recovery_record(answer):
    salt = secrets.token_hex(16)
    normalized = normalize_recovery_answer(answer)

    return {
        "recovery_salt": salt,
        "recovery_hash": password_hash(
            normalized,
            salt,
        ),
    }


def verify_recovery_answer(answer, record):
    try:
        if not record.get("recovery_salt") or not record.get("recovery_hash"):
            return False

        normalized = normalize_recovery_answer(answer)

        candidate = password_hash(
            normalized,
            record["recovery_salt"],
        )

        return secrets.compare_digest(
            candidate,
            record["recovery_hash"],
        )
    except Exception:
        return False


def validate_username(username):
    username = username.strip()

    if not 3 <= len(username) <= 32:
        return False, "Username must be 3–32 characters."

    if not re.fullmatch(r"[A-Za-z0-9._-]+", username):
        return False, "Use only letters, numbers, dot, underscore, or hyphen."

    return True, None


def validate_password(password):
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    return True, None


def user_slug(username):
    # Deterministic and filesystem-safe.
    return hashlib.sha256(
        username.strip().lower().encode("utf-8")
    ).hexdigest()[:16]


def user_workspace(username):
    slug = user_slug(username)

    user_root = os.path.join(
        USERS_ROOT,
        slug,
    )

    database_path = os.path.join(
        user_root,
        "vendorsense_database.json",
    )

    archive_dir = os.path.join(
        user_root,
        "invoice_archive",
    )

    os.makedirs(archive_dir, exist_ok=True)

    return user_root, database_path, archive_dir


def user_bank_id(username):
    return f"vendorsense-user-{user_slug(username)}"


def ensure_user_hindsight_bank(username, bank_id=None):
    """Ensure the authenticated user's Hindsight bank exists."""
    bank_id = bank_id or user_bank_id(username)

    # The original single-user demo bank remains the first account's bank.
    # New accounts always get their own bank.
    if bank_id == LEGACY_BANK_ID:
        return bank_id

    try:
        hindsight.create_bank(
            bank_id=bank_id,
            name=f"VendorSense — {username}",
            mission=(
                "Private Accounts Payable memory for this VendorSense user only. "
                "Store and retrieve this user's vendor experiences and "
                "human-confirmed invoice decisions."
            ),
        )
    except Exception:
        # If the bank already exists, create_bank is harmless to call again.
        # Any real recall/retain failure is still surfaced by those operations.
        pass

    return bank_id


def memory_item_text(item):
    if isinstance(item, dict):
        return (
            item.get("text")
            or item.get("content")
            or item.get("memory")
            or ""
        )

    return (
        getattr(item, "text", None)
        or getattr(item, "content", None)
        or str(item)
    )


def copy_legacy_workspace_to_first_user(
    destination_database,
    destination_archive,
):
    """
    Preserve the existing single-user demo data the first time an account
    is created. Later users start with an empty private workspace.
    """
    legacy_database = os.path.join(
        APP_ROOT,
        "vendorsense_database.json",
    )
    legacy_archive = os.path.join(
        APP_ROOT,
        "invoice_archive",
    )

    if os.path.exists(destination_database):
        return False

    copied = False

    if os.path.exists(legacy_database):
        try:
            with open(legacy_database, "r", encoding="utf-8") as f:
                legacy = json.load(f)

            if isinstance(legacy, dict) and (
                legacy.get("invoices") or legacy.get("activity")
            ):
                with open(
                    destination_database,
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(
                        legacy,
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                copied = True
        except Exception:
            pass

    if os.path.isdir(legacy_archive):
        try:
            for item in Path(legacy_archive).iterdir():
                if item.is_file():
                    target = Path(destination_archive) / item.name
                    if not target.exists():
                        shutil.copy2(item, target)
            copied = True or copied
        except Exception:
            pass

    return copied


def render_login_page():
    st.markdown(
        """
        <style>
        .auth-wrap {
            max-width: 560px;
            margin: 7vh auto 0 auto;
            padding: 34px;
            background: #111722;
            border: 1px solid #222d3d;
            border-radius: 18px;
        }
        .auth-brand {
            font-size: 32px;
            font-weight: 800;
            color: #f4f7fb;
            text-align: center;
        }
        .auth-sub {
            color: #8c98aa;
            text-align: center;
            margin: 7px 0 25px 0;
        }
        .auth-note {
            color: #68758a;
            font-size: 12px;
            text-align: center;
            margin-top: 18px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="auth-wrap">
            <div class="auth-brand">🧠 VendorSense</div>
            <div class="auth-sub">
                Intelligent Accounts Payable · Private Workspace
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, signup_tab, forgot_tab = st.tabs(
        ["🔐 Login", "✨ Create Account", "🔑 Forgot Password"]
    )

    with login_tab:
        with st.form("vendor_login_form"):
            username = st.text_input(
                "Username",
                placeholder="your.username",
            )
            password = st.text_input(
                "Password",
                type="password",
            )

            submitted = st.form_submit_button(
                "Login",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            users = load_users()
            key = username.strip().lower()
            record = users.get(key)

            if record and verify_password(password, record):
                if not record.get("bank_id"):
                    # Accounts created before per-user Hindsight isolation
                    # receive their own private bank on next successful login.
                    record["bank_id"] = user_bank_id(record["username"])
                    users[key] = record
                    save_users(users)

                st.session_state.authenticated = True
                st.session_state.username = record["username"]
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with signup_tab:
        with st.form("vendor_signup_form"):
            new_username = st.text_input(
                "Choose a username",
                placeholder="your.username",
            )
            new_password = st.text_input(
                "Create password",
                type="password",
            )
            confirm_password = st.text_input(
                "Confirm password",
                type="password",
            )
            favorite_color = st.text_input(
                "Favorite color",
                placeholder="e.g. blue",
                help=(
                    "Used only to verify identity during password recovery. "
                    "Case and extra spaces are ignored."
                ),
            )

            create = st.form_submit_button(
                "Create Account",
                type="primary",
                use_container_width=True,
            )

        if create:
            ok, error = validate_username(new_username)

            if not ok:
                st.error(error)
                return

            ok, error = validate_password(new_password)

            if not ok:
                st.error(error)
                return

            if new_password != confirm_password:
                st.error("Passwords do not match.")
                return

            if not normalize_recovery_answer(favorite_color):
                st.error("Please enter your favorite color.")
                return

            users = load_users()
            key = new_username.strip().lower()

            if key in users:
                st.error("That username already exists.")
                return

            _, new_database, new_archive = user_workspace(
                new_username.strip()
            )

            first_user = len(users) == 0

            new_bank_id = (
                LEGACY_BANK_ID
                if first_user
                else user_bank_id(new_username.strip())
            )

            users[key] = {
                "username": new_username.strip(),
                "bank_id": new_bank_id,
                **make_password_record(new_password),
                **make_recovery_record(favorite_color),
                "created_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            }

            save_users(users)

            if first_user:
                copy_legacy_workspace_to_first_user(
                    new_database,
                    new_archive,
                )


            st.session_state.authenticated = True
            st.session_state.username = new_username.strip()
            st.success(
                "Account created. Your private VendorSense workspace is ready."
            )
            st.rerun()

    with forgot_tab:
        st.info(
            "Forgot your password? Verify your username and favorite color, "
            "then create a new password."
        )

        with st.form("vendor_forgot_password_form"):
            recovery_username = st.text_input(
                "Username",
                placeholder="your.username",
            )
            recovery_color = st.text_input(
                "Favorite color",
                placeholder="your saved recovery color",
            )
            new_recovery_password = st.text_input(
                "New password",
                type="password",
            )
            confirm_recovery_password = st.text_input(
                "Confirm new password",
                type="password",
            )

            reset = st.form_submit_button(
                "Reset Password",
                type="primary",
                use_container_width=True,
            )

        if reset:
            users = load_users()
            key = recovery_username.strip().lower()
            record = users.get(key)

            valid_recovery = (
                record is not None
                and bool(record.get("recovery_hash"))
                and verify_recovery_answer(
                    recovery_color,
                    record,
                )
            )

            if not valid_recovery:
                st.error(
                    "Recovery details did not match."
                )
                return

            ok, error = validate_password(
                new_recovery_password
            )

            if not ok:
                st.error(error)
                return

            if new_recovery_password != confirm_recovery_password:
                st.error("New passwords do not match.")
                return

            new_record = make_password_record(
                new_recovery_password
            )

            # Keep username, recovery answer and created_at;
            # replace only the password record.
            record.update(new_record)

            users[key] = record
            save_users(users)

            st.success(
                "Password reset successfully. "
                "Use your new password to log in."
            )

    st.markdown(
        """
        <div class="auth-note">
            Each account has its own invoice history, archived files,
            activity log, and private Hindsight memory.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# SESSION AUTH STATE
# ============================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "username" not in st.session_state:
    st.session_state.username = None

if not st.session_state.authenticated:
    render_login_page()
    st.stop()

CURRENT_USER = st.session_state.username

users = load_users()
current_user_record = users.get(
    CURRENT_USER.strip().lower(),
    {},
)

# Per-user local storage.
USER_ROOT, DATABASE_PATH, ARCHIVE_DIR = user_workspace(
    CURRENT_USER
)

# Per-user Hindsight memory boundary.
BANK_ID = ensure_user_hindsight_bank(
    CURRENT_USER,
    current_user_record.get("bank_id"),
)

# Persist the bank ID if this is an older account.
if not current_user_record.get("bank_id"):
    current_user_record["bank_id"] = BANK_ID
    users[CURRENT_USER.strip().lower()] = current_user_record
    save_users(users)

os.makedirs(ARCHIVE_DIR, exist_ok=True)


# ============================================================
# PERSISTENT APPLICATION DATABASE
# ============================================================


def load_database():

    default_database = {
        "invoices": [],
        "activity": [],
    }

    if not os.path.exists(DATABASE_PATH):
        try:
            with open(DATABASE_PATH, "w", encoding="utf-8") as f:
                json.dump(default_database, f, indent=2)
        except Exception:
            pass
        return default_database

    try:
        with open(DATABASE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default_database
        data.setdefault("invoices", [])
        data.setdefault("activity", [])
        return data
    except Exception:
        return default_database


def save_database(database):

    temp_path = DATABASE_PATH + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, DATABASE_PATH)
        return True
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False


def invoice_key(invoice):
    return (
        str(invoice.get("vendor") or "").strip().lower(),
        str(invoice.get("invoice_id") or "").strip().lower(),
    )


def safe_filename(value):
    value = str(value or "invoice")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("._-") or "invoice"


def archive_uploaded_file(file_bytes, original_filename, invoice):
    """
    Permanently saves the exact uploaded invoice file in invoice_archive/.
    Works for PDF, PNG, JPG, and JPEG.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    vendor = safe_filename(invoice.get("vendor") or "unknown_vendor")
    invoice_id = safe_filename(invoice.get("invoice_id") or "unknown_invoice")

    original_filename = os.path.basename(original_filename or "invoice")
    source_name = safe_filename(os.path.splitext(original_filename)[0])
    extension = os.path.splitext(original_filename)[1].lower() or ".bin"

    archive_filename = (
        f"{vendor}__{invoice_id}__{source_name}__{file_hash[:12]}{extension}"
    )
    archive_path = os.path.join(ARCHIVE_DIR, archive_filename)

    if not os.path.exists(archive_path):
        with open(archive_path, "wb") as f:
            f.write(file_bytes)

    app_root = os.path.dirname(os.path.abspath(__file__))

    return {
        "original_filename": original_filename,
        "archive_filename": archive_filename,
        "archive_path": os.path.relpath(archive_path, app_root),
        "file_sha256": file_hash,

        # Backward-compatible fields for invoices already stored by the
        # PDF-only version.
        "pdf_archive_filename": archive_filename if extension == ".pdf" else None,
        "pdf_archive_path": os.path.relpath(archive_path, app_root) if extension == ".pdf" else None,
        "pdf_sha256": file_hash if extension == ".pdf" else None,
    }


def parse_invoice_image(image_bytes, mime_type):
    """
    Uses Groq vision to extract structured invoice data from a PNG/JPG/JPEG.
    This function extracts data only; the AP decision remains in analyze_invoice().
    """
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    prompt = """
You are the invoice extraction component of VendorSense.

Read the invoice image and extract ONLY the fields below.
Do not make an approval, rejection, fraud, or risk decision.

Return a JSON object with exactly these keys:
{
  "vendor": string or null,
  "invoice_id": string or null,
  "amount": number or null,
  "currency": string or "INR",
  "purchase_order": string or null,
  "payment_terms": string or null,
  "bank_account_last4": string or null,
  "description": string or null
}

Rules:
- Use the supplier/vendor/seller name as vendor.
- Amount must be the final total due/total amount, not subtotal.
- If a bank/account number is visible, return only its last 4 digits.
- Do not guess values that are not visible.
- Preserve invoice IDs and PO numbers exactly as shown when possible.
"""

    response = groq_client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
        temperature=0.1,
        max_completion_tokens=900,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content.strip()
    content = re.sub(
        r"```json\s*|\s*```",
        "",
        content,
        flags=re.IGNORECASE,
    ).strip()

    invoice = json.loads(content)
    invoice.setdefault("currency", "INR")
    invoice["source"] = "Image upload"
    return invoice


def upsert_invoice_record(invoice, decision):

    database = st.session_state.database
    key = invoice_key(invoice)
    existing_index = None

    for index, record in enumerate(database["invoices"]):
        record_key = (
            str(record.get("vendor") or "").strip().lower(),
            str(record.get("invoice_id") or "").strip().lower(),
        )
        if record_key == key and key != ("", ""):
            existing_index = index
            break

    record = {
        "vendor": invoice.get("vendor"),
        "invoice_id": invoice.get("invoice_id"),
        "amount": invoice.get("amount"),
        "currency": invoice.get("currency"),
        "purchase_order": invoice.get("purchase_order"),
        "payment_terms": invoice.get("payment_terms"),
        "bank_account_last4": invoice.get("bank_account_last4"),
        "description": invoice.get("description"),
        "source": invoice.get("source"),
        "original_filename": invoice.get("original_filename"),
        "archive_filename": invoice.get("archive_filename"),
        "archive_path": invoice.get("archive_path"),
        "file_sha256": invoice.get("file_sha256"),
        "pdf_archive_filename": invoice.get("pdf_archive_filename"),
        "pdf_archive_path": invoice.get("pdf_archive_path"),
        "pdf_sha256": invoice.get("pdf_sha256"),
        "decision": decision.get("decision"),
        "confidence": decision.get("confidence"),
        "reason": decision.get("reason"),
        "evidence": decision.get("evidence", []),
        "bank_change_detected": decision.get("bank_change_detected", False),
        "memory_used": decision.get("memory_used", False),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "human_decision": None,
        "review_note": None,
        "learned_at": None,
    }

    if existing_index is not None:
        old = database["invoices"][existing_index]
        record["human_decision"] = old.get("human_decision")
        record["review_note"] = old.get("review_note")
        record["learned_at"] = old.get("learned_at")

        if not record.get("original_filename"):
            record["original_filename"] = old.get("original_filename")
        if not record.get("archive_filename"):
            record["archive_filename"] = old.get("archive_filename") or old.get("pdf_archive_filename")
        if not record.get("archive_path"):
            record["archive_path"] = old.get("archive_path") or old.get("pdf_archive_path")
        if not record.get("file_sha256"):
            record["file_sha256"] = old.get("file_sha256") or old.get("pdf_sha256")
        if not record.get("pdf_archive_filename"):
            record["pdf_archive_filename"] = old.get("pdf_archive_filename")
        if not record.get("pdf_archive_path"):
            record["pdf_archive_path"] = old.get("pdf_archive_path")
        if not record.get("pdf_sha256"):
            record["pdf_sha256"] = old.get("pdf_sha256")
        database["invoices"][existing_index] = record
    else:
        database["invoices"].append(record)

    save_database(database)


def update_human_decision(invoice, human_decision, review_note):

    database = st.session_state.database
    key = invoice_key(invoice)

    for record in reversed(database["invoices"]):
        record_key = (
            str(record.get("vendor") or "").strip().lower(),
            str(record.get("invoice_id") or "").strip().lower(),
        )
        if record_key == key:
            record["human_decision"] = human_decision
            record["review_note"] = review_note
            record["learned_at"] = datetime.now().isoformat(timespec="seconds")
            break

    save_database(database)


def database_metrics(database):

    invoices = database.get("invoices", [])

    return {
        "invoice_count": len(invoices),
        "auto_count": sum(1 for item in invoices if item.get("decision") == "AUTO_PROCESS"),
        "exception_count": sum(1 for item in invoices if item.get("decision") == "EXCEPTION"),
        "learned_count": sum(1 for item in invoices if item.get("human_decision") in {"APPROVED", "REJECTED"}),
    }


database = load_database()
metrics = database_metrics(database)


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "page": "Overview",
    "invoice": None,
    "memory": None,
    "decision": None,
    "raw_text": None,
    "processed": False,
    "learning_status": None,
    "activity": [],
    "invoice_count": 0,
    "auto_count": 0,
    "exception_count": 0,
    "learned_count": 0,
    "exceptions": [],
}

for key, value in defaults.items():

    if key not in st.session_state:
        if key == "activity":
            st.session_state[key] = database.get("activity", [])[-10:][::-1]
        elif key == "invoice_count":
            st.session_state[key] = metrics["invoice_count"]
        elif key == "auto_count":
            st.session_state[key] = metrics["auto_count"]
        elif key == "exception_count":
            st.session_state[key] = metrics["exception_count"]
        elif key == "learned_count":
            st.session_state[key] = metrics["learned_count"]
        else:
            st.session_state[key] = value

if "database" not in st.session_state:
    st.session_state.database = database


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>

    .stApp {
        background-color: #090d14;
    }

    section[data-testid="stSidebar"] {
        background-color: #0c1119;
        border-right: 1px solid #202938;
    }

    .block-container {
        max-width: 1400px;
        padding-top: 2rem;
    }

    h1, h2, h3 {
        color: #f4f7fb !important;
    }

    .metric-card {
        background: #111722;
        border: 1px solid #222d3d;
        border-radius: 14px;
        padding: 20px;
    }

    .metric-label {
        color: #7f8ba0;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .metric-value {
        color: #f5f7fa;
        font-size: 30px;
        font-weight: 700;
        margin-top: 7px;
    }

    .metric-small {
        color: #6f7b8f;
        font-size: 12px;
        margin-top: 4px;
    }

    .section-card {
        background: #111722;
        border: 1px solid #222d3d;
        border-radius: 14px;
        padding: 22px;
        margin-bottom: 20px;
    }

    .memory-card {
        background: #121329;
        border: 1px solid #38336e;
        border-radius: 14px;
        padding: 22px;
    }

    .success-card {
        background: #0d2118;
        border: 1px solid #286943;
        border-radius: 14px;
        padding: 22px;
    }

    .danger-card {
        background: #281417;
        border: 1px solid #78353c;
        border-radius: 14px;
        padding: 22px;
    }

    .small-text {
        color: #8c98aa;
        font-size: 13px;
    }

    .brand {
        font-size: 26px;
        font-weight: 800;
        color: white;
    }

    .brand-subtitle {
        color: #69768a;
        font-size: 11px;
        margin-top: -5px;
        margin-bottom: 25px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# FUNCTIONS
# ============================================================

def extract_pdf_text(uploaded_file):

    reader = PdfReader(uploaded_file)

    pages = []

    for page in reader.pages:

        text = page.extract_text()

        if text:
            pages.append(text)

    return "\n".join(pages)


def _clean_field(value):
    if value is None:
        return None

    value = re.sub(r"\s+", " ", str(value)).strip()

    if not value:
        return None

    return value


def _first_non_empty_line(text):
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return None


def _find_labeled_line_value(text, labels):
    """
    Finds values in common invoice layouts such as:
        Supplier
        Nova Office Systems

    and:
        Supplier: Nova Office Systems
    """
    label_pattern = "|".join(
        re.escape(label) for label in labels
    )

    # Label + value on the same line.
    match = re.search(
        rf"(?:{label_pattern})\s*[:\-]\s*(.+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return _clean_field(match.group(1))

    # Label on one line, value on the next non-empty line.
    match = re.search(
        rf"(?:{label_pattern})\s*\n\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        candidate = _clean_field(match.group(1))

        # Avoid accidentally taking another section heading.
        if candidate and candidate.casefold() not in {
            "invoice details",
            "bill to",
            "bill from",
            "tax invoice",
            "invoice",
        }:
            return candidate

    return None


def parse_invoice(text):

    invoice = {
        "vendor": None,
        "invoice_id": None,
        "amount": None,
        "currency": "INR",
        "purchase_order": None,
        "payment_terms": None,
        "bank_account_last4": None,
        "description": None,
        "source": "PDF upload",
    }

    # --------------------------------------------------------
    # Vendor / supplier name
    # --------------------------------------------------------
    vendor = _find_labeled_line_value(
        text,
        [
            "Vendor",
            "Supplier",
            "Seller",
        ],
    )

    # "Bill From" is common on invoices.
    if not vendor:
        vendor = _find_labeled_line_value(
            text,
            [
                "Bill From",
                "Billed From",
            ],
        )

    # Fallback: many invoices place the supplier name at the very
    # top before "INVOICE" / "TAX INVOICE".
    if not vendor:
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        for line in lines[:6]:
            normalized = line.casefold()

            if normalized in {
                "invoice",
                "tax invoice",
                "commercial invoice",
                "bill",
            }:
                continue

            if "invoice" in normalized and len(line) < 40:
                continue

            # Prefer a title-like company name over an address/section.
            if (
                len(line) <= 80
                and not re.search(r"\b(?:road|street|estate|plot|unit)\b", line, re.I)
                and not re.search(r"\bGSTIN\b|\bIFSC\b", line, re.I)
            ):
                vendor = _clean_field(line)
                break

    invoice["vendor"] = vendor

    # --------------------------------------------------------
    # Invoice ID
    # Handles:
    #   Invoice No: INV-123
    #   Invoice Number: INV-123
    #   Invoice ID: INV-123
    # --------------------------------------------------------
    match = re.search(
        r"Invoice\s*(?:ID|No\.?|Number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_-]*)",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice["invoice_id"] = _clean_field(match.group(1))

    # --------------------------------------------------------
    # Purchase order
    # Handles:
    #   Purchase Order: AIS-2419
    #   PO Number: PO-NOS-5618
    #   PO: PO-123
    # --------------------------------------------------------
    match = re.search(
        r"(?:Purchase\s*Order|PO(?:\s*(?:Number|No\.?))?)"
        r"\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_-]*)",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice["purchase_order"] = _clean_field(
            match.group(1)
        )

    # --------------------------------------------------------
    # Payment terms
    # --------------------------------------------------------
    match = re.search(
        r"(?:Payment\s*Terms|Terms)\s*[:\-]?\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice["payment_terms"] = _clean_field(
            match.group(1)
        )

    # --------------------------------------------------------
    # Currency
    # --------------------------------------------------------
    match = re.search(
        r"Currency\s*[:\-]?\s*([A-Z]{3})",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice["currency"] = match.group(1).upper()

    # --------------------------------------------------------
    # Bank account last 4
    # --------------------------------------------------------
    match = re.search(
        r"(?:Bank\s*Account|Account)\s*[:\-]?\s*"
        r"(?:X+|\*+|•+)?\s*(\d{4})\b",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice["bank_account_last4"] = match.group(1)

    # --------------------------------------------------------
    # Amount
    # --------------------------------------------------------
    patterns = [
        r"Total\s*Due\s*[:\-]?\s*[₹■]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"Total\s*Amount\s*[:\-]?\s*[₹■]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"Grand\s*Total\s*[:\-]?\s*[₹■]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"Amount\s*Payable\s*[:\-]?\s*[₹■]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"Amount\s*[:\-]?\s*[₹■]?\s*([\d,]+(?:\.\d{1,2})?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            try:

                invoice["amount"] = float(
                    match.group(1).replace(",", "")
                )

                break

            except ValueError:
                pass

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------
    match = re.search(
        r"Description\s*[:\-]?\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        description = _clean_field(match.group(1))

        # Avoid treating table headers as an actual description.
        if description and description.casefold() not in {
            "qty",
            "quantity",
            "unit price",
            "amount",
        }:
            invoice["description"] = description

    return invoice


def recall_memory(invoice):

    if not BANK_ID:
        return {"error": "User memory bank is not available."}

    query = f"""
VendorSense Accounts Payable evaluation.

Vendor: {invoice.get('vendor')}
Invoice ID: {invoice.get('invoice_id')}
Amount: {invoice.get('amount')}
Purchase Order: {invoice.get('purchase_order')}
Payment Terms: {invoice.get('payment_terms')}
Current Bank Ending: {invoice.get('bank_account_last4')}

Retrieve relevant previous experiences with this vendor.

Look for:

- previous approvals
- previous rejections
- typical invoice amounts
- payment terms
- purchase order patterns
- verified bank account information
- previous exceptions
- human decisions
- learned vendor patterns

The memory will be used to determine whether the
current invoice is routine or requires human review.
"""

    try:

        result = hindsight.recall(
            bank_id=BANK_ID,
            query=query,
            max_tokens=2500,
            budget="mid",
        )

        return result

    except Exception as e:

        return {
            "error": str(e)
        }


def memory_to_text(memory):

    if not memory:
        return "No memory returned."

    if isinstance(memory, dict):

        if memory.get("error"):
            return f"Memory error: {memory['error']}"

        results = memory.get("results", [])

        if results:

            output = []

            for item in results:

                if isinstance(item, dict):

                    value = (
                        item.get("text")
                        or item.get("content")
                        or item.get("memory")
                        or str(item)
                    )

                else:

                    value = str(item)

                output.append(value)

            return "\n\n".join(output)

        return "No relevant previous vendor experience found."

    return str(memory)


def analyze_invoice(invoice, memory):

    memory_text = memory_to_text(memory)

    system_prompt = """
You are VendorSense, an AI Accounts Payable agent.

Evaluate the current invoice against previous vendor
experience retrieved from Hindsight.

Hindsight memory is evidence, not absolute truth.

Rules:

1. A vendor with no relevant experience should normally
   require human review.

2. A known vendor can be AUTO_PROCESS if the invoice is
   consistent with learned vendor behavior.

3. Meaningful deviations should trigger EXCEPTION.

4. A bank account change must trigger EXCEPTION.

5. Never claim that money was actually transferred.

6. AUTO_PROCESS means simulated AP routing only.

Return ONLY JSON:

{
    "decision": "AUTO_PROCESS" or "EXCEPTION",
    "confidence": "HIGH" or "MEDIUM" or "LOW",
    "reason": "short explanation",
    "evidence": [
        "point 1",
        "point 2",
        "point 3"
    ],
    "bank_change_detected": true or false,
    "memory_used": true or false
}
"""

    user_prompt = f"""
CURRENT INVOICE:

{json.dumps(invoice, indent=2)}

HINDSIGHT MEMORY:

{memory_text}

Evaluate this invoice.
"""

    try:

        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0.1,
            max_tokens=700,
        )

        content = response.choices[0].message.content.strip()

        content = re.sub(
            r"```json\s*|\s*```",
            "",
            content,
            flags=re.IGNORECASE,
        ).strip()

        result = json.loads(content)

        if result.get("bank_change_detected") is True:
            result["decision"] = "EXCEPTION"

        return result

    except Exception as e:

        return {
            "decision": "EXCEPTION",
            "confidence": "LOW",
            "reason": "Automated analysis failed safely.",
            "evidence": [
                "Human review is required."
            ],
            "bank_change_detected": False,
            "memory_used": False,
        }


def teach_hindsight(invoice, decision, reason):

    if not BANK_ID:
        return False, "User memory bank is not available."

    experience = f"""
VendorSense AP learning event.

User workspace: {CURRENT_USER}

Vendor: {invoice.get('vendor')}
Invoice ID: {invoice.get('invoice_id')}
Amount: ₹{invoice.get('amount')}
Purchase Order: {invoice.get('purchase_order')}
Payment Terms: {invoice.get('payment_terms')}
Bank ending: {invoice.get('bank_account_last4')}

Human decision: {decision}

Human review note:
{reason}

This is a human-confirmed AP experience.

Use this experience when evaluating future invoices
from this vendor.
"""

    try:

        hindsight.retain(
            bank_id=BANK_ID,
            content=experience,
        )

        return True, None

    except Exception as e:

        return False, str(e)


def add_activity(title, description):

    item = {
        "title": title,
        "description": description,
        "time": datetime.now().strftime("%H:%M:%S"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    st.session_state.activity.insert(0, item)
    st.session_state.activity = st.session_state.activity[:10]

    database = st.session_state.database
    database["activity"].append(item)
    database["activity"] = database["activity"][-100:]
    save_database(database)


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

with st.sidebar:

    st.markdown(
        '<div class="brand">🧠 VendorSense</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="brand-subtitle">Intelligent Accounts Payable</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        f"Signed in as **{CURRENT_USER}**"
    )

    st.caption(
        "Private workspace • isolated data"
    )

    if st.button(
        "↪  Logout",
        use_container_width=True,
    ):
        for key in list(st.session_state.keys()):
            del st.session_state[key]

        st.rerun()

    users = load_users()
    current_user_key = CURRENT_USER.strip().lower()
    current_user_record = users.get(current_user_key, {})

    if not current_user_record.get("recovery_hash"):
        with st.expander("🔑 Set Password Recovery", expanded=True):
            st.caption(
                "Your account was created before recovery was enabled. "
                "Set a favorite color now so you can reset your password later."
            )

            with st.form("set_recovery_color_form"):
                recovery_color = st.text_input(
                    "Favorite color",
                    type="password",
                    placeholder="your recovery color",
                )
                save_recovery = st.form_submit_button(
                    "Save Recovery Color",
                    use_container_width=True,
                )

            if save_recovery:
                if not normalize_recovery_answer(recovery_color):
                    st.error("Please enter a favorite color.")
                else:
                    current_user_record.update(
                        make_recovery_record(recovery_color)
                    )
                    users[current_user_key] = current_user_record
                    save_users(users)
                    st.success("Recovery color saved.")

    st.divider()

    st.caption("WORKSPACE")

    if st.button(
        "⌂  Overview",
        use_container_width=True,
    ):
        st.session_state.page = "Overview"

    if st.button(
        "▣  Invoice Queue",
        use_container_width=True,
    ):
        st.session_state.page = "Invoice Queue"

    if st.button(
        "⚠  Exceptions",
        use_container_width=True,
    ):
        st.session_state.page = "Exceptions"

    if st.button(
        "◈  Vendor Memory",
        use_container_width=True,
    ):
        st.session_state.page = "Vendor Memory"

    st.divider()

    st.caption("SYSTEM")

    st.success("Hindsight connected")

    st.success("Groq reasoning online")

    st.divider()

    st.caption(
        "Synthetic hackathon data. "
        "No real payments are executed."
    )


# ============================================================
# PAGE: OVERVIEW
# ============================================================

if st.session_state.page == "Overview":

    st.title("Accounts Payable Intelligence")

    st.caption(
        "An agent that learns what normal looks like for every vendor."
    )

    st.divider()

    # Metrics
    c1, c2, c3, c4 = st.columns(4)

    with c1:

        st.metric(
            "Invoices Processed",
            st.session_state.invoice_count,
        )

    with c2:

        st.metric(
            "Auto-Processed",
            st.session_state.auto_count,
        )

    with c3:

        st.metric(
            "Human Review",
            st.session_state.exception_count,
        )

    with c4:

        st.metric(
            "Learning Events",
            st.session_state.learned_count,
        )

    st.divider()

    # Intake
    left, right = st.columns([1.5, 1])

    with left:

        st.subheader("📄 Invoice Intake")

        st.write(
            "Upload a synthetic invoice as a PDF, PNG, JPG, or JPEG "
            "to simulate an invoice entering the AP workflow."
        )

        uploaded_file = st.file_uploader(
            "Invoice File",
            type=["pdf", "png", "jpg", "jpeg"],
            key="overview_upload",
        )

        if uploaded_file:

            st.info(
                f"Selected: {uploaded_file.name}"
            )

            if st.button(
                "🚀 Analyze Invoice",
                type="primary",
                use_container_width=True,
            ):

                with st.spinner(
                    "Extracting invoice information..."
                ):

                    try:

                        file_bytes = uploaded_file.getvalue()
                        extension = os.path.splitext(
                            uploaded_file.name
                        )[1].lower()

                        if extension in {".png", ".jpg", ".jpeg"}:
                            if len(file_bytes) > 20 * 1024 * 1024:
                                st.error(
                                    "Image is larger than 20 MB. "
                                    "Please upload a smaller PNG/JPG/JPEG invoice."
                                )
                                st.stop()

                        if extension == ".pdf":

                            import io

                            raw_text = extract_pdf_text(
                                io.BytesIO(file_bytes)
                            )

                            invoice = parse_invoice(
                                raw_text
                            )

                        elif extension in {".png", ".jpg", ".jpeg"}:

                            mime_type = {
                                ".png": "image/png",
                                ".jpg": "image/jpeg",
                                ".jpeg": "image/jpeg",
                            }[extension]

                            raw_text = None

                            invoice = parse_invoice_image(
                                file_bytes,
                                mime_type,
                            )

                        else:

                            st.error(
                                "Unsupported invoice format."
                            )
                            st.stop()

                        archive_info = archive_uploaded_file(
                            file_bytes,
                            uploaded_file.name,
                            invoice,
                        )

                        invoice.update(archive_info)

                        st.session_state.raw_text = raw_text
                        st.session_state.invoice = invoice

                    except Exception as e:

                        st.error(
                            f"Invoice extraction/archive failed: {e}"
                        )

                        st.stop()

                add_activity(
                    "Invoice captured",
                    f"{invoice.get('invoice_id') or 'Unknown invoice'} extracted.",
                )

                with st.spinner(
                    "Recalling vendor experience from Hindsight..."
                ):

                    memory = recall_memory(
                        invoice
                    )

                    st.session_state.memory = memory

                add_activity(
                    "Hindsight recall",
                    f"Experience retrieved for {invoice.get('vendor') or 'vendor'}.",
                )

                with st.spinner(
                    "Groq is evaluating the invoice..."
                ):

                    decision = analyze_invoice(
                        invoice,
                        memory,
                    )

                    st.session_state.decision = decision
                    st.session_state.processed = True
                    st.session_state.learning_status = None

                # Persist the processed invoice before leaving the page.
                upsert_invoice_record(invoice, decision)

                add_activity(
                    "Invoice file archived permanently",
                    f"{invoice.get('original_filename') or 'Invoice file'} saved in invoice_archive/.",
                )

                current_metrics = database_metrics(st.session_state.database)
                st.session_state.invoice_count = current_metrics["invoice_count"]

                if decision["decision"] == "AUTO_PROCESS":

                    st.session_state.auto_count = current_metrics["auto_count"]

                    add_activity(
                        "Invoice auto-processed",
                        "Invoice matched learned vendor behavior.",
                    )

                else:

                    st.session_state.exception_count = current_metrics["exception_count"]

                    add_activity(
                        "Exception created",
                        "Human review required.",
                    )

                st.session_state.page = "Invoice Queue"

                st.rerun()

    with right:

        st.subheader("🧠 Agent Pipeline")

        st.info("1  📄 Invoice captured")

        st.info("2  🧠 Hindsight recall")

        st.info("3  🤖 Groq reasoning")

        st.info("4  ⚡ Decision")

        st.info("5  👤 Human review if needed")

        st.info("6  🧠 Hindsight retain")

    st.divider()

    st.subheader("Recent Activity")

    if st.session_state.activity:

        for item in st.session_state.activity:

            st.write(
                f"**{item['title']}** — "
                f"{item['description']} "
                f"`{item['time']}`"
            )

    else:

        st.caption(
            "No activity yet. Upload an invoice to begin."
        )


# ============================================================
# PAGE: INVOICE QUEUE
# ============================================================

elif st.session_state.page == "Invoice Queue":

    st.title("Invoice Queue")

    st.caption(
        "Current invoice evaluation and agent decision."
    )

    if not st.session_state.processed:

        st.info(
            "No invoice has been processed yet. "
            "Go to Overview and upload a PDF."
        )

    else:

        invoice = st.session_state.invoice
        memory = st.session_state.memory
        decision = st.session_state.decision

        st.subheader("Current Invoice")

        c1, c2, c3 = st.columns(3)

        with c1:

            st.write("**Vendor**")

            st.write(
                invoice.get("vendor") or "Unknown"
            )

        with c2:

            st.write("**Invoice ID**")

            st.write(
                invoice.get("invoice_id") or "Unknown"
            )

        with c3:

            st.write("**Amount**")

            amount = invoice.get("amount")

            if amount:
                st.write(
                    f"₹{amount:,.2f}"
                )
            else:
                st.write("Unknown")

        st.divider()

        c1, c2, c3 = st.columns(3)

        with c1:

            st.write("**Purchase Order**")

            st.write(
                invoice.get("purchase_order") or "—"
            )

        with c2:

            st.write("**Payment Terms**")

            st.write(
                invoice.get("payment_terms") or "—"
            )

        with c3:

            st.write("**Bank Ending**")

            if invoice.get("bank_account_last4"):

                st.write(
                    f"•••• {invoice['bank_account_last4']}"
                )

            else:

                st.write("—")

        st.divider()

        st.subheader("🗂 Stored Invoice File")

        archive_path = (
            invoice.get("archive_path")
            or invoice.get("pdf_archive_path")
        )
        original_name = invoice.get("original_filename")

        if archive_path and os.path.exists(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), archive_path)
        ):
            st.success(
                f"File permanently archived: {original_name or 'uploaded invoice'}"
            )
            st.caption(f"Private storage path: {archive_path}")
        else:
            st.warning(
                "The archived invoice file is not available on this machine."
            )

        left, right = st.columns(2)

        with left:

            st.subheader("🧠 Hindsight Memory")

            if isinstance(memory, dict) and memory.get("results"):

                st.success(
                    "Relevant vendor experience found."
                )

                st.write(
                    memory_to_text(memory)
                )

            elif isinstance(memory, dict) and memory.get("error"):

                st.error(
                    memory["error"]
                )

            else:

                st.warning(
                    "No relevant previous vendor experience found."
                )

                st.write(
                    "This is a new learning situation. "
                    "A human decision can become future experience."
                )

        with right:

            st.subheader("🤖 Agent Decision")

            if decision["decision"] == "AUTO_PROCESS":

                st.success(
                    "🟢 AUTO-PROCESS"
                )

            else:

                st.error(
                    "🔴 EXCEPTION"
                )

            st.write(
                f"**Confidence:** {decision.get('confidence', 'LOW')}"
            )

            st.write(
                f"**Reason:** {decision.get('reason', '')}"
            )

            if decision.get("bank_change_detected"):

                st.warning(
                    "Bank account change detected."
                )

        st.divider()

        st.subheader("Evidence")

        evidence = decision.get(
            "evidence",
            [],
        )

        for item in evidence:

            st.write(
                f"✓ {item}"
            )

        if decision["decision"] == "EXCEPTION":

            st.divider()

            st.subheader(
                "👤 Human Review"
            )

            st.warning(
                "This invoice requires human confirmation."
            )

            review_note = st.text_area(
                "Review note",
                placeholder=(
                    "Explain what you verified..."
                ),
            )

            c1, c2 = st.columns(2)

            with c1:

                if st.button(
                    "✅ Approve & Teach Agent",
                    use_container_width=True,
                ):

                    if not review_note.strip():

                        review_note = (
                            "Human reviewer approved "
                            "after manual verification."
                        )

                    with st.spinner(
                        "Teaching VendorSense..."
                    ):

                        success, error = teach_hindsight(
                            invoice,
                            "APPROVED",
                            review_note,
                        )

                    if success:

                        update_human_decision(
                            invoice,
                            "APPROVED",
                            review_note,
                        )

                        st.session_state.learned_count = database_metrics(
                            st.session_state.database
                        )["learned_count"]

                        st.session_state.learning_status = "approved"

                        add_activity(
                            "Agent learned",
                            "Human approval retained in Hindsight.",
                        )

                        st.success(
                            "Approved. VendorSense has learned from this decision."
                        )

                    else:

                        st.error(error)

            with c2:

                if st.button(
                    "❌ Reject & Teach Agent",
                    use_container_width=True,
                ):

                    if not review_note.strip():

                        review_note = (
                            "Human reviewer rejected "
                            "after manual verification."
                        )

                    with st.spinner(
                        "Teaching VendorSense..."
                    ):

                        success, error = teach_hindsight(
                            invoice,
                            "REJECTED",
                            review_note,
                        )

                    if success:

                        update_human_decision(
                            invoice,
                            "REJECTED",
                            review_note,
                        )

                        st.session_state.learned_count = database_metrics(
                            st.session_state.database
                        )["learned_count"]

                        st.session_state.learning_status = "rejected"

                        add_activity(
                            "Agent learned",
                            "Human rejection retained in Hindsight.",
                        )

                        st.error(
                            "Rejected. VendorSense has learned from this decision."
                        )

                    else:

                        st.error(error)

        else:

            st.divider()

            st.success(
                "Invoice routed through simulated AP processing."
            )

            st.caption(
                "No real payment was executed."
            )

        if st.session_state.learning_status:

            st.divider()

            st.info(
                "🧠 Hindsight learning event recorded. "
                "Future invoices can use this experience."
            )


# ============================================================
# PAGE: EXCEPTIONS
# ============================================================

elif st.session_state.page == "Exceptions":

    st.title("Exceptions")

    st.caption(
        "Invoices that require human attention."
    )

    if (
        st.session_state.processed
        and st.session_state.decision
        and st.session_state.decision["decision"] == "EXCEPTION"
    ):

        invoice = st.session_state.invoice
        decision = st.session_state.decision

        st.error(
            "🔴 Current invoice requires human review."
        )

        st.subheader(
            invoice.get("invoice_id") or "Unknown invoice"
        )

        st.write(
            f"**Vendor:** {invoice.get('vendor')}"
        )

        st.write(
            f"**Reason:** {decision.get('reason')}"
        )

        if decision.get("bank_change_detected"):

            st.warning(
                "⚠ Bank account difference detected."
            )

        st.info(
            "Open Invoice Queue to approve/reject "
            "and teach the agent."
        )

    else:

        st.success(
            "No active exceptions."
        )

        st.caption(
            "When VendorSense detects a meaningful deviation, "
            "it will appear here."
        )


# ============================================================
# PAGE: VENDOR MEMORY
# ============================================================

elif st.session_state.page == "Vendor Memory":

    st.title("Vendor Memory")

    st.caption(
        "Experience retrieved from Hindsight."
    )

    if not st.session_state.processed:

        st.info(
            "Process an invoice first to see relevant vendor memory."
        )

    else:

        invoice = st.session_state.invoice
        memory = st.session_state.memory

        st.subheader(
            invoice.get("vendor") or "Unknown Vendor"
        )

        st.write(
            "Vendor experience retrieved for this invoice."
        )

        st.divider()

        if isinstance(memory, dict) and memory.get("results"):

            st.success(
                "Hindsight returned relevant experience."
            )

            st.write(
                memory_to_text(memory)
            )

        elif isinstance(memory, dict) and memory.get("error"):

            st.error(
                memory["error"]
            )

        else:

            st.warning(
                "No previous vendor experience was found."
            )

            st.write(
                """
                This is exactly where VendorSense begins learning.

                Once a human approves or rejects this invoice,
                that decision is retained in Hindsight and can
                influence future invoice evaluations.
                """
            )

        st.divider()

        st.subheader("Learning Status")

        st.metric(
            "Human decisions retained",
            st.session_state.learned_count,
        )

        if st.session_state.learning_status == "approved":

            st.success(
                "Latest decision: APPROVED → retained in Hindsight"
            )

        elif st.session_state.learning_status == "rejected":

            st.error(
                "Latest decision: REJECTED → retained in Hindsight"
            )

        else:

            st.info(
                "No human learning event recorded for the current invoice."
            )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "VendorSense • Hindsight-powered Accounts Payable Agent • "
    "Synthetic hackathon data • No real payments executed"
)