"""Communication Dispatcher Agent: sends outbound email via SMTP only (Gmail)."""

import os
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from db.database import get_session
from db.models import Client, Communication, Invoice

load_dotenv()

# Config
MIN_DAYS_BETWEEN_CONTACT = int(os.getenv("MIN_DAYS_BETWEEN_CONTACT", "3"))
RATE_LIMIT_SECONDS = float(os.getenv("DISPATCH_RATE_LIMIT_SECONDS", "1.0"))

# SMTP only (Gmail: smtp.gmail.com:587, STARTTLS, app password)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").lower() in ("1", "true", "yes")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@localhost"))

# Twilio (optional; used for level-3 escalation calls)
TWILIO_ACCOUNT_SID = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
TWILIO_FROM_NUMBER = (os.getenv("TWILIO_FROM_NUMBER") or "").strip()
ESCALATION_CALL_TO = (os.getenv("ESCALATION_CALL_TO") or "8019213363").strip()
TWILIO_VOICE_TWIML_BASE_URL = (os.getenv("TWILIO_VOICE_TWIML_BASE_URL") or "").rstrip("/")


def _last_sent_at_for_invoice(session, invoice_id: int) -> Optional[datetime]:
    """Return most recent sent_at for this invoice's outbound communications."""
    stmt = (
        select(Communication.sent_at)
        .where(
            Communication.invoice_id == invoice_id,
            Communication.direction == "outbound",
            Communication.sent_at.isnot(None),
        )
        .order_by(Communication.sent_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def _should_skip_recent_contact(session, invoice_id: int) -> bool:
    last = _last_sent_at_for_invoice(session, invoice_id)
    if last is None:
        return False
    return (datetime.utcnow() - last.replace(tzinfo=None)).days < MIN_DAYS_BETWEEN_CONTACT


def _send_email(to: str, subject: str, body: str) -> Optional[str]:
    """Send email via SMTP (Gmail-ready: STARTTLS on 587). Returns message-id or None."""
    if not SMTP_USER or not SMTP_PASSWORD:
        return None
    try:
        msg = MIMEMultipart()
        msg["Subject"] = subject or "Invoice reminder"
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        return f"<sent-{datetime.utcnow().isoformat()}@invoice-chaser>"
    except Exception:
        return None


def _send_level3_call(comm: Communication) -> None:
    """Best-effort Twilio voice call when escalation_level == 3."""
    if comm.escalation_level != 3:
        return
    if not (
        TWILIO_ACCOUNT_SID
        and TWILIO_AUTH_TOKEN
        and TWILIO_FROM_NUMBER
        and ESCALATION_CALL_TO
        and TWILIO_VOICE_TWIML_BASE_URL
    ):
        return
    try:
        from twilio.rest import Client as TwilioClient  # type: ignore[import]
    except Exception:
        return
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        twiml_url = f"{TWILIO_VOICE_TWIML_BASE_URL}/twilio/voice/escalation?communication_id={comm.id}"
        call = client.calls.create(
            url=twiml_url,
            to=ESCALATION_CALL_TO,
            from_=TWILIO_FROM_NUMBER,
        )
        # Store Twilio call SID on the communication for diagnostics.
        comm.twilio_sid = getattr(call, "sid", None)
    except Exception:
        # Ignore call failures so email still goes out.
        return


def send_selected_communications(communication_ids: List[int]) -> int:
    """
    Send only the given outbound communications (by id) via SMTP.
    Skips if client has no email or is opted out. Returns count sent.
    """
    if not communication_ids:
        return 0
    sent = 0
    with get_session() as session:
        stmt = (
            select(Communication)
            .options(
                joinedload(Communication.invoice).joinedload(Invoice.client),
            )
            .where(
                Communication.id.in_(communication_ids),
                Communication.direction == "outbound",
                Communication.sent_at.is_(None),
            )
        )
        pending = list(session.scalars(stmt).unique().all())

        for comm in pending:
            inv = comm.invoice
            client: Client = inv.client
            if client.opted_out or not client.email:
                continue
            mid = _send_email(
                client.email,
                comm.subject or "Invoice reminder",
                comm.body,
            )
            if mid is not None:
                comm.sent_at = datetime.utcnow()
                comm.message_id = mid
                _send_level3_call(comm)
                sent += 1
            time.sleep(RATE_LIMIT_SECONDS)
    return sent


def run_communication_dispatcher() -> int:
    """
    Load all outbound communications with sent_at=NULL (email only),
    respect client opted_out and 3-day rule, send via SMTP. Returns number sent.
    """
    sent = 0
    with get_session() as session:
        stmt = (
            select(Communication)
            .options(
                joinedload(Communication.invoice).joinedload(Invoice.client),
            )
            .where(
                Communication.direction == "outbound",
                Communication.sent_at.is_(None),
                Communication.channel == "email",
            )
        )
        pending = list(session.scalars(stmt).unique().all())

        for comm in pending:
            inv = comm.invoice
            client: Client = inv.client
            if client.opted_out or not client.email:
                continue
            if _should_skip_recent_contact(session, comm.invoice_id):
                continue
            mid = _send_email(
                client.email,
                comm.subject or "Invoice reminder",
                comm.body,
            )
            if mid is not None:
                comm.sent_at = datetime.utcnow()
                comm.message_id = mid
                _send_level3_call(comm)
                sent += 1
            time.sleep(RATE_LIMIT_SECONDS)
    return sent
