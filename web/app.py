"""Minimal Flask app for Twilio SMS webhook, health check, and Clients API."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request

# Ensure project root on path when running from web/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.response_handler import process_inbound_email, process_inbound_sms

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@app.route("/webhook/sms", methods=["POST"])
def twilio_sms_webhook():
    """
    Twilio inbound SMS webhook.
    Expects form fields: From, Body; optional MessageSid.
    """
    from_phone = request.form.get("From", "").strip()
    body = request.form.get("Body", "")
    message_sid = request.form.get("MessageSid", "").strip()
    if not from_phone:
        return "", 400
    process_inbound_sms(from_phone, body, external_id=message_sid or None)
    return "", 200


@app.route("/twilio/voice/escalation", methods=["GET", "POST"])
def twilio_voice_escalation():
    """
    Twilio Voice webhook for level-3 escalation calls.
    Reads back a customized message about the specific invoice/communication.
    """
    from sqlalchemy import select
    from xml.sax.saxutils import escape as xml_escape
    from db.database import get_session
    from db.models import Client, Communication, Invoice

    comm_id = request.values.get("communication_id", type=int)
    with get_session() as session:
        comm = session.get(Communication, comm_id) if comm_id else None
        if not comm:
            text = (
                "Hello. This is an automated call from Accounts Receivable about an overdue invoice. "
                "Please check your email for details or contact us to discuss your account."
            )
        else:
            inv = session.get(Invoice, comm.invoice_id)
            client = session.get(Client, inv.client_id) if inv else None
            name = (client.name if client and client.name else "customer")
            amount = getattr(inv, "amount", None)
            currency = getattr(inv, "currency", "USD") if inv else "USD"
            days_overdue = getattr(inv, "days_overdue", None)
            parts = [f"Hello {name}. This is an urgent call about your overdue invoice."]
            if amount is not None:
                parts.append(f"The amount due is {amount:.2f} {currency}.")
            if days_overdue is not None:
                parts.append(f"The invoice is {days_overdue} days past the due date.")
            # Prefer the LLM-generated escalation body if available as additional context.
            if comm.body:
                parts.append("Here is a summary of your notice:")
                parts.append(comm.body)
            parts.append("Please make payment as soon as possible or contact us to discuss options.")
            text = " ".join(parts)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say voice=\"alice\">{xml_escape(text)}</Say>"
        "</Response>"
    )
    return Response(xml, mimetype="text/xml")


# ----- Clients API -----

def _client_to_json(client, invoice_stats=None, last_contact=None):
    """Serialize Client to dict with optional stats."""
    out = {
        "id": client.id,
        "name": client.name,
        "email": client.email or "",
        "phone": client.phone or "",
        "contact_preference": client.contact_preference or "both",
        "opted_out": client.opted_out,
        "opted_out_at": (client.opted_out_at.isoformat() if client.opted_out_at else None),
    }
    if invoice_stats is not None:
        out["invoice_count"] = invoice_stats.get("total", 0)
        out["paid_count"] = invoice_stats.get("paid", 0)
        out["paid_pct"] = invoice_stats.get("paid_pct")
    out["last_contact"] = last_contact
    return out


def _get_client_invoice_stats(session, client_id):
    from sqlalchemy import func, select
    from db.models import Invoice, InvoiceStatus
    total = session.scalar(select(func.count(Invoice.id)).where(Invoice.client_id == client_id)) or 0
    paid = session.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.client_id == client_id,
            Invoice.status == InvoiceStatus.PAID.value,
        )
    ) or 0
    paid_pct = round(100 * paid / total, 1) if total else 0
    return {"total": total, "paid": paid, "paid_pct": paid_pct}


def _get_client_last_contact(session, client_id):
    from sqlalchemy import select
    from db.models import Communication, Invoice
    stmt = (
        select(Communication)
        .join(Invoice, Communication.invoice_id == Invoice.id)
        .where(Invoice.client_id == client_id)
        .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc())
        .limit(1)
    )
    comm = session.scalar(stmt)
    if not comm:
        return None
    ts = comm.sent_at or comm.created_at
    return {
        "channel": comm.channel.upper(),
        "at": ts.isoformat() if ts else None,
        "preview": (comm.body or "")[:50] + ("..." if len(comm.body or "") > 50 else ""),
    }


@app.route("/api/clients", methods=["GET"])
def list_clients():
    """List clients with optional search (name, phone, email)."""
    from sqlalchemy import or_, select
    from db.database import get_session
    from db.models import Client
    q = request.args.get("q", "").strip()
    with get_session() as session:
        stmt = select(Client).order_by(Client.id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Client.name.ilike(like),
                    Client.phone.ilike(like),
                    Client.email.ilike(like),
                )
            )
        clients = session.scalars(stmt).all()
        result = []
        for c in clients:
            stats = _get_client_invoice_stats(session, c.id)
            last = _get_client_last_contact(session, c.id)
            result.append(_client_to_json(c, invoice_stats=stats, last_contact=last))
        return {"clients": result}, 200


@app.route("/api/clients", methods=["POST"])
def create_client():
    """Create a new client."""
    from db.database import get_session
    from db.models import Client, ContactPreference
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}, 400
    email = (data.get("email") or "").strip() or None
    phone = (data.get("phone") or "").strip() or None
    contact_preference = (data.get("contact_preference") or "both").strip().lower()
    if contact_preference not in ("email", "sms", "both"):
        contact_preference = "both"
    with get_session() as session:
        client = Client(
            name=name,
            email=email,
            phone=phone,
            contact_preference=contact_preference,
        )
        session.add(client)
        session.flush()
        out = _client_to_json(client)
        return out, 201


@app.route("/api/clients/<int:client_id>", methods=["GET"])
def get_client(client_id):
    """Get one client with invoice stats and last contact."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice

    include_current = bool(request.args.get("include_current_invoice"))
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        stats = _get_client_invoice_stats(session, client_id)
        last = _get_client_last_contact(session, client_id)
        payload = _client_to_json(client, invoice_stats=stats, last_contact=last)
        if include_current:
            # choose most relevant invoice: overdue with highest days_overdue, else most recent by due_date
            stmt = (
                select(Invoice)
                .where(Invoice.client_id == client_id)
                .order_by(
                    (Invoice.status == "overdue").desc(),
                    Invoice.days_overdue.desc(),
                    Invoice.due_date.desc(),
                )
                .limit(1)
            )
            inv = session.scalar(stmt)
            if inv:
                payload["current_invoice"] = _invoice_to_json(inv, client_name=client.name)
            else:
                payload["current_invoice"] = None
        return payload, 200


@app.route("/api/clients/<int:client_id>/journey", methods=["GET"])
def get_client_journey(client_id: int):
    """
    Aggregate journey payload for a single client:
    - client summary (with current_invoice when available)
    - communications timeline (same as /api/clients/<id>/communications)
    """
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Communication, Invoice, Response

    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404

        stats = _get_client_invoice_stats(session, client_id)
        last = _get_client_last_contact(session, client_id)
        client_payload = _client_to_json(client, invoice_stats=stats, last_contact=last)

        # current invoice using same ordering as in get_client (include_current branch)
        stmt_inv = (
            select(Invoice)
            .where(Invoice.client_id == client_id)
            .order_by(
                (Invoice.status == "overdue").desc(),
                Invoice.days_overdue.desc(),
                Invoice.due_date.desc(),
            )
            .limit(1)
        )
        inv = session.scalar(stmt_inv)
        if inv:
            client_payload["current_invoice"] = _invoice_to_json(inv, client_name=client.name)
        else:
            client_payload["current_invoice"] = None

        # communications timeline (similar to list_client_communications)
        stmt_comm = (
            select(Communication, Response.raw_content.label("response_content"), Response.intent, Response.processed_at)
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .outerjoin(Response, Response.communication_id == Communication.id)
            .where(Invoice.client_id == client_id)
            .order_by(
                Communication.sent_at.desc().nullslast(),
                Communication.created_at.desc(),
                Response.processed_at.desc().nullslast(),
            )
        )
        rows = session.execute(stmt_comm).all()
        seen = set()
        comms = []
        for row in rows:
            comm, resp_content, intent, processed_at = row
            if comm.id in seen:
                continue
            seen.add(comm.id)
            ts = comm.sent_at or comm.created_at
            date_str = f"{ts.month}/{ts.day}" if ts else "—"
            comms.append(
                {
                    "id": comm.id,
                    "date": date_str,
                    "level": f"L{comm.escalation_level}" if comm.escalation_level is not None else "—",
                    "channel": (comm.channel or "").upper(),
                    "response": (resp_content or "")[:80] if resp_content else (comm.body or "")[:80],
                    "status": "Done" if (processed_at or intent) else "Pending",
                }
            )

    # simple expected collection & recommendation based on current invoice status
    def expected_collection_pct(status: str | None) -> int:
        if not status:
            return 0
        s = status.lower()
        if s == "paid":
            return 100
        if s == "promise_to_pay":
            return 85
        if s == "pending":
            return 70
        if s == "overdue":
            return 45
        return 50

    cur = client_payload.get("current_invoice")
    status = (cur or {}).get("status")
    pct = expected_collection_pct(status)
    if status is None:
        recommendation = "No active invoice for this client."
    else:
        s = status.lower()
        if s == "promise_to_pay":
            recommendation = "Client has promised to pay. Send a gentle confirmation close to the promised date."
        elif s == "overdue":
            recommendation = "Invoice is overdue. Consider sending the next escalation message or scheduling a call."
        elif s == "paid":
            recommendation = "Invoice is paid. You can archive this journey or thank the client."
        else:
            recommendation = "Invoice is pending. Optionally send a reminder before the due date."

    journey = {
        "client": client_payload,
        "communications": comms,
        "expected_collection_pct": pct,
        "recommended_action": recommendation,
    }
    return journey, 200


@app.route("/api/clients/<int:client_id>", methods=["PUT"])
def update_client(client_id):
    """Update a client."""
    from db.database import get_session
    from db.models import Client, ContactPreference
    data = request.get_json(silent=True) or {}
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        if "name" in data and data["name"] is not None:
            name = str(data["name"]).strip()
            if name:
                client.name = name
        if "email" in data:
            client.email = str(data["email"]).strip() or None
        if "phone" in data:
            client.phone = str(data["phone"]).strip() or None
        if "contact_preference" in data:
            cp = str(data["contact_preference"]).strip().lower()
            if cp in ("email", "sms", "both"):
                client.contact_preference = cp
        if "opted_out" in data:
            client.opted_out = bool(data["opted_out"])
            client.opted_out_at = datetime.now(timezone.utc) if client.opted_out else None
        return _client_to_json(client), 200


@app.route("/api/clients/<int:client_id>", methods=["DELETE"])
def delete_client(client_id):
    """Delete a client (fails if has invoices)."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        has_invoices = session.scalar(select(Invoice.id).where(Invoice.client_id == client_id).limit(1)) is not None
        if has_invoices:
            return {"error": "Cannot delete client with existing invoices"}, 409
        session.delete(client)
        return "", 204


@app.route("/api/clients/<int:client_id>/block", methods=["POST"])
def block_client(client_id):
    """Mark client as opted out (blocked)."""
    from db.database import get_session
    from db.models import Client
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        client.opted_out = True
        client.opted_out_at = datetime.now(timezone.utc)
        return _client_to_json(client), 200


# ----- Invoices API -----

def _invoice_to_json(inv, client_name=None):
    """Serialize Invoice to dict with optional client_name."""
    out = {
        "id": inv.id,
        "client_id": inv.client_id,
        "amount": inv.amount,
        "currency": inv.currency or "USD",
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "status": inv.status or "pending",
        "days_overdue": inv.days_overdue or 0,
        "escalation_level": inv.escalation_level,
        "human_override": inv.human_override or False,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
    }
    if client_name is not None:
        out["client_name"] = client_name
    return out


@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    """List invoices with optional client_id filter."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice
    client_id = request.args.get("client_id", type=int)
    with get_session() as session:
        stmt = (
            select(Invoice, Client.name)
            .join(Client, Invoice.client_id == Client.id)
            .order_by(Invoice.id)
        )
        if client_id is not None:
            stmt = stmt.where(Invoice.client_id == client_id)
        rows = session.execute(stmt).all()
        result = [_invoice_to_json(inv, client_name=name) for inv, name in rows]
        return {"invoices": result}, 200


@app.route("/api/invoices", methods=["POST"])
def create_invoice():
    """Create a new invoice for a client."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice, InvoiceStatus
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    if client_id is None:
        return {"error": "client_id is required"}, 400
    try:
        client_id = int(client_id)
    except (TypeError, ValueError):
        return {"error": "client_id must be an integer"}, 400
    amount = data.get("amount")
    if amount is None:
        return {"error": "amount is required"}, 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"error": "amount must be a number"}, 400
    if amount < 0:
        return {"error": "amount must be non-negative"}, 400
    currency = (data.get("currency") or "USD").strip() or "USD"
    due_date_str = (data.get("due_date") or "").strip()
    if not due_date_str:
        return {"error": "due_date is required"}, 400
    try:
        from datetime import date as date_type
        due_date = date_type.fromisoformat(due_date_str)
    except (ValueError, TypeError):
        return {"error": "due_date must be ISO date (YYYY-MM-DD)"}, 400
    status = (data.get("status") or "pending").strip().lower()
    if status not in ("pending", "overdue", "paid"):
        status = "pending"
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        inv = Invoice(
            client_id=client_id,
            amount=amount,
            currency=currency,
            due_date=due_date,
            status=status,
        )
        session.add(inv)
        session.flush()
        inv_id = inv.id
    # Mark overdue immediately if due_date is already in the past
    from agents.invoice_monitor import update_invoice_if_overdue
    update_invoice_if_overdue(inv_id)
    with get_session() as session:
        inv = session.get(Invoice, inv_id)
        client = session.get(Client, inv.client_id)
        return _invoice_to_json(inv, client_name=client.name if client else None), 201


@app.route("/api/invoices/<int:invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    """Get one invoice with client name."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return {"error": "Invoice not found"}, 404
        client = session.get(Client, inv.client_id)
        name = client.name if client else None
        return _invoice_to_json(inv, client_name=name), 200


@app.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
def update_invoice(invoice_id):
    """Update an invoice."""
    from db.database import get_session
    from db.models import Client, Invoice
    data = request.get_json(silent=True) or {}
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return {"error": "Invoice not found"}, 404
        if "amount" in data and data["amount"] is not None:
            try:
                amount = float(data["amount"])
                if amount >= 0:
                    inv.amount = amount
            except (TypeError, ValueError):
                pass
        if "currency" in data and data["currency"] is not None:
            inv.currency = str(data["currency"]).strip() or "USD"
        if "due_date" in data and data["due_date"] is not None:
            try:
                from datetime import date as date_type
                due_date_str = str(data["due_date"]).strip()
                inv.due_date = date_type.fromisoformat(due_date_str)
            except (ValueError, TypeError):
                pass
        if "status" in data and data["status"] is not None:
            s = str(data["status"]).strip().lower()
            if s in ("pending", "overdue", "paid"):
                inv.status = s
        if "days_overdue" in data and data["days_overdue"] is not None:
            try:
                inv.days_overdue = int(data["days_overdue"])
            except (TypeError, ValueError):
                pass
        if "human_override" in data:
            inv.human_override = bool(data["human_override"])
    # Mark overdue immediately if due_date is now in the past
    from agents.invoice_monitor import update_invoice_if_overdue
    update_invoice_if_overdue(invoice_id)
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        client = session.get(Client, inv.client_id)
        return _invoice_to_json(inv, client_name=client.name if client else None), 200


@app.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    """Delete an invoice (fails if has communications)."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Communication, Invoice
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return {"error": "Invoice not found"}, 404
        has_comms = session.scalar(
            select(Communication.id).where(Communication.invoice_id == invoice_id).limit(1)
        ) is not None
        if has_comms:
            return {"error": "Cannot delete invoice with existing communications"}, 409
        session.delete(inv)
        return "", 204


# ----- Client communications -----

@app.route("/api/clients/<int:client_id>/communications", methods=["GET"])
def list_client_communications(client_id):
    """List communications for all invoices of this client (for history table)."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Communication, Invoice, Response
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            return {"error": "Client not found"}, 404
        stmt = (
            select(Communication, Response.raw_content.label("response_content"), Response.intent, Response.processed_at)
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .outerjoin(Response, Response.communication_id == Communication.id)
            .where(Invoice.client_id == client_id)
            .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc(), Response.processed_at.desc().nullslast())
        )
        rows = session.execute(stmt).all()
        seen = set()
        result = []
        for row in rows:
            comm, resp_content, intent, processed_at = row
            if comm.id in seen:
                continue
            seen.add(comm.id)
            ts = comm.sent_at or comm.created_at
            date_str = f"{ts.month}/{ts.day}" if ts else "—"
            result.append({
                "id": comm.id,
                "date": date_str,
                "level": f"L{comm.escalation_level}" if comm.escalation_level is not None else "—",
                "channel": (comm.channel or "").upper(),
                "response": (resp_content or "")[:80] if resp_content else (comm.body or "")[:80],
                "status": "Done" if (processed_at or intent) else "Pending",
            })
        return {"communications": result}, 200


# ----- Overview / analytics endpoints -----


@app.route("/api/overview", methods=["GET"])
def overview_counts():
    """High-level counts for dashboard overview strip."""
    from sqlalchemy import func, select
    from db.database import get_session
    from db.models import Client, Communication, Invoice, InvoiceStatus, Response

    with get_session() as session:
        n_clients = session.scalar(select(func.count(Client.id))) or 0
        n_inv = session.scalar(select(func.count(Invoice.id))) or 0
        n_overdue = (
            session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.status == InvoiceStatus.OVERDUE.value
                )
            )
            or 0
        )
        n_paid = (
            session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.status == InvoiceStatus.PAID.value
                )
            )
            or 0
        )
        n_comm = session.scalar(select(func.count(Communication.id))) or 0
        n_pending_send = (
            session.scalar(
                select(func.count(Communication.id)).where(
                    Communication.direction == "outbound",
                    Communication.sent_at.is_(None),
                )
            )
            or 0
        )
        n_resp = session.scalar(select(func.count(Response.id))) or 0
    return {
        "clients": n_clients,
        "invoices": n_inv,
        "overdue": n_overdue,
        "paid": n_paid,
        "communications": n_comm,
        "pending_send": n_pending_send,
        "responses": n_resp,
    }, 200


@app.route("/api/overdue-activity", methods=["GET"])
def overdue_activity():
    """List overdue invoices for monitor-style activity view."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Invoice, InvoiceStatus

    with get_session() as session:
        stmt = (
            select(Invoice, Client.name.label("client_name"))
            .join(Client, Invoice.client_id == Client.id)
            .where(Invoice.status == InvoiceStatus.OVERDUE.value)
            .order_by(Invoice.days_overdue.desc().nullslast(), Invoice.id)
        )
        rows = session.execute(stmt).all()
        result = []
        for inv, name in rows:
            result.append(
                {
                    "id": inv.id,
                    "client_name": name,
                    "amount": inv.amount,
                    "currency": inv.currency,
                    "due_date": inv.due_date.isoformat() if inv.due_date else None,
                    "days_overdue": inv.days_overdue or 0,
                    "escalation_level": inv.escalation_level,
                }
            )
    return {"overdue_invoices": result}, 200


@app.route("/api/pending-communications", methods=["GET"])
def pending_communications():
    """Communications generated but not yet sent (sent_at is NULL)."""
    from sqlalchemy import select
    from db.database import get_session
    from db.models import Client, Communication, Invoice

    with get_session() as session:
        stmt = (
            select(Communication, Invoice.id.label("invoice_id"), Client.name.label("client_name"))
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .join(Client, Invoice.client_id == Client.id)
            .where(
                Communication.direction == "outbound",
                Communication.sent_at.is_(None),
            )
            .order_by(Communication.id.desc())
        )
        rows = session.execute(stmt).all()
        result = []
        for comm, invoice_id, client_name in rows:
            body = comm.body or ""
            preview = body[:120] + ("..." if len(body) > 120 else "")
            result.append(
                {
                    "id": comm.id,
                    "invoice_id": invoice_id,
                    "client_name": client_name,
                    "channel": comm.channel,
                    "escalation_level": comm.escalation_level,
                    "body_preview": preview,
                }
            )
    return {"pending": result}, 200


# ----- Pipeline control endpoints -----


@app.route("/api/pipeline/invoice-monitor", methods=["POST"])
def pipeline_invoice_monitor():
    """Run the invoice monitor agent (mark overdue, set escalation level)."""
    from agents.invoice_monitor import run_invoice_monitor

    updated = run_invoice_monitor()
    return {"updated": updated}, 200


@app.route("/api/pipeline/message-generator", methods=["POST"])
def pipeline_message_generator():
    """Run the message generator agent, optionally limited to invoice_ids."""
    from agents.message_generator_agent import run_message_generator

    data = request.get_json(silent=True) or {}
    invoice_ids = data.get("invoice_ids")
    if invoice_ids is not None and not isinstance(invoice_ids, list):
        return {"error": "invoice_ids must be a list of integers"}, 400
    created = run_message_generator(invoice_ids=invoice_ids)
    return {"created": created}, 200


@app.route("/api/pipeline/dispatcher", methods=["POST"])
def pipeline_dispatcher():
    """Run the communication dispatcher to send pending messages."""
    from agents.communication_dispatcher import run_communication_dispatcher

    sent = run_communication_dispatcher()
    return {"sent": sent}, 200


@app.route("/api/pipeline/analytics-report", methods=["POST"])
def pipeline_analytics_report():
    """Run analytics reporter and return the report path."""
    from agents.analytics_reporter import run_analytics_reporter

    path = run_analytics_reporter()
    return {"report_path": str(path)}, 200


@app.route("/api/pipeline/full", methods=["POST"])
def pipeline_full():
    """Run full pipeline: invoice monitor → message generator → dispatcher."""
    from agents.invoice_monitor import run_invoice_monitor
    from agents.message_generator_agent import run_message_generator
    from agents.communication_dispatcher import run_communication_dispatcher

    updated = run_invoice_monitor()
    created = run_message_generator()
    sent = run_communication_dispatcher()
    return {"monitor_updated": updated, "messages_created": created, "sent": sent}, 200


@app.route("/api/pipeline/orchestrator-demo", methods=["POST"])
def pipeline_orchestrator_demo():
    """
    Run a demo pipeline for a single client (similar to Streamlit orchestrator page).

    Uses DEMO_CLIENT_EMAIL / DEMO_CLIENT_NAME env vars.
    """
    from datetime import date, timedelta
    import html
    import os
    from sqlalchemy import select

    from db.database import get_session
    from db.models import (
        Client,
        Communication,
        ContactPreference,
        Invoice,
        InvoiceStatus,
        Response,
    )
    from agents.invoice_monitor import run_invoice_monitor
    from agents.message_generator_agent import run_message_generator

    steps: list[dict] = []

    def push_step(num: int, title: str, body: str, status: str = "ok"):
        steps.append(
            {
                "step": num,
                "title": title,
                "body": html.escape(body),
                "status": status,
            }
        )

    demo_email = os.getenv("DEMO_CLIENT_EMAIL", "demo@example.com").strip()
    demo_name = os.getenv("DEMO_CLIENT_NAME", "Demo Client").strip() or demo_email.split("@")[0]

    try:
        # Step 1: create or get client
        with get_session() as session:
            existing = session.scalars(
                select(Client).where(Client.email == demo_email)
            ).first()
            if existing:
                client_id = existing.id
                push_step(1, "Client", f"Using existing client {existing.name} ({demo_email})")
            else:
                c = Client(
                    name=demo_name,
                    email=demo_email,
                    contact_preference=ContactPreference.EMAIL.value,
                )
                session.add(c)
                session.flush()
                client_id = c.id
                push_step(1, "Client", f"Created client {demo_name} ({demo_email})")

        # Step 2: create two invoices (one overdue, one normal)
        today = date.today()
        with get_session() as session:
            inv_overdue = Invoice(
                client_id=client_id,
                amount=500.0,
                currency="USD",
                due_date=today - timedelta(days=10),
                status=InvoiceStatus.OVERDUE.value,
                days_overdue=10,
                escalation_level=1,
            )
            inv_normal = Invoice(
                client_id=client_id,
                amount=200.0,
                currency="USD",
                due_date=today + timedelta(days=30),
                status=InvoiceStatus.PENDING.value,
            )
            session.add_all([inv_overdue, inv_normal])
            session.flush()
            inv_overdue_id, inv_normal_id = inv_overdue.id, inv_normal.id
        push_step(
            2,
            "Invoices",
            f"Created 2 invoices: #{inv_overdue_id} (overdue, level 1), #{inv_normal_id} (pending)",
        )

        # Step 3: invoice monitor
        n_monitor = run_invoice_monitor()
        push_step(
            3, "Invoice Monitor", f"Updated {n_monitor} overdue invoice(s) (status + escalation level)"
        )

        # Step 4: message generator for the overdue invoice
        n_msg = run_message_generator(invoice_ids=[inv_overdue_id])
        push_step(
            4,
            "Message Generator",
            f"Generated {n_msg} message(s) for overdue invoice #{inv_overdue_id}",
        )

        # Step 5: preview latest message for the overdue invoice
        with get_session() as session:
            stmt = (
                select(Communication.body, Communication.subject)
                .where(
                    Communication.invoice_id == inv_overdue_id,
                    Communication.direction == "outbound",
                    Communication.sent_at.is_(None),
                )
                .order_by(Communication.id.desc())
                .limit(1)
            )
            row = session.execute(stmt).first()
        if row:
            msg_body_preview, msg_subject = row
            body_str = (msg_body_preview or "")[:500]
            if msg_body_preview and len(msg_body_preview) > 500:
                body_str += "..."
            push_step(
                5,
                "Message to mail",
                f"Subject: {msg_subject or '(none)'}\n\nBody (will be mailed to {demo_email}):\n\n{body_str}",
            )
        else:
            push_step(
                5,
                "Message to mail",
                f"No pending message for invoice #{inv_overdue_id} (generator created 0 this run).",
            )

        # Step 6: process a manual email dispute
        dispute_subject = "Re: Invoice"
        dispute_body = "I dispute this invoice. I won't pay."
        process_inbound_email(
            demo_email,
            dispute_subject,
            dispute_body,
            external_id="orchestrator-demo",
        )
        push_step(
            6,
            "Process email (manual)",
            f"Processed inbound from {demo_email}: subject '{dispute_subject}', body '{dispute_body}'",
        )

        # Step 7: result – latest response intent/action
        with get_session() as session:
            row = session.execute(
                select(Response.intent, Response.action_taken)
                .order_by(Response.id.desc())
                .limit(1)
            ).first()
        if row:
            intent, action_taken = row
            push_step(
                7,
                "Result",
                f"Latest response intent = {intent}, action_taken = {action_taken or '—'}",
            )
        else:
            push_step(7, "Result", "No responses recorded yet.")
        status = 200
    except Exception as exc:  # pragma: no cover - safety net
        push_step(0, "Error", str(exc), status="error")
        status = 500

    return {"steps": steps}, status


# ----- Message generation & sending -----


@app.route("/api/invoices/<int:invoice_id>/generate-message", methods=["POST"])
def generate_message_for_invoice(invoice_id: int):
    """
    Generate an escalation message for one invoice.

    Request JSON:
      - channel: \"email\" or \"sms\" (required)
      - additional_context: optional string
      - save: bool (default False) – if True, create a Communication row (pending send)
    """
    from datetime import date as date_type
    from sqlalchemy import select

    from db.database import get_session
    from db.models import Client, Communication, Invoice
    from agents.message_generator_agent import InvoiceInput, EscalationMessage, generate_escalation_message

    data = request.get_json(silent=True) or {}
    channel = (data.get("channel") or "").strip().lower()
    if channel not in ("email", "sms"):
        return {"error": "channel must be 'email' or 'sms'"}, 400
    additional_context = (data.get("additional_context") or "").strip() or None
    save = bool(data.get("save", False))

    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return {"error": "Invoice not found"}, 404
        client = session.get(Client, inv.client_id)
        if not client:
            return {"error": "Client not found for invoice"}, 404

        payload = InvoiceInput(
            invoice_id=str(inv.id),
            client_name=client.name or f"Client #{client.id}",
            amount=inv.amount,
            currency=inv.currency or "USD",
            due_date=inv.due_date or date_type.today(),
            days_overdue=inv.days_overdue or 0,
            level=inv.escalation_level or 1,
            channel=channel,  # type: ignore[arg-type]
            additional_context=additional_context,
        )
        msg = generate_escalation_message(payload)
        if not isinstance(msg, EscalationMessage):
            return {"error": "LLM did not return EscalationMessage"}, 500

        comm_id = None
        if save:
            comm = Communication(
                invoice_id=inv.id,
                channel=msg.channel,
                direction="outbound",
                body=msg.body,
                subject=msg.subject,
                escalation_level=msg.level,
                sent_at=None,
            )
            session.add(comm)
            session.flush()
            comm_id = comm.id

    resp = {
        "message": {
            "invoice_id": msg.invoice_id,
            "level": msg.level,
            "channel": msg.channel,
            "subject": msg.subject,
            "body": msg.body,
        },
        "communication_id": comm_id,
    }
    return resp, 200


@app.route("/api/communications/send", methods=["POST"])
def send_selected_communications_api():
    """Send selected communications (by id) via dispatcher."""
    from agents.communication_dispatcher import send_selected_communications

    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return {"error": "ids must be a list of integers"}, 400
    sent = send_selected_communications(ids)
    return {"sent": sent}, 200


# ----- Simulate inbound + Twilio voice test -----


@app.route("/api/simulate/sms", methods=["POST"])
def simulate_sms():
    """Simulate inbound SMS for testing (no Twilio required)."""
    data = request.get_json(silent=True) or {}
    from_phone = (data.get("from_phone") or "").strip()
    body = (data.get("body") or "").strip()
    if not from_phone or not body:
        return {"error": "from_phone and body are required"}, 400
    process_inbound_sms(from_phone, body, external_id="dashboard-simulated-sms")
    return {"status": "ok"}, 200


@app.route("/api/simulate/email", methods=["POST"])
def simulate_email():
    """Simulate inbound email for testing."""
    data = request.get_json(silent=True) or {}
    from_addr = (data.get("from_email") or "").strip()
    subject = (data.get("subject") or "Re: Invoice").strip()
    body = (data.get("body") or "").strip()
    if not from_addr or not body:
        return {"error": "from_email and body are required"}, 400
    process_inbound_email(from_addr, subject, body, external_id="dashboard-simulated-email")
    return {"status": "ok"}, 200


@app.route("/api/twilio/voice-test", methods=["POST"])
def twilio_voice_test():
    """
    Place a simple Twilio test call using configured credentials.

    Request JSON:
      - to: destination phone number (optional; falls back to ESCALATION_CALL_TO)
    """
    import os

    try:
        from twilio.rest import Client as TwilioClient  # type: ignore[import]
    except Exception as exc:  # pragma: no cover - library not installed
        return {"error": f"Twilio client library not available: {exc}"}, 500

    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    default_to = (os.environ.get("ESCALATION_CALL_TO") or "").strip()

    if not sid or not token or not from_num:
        return {"error": "Missing Twilio credentials (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER)"}, 400

    data = request.get_json(silent=True) or {}
    to_number = (data.get("to") or default_to).strip()
    if not to_number:
        return {"error": "Destination phone number is required"}, 400

    try:
        client = TwilioClient(sid, token)
        call = client.calls.create(
            url="http://demo.twilio.com/docs/voice.xml",
            to=to_number,
            from_=from_num,
        )
        sid_str = getattr(call, "sid", "") or "(no SID returned)"
        return {"status": "ok", "call_sid": sid_str}, 200
    except Exception as exc:  # pragma: no cover - external service
        return {"error": f"Failed to place call: {exc}"}, 500


def main():
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")


if __name__ == "__main__":
    main()
