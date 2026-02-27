# Invoice Chaser

## Problem Statement

Small businesses struggle with timely collection of overdue invoices. Manual follow-ups are time-consuming, inconsistent, and often delayed. There is a need for an automated, intelligent system that can monitor invoice status, generate context-aware escalation messages, dispatch them via preferred channels (email/SMS), and process customer responses—all while respecting contact preferences and escalation rules.

## Proposed Solution and Approach

Invoice Chaser is a modular AI-powered system built around five coordinated agents:

1. **Invoice Monitor** – Marks invoices overdue when due dates pass and assigns escalation levels (1: 1–7 days, 2: 8–14 days, 3: 15+ days).
2. **Message Generator** – Uses a local LLM (Ollama with Qwen2.5) to create personalized email/SMS per client preference and escalation level.
3. **Communication Dispatcher** – Sends messages via SMTP (email) and Twilio (SMS); respects minimum days between contacts.
4. **Response Handler** – Classifies inbound email/SMS intent (pay/dispute/ignore) via LLM, updates invoice status (e.g., mark paid), and handles opt-out.
5. **Analytics Reporter** – Writes KPIs and reports to CSV.

An APScheduler orchestrator runs the pipeline on configurable schedules (daily chase, weekly analytics, periodic response polling). A Streamlit dashboard provides a test UI; a Flask API exposes webhooks for Twilio and REST endpoints for clients/invoices.

## Technology Stack and Third-Party Resources

### AI/ML Tools

| Resource | Version | License | URL |
|----------|---------|---------|-----|
| Ollama | (local runtime) | MIT | https://github.com/ollama/ollama |
| Qwen2.5 7B Instruct (via Ollama) | qwen2.5:7b-instruct-q4_K_M | Apache 2.0 | https://ollama.com/library/qwen2.5 |

### Python Libraries

| Library | Purpose | License |
|---------|---------|---------|
| SQLAlchemy ≥2.0 | ORM and database | MIT |
| APScheduler | Scheduled jobs | MIT |
| Flask | Web API and webhooks | BSD-3-Clause |
| Streamlit | Admin dashboard | Apache 2.0 |
| Pydantic | Data validation | MIT |
| python-dotenv | Environment config | BSD-3-Clause |
| PyYAML | Config parsing | MIT |
| Twilio | SMS and voice | MIT |
| imapclient | IMAP email polling | BSD |
| pandas | Data analysis | BSD-3-Clause |
| matplotlib, seaborn | Charts and reports | PSF |
| pytest | Testing | MIT |

### External Services

- **Twilio** – SMS delivery and level-3 voice escalation calls (subject to Twilio ToS).
- **SMTP (e.g., Gmail)** – Outbound email delivery.
- **IMAP (e.g., Gmail)** – Optional inbound email polling for response handling.

**Credential Security:** API keys, tokens, and passwords must be stored in environment variables (e.g., `.env`) and must not be hardcoded in submitted code. Use `.env.example` as a template.

## Setup and Run Instructions

### Prerequisites

- Python 3.10+
- Ollama installed and running locally (`ollama run qwen2.5:7b-instruct-q4_K_M`)

### Installation

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your credentials (SMTP, Twilio, IMAP as needed). Do not commit `.env`.

### Quick Start

```bash
python -m db.seed_sample_data   # Creates 3 sample clients and invoices
python run_demo.py              # Runs Monitor → Generator → Dispatcher → Analytics
```

### Orchestrator (Scheduled Pipeline)

```bash
python orchestrator.py
```

Runs the chase pipeline daily, analytics weekly, and response poll every 15 minutes (configurable via `CRON_*` env vars).

### Web API and Webhooks

```bash
python -m web.app
```

- Set Twilio webhook URL to `https://your-host/webhook/sms` for inbound SMS.
- REST API: `/api/clients`, `/api/invoices`, `/api/overview`, `/api/pipeline/*`, etc.

### Streamlit Dashboard

```bash
streamlit run dashboard.py
```

Provides UI for testing: Overview, Invoices, Clients, Message Generator, Response Handling, Pipeline, and more.

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy URL (default: `sqlite:///invoice_chaser.db`) |
| `OLLAMA_API_URL`, `OLLAMA_MODEL` | Ollama endpoint and model |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Twilio SMS/voice |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Email sending |
| `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD` | Optional inbound email |
| `MIN_DAYS_BETWEEN_CONTACT` | Skip send if last contact within N days (default 3) |
| `REPORT_DIR` | Analytics output (default `reports`) |

## Project Layout

- `db/` – Models, database, seed data
- `agents/` – Invoice monitor, message generator, dispatcher, response handler, analytics reporter
- `config/` – `escalation_rules.yaml`
- `web/` – Flask app (webhooks, REST API)
- `orchestrator.py` – APScheduler entrypoint
- `dashboard.py` – Streamlit test dashboard
- `run_demo.py` – One-shot demo

## Escalation Levels

| Level | Days overdue | Tone |
|-------|--------------|------|
| 1 | 1–7 | Friendly reminder |
| 2 | 8–14 | Firm |
| 3 | 15+ | Urgent / final notice |

Rules are configurable in `config/escalation_rules.yaml`.

## Team Members

| Name | Role |
|------|------|
| *[Add team member names and roles]* | |

---

*This project uses third-party open-source libraries and APIs as documented above. All credentials are managed via environment variables and are not hardcoded in the codebase.*
