"""Message Generator Agent: creates personalized escalation messages via LLM; reads/writes shared DB."""

from datetime import date
from typing import Literal, Optional
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from db.database import get_session
from db.models import (
    Client,
    Communication,
    ContactPreference,
    Invoice as DBInvoice,
    InvoiceStatus,
)

load_dotenv()


# Pydantic models for LLM I/O (distinct from db.models.Invoice)
class InvoiceInput(BaseModel):
    invoice_id: str
    client_name: str
    amount: float
    currency: str
    due_date: date
    days_overdue: int
    level: int
    channel: Literal["email", "sms"]
    additional_context: Optional[str] = None


class EscalationMessage(BaseModel):
    invoice_id: str
    level: int
    channel: Literal["email", "sms"]
    subject: Optional[str] = None
    body: str
    source: Literal["template", "llm"] = "llm"  # For dashboard Template vs LLM toggle


OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")


def _ollama_generate(prompt: str) -> str:
    """
    Call local Ollama REST API and return the generated text.
    Uses /api/generate with stream=false and the configured model.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_body = resp.read().decode("utf-8")
        obj = json.loads(resp_body)
        text = obj.get("response", "")
        if not isinstance(text, str):
            raise ValueError("Invalid response field from Ollama")
        return text
    except Exception as exc:  # pragma: no cover - network / env issues
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _payment_links_for_invoice(invoice: InvoiceInput, channel: Literal["email", "sms"]) -> str:
    """
    Build mock payment links to append to all messages.

    These are non-functional placeholder URLs that demonstrate where a real
    payment link would go in production.
    """
    pay_url = f"https://pay.example.com/invoice/{invoice.invoice_id}"
    portal_url = f"https://portal.example.com/invoices/{invoice.invoice_id}"
    if channel == "sms":
        # Keep very short for SMS; dispatcher will still truncate to 160 chars overall.
        return f" Pay: {pay_url}"
    # Email: multi-line with a small call to action.
    return (
        f"\n\nYou can pay securely online here:\n{pay_url}\n\n"
        f"To review your statement, visit:\n{portal_url}\n"
    )


def _render_template(invoice: InvoiceInput) -> EscalationMessage:
    """Static fallback templates when LLM is unavailable or fails."""
    level = invoice.level
    if invoice.channel == "sms":
        if level >= 3:
            body = (
                f"URGENT: Invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"is {invoice.days_overdue} days overdue. Please pay immediately or contact us to discuss."
            )
        elif level == 2:
            body = (
                f"Reminder: Invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"is overdue by {invoice.days_overdue} days. Please make payment soon."
            )
        else:
            body = (
                f"Hi {invoice.client_name}, invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"was due on {invoice.due_date}. Please pay at your earliest convenience."
            )
        body = (body + _payment_links_for_invoice(invoice, "sms"))[:160]
        subject: Optional[str] = None
    else:
        if level >= 3:
            subject = f"Urgent final notice – invoice {invoice.invoice_id} overdue"
            body = (
                f"Dear {invoice.client_name},\n\n"
                f"Our records show that invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"remains unpaid and is now {invoice.days_overdue} days past due (due date: {invoice.due_date}).\n\n"
                "This is an urgent reminder. Please make payment immediately or contact us to discuss a payment plan.\n\n"
                "If you have already arranged payment, please disregard this message and let us know.\n\n"
                "Best regards,\nAccounts Receivable"
            )
        elif level == 2:
            subject = f"Second reminder – invoice {invoice.invoice_id} overdue"
            body = (
                f"Dear {invoice.client_name},\n\n"
                f"This is a friendly reminder that invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"was due on {invoice.due_date} and is now {invoice.days_overdue} days overdue.\n\n"
                "Please arrange payment soon or contact us if there is an issue with this invoice.\n\n"
                "Best regards,\nAccounts Receivable"
            )
        else:
            subject = f"Reminder – invoice {invoice.invoice_id} due"
            body = (
                f"Dear {invoice.client_name},\n\n"
                f"We wanted to remind you that invoice {invoice.invoice_id} for {invoice.amount:.2f} {invoice.currency} "
                f"was due on {invoice.due_date} and appears outstanding.\n\n"
                "If you have already paid, thank you and please ignore this notice. Otherwise, please make payment at your earliest convenience.\n\n"
                "Best regards,\nAccounts Receivable"
            )
    if invoice.channel == "email":
        body = body + _payment_links_for_invoice(invoice, "email")
    return EscalationMessage(
        invoice_id=invoice.invoice_id,
        level=invoice.level,
        channel=invoice.channel,
        subject=subject,
        body=body,
        source="template",
    )


def generate_escalation_message(invoice: InvoiceInput) -> EscalationMessage:
    """Generate a personalized escalation message for the given invoice (LLM call)."""
    channel_description = (
        "SMS message under 160 characters"
        if invoice.channel == "sms"
        else "professional email"
    )
    prompt = (
        f"Generate a {channel_description} for client {invoice.client_name} "
        f"about overdue invoice {invoice.invoice_id}.\n"
        f"Amount: {invoice.amount} {invoice.currency}.\n"
        f"Due date: {invoice.due_date}.\n"
        f"Days overdue: {invoice.days_overdue}.\n"
        f"Escalation level: {invoice.level}.\n"
    )
    if invoice.additional_context:
        prompt += f"Additional context: {invoice.additional_context}\n"
    prompt += (
        "Use the appropriate tone for the escalation level as described above. "
        "Assume that the message will include an online payment link at the end, and encourage the customer to use it to pay securely. "
        "Return only the message text; do not include any explanations or metadata."
    )

    try:
        raw = _ollama_generate(prompt).strip()
    except RuntimeError:
        # Fallback to static templates if LLM is unavailable or fails
        return _render_template(invoice)

    if invoice.channel == "sms":
        body = raw.replace("\n", " ")
        body = (body + _payment_links_for_invoice(invoice, "sms"))[:160]
        subject: Optional[str] = None
    else:
        body = raw + _payment_links_for_invoice(invoice, "email")
        subject = None

    return EscalationMessage(
        invoice_id=invoice.invoice_id,
        level=invoice.level,
        channel=invoice.channel,
        subject=subject,
        body=body,
        source="llm",
    )


def _channels_for_client(client: Client) -> list[Literal["email", "sms"]]:
    pref = client.contact_preference or ContactPreference.BOTH.value
    if pref == ContactPreference.EMAIL.value:
        return ["email"]
    if pref == ContactPreference.SMS.value:
        return ["sms"]
    return ["email", "sms"]


def run_message_generator(invoice_ids: Optional[list[int]] = None) -> int:
    """
    Load overdue invoices from DB (or by ids), generate email/SMS per client preference,
    write rows to communications (direction=outbound, sent_at=NULL).
    Returns number of communications created.
    """
    with get_session() as session:
        stmt = (
            select(DBInvoice)
            .options(joinedload(DBInvoice.client))
            .where(
                DBInvoice.status == InvoiceStatus.OVERDUE.value,
                DBInvoice.human_override.is_(False),
                DBInvoice.escalation_level.isnot(None),
            )
        )
        if invoice_ids is not None:
            stmt = stmt.where(DBInvoice.id.in_(invoice_ids))
        invoices = list(session.scalars(stmt).unique().all())

        created = 0
        for inv in invoices:
            client = inv.client
            if client.opted_out:
                continue
            channels = _channels_for_client(client)
            for ch in channels:
                payload = InvoiceInput(
                    invoice_id=str(inv.id),
                    client_name=client.name,
                    amount=inv.amount,
                    currency=inv.currency,
                    due_date=inv.due_date,
                    days_overdue=inv.days_overdue,
                    level=inv.escalation_level or 1,
                    channel=ch,
                )
                try:
                    msg = generate_escalation_message(payload)
                    if not isinstance(msg, EscalationMessage):
                        continue
                except Exception:
                    continue
                import json
                meta = {"source": msg.source, "template_preview": _render_template(payload).body[:300]}
                comm = Communication(
                    invoice_id=inv.id,
                    channel=msg.channel,
                    direction="outbound",
                    body=msg.body,
                    subject=msg.subject,
                    escalation_level=msg.level,
                    sent_at=None,
                    metadata_json=json.dumps(meta),
                )
                session.add(comm)
                created += 1
        return created
