"""Response Handler Agent: processes inbound email (and optional SMS), classifies intent via LLM, updates DB.

- Inbound email: match by From address to Client (normalized), classify intent, store Response, update Invoice (pay -> paid).
- IMAP poll: fetch unseen from Gmail (IMAP_* env), process each with process_inbound_email.
- Dashboard can trigger poll or submit manual email for processing.
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, Tuple
import urllib.request

from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from db.database import get_session
from db.models import (
    Client,
    Communication,
    Invoice,
    InvoiceStatus,
    Response,
    ResponseIntent,
)

load_dotenv()


class ClassifierResult(BaseModel):
    intent: str
    confidence: float


OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
# Only mark invoice as paid when intent is "pay" and confidence >= this (avoid false positives)
MIN_CONFIDENCE_MARK_PAID = float(os.getenv("MIN_CONFIDENCE_MARK_PAID", "0.7"))


def _normalize_email(addr: str) -> str:
    """Lowercase and strip; extract first address if angle-bracket form."""
    if not addr or not isinstance(addr, str):
        return ""
    s = addr.strip().lower()
    m = re.search(r"[\w._%+-]+@[\w.-]+\.[a-z]{2,}", s)
    return m.group(0) if m else s


def _ollama_generate(prompt: str) -> str:
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
    with urllib.request.urlopen(req, timeout=60) as resp:  # pragma: no cover - I/O
        obj = json.loads(resp.read().decode("utf-8"))
    text = obj.get("response", "")
    if not isinstance(text, str):
        raise ValueError("Invalid response field from Ollama")
    return text


# Phrases that mean the customer is refusing or will not pay (never mark as paid)
REFUSAL_PHRASES = (
    "won't pay", "will not pay", "wont pay", "refuse to pay", "refusing to pay",
    "cannot pay", "can't pay", "cant pay", "don't pay", "do not pay", "dont pay",
    "never pay", "not paying", "not going to pay", "refuse payment", "refusing payment",
    "won’t pay", "can’t pay", "don’t pay", "wouldn't pay", "would not pay",
)

# Phrases that strongly indicate the customer has already paid (not just a promise)
PAID_CONFIRMATION_PHRASES = (
    "i have paid",
    "i've paid",
    "we have paid",
    "we've paid",
    "already paid",
    "payment made",
    "payment has been made",
    "have just paid",
    "just paid",
    "paid this invoice",
    "paid the invoice",
    "we paid",
    "i paid",
)


def _message_indicates_refusal(text: str) -> bool:
    """True if the message clearly indicates refusal to pay (safety check)."""
    if not text:
        return False
    lower = text.strip().lower()
    return any(phrase in lower for phrase in REFUSAL_PHRASES)


def _message_indicates_already_paid(text: str) -> bool:
    """True if the message clearly indicates payment has already been made."""
    if not text:
        return False
    lower = text.strip().lower()
    return any(phrase in lower for phrase in PAID_CONFIRMATION_PHRASES)


def _generate_dispute_auto_reply(
    channel: str,
    invoice: Optional[Invoice],
    client: Optional[Client],
    original_text: str,
) -> tuple[str, Optional[str]]:
    """
    Use the LLM (Ollama) to generate a negotiation-style reply for disputes.

    Returns (body, subject). Subject is only used for email channel.
    """
    # Basic invoice context for grounding
    inv_id = getattr(invoice, "id", None)
    amount = getattr(invoice, "amount", None)
    currency = getattr(invoice, "currency", "USD") if invoice else "USD"
    days_overdue = getattr(invoice, "days_overdue", None)
    client_name = getattr(client, "name", "") if client else ""

    base_context = []
    if inv_id is not None:
        base_context.append(f"Invoice ID: {inv_id}")
    if amount is not None:
        base_context.append(f"Amount: {amount:.2f} {currency}")
    if days_overdue is not None:
        base_context.append(f"Days overdue: {days_overdue}")
    if client_name:
        base_context.append(f"Customer name: {client_name}")
    context_text = "\n".join(base_context) if base_context else "No structured invoice context."

    if channel == "sms":
        style = (
            "Compose a single SMS message under 160 characters. "
            "Be concise, empathetic, and clearly offer or reference a payment plan."
        )
    else:
        style = (
            "Compose a short, professional email body (no subject line) that:\n"
            "- Acknowledges the customer's dispute or inability to pay in full\n"
            "- Proposes 2-3 clear payment plan options (e.g. 3 monthly installments, 50% now / 50% next month)\n"
            "- Briefly explains what the invoice is for in plain language\n"
            "- Invites the customer to choose an option or suggest another plan\n"
        )

    prompt = (
        "You are an accounts receivable assistant for a small business.\n\n"
        "The customer has disputed an invoice or said they cannot pay in full. "
        "You must respond in a way that keeps the relationship positive while trying to secure payment.\n\n"
        f"{style}\n\n"
        "Invoice context:\n"
        f"{context_text}\n\n"
        "Customer message:\n"
        f"{original_text.strip()}\n\n"
        "Return only the reply text; do not include any explanations or commentary."
    )

    try:
        raw = _ollama_generate(prompt).strip()
    except Exception:
        # Fallback static templates
        if channel == "sms":
            body = (
                "We understand you can't pay in full. "
                "We can offer a payment plan. Reply to discuss options."
            )
            return body[:160], None
        else:
            body = (
                "We understand that paying the full amount right now may be difficult.\n\n"
                "We can offer flexible options, such as:\n"
                "- Splitting the balance into 3 equal monthly payments\n"
                "- Paying 50% now and 50% next month\n"
                "- Setting specific dates that work better for your cash flow\n\n"
                "Please let us know which option works best for you, or suggest an alternative.\n\n"
                "Best regards,\nAccounts Receivable"
            )
            return body, None

    if channel == "sms":
        return raw.replace("\n", " ")[:160], None
    return raw, None


def classify_intent(text: str) -> Tuple[str, float]:
    """Classify message intent. Returns (intent, confidence)."""
    if not text or not text.strip():
        return ResponseIntent.UNKNOWN.value, 0.0
    try:
        raw = _ollama_generate(
            "Classify the following customer message into exactly one intent.\n\n"
            "pay: customer CONFIRMS they have already paid, or clearly PROMISES to pay (e.g. 'I paid', 'we will pay by Friday'). "
            "Do NOT use pay for: refusal, 'won't pay', 'can't pay', 'will not pay', or any negative statement about paying.\n"
            "dispute: disagreement, complaint, refusal to pay, questioning the invoice, or saying they won't/can't pay.\n"
            "ignore: spam, irrelevant, or unclear.\n\n"
            "Reply with JSON only: "
            '{"intent": "pay"|"dispute"|"ignore", "confidence": 0.0-1.0}\n\n'
            f"Message:\n{text.strip()}"
        )
        data = json.loads(raw)
        intent = data.get("intent", ResponseIntent.UNKNOWN.value)
        confidence = float(data.get("confidence", 0.0))
        if intent not in ("pay", "dispute", "ignore"):
            intent = ResponseIntent.UNKNOWN.value
        # Refusal phrases ("won't pay", etc.) → always dispute, regardless of LLM
        if _message_indicates_refusal(text):
            intent = ResponseIntent.DISPUTE.value
            confidence = max(confidence, 0.8)
        return intent, confidence
    except Exception:  # pragma: no cover - malformed JSON / network
        pass
    # Fallback when Ollama unavailable: simple keyword match for demo
    lower = text.strip().lower()
    if any(p in lower for p in ("i'll pay", "i will pay", "we'll pay", "will pay", "pay by friday", "pay next week", "i've paid", "already paid", "payment made")):
        return ResponseIntent.PAY.value, 0.85
    if any(p in lower for p in ("won't pay", "wont pay", "dispute", "refuse", "can't pay")):
        return ResponseIntent.DISPUTE.value, 0.8
    return ResponseIntent.UNKNOWN.value, 0.0


def _find_client_by_phone(session, phone: str) -> Optional[Client]:
    normalized = phone.strip().replace(" ", "")
    stmt = select(Client).where(Client.phone.isnot(None))
    for c in session.scalars(stmt).all():
        if c.phone and c.phone.replace(" ", "") == normalized:
            return c
    return None


def _find_recent_invoice_for_client(session, client_id: int) -> Optional[Invoice]:
    """Find most recent overdue or promise-to-pay invoice for client (so 'I've paid' can update it)."""
    stmt = (
        select(Invoice)
        .where(
            Invoice.client_id == client_id,
            Invoice.status.in_([InvoiceStatus.OVERDUE.value, InvoiceStatus.PROMISE_TO_PAY.value]),
        )
        .order_by(Invoice.updated_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def process_inbound_sms(from_phone: str, body: str, external_id: Optional[str] = None) -> None:
    """
    Handle inbound SMS: STOP -> opt-out; else classify, store in responses, optionally update invoice.
    """
    body_clean = (body or "").strip().upper()
    if body_clean == "STOP" or body_clean == "STOPALL" or body_clean == "UNSUBSCRIBE":
        with get_session() as session:
            client = _find_client_by_phone(session, from_phone)
            if client:
                client.opted_out = True
                client.opted_out_at = datetime.utcnow()
        return

    with get_session() as session:
        client = _find_client_by_phone(session, from_phone)
        invoice = _find_recent_invoice_for_client(session, client.id) if client else None
        intent, confidence = classify_intent(body or "")
        already_paid = _message_indicates_already_paid(body or "")

        resp = Response(
            communication_id=None,
            external_id=external_id,
            raw_content=body or "",
            intent=intent,
            intent_confidence=confidence,
            processed_at=datetime.utcnow(),
        )
        session.add(resp)
        session.flush()

        if (
            intent == ResponseIntent.PAY.value
            and invoice
            and confidence >= MIN_CONFIDENCE_MARK_PAID
        ):
            if already_paid:
                invoice.status = InvoiceStatus.PAID.value
            else:
                invoice.status = InvoiceStatus.PROMISE_TO_PAY.value

        # Auto-replies for key intents (SMS)
        if invoice and intent == ResponseIntent.PAY.value and confidence >= MIN_CONFIDENCE_MARK_PAID:
            if already_paid:
                auto_body = (
                    "Thank you for your payment. If this was sent in error, please contact us."
                )
                resp.action_taken = "marked_paid_auto_replied_thank_you"
            else:
                auto_body = (
                    "Thanks for confirming you'll pay. Please use the payment link in our message to complete payment."
                )
                resp.action_taken = "marked_promise_to_pay_auto_replied_acknowledge_promise"
            auto_comm = Communication(
                invoice_id=invoice.id,
                channel="sms",
                direction="outbound",
                body=auto_body[:160],
                subject=None,
                escalation_level=invoice.escalation_level,
                sent_at=None,
            )
            session.add(auto_comm)
        elif invoice and intent == ResponseIntent.DISPUTE.value:
            auto_body, _ = _generate_dispute_auto_reply(
                channel="sms",
                invoice=invoice,
                client=client,
                original_text=body or "",
            )
            if auto_body:
                auto_comm = Communication(
                    invoice_id=invoice.id,
                    channel="sms",
                    direction="outbound",
                    body=auto_body,
                    subject=None,
                    escalation_level=invoice.escalation_level,
                    sent_at=None,
                )
                session.add(auto_comm)
                resp.action_taken = "auto_replied_payment_plan_offer"


def _find_client_by_email(session, from_addr: str) -> Optional[Client]:
    """Find client by normalized email (exact match after normalize)."""
    norm = _normalize_email(from_addr)
    if not norm:
        return None
    for c in session.scalars(select(Client).where(Client.email.isnot(None))).all():
        if c.email and _normalize_email(c.email) == norm:
            return c
    return None


def process_inbound_email(
    from_addr: str, subject: str, body: str, external_id: Optional[str] = None
) -> None:
    """Classify inbound email, store Response, update invoice if intent=pay (match client by From)."""
    with get_session() as session:
        client = _find_client_by_email(session, from_addr)
        invoice = _find_recent_invoice_for_client(session, client.id) if (client and client.id) else None
        combined_text = f"{subject or ''}\n{body or ''}"
        intent, confidence = classify_intent(combined_text)
        already_paid = _message_indicates_already_paid(combined_text)

        resp = Response(
            communication_id=None,
            external_id=external_id,
            raw_content=f"Subject: {subject}\n\n{body}",
            intent=intent,
            intent_confidence=confidence,
            processed_at=datetime.utcnow(),
        )
        session.add(resp)
        session.flush()
        if (
            intent == ResponseIntent.PAY.value
            and invoice
            and confidence >= MIN_CONFIDENCE_MARK_PAID
        ):
            if already_paid:
                invoice.status = InvoiceStatus.PAID.value
            else:
                invoice.status = InvoiceStatus.PROMISE_TO_PAY.value

        # Auto-replies for key intents (Email)
        if invoice and intent == ResponseIntent.PAY.value and confidence >= MIN_CONFIDENCE_MARK_PAID:
            if already_paid:
                body_text = (
                    "Dear {},\n\n"
                    "Thank you for your payment. If you believe this message is in error, please reply and let us know.\n\n"
                    "Best regards,\nAccounts Receivable"
                ).format(client.name if client and client.name else "customer")
                resp.action_taken = "marked_paid_auto_replied_thank_you"
            else:
                body_text = (
                    "Dear {},\n\n"
                    "Thank you for confirming that you will pay this invoice. "
                    "Please use the payment link in the reminder we sent to complete the payment.\n\n"
                    "Best regards,\nAccounts Receivable"
                ).format(client.name if client and client.name else "customer")
                resp.action_taken = "marked_promise_to_pay_auto_replied_acknowledge_promise"
            auto_comm = Communication(
                invoice_id=invoice.id,
                channel="email",
                direction="outbound",
                body=body_text,
                subject=f"Re: Invoice {invoice.id} payment confirmation",
                escalation_level=invoice.escalation_level,
                sent_at=None,
            )
            session.add(auto_comm)
        elif invoice and intent == ResponseIntent.DISPUTE.value:
            auto_body, auto_subject = _generate_dispute_auto_reply(
                channel="email",
                invoice=invoice,
                client=client,
                original_text=combined_text,
            )
            if auto_body:
                auto_comm = Communication(
                    invoice_id=invoice.id,
                    channel="email",
                    direction="outbound",
                    body=auto_body,
                    subject=auto_subject or f"Re: Invoice {invoice.id}",
                    escalation_level=invoice.escalation_level,
                    sent_at=None,
                )
                session.add(auto_comm)
                resp.action_taken = "auto_replied_payment_plan_offer"


def process_pending_responses() -> int:
    """
    Poll IMAP (Gmail: imap.gmail.com) for UNSEEN emails, process each with process_inbound_email.
    Requires IMAP_HOST, IMAP_USER, IMAP_PASSWORD in env. Returns number of emails processed.
    """
    import email
    from email import policy

    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")
    if not user or not password:
        return 0
    processed = 0
    try:
        from imapclient import IMAPClient
        with IMAPClient(host, use_uid=True) as imap:
            imap.login(user, password)
            imap.select_folder("INBOX")
            ids = imap.search("UNSEEN")
            for uid in ids:
                data = imap.fetch(uid, ["BODY[]"])
                if uid not in data:
                    continue
                msg = data[uid]
                raw = msg.get(b"BODY[]")
                if raw is None:
                    continue
                body_bytes = raw if isinstance(raw, bytes) else raw.encode()
                try:
                    parsed = email.message_from_bytes(body_bytes, policy=policy.default)
                    from_addr = (parsed.get("From") or "").strip()
                    subject = (parsed.get("Subject") or "").strip()
                    body_str = ""
                    if parsed.is_multipart():
                        for part in parsed.walk():
                            if part.get_content_type() == "text/plain":
                                body_str = part.get_content() or ""
                                if isinstance(body_str, bytes):
                                    body_str = body_str.decode("utf-8", errors="replace")
                                break
                    else:
                        body_str = parsed.get_content() or ""
                        if isinstance(body_str, bytes):
                            body_str = body_str.decode("utf-8", errors="replace")
                    if not body_str:
                        body_str = str(parsed)
                except Exception:
                    body_str = body_bytes.decode("utf-8", errors="replace")
                    from_addr = ""
                    subject = ""
                process_inbound_email(from_addr, subject, body_str, external_id=f"imap-{uid}")
                processed += 1
    except Exception:
        pass
    return processed
