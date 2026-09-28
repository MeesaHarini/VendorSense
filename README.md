
VendorSense
AI Accounts Payable agent that learns from human invoice decisions using Hindsight memory.

VendorSense evaluates invoices using current invoice evidence plus relevant vendor history retrieved from Hindsight. When an invoice needs human review, the confirmed human decision is retained in Hindsight so future invoices can use that experience.

Safety: AUTO_PROCESS means simulated Accounts Payable routing/approval only. No real payments are executed. Demo data is synthetic.

What VendorSense does
Invoice
   ↓
Extract invoice details
   ↓
Hindsight Recall
   ↓
Groq reasoning
   ↓
AUTO_PROCESS / EXCEPTION
   ↓
Human confirmation when required
   ↓
Hindsight Retain
   ↓
Future invoices use the confirmed experience
The goal is not just to read an invoice. Previous human decisions become useful context for later invoices from the same vendor.

Core workflow
1. Invoice intake
The application accepts invoice documents and extracts fields such as vendor, invoice ID, amount, purchase order, payment terms, and bank account ending. PDF invoices are parsed with pypdf; image-based invoices use the configured Groq vision workflow.

2. Hindsight Recall
Before the LLM makes its recommendation, VendorSense queries Hindsight for relevant previous vendor experiences, including approvals, rejections, typical amounts, payment terms, PO patterns, verified bank information, previous exceptions, human decisions, and learned vendor patterns.

result = hindsight.recall(
    bank_id=BANK_ID,
    query=query,
    max_tokens=2500,
    budget="mid",
)
The retrieved memory is passed into the reasoning prompt alongside the current invoice.

3. AI reasoning
Groq evaluates the current invoice using the invoice data and retrieved Hindsight memory. The result includes a decision, confidence, reason, evidence, bank-change signal, and whether memory was used.

VendorSense treats Hindsight memory as evidence, not absolute truth.

4. Human review
Meaningful deviations go to an exception path. A detected bank-account change is forced to EXCEPTION in application logic rather than relying only on model interpretation.

if result.get("bank_change_detected") is True:
    result["decision"] = "EXCEPTION"
5. Hindsight Retain
Human confirmation is the learning boundary. When a reviewer approves or rejects an invoice, VendorSense creates a learning event containing vendor context, invoice details, the human decision, and review note.

hindsight.retain(
    bank_id=BANK_ID,
    content=experience,
)
The next invoice can retrieve that confirmed experience through Hindsight Recall.

Why Hindsight is important
Without persistent memory, each invoice is evaluated with little or no vendor-specific history. With Hindsight, the system can retrieve previous experiences and human-confirmed outcomes before evaluating the next invoice.

First interaction	Later interaction
Little vendor-specific context	Relevant vendor experience is available
Conservative evaluation	Historical context informs evaluation
Human decision creates learning data	Previous learning can be recalled
Agent starts with little experience	Agent can use accumulated experience
Architecture
                       ┌──────────────────────┐
                       │      Streamlit UI    │
                       │ Invoice intake/review│
                       └──────────┬───────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │ Invoice extraction   │
                       │ PDF / image parsing  │
                       └──────────┬───────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │   Hindsight Recall   │
                       │  Vendor experience   │
                       └──────────┬───────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │    Groq reasoning    │
                       │ Current + historical│
                       │       context        │
                       └──────────┬───────────┘
                                  │
                       ┌──────────┴───────────┐
                       ▼                      ▼
              ┌────────────────┐      ┌─────────────────┐
              │  AUTO_PROCESS  │      │    EXCEPTION    │
              │ simulated AP   │      │ Human review    │
              └────────────────┘      └────────┬────────┘
                                               │
                                               ▼
                                     ┌─────────────────┐
                                     │ Human confirmed │
                                     │     outcome     │
                                     └────────┬────────┘
                                              │
                                              ▼
                                     ┌─────────────────┐
                                     │ Hindsight Retain│
                                     └─────────────────┘
Technology stack
Python 3.11

Streamlit

Groq

Hindsight by Vectorize

pypdf

python-dotenv

Project structure
VendorSense/
├── app.py
├── requirements.txt
├── .gitignore
├── .streamlit/
│   └── config.toml
├── README.md
└── local runtime data/
    ├── vendorsense_users.json
    ├── users/
    └── invoice archives/
Local runtime data should not be committed to the repository.

Setup
1. Clone
git clone https://github.com/MeesaHarini/VendorSense.git
cd VendorSense
2. Virtual environment (Windows PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
3. Install dependencies
pip install -r requirements.txt
4. Configure environment variables
Create .env in the project root:

GROQ_API_KEY=your_groq_api_key
HINDSIGHT_API_KEY=your_hindsight_api_key
Never commit .env or API keys.

5. Run
streamlit run app.py
Hindsight integration
VendorSense uses Hindsight for two explicit operations:

Recall

hindsight.recall(
    bank_id=BANK_ID,
    query=query,
    max_tokens=2500,
    budget="mid",
)
Retain

hindsight.retain(
    bank_id=BANK_ID,
    content=experience,
)
The application uses per-user memory banks so different users do not share learned vendor experiences.

Safety design
Hindsight memories are evidence, not unquestionable truth.

The agent does not execute real financial transfers.

AUTO_PROCESS is simulated AP routing/approval.

Meaningful deviations are routed to human review.

Bank-account changes are forced into the exception path.

Human approvals/rejections are the learning signal.

Synthetic demo data is used.

Secrets are stored in environment variables.

LLM failure falls back to a human-review-safe path.

Demo scenario
A first invoice arrives with little vendor-specific history.

VendorSense recalls Hindsight memory and evaluates the invoice.

A human reviews and confirms the outcome.

VendorSense retains that confirmed experience in Hindsight.

A later invoice from the same vendor can retrieve the prior experience.

A meaningful deviation, such as changed bank details, still triggers human review.

Screenshots








Project links
GitHub: https://github.com/MeesaHarini/VendorSense

Hindsight GitHub: https://github.com/vectorize-io/hindsight

Hindsight Documentation: https://hindsight.vectorize.io/

Vectorize — Agent Memory: https://vectorize.io/what-is-agent-memory

Article: https://dev.to/harini_varma_a5c641756f3e/i-used-hindsight-to-remember-human-invoice-decisions-4ilb

Limitations
VendorSense is a focused prototype rather than a production financial system.

Application runtime data uses local persistence.

Demo data is synthetic.

No banking/payment execution system is connected.

Automated routing is simulated.

LLM and memory availability depend on external APIs.

Production use would require stronger identity, audit, persistence, access-control, and financial controls.

Future improvements
Durable production database storage

Stronger audit trails

Enterprise identity and role management

More invoice/document formats

Configurable approval policies

Expanded monitoring and observability

Production-grade ERP and payment integrations

License
