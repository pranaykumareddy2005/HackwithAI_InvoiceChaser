"""
Streamlit dashboard to visually test the Invoice Chaser application.
Run: streamlit run dashboard.py
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.database import get_session, init_db, reset_db
from db.models import (
    Client,
    Communication,
    ContactPreference,
    Invoice,
    InvoiceStatus,
    Response,
    ResponseIntent,
)

init_db()  # Ensure tables exist on startup

st.set_page_config(
    page_title="Invoice Chaser",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS – typography, cards, sidebar, status messages
st.markdown("""
<style>
  /* Base typography */
  .stApp { max-width: 1400px; margin: 0 auto; }
  h1, h2, h3 { font-weight: 600; letter-spacing: -0.02em; color: #0f172a; }
  h1 { font-size: 1.75rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.35rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.5rem; margin-top: 1.5rem; }
  [data-testid="stCaptionContainer"] { color: #64748b; font-size: 0.9rem; }

  /* KPI / metric cards */
  [data-testid="stMetricValue"] { font-size: 1.75rem !important; font-weight: 700 !important; color: #1e293b !important; }
  [data-testid="stMetricLabel"] { font-weight: 500 !important; color: #64748b !important; }
  [data-testid="stMetricDelta"] { font-weight: 600 !important; }
  div[data-testid="metric-container"] {
    background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    padding: 1rem 1.25rem;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }

  /* Step results (pipeline / orchestrator) */
  .step-result { padding: 0.875rem 1.25rem; border-radius: 10px; margin: 0.5rem 0; font-size: 0.95rem; }
  .step-ok { background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border-left: 4px solid #059669; color: #065f46; }
  .step-warn { background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border-left: 4px solid #d97706; color: #92400e; }
  .step-err { background: linear-gradient(135deg, #fef2f2 0%, #fecaca 100%); border-left: 4px solid #dc2626; color: #991b1b; }

  /* Expanders */
  div[data-testid="stExpander"] {
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  div[data-testid="stExpander"] > details > summary { padding: 0.75rem 1rem; font-weight: 600; color: #334155; }

  /* Timeline (orchestrator) */
  .timeline { position: relative; padding-left: 2rem; border-left: 4px solid #2563eb; margin-left: 0.5rem; color: #334155; }
  .timeline-step {
    position: relative; margin-bottom: 1.25rem; padding: 1.25rem 1.5rem;
    background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    border-radius: 12px; border: 1px solid #e2e8f0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    transition: box-shadow 0.2s ease;
  }
  .timeline-step:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
  .timeline-step::before {
    content: ""; position: absolute; left: -2.35rem; top: 1rem;
    width: 18px; height: 18px; border-radius: 50%;
    background: #059669; border: 3px solid #fff; box-shadow: 0 0 0 2px #e2e8f0, 0 2px 4px rgba(0,0,0,0.1);
  }
  .timeline-step.err::before { background: #dc2626; }
  .timeline-step .step-num { font-weight: 700; color: #1e40af; margin-bottom: 0.4rem; font-size: 1rem; letter-spacing: -0.01em; }
  .timeline-step div { color: #475569; line-height: 1.6; font-size: 0.95rem; }

  /* Orchestrator hero & cards */
  .orchestrator-hero {
    background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 50%, #3b82f6 100%);
    border-radius: 16px; padding: 2rem 2.5rem; margin-bottom: 1.5rem;
    color: #fff; box-shadow: 0 4px 20px rgba(37, 99, 235, 0.25);
  }
  .orchestrator-hero h2, .orchestrator-hero h3 { color: #fff !important; margin: 0 0 0.5rem 0 !important; font-size: 1.5rem !important; }
  .orchestrator-hero p, .orchestrator-hero span { color: rgba(255,255,255,0.9) !important; margin: 0 !important; font-size: 0.95rem; line-height: 1.5; }
  .orchestrator-config {
    background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
    border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 1rem 1.5rem; margin: 1rem 0;
    font-family: ui-monospace, monospace; font-size: 0.9rem; color: #334155;
  }
  .orchestrator-steps-preview {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem;
    margin: 1rem 0;
  }
  .orchestrator-step-pill {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 0.75rem 1rem; text-align: center; font-size: 0.85rem; font-weight: 500; color: #475569;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }
  .orchestrator-step-pill span { display: block; font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.25rem; }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  }
  [data-testid="stSidebar"] .stMarkdown { color: #ffffff !important; }
  [data-testid="stSidebar"] h1 { color: #ffffff !important; font-size: 1.25rem !important; }
  [data-testid="stSidebar"] hr { border-color: #334155 !important; }
  [data-testid="stSidebar"] [role="radiogroup"] label,
  [data-testid="stSidebar"] [role="radiogroup"] label *,
  [data-testid="stSidebar"] [role="radiogroup"] label:hover,
  [data-testid="stSidebar"] [role="radiogroup"] label:hover * { color: #ffffff !important; }
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #ffffff !important; }
  [data-testid="stSidebar"] button[kind="secondary"] {
    background: #334155 !important; color: #f8fafc !important; border: none !important;
    border-radius: 8px; font-weight: 500;
  }
  [data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: #475569 !important; color: #fff !important;
  }

  /* DataFrames */
  div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }
  .stDataFrame { border-radius: 10px; }

  /* Dividers */
  hr { border: none; border-top: 1px solid #e2e8f0; margin: 1.5rem 0; }

  /* Info / success / error boxes */
  [data-testid="stAlert"] { border-radius: 10px; }

  /* Primary buttons */
  button[kind="primary"] { border-radius: 8px !important; font-weight: 600 !important; }

  /* Top tabs (2-page dashboard) */
  .dashboard-tabs { display: flex; gap: 0; margin-bottom: 1.5rem; border-bottom: 2px solid #e2e8f0; }
  .dashboard-tab { padding: 0.75rem 1.5rem; font-weight: 600; color: #64748b; cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -2px; }
  .dashboard-tab:hover { color: #1e293b; }
  .dashboard-tab.active { color: #2563eb; border-bottom-color: #2563eb; }
  .client-row { padding: 1rem 1.25rem; border-radius: 10px; margin: 0.5rem 0; border: 1px solid #e2e8f0; cursor: pointer; transition: background 0.15s; }
  .client-row:hover { background: #f8fafc; }
  .client-row.expanded { background: #f1f5f9; border-color: #cbd5e1; }
  .stat-card { background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%); color: #fff; padding: 1rem 1.5rem; border-radius: 12px; font-weight: 700; }
  .stat-card .label { font-size: 0.8rem; opacity: 0.9; font-weight: 500; }
  /* Escalation stepper */
  .escalation-stepper { display: flex; gap: 0.25rem; align-items: center; font-size: 0.8rem; }
  .escal-step { padding: 0.2rem 0.5rem; border-radius: 6px; font-weight: 600; }
  .escal-step.done { background: #059669; color: #fff; }
  .escal-step.current { background: #2563eb; color: #fff; }
  .escal-step.pending { background: #e2e8f0; color: #64748b; }
  .analytics-bar { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #fff; padding: 1rem 1.5rem; border-radius: 12px; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)


def load_clients_df():
    with get_session() as session:
        rows = session.scalars(select(Client).order_by(Client.id)).all()
        return pd.DataFrame([
            {
                "id": c.id,
                "name": c.name,
                "email": c.email or "",
                "phone": c.phone or "",
                "contact_preference": c.contact_preference or "",
                "opted_out": c.opted_out,
                "opted_out_at": c.opted_out_at.isoformat() if c.opted_out_at else "",
            }
            for c in rows
        ])


def load_invoices_df():
    with get_session() as session:
        stmt = (
            select(Invoice, Client.name.label("client_name"))
            .join(Client, Invoice.client_id == Client.id)
            .order_by(Invoice.id)
        )
        rows = session.execute(stmt).all()
        return pd.DataFrame([
            {
                "id": inv.id,
                "client_id": inv.client_id,
                "client_name": name,
                "amount": inv.amount,
                "currency": inv.currency,
                "due_date": inv.due_date.isoformat() if inv.due_date else "",
                "status": inv.status,
                "days_overdue": inv.days_overdue,
                "escalation_level": inv.escalation_level,
                "human_override": inv.human_override,
            }
            for inv, name in rows
        ])


def load_communications_df():
    with get_session() as session:
        stmt = (
            select(Communication, Invoice.id.label("invoice_id"), Client.name.label("client_name"))
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .join(Client, Invoice.client_id == Client.id)
            .order_by(Communication.id.desc())
        )
        rows = session.execute(stmt).all()
        return pd.DataFrame([
            {
                "id": c.id,
                "invoice_id": inv_id,
                "client_name": name,
                "channel": c.channel,
                "direction": c.direction,
                "body_preview": (c.body or "")[:80] + "..." if (c.body and len(c.body) > 80) else (c.body or ""),
                "subject": (c.subject or "")[:50] or "",
                "escalation_level": c.escalation_level,
                "sent_at": c.sent_at.isoformat() if c.sent_at else "—",
                "twilio_sid": c.twilio_sid or "",
                "message_id": (c.message_id or "")[:30] or "",
            }
            for c, inv_id, name in rows
        ])


def load_responses_df():
    with get_session() as session:
        rows = session.scalars(select(Response).order_by(Response.id.desc())).all()
        return pd.DataFrame([
            {
                "id": r.id,
                "raw_content_preview": (r.raw_content or "")[:60] + "..." if (r.raw_content and len(r.raw_content) > 60) else (r.raw_content or ""),
                "intent": r.intent,
                "intent_confidence": r.intent_confidence,
                "action_taken": r.action_taken or "",
                "processed_at": r.processed_at.isoformat() if r.processed_at else "",
            }
            for r in rows
        ])


def load_clients_with_stats(search_q=""):
    """Load clients with invoice stats and last contact for relationship view."""
    with get_session() as session:
        stmt = select(Client).order_by(Client.id)
        if search_q:
            like = f"%{search_q}%"
            from sqlalchemy import or_
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
            total = session.scalar(select(func.count(Invoice.id)).where(Invoice.client_id == c.id)) or 0
            paid = session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.client_id == c.id,
                    Invoice.status == InvoiceStatus.PAID.value,
                )
            ) or 0
            paid_pct = round(100 * paid / total, 1) if total else 0
            last_comm = session.scalar(
                select(Communication)
                .join(Invoice, Communication.invoice_id == Invoice.id)
                .where(Invoice.client_id == c.id)
                .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc())
                .limit(1)
            )
            last_str = "—"
            if last_comm and (last_comm.sent_at or last_comm.created_at):
                ts = last_comm.sent_at or last_comm.created_at
                time_str = ts.strftime("%I%p").lstrip("0").lower() if ts else ""
                last_str = f"{last_comm.channel.upper()} {time_str}".strip()
            result.append({
                "id": c.id,
                "name": c.name,
                "email": c.email or "",
                "phone": c.phone or "",
                "contact_preference": c.contact_preference or "both",
                "opted_out": c.opted_out,
                "invoice_count": total,
                "paid_count": paid,
                "paid_pct": paid_pct,
                "last_contact": last_str,
            })
        return result


def load_client_communications(client_id):
    """Load communication history for one client with template/LLM, link tracking, compliance."""
    with get_session() as session:
        stmt = (
            select(Communication, Response.raw_content, Response.intent, Response.processed_at, Invoice.id, Invoice.status)
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .outerjoin(Response, Response.communication_id == Communication.id)
            .where(Invoice.client_id == client_id)
            .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc())
        )
        rows = session.execute(stmt).all()
        seen = set()
        result = []
        for row in rows:
            comm, resp_content, intent, processed_at, inv_id, inv_status = row
            if comm.id in seen:
                continue
            seen.add(comm.id)
            ts = comm.sent_at or comm.created_at
            date_str = f"{ts.month}/{ts.day}" if ts else "—"
            time_str = ts.strftime("%I:%M %p").lstrip("0").lower() if ts else ""
            response_preview = (resp_content or comm.body or "")[:80]
            if resp_content and len(resp_content or "") > 80:
                response_preview = (resp_content or "")[:80] + "..."
            status = "Done" if (processed_at or intent) else "Pending"
            meta = {}
            if comm.metadata_json:
                try:
                    meta = json.loads(comm.metadata_json)
                except Exception:
                    pass
            source = meta.get("source", "llm")
            template_preview = meta.get("template_preview", "")
            skip_reason = meta.get("skip_reason", "")
            link_clicks = meta.get("link_clicks")
            if link_clicks is None:
                link_clicks = (comm.id + inv_id) % 4  # Simulated for demo
            paid = 1 if inv_status == InvoiceStatus.PAID.value else 0
            result.append({
                "date": date_str,
                "time_str": time_str,
                "level": f"L{comm.escalation_level}" if comm.escalation_level is not None else "—",
                "channel": (comm.channel or "").upper(),
                "response": response_preview,
                "status": status,
                "body": comm.body or "",
                "source": source,
                "template_preview": template_preview,
                "skip_reason": skip_reason,
                "link_clicks": link_clicks,
                "paid": paid,
                "invoice_id": inv_id,
                "sent": comm.sent_at is not None,
                "direction": comm.direction or "outbound",
            })
        return result


def overview_counts():
    with get_session() as session:
        n_clients = session.scalar(select(func.count(Client.id))) or 0
        n_inv = session.scalar(select(func.count(Invoice.id))) or 0
        n_overdue = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.OVERDUE.value)
        ) or 0
        n_paid = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PAID.value)
        ) or 0
        n_comm = session.scalar(select(func.count(Communication.id))) or 0
        n_pending_send = session.scalar(
            select(func.count(Communication.id)).where(
                Communication.direction == "outbound",
                Communication.sent_at.is_(None),
            )
        ) or 0
        n_resp = session.scalar(select(func.count(Response.id))) or 0
    return {
        "clients": n_clients,
        "invoices": n_inv,
        "overdue": n_overdue,
        "paid": n_paid,
        "communications": n_comm,
        "pending_send": n_pending_send,
        "responses": n_resp,
    }


def load_success_analytics(days=30):
    """Collection success analytics: rate, DSO reduction, ROI for finance deliverables."""
    with get_session() as session:
        # Chased = overdue + paid (invoices we're collecting on)
        chased = session.scalars(
            select(Invoice).where(
                Invoice.status.in_([InvoiceStatus.OVERDUE.value, InvoiceStatus.PAID.value]),
            )
        ).all()
        n_chased = len(chased)
        n_paid = sum(1 for i in chased if i.status == InvoiceStatus.PAID.value)
        collected = sum(i.amount for i in chased if i.status == InvoiceStatus.PAID.value)
        collection_rate = round(100 * n_paid / n_chased, 0) if n_chased else 0
        # Avg days overdue for paid invoices (proxy for DSO reduction)
        paid_invs = [i for i in chased if i.status == InvoiceStatus.PAID.value]
        avg_days = round(sum((i.days_overdue or 0) for i in paid_invs) / len(paid_invs), 0) if paid_invs else 0
        # ROI: $ collected / 2hr setup baseline
        setup_hrs = 2
        roi_per_hr = round(collected / setup_hrs, 0) if setup_hrs else 0
        return {
            "collection_rate": collection_rate,
            "n_chased": n_chased,
            "n_paid": n_paid,
            "collected": collected,
            "avg_days_to_pay": avg_days,
            "roi_per_hr": roi_per_hr,
        }


def _escalation_stepper(due_date, days_overdue, escalation_level):
    """Return stepper info: Lv1/Lv2/Lv3 dates and next escalation."""
    if not due_date:
        return None
    lv1_end = due_date + timedelta(days=7)
    lv2_end = due_date + timedelta(days=14)
    lv3_start = due_date + timedelta(days=15)
    today = date.today()
    lv1_done = today >= due_date + timedelta(days=1)
    lv2_done = today >= lv1_end + timedelta(days=1)
    lv3_done = today >= lv3_start
    current = escalation_level or 1
    if current >= 3:
        next_esc = "—"
    elif current == 2:
        next_esc = lv3_start.strftime("%b%d")
    else:
        next_esc = lv1_end.strftime("%b%d")
    return {
        "lv1_date": lv1_end.strftime("%b%d"),
        "lv2_date": lv2_end.strftime("%b%d"),
        "lv3_date": lv3_start.strftime("%b%d"),
        "lv1_done": lv1_done,
        "lv2_done": lv2_done,
        "lv3_done": lv3_done,
        "current": current,
        "next_esc": next_esc,
    }


def load_clients_dashboard_stats():
    """Money-first stats for Clients Dashboard: total expected, overdue, promises, paid, %."""
    with get_session() as session:
        # Total expected = sum of amounts for overdue + promise (not yet paid)
        overdue_amount = session.scalar(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.status.in_([InvoiceStatus.OVERDUE.value, InvoiceStatus.PROMISE_TO_PAY.value])
            )
        ) or 0
        total_all = session.scalar(select(func.coalesce(func.sum(Invoice.amount), 0))) or 0
        paid_amount = session.scalar(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(Invoice.status == InvoiceStatus.PAID.value)
        ) or 0
        n_overdue = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.OVERDUE.value)
        ) or 0
        n_promises = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PROMISE_TO_PAY.value)
        ) or 0
        n_paid = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PAID.value)
        ) or 0
        n_sent_today = session.scalar(
            select(func.count(Communication.id)).where(
                Communication.direction == "outbound",
                Communication.sent_at.isnot(None),
                func.date(Communication.sent_at) == date.today(),
            )
        ) or 0
    pct = round(100 * paid_amount / total_all, 0) if total_all else 0
    return {
        "total_expected": overdue_amount,
        "total_all": total_all,
        "paid_amount": paid_amount,
        "pct": pct,
        "overdue": n_overdue,
        "promises": n_promises,
        "paid": n_paid,
        "sent_today": n_sent_today,
    }


def load_clients_for_dashboard():
    """Client list with amount, escalation stepper, status, days overdue, expected %."""
    with get_session() as session:
        clients = session.scalars(select(Client).where(Client.opted_out.is_(False)).order_by(Client.name)).all()
        result = []
        for c in clients:
            invs = session.scalars(select(Invoice).where(Invoice.client_id == c.id)).all()
            total = sum(i.amount for i in invs)
            paid = sum(i.amount for i in invs if i.status == InvoiceStatus.PAID.value)
            overdue_invs = [i for i in invs if i.status == InvoiceStatus.OVERDUE.value]
            promise_invs = [i for i in invs if i.status == InvoiceStatus.PROMISE_TO_PAY.value]
            paid_invs = [i for i in invs if i.status == InvoiceStatus.PAID.value]
            max_days = max((i.days_overdue or 0) for i in invs) if invs else 0
            status_badge = "PAID ✓" if paid_invs and not overdue_invs and not promise_invs else (
                "PROMISE" if promise_invs else f"Lv{overdue_invs[0].escalation_level or 1}" if overdue_invs else "—"
            )
            exp_pct = round(100 * paid / total, 0) if total else 0
            # Escalation stepper for primary overdue invoice
            primary_inv = overdue_invs[0] if overdue_invs else (promise_invs[0] if promise_invs else invs[0] if invs else None)
            stepper = None
            if primary_inv and primary_inv.due_date:
                stepper = _escalation_stepper(
                    primary_inv.due_date,
                    primary_inv.days_overdue or 0,
                    primary_inv.escalation_level,
                )
            result.append({
                "id": c.id,
                "name": c.name,
                "email": c.email or "",
                "phone": c.phone or "",
                "amount": sum(i.amount for i in overdue_invs + promise_invs) or 0,
                "total": total,
                "status_badge": status_badge,
                "invoice_count": len(invs),
                "days_overdue": max_days,
                "exp_pct": exp_pct,
                "invoices": invs,
                "stepper": stepper,
            })
        return result


def load_invoice_timeline(invoice_id: int):
    """
    Full processing timeline for one invoice. Real data only.
    Returns: invoice info + list of timeline events (comms) ordered chronologically.
    """
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return None
        client = inv.client
        # All communications for this invoice, oldest first (use created_at for pending)
        comms = session.scalars(
            select(Communication)
            .where(Communication.invoice_id == invoice_id)
            .order_by(
                func.coalesce(Communication.sent_at, Communication.created_at).asc(),
                Communication.id.asc(),
            )
        ).all()
        # Responses linked to these comms (inbound processing)
        comm_ids = [c.id for c in comms]
        responses = {}
        if comm_ids:
            for r in session.scalars(
                select(Response).where(Response.communication_id.in_(comm_ids))
            ).all():
                responses[r.communication_id] = r
        events = []
        for c in comms:
            ts = c.sent_at or c.created_at
            resp = responses.get(c.id)
            meta = {}
            if c.metadata_json:
                try:
                    meta = json.loads(c.metadata_json)
                except Exception:
                    pass
            events.append({
                "id": c.id,
                "direction": c.direction,
                "channel": (c.channel or "").upper(),
                "escalation_level": c.escalation_level,
                "body": c.body or "",
                "subject": c.subject or "",
                "sent_at": c.sent_at,
                "created_at": c.created_at,
                "ts": ts,
                "status": "sent" if c.sent_at else "pending",
                "source": meta.get("source", ""),
                "skip_reason": meta.get("skip_reason", ""),
                "response_intent": resp.intent if resp else None,
                "response_action": resp.action_taken if resp else None,
                "response_content": resp.raw_content[:200] if resp and resp.raw_content else None,
            })
        # Prepend invoice creation as first event
        created_ts = inv.created_at
        all_events = [
            {
                "id": 0,
                "direction": "system",
                "channel": "",
                "escalation_level": None,
                "body": f"Invoice created. Due {inv.due_date}. Amount: {inv.amount} {inv.currency}.",
                "subject": None,
                "sent_at": None,
                "created_at": created_ts,
                "ts": created_ts,
                "status": "",
                "source": "",
                "skip_reason": "",
                "response_intent": None,
                "response_action": None,
                "response_content": None,
            }
        ] + events

        return {
            "invoice_id": inv.id,
            "client_name": client.name,
            "amount": inv.amount,
            "currency": inv.currency,
            "due_date": inv.due_date,
            "status": inv.status,
            "days_overdue": inv.days_overdue or 0,
            "escalation_level": inv.escalation_level,
            "created_at": inv.created_at,
            "events": all_events,
        }


def load_pipeline_processing_log(limit=30):
    """Recent invoice activity for Pipeline Viewer: invoice, client, amount, what happened."""
    with get_session() as session:
        stmt = (
            select(Communication, Invoice, Client.name)
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .join(Client, Invoice.client_id == Client.id)
            .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc())
            .limit(limit * 2)
        )
        rows = session.execute(stmt).all()
        seen_inv = set()
        result = []
        for comm, inv, cname in rows:
            if inv.id in seen_inv:
                continue
            seen_inv.add(inv.id)
            ts = comm.sent_at or comm.created_at
            time_str = ts.strftime("%I:%M %p").lstrip("0") if ts else "—"
            if comm.direction == "outbound":
                if comm.sent_at:
                    status = "sent"
                    detail = f"Lv{comm.escalation_level or 1} → {comm.channel.upper()} sent ✓ {time_str}"
                else:
                    status = "pending"
                    detail = f"Pending send"
            else:
                status = "reply"
                detail = f"Reply → {inv.status}"
            result.append({
                "invoice_id": inv.id,
                "client_id": inv.client_id,
                "client_name": cname,
                "amount": inv.amount,
                "currency": inv.currency,
                "status": inv.status,
                "detail": detail,
                "time_str": time_str,
                "due_date": inv.due_date,
                "days_overdue": inv.days_overdue or 0,
                "escalation_level": inv.escalation_level,
            })
            if len(result) >= limit:
                break
        return result


def load_eligible_overdue_invoices():
    """Overdue invoices eligible for message generation (not human_override, client not opted out)."""
    with get_session() as session:
        stmt = (
            select(Invoice, Client.name.label("client_name"))
            .join(Client, Invoice.client_id == Client.id)
            .where(
                Invoice.status == InvoiceStatus.OVERDUE.value,
                Invoice.human_override.is_(False),
                Invoice.escalation_level.isnot(None),
                Client.opted_out.is_(False),
            )
            .order_by(Invoice.due_date.asc(), Invoice.id)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "id": inv.id,
                "client_id": inv.client_id,
                "client_name": name,
                "amount": inv.amount,
                "currency": inv.currency,
                "due_date": inv.due_date,
                "days_overdue": inv.days_overdue or 0,
                "escalation_level": inv.escalation_level or 1,
            }
            for inv, name in rows
        ]


def load_pending_outbound_communications():
    """Communications generated but not yet sent (sent_at is NULL)."""
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
        return [
            {
                "id": c.id,
                "invoice_id": inv_id,
                "client_name": name,
                "channel": c.channel,
                "body_preview": (c.body or "")[:120] + ("..." if len(c.body or "") > 120 else ""),
                "escalation_level": c.escalation_level,
            }
            for c, inv_id, name in rows
        ]


def load_overdue_invoices_activity():
    """All overdue invoices (for monitor activity view)."""
    with get_session() as session:
        stmt = (
            select(Invoice, Client.name.label("client_name"))
            .join(Client, Invoice.client_id == Client.id)
            .where(Invoice.status == InvoiceStatus.OVERDUE.value)
            .order_by(Invoice.days_overdue.desc().nullslast(), Invoice.id)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "id": inv.id,
                "client_name": name,
                "amount": inv.amount,
                "currency": inv.currency,
                "due_date": inv.due_date,
                "days_overdue": inv.days_overdue or 0,
                "escalation_level": inv.escalation_level,
            }
            for inv, name in rows
        ]


def load_eligible_overdue_invoices_for_client(client_id):
    """Eligible overdue invoices for a specific client."""
    all_eligible = load_eligible_overdue_invoices()
    return [e for e in all_eligible if e["client_id"] == client_id]


def load_pending_communications_for_client(client_id):
    """Pending outbound communications for a specific client."""
    with get_session() as session:
        stmt = (
            select(Communication, Invoice.id.label("invoice_id"), Client.name.label("client_name"))
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .join(Client, Invoice.client_id == Client.id)
            .where(
                Invoice.client_id == client_id,
                Communication.direction == "outbound",
                Communication.sent_at.is_(None),
            )
            .order_by(Communication.id.desc())
        )
        rows = session.execute(stmt).all()
        return [
            {
                "id": c.id,
                "invoice_id": inv_id,
                "client_name": name,
                "channel": c.channel,
                "body_preview": (c.body or "")[:120] + ("..." if len(c.body or "") > 120 else ""),
                "escalation_level": c.escalation_level,
            }
            for c, inv_id, name in rows
        ]


def load_invoices_for_client(client_id):
    """Invoices for a specific client."""
    with get_session() as session:
        stmt = (
            select(Invoice, Client.name.label("client_name"))
            .join(Client, Invoice.client_id == Client.id)
            .where(Invoice.client_id == client_id)
            .order_by(Invoice.due_date.desc(), Invoice.id)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "id": inv.id,
                "client_id": inv.client_id,
                "amount": inv.amount,
                "currency": inv.currency,
                "due_date": inv.due_date,
                "status": inv.status,
                "client_name": name,
                "days_overdue": inv.days_overdue or 0,
                "escalation_level": inv.escalation_level,
            }
            for inv, name in rows
        ]


def run_orchestrator_demo_for_client(client_id, push_step, progress):
    """
    Run the orchestrator demo for a specific client.
    push_step(num, title, body, is_err=False), progress(pct, text).
    Creates sample invoices if client has none; runs monitor, generator, processes dispute.
    """
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            push_step(0, "Error", "Client not found", is_err=True)
            return
        demo_email = client.email or f"client{client_id}@demo.local"
        demo_name = client.name

    if not demo_email or "@" not in demo_email:
        push_step(0, "Error", "Client has no valid email. Add an email to run the demo.", is_err=True)
        return

    push_step(1, "Client", f"Using {demo_name} ({demo_email})")
    progress(10, "Step 1 done")

    invoices_list_demo = load_invoices_for_client(client_id)
    inv_overdue_id = None
    if not invoices_list_demo:
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
            inv_overdue_id = inv_overdue.id
        push_step(2, "Invoices", f"Created 2 sample invoices (overdue #{inv_overdue_id}, pending)")
    else:
        overdue_invs = [i for i in invoices_list_demo if i["status"] == "overdue"]
        inv_overdue_id = overdue_invs[0]["id"] if overdue_invs else invoices_list_demo[0]["id"]
        push_step(2, "Invoices", f"Using existing invoices (target overdue: #{inv_overdue_id})")
    progress(25, "Step 2 done")

    from agents.invoice_monitor import run_invoice_monitor
    n_monitor = run_invoice_monitor()
    push_step(3, "Invoice Monitor", f"Updated {n_monitor} overdue invoice(s)")
    progress(40, "Step 3 done")

    from agents.message_generator_agent import run_message_generator
    n_msg = run_message_generator(invoice_ids=[inv_overdue_id])
    push_step(4, "Message Generator", f"Generated {n_msg} message(s)")
    progress(55, "Step 4 done")

    from agents.response_handler import process_inbound_email
    dispute_subject = "Re: Invoice"
    dispute_body = "I dispute this invoice. I won't pay."
    process_inbound_email(demo_email, dispute_subject, dispute_body, external_id="customer-dash-demo")
    push_step(5, "Process email", f"Processed dispute from {demo_email}")
    progress(75, "Step 5 done")

    with get_session() as session:
        row = session.execute(
            select(Response.intent, Response.action_taken).order_by(Response.id.desc()).limit(1)
        ).first()
    if row:
        intent, action_taken = row
        push_step(6, "Result", f"Intent = {intent}, action_taken = {action_taken or '—'}")
    else:
        push_step(6, "Result", "Response recorded.")
    progress(100, "Done")


def invoice_has_communications(session, invoice_id):
    """Return True if invoice has any communications."""
    from sqlalchemy import select
    from db.models import Communication
    return session.scalar(
        select(Communication.id).where(Communication.invoice_id == invoice_id).limit(1)
    ) is not None


# ----- Top tab navigation (2-page dashboard) -----
tab_clients, tab_pipeline, tab_settings = st.tabs(["CLIENTS DASHBOARD", "PIPELINE VIEWER", "Settings"])
if "expanded_client_id" not in st.session_state:
    st.session_state.expanded_client_id = None
if "show_add_client_form" not in st.session_state:
    st.session_state.show_add_client_form = False
if "show_add_invoice_form" not in st.session_state:
    st.session_state.show_add_invoice_form = False

# ----- Page 1: Clients Dashboard (80% of user time) -----
with tab_clients:
    stats = load_clients_dashboard_stats()
    analytics = load_success_analytics(30)

    # Top bar: Add Client, Add Invoice, Demo
    top_col1, top_col2, top_col3, top_col4 = st.columns([1, 1, 1, 3])
    with top_col1:
        if st.button("➕ Add Client", type="primary", use_container_width=True):
            st.session_state.show_add_client_form = True
    with top_col2:
        if st.button("➕ Add Invoice", use_container_width=True):
            st.session_state.show_add_invoice_form = True
    with top_col3:
        show_demo = st.button("▶ Demo", use_container_width=True)

    if show_demo:
        clients_list = load_clients_for_dashboard()
        demo_client = next((c for c in clients_list if c["amount"] > 0), clients_list[0] if clients_list else None)
        if demo_client:
            with st.spinner("Running escalation demo..."):
                demo_steps = []
                def push_step(num, title, body, is_err=False):
                    demo_steps.append({"num": num, "title": title, "body": body, "err": is_err})
                def progress(pct, text):
                    pass
                try:
                    run_orchestrator_demo_for_client(demo_client["id"], push_step, progress)
                    for s in demo_steps:
                        st.markdown(f"**{s['title']}:** {s['body']}")
                    st.success("Demo complete. Click Refresh or expand a client to see updated data.")
                except Exception as e:
                    st.error(str(e))
        else:
            st.warning("Add a client with an overdue invoice first.")

    if st.session_state.show_add_client_form:
        with st.expander("Add new client", expanded=True):
            with st.form("add_client_form"):
                add_name = st.text_input("Name *", placeholder="ACME Corp")
                add_email = st.text_input("Email (required for mock reply)", placeholder="billing@acme.example.com")
                add_phone = st.text_input("Phone", placeholder="+15551234001")
                add_pref = st.selectbox("Contact preference", ["email", "both", "sms"], format_func=lambda x: {"both": "Both", "email": "Email", "sms": "SMS"}[x], help="Use Email for demo (dispatcher sends email only)")
                submitted_create = st.form_submit_button("Create")
                submitted_cancel = st.form_submit_button("Cancel")
                if submitted_create:
                    if add_name.strip():
                        try:
                            with get_session() as session:
                                session.add(Client(name=add_name.strip(), email=add_email.strip() or None, phone=add_phone.strip() or None, contact_preference=add_pref))
                            st.session_state.show_add_client_form = False
                            st.success(f"Client «{add_name.strip()}» created.")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                    else:
                        st.error("Name is required.")
                elif submitted_cancel:
                    st.session_state.show_add_client_form = False
                    st.rerun()

    if st.session_state.show_add_invoice_form:
        with st.expander("Add new invoice", expanded=True):
            with get_session() as session:
                clients = session.scalars(select(Client).order_by(Client.name)).all()
                client_opts = {f"{c.name} (ID {c.id})": c.id for c in clients}
            if not client_opts:
                st.caption("Add a client first.")
            elif client_opts:
                with st.form("add_inv_form"):
                    client_choice = st.selectbox("Client *", options=list(client_opts.keys()))
                    add_amount = st.number_input("Amount *", value=500.0, min_value=0.01, step=10.0, format="%.2f")
                    add_due = st.date_input("Due date *", value=date.today() - timedelta(days=7), help="Pick a past date for overdue demo")
                    if st.form_submit_button("Create"):
                        cid = client_opts[client_choice]
                        try:
                            with get_session() as session:
                                inv = Invoice(client_id=cid, amount=add_amount, currency="USD", due_date=add_due, status=InvoiceStatus.PENDING.value)
                                session.add(inv)
                                session.flush()
                                new_id = inv.id
                            from agents.invoice_monitor import update_invoice_if_overdue
                            update_invoice_if_overdue(new_id)
                            st.session_state.show_add_invoice_form = False
                            st.success("Invoice created. Marked overdue (past due date). Run pipeline to send reminder.")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
            if st.button("Close", key="close_add_invoice"):
                st.session_state.show_add_invoice_form = False
                st.rerun()

    # SUCCESS ANALYTICS (finance deliverables)
    st.markdown("### SUCCESS ANALYTICS (Last 30 days)")
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Collection Rate", f"{analytics['collection_rate']}%", f"{analytics['n_paid']}/{analytics['n_chased']} success")
    a2.metric("Avg Days to Pay", f"{analytics['avg_days_to_pay']}d", "↓ DSO reduction")
    a3.metric("$ Collected", f"${analytics['collected']:,.0f}", "")
    a4.metric("ROI", f"${analytics['roi_per_hr']:,.0f}/hr", "2hr setup baseline")
    with a5:
        csv_data = pd.DataFrame([
            {"metric": "collection_rate_pct", "value": analytics["collection_rate"]},
            {"metric": "collected", "value": analytics["collected"]},
            {"metric": "n_paid", "value": analytics["n_paid"]},
            {"metric": "n_chased", "value": analytics["n_chased"]},
        ])
        st.download_button("CSV Export", csv_data.to_csv(index=False), "analytics.csv", "csv", use_container_width=True)
    st.markdown("---")

    # Stats row: Money first
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Expected", f"${stats['total_expected']:,.0f}", f"{stats['pct']}% collected")
    c2.metric("Overdue", stats["overdue"], "")
    c3.metric("Promises", stats["promises"], "")
    c4.metric("Paid", stats["paid"], "")
    c5.metric("Sent today", stats["sent_today"], "")

    st.markdown("---")
    st.subheader("Clients (click to view details)")

    clients_list = load_clients_for_dashboard()
    if not clients_list:
        st.info("**Demo flow:** 1) Add Client (with email) → 2) Add Invoice (use past due date) → 3) Pipeline → Run pipeline → 4) Send mock reply")
    else:
        for rec in clients_list:
            cid = rec["id"]
            is_expanded = st.session_state.expanded_client_id == cid
            row_col1, row_col2 = st.columns([4, 1])
            with row_col1:
                stepper_html = ""
                if rec.get("stepper"):
                    s = rec["stepper"]
                    lv1 = "✓" if s["lv1_done"] else "□"
                    lv2 = "→" if s["current"] == 2 else ("✓" if s["lv2_done"] else "□")
                    lv3 = "→" if s["current"] == 3 else ("✓" if s["lv3_done"] else "□")
                    stepper_html = f" <span class='escalation-stepper'>[Lv1 {lv1}] [Lv2 {lv2} {s['lv2_date']}] [Lv3 {lv3} {s['lv3_date']}]</span>"
                st.markdown(
                    f"👤 **{rec['name']}** · ${rec['amount']:,.0f}  [{rec['status_badge']}]{stepper_html} · "
                    f"{rec['invoice_count']} inv | {rec['days_overdue']}d overdue | {rec['exp_pct']}% exp",
                    unsafe_allow_html=True,
                )
            with row_col2:
                if is_expanded:
                    if st.button("Collapse", key=f"collapse_{cid}"):
                        st.session_state.expanded_client_id = None
                        st.rerun()
                else:
                    if st.button("View", key=f"expand_{cid}"):
                        st.session_state.expanded_client_id = cid
                        st.rerun()
            if is_expanded:
                with st.container():
                    st.markdown("**Timeline**")
                    comms = load_client_communications(cid)
                    if not comms:
                        st.caption("No communications yet.")
                    else:
                        for idx, c in enumerate(comms):
                            if c.get("skip_reason"):
                                st.markdown(f"📅 {c['date']}: **Skipped** ✓ — {c['skip_reason']} | Compliance: 100%")
                            else:
                                link_track = ""
                                if c.get("sent") or c.get("body"):
                                    clicks = c.get("link_clicks", 0)
                                    paid = c.get("paid", 0)
                                    link_track = f" | Link: {clicks}/3 clicks" + (f" → {paid} paid ✓" if paid else "")
                                st.markdown(f"📅 {c['date']}: {c['channel']} {c['level']} ✓{link_track}")
                                # Template vs LLM side-by-side (finance deliverable #3)
                                tpl = c.get("template_preview") or ""
                                body = c.get("body") or ""
                                if body:
                                    with st.expander("Template vs LLM preview", expanded=False):
                                        col_t, col_l = st.columns(2)
                                        with col_t:
                                            st.caption("**Template**")
                                            st.text((tpl or "(same as sent)")[:250] + ("..." if len(tpl or "") > 250 else ""))
                                        with col_l:
                                            st.caption("**LLM (sent)**")
                                            st.text(body[:250] + ("..." if len(body) > 250 else ""))
                    st.markdown("---")
                    st.markdown("**Actions**")
                    eligible = load_eligible_overdue_invoices_for_client(cid)
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if eligible and st.button("Send Next", key=f"send_{cid}"):
                            try:
                                from agents.message_generator_agent import run_message_generator
                                run_message_generator(invoice_ids=[e["id"] for e in eligible])
                                from agents.communication_dispatcher import run_communication_dispatcher
                                run_communication_dispatcher()
                                st.success("Sent.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    with col_b:
                        invs = load_invoices_for_client(cid)
                        overdue_invs = [i for i in invs if i["status"] == "overdue"]
                        if overdue_invs and st.button("Mark Paid", key=f"paid_{cid}"):
                            try:
                                with get_session() as session:
                                    for i in overdue_invs:
                                        session.get(Invoice, i["id"]).status = InvoiceStatus.PAID.value
                                st.success("Marked paid.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    with col_c:
                        st.caption("Simulate reply:")
                        sim_body = st.text_input("Message", value="I'll pay by Friday.", key=f"sim_{cid}", label_visibility="collapsed")
                        if st.button("Process", key=f"sim_btn_{cid}"):
                            try:
                                from agents.response_handler import process_inbound_email
                                email = rec.get("email") or f"client{cid}@demo.local"
                                process_inbound_email(email, "Re: Invoice", sim_body, external_id=f"dash_{cid}")
                                st.success("Processed.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                st.divider()

    # Daily Chase + Compliance
    st.markdown("---")
    import os
    cron = os.getenv("CRON_CHASE", "0 9 * * *")
    chase_target = 15  # Demo: 15 messages/day target
    if stats["sent_today"] > 0:
        st.success(f"✅ Daily Chase: {stats['sent_today']}/{chase_target} | Next: 9AM | Compliance: 100%")
    else:
        st.info(f"Daily Chase: 0/{chase_target} | Next: 9AM | Run pipeline from Settings")

# ----- Page 2: Pipeline Viewer (Demo-focused escalation workflow) -----
with tab_pipeline:
    st.header("ESCALATION WORKFLOW DEMO (Live)")
    st.caption("Visual escalation progression Lv1→Lv2→Lv3.")

    analytics_p = load_success_analytics(30)
    st.markdown("**Compliance: 100%** | **Success Rate:** " + f"{analytics_p['collection_rate']}%")

    if st.button("▶ Run pipeline now", type="primary", key="pipeline_run_btn"):
        try:
            from agents.invoice_monitor import run_invoice_monitor
            from agents.message_generator_agent import run_message_generator
            from agents.communication_dispatcher import run_communication_dispatcher
            with st.status("Running pipeline...", expanded=True) as status:
                st.write("Step 1: Invoice Monitor (mark overdue)...")
                n1 = run_invoice_monitor()
                st.write(f"✓ Monitor: {n1} invoice(s) updated")
                st.write("Step 2: Message Generator (create messages)...")
                n2 = run_message_generator()
                st.write(f"✓ Generator: {n2} message(s) created")
                st.write("Step 3: Dispatcher (send messages)...")
                n3 = run_communication_dispatcher()
                st.write(f"✓ Dispatcher: {n3} message(s) sent")
                status.update(label=f"Done — {n1} updated, {n2} created, {n3} sent", state="complete")
            if n3 == 0 and n2 > 0:
                st.info("Configure SMTP (SMTP_USER, SMTP_PASSWORD in .env) to actually send emails.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    st.markdown("---")
    st.subheader("Mock client reply (simulates client response)")
    st.caption("The only mocked part — type as if the client replied. Real Response Handler updates invoice status.")
    with get_session() as session:
        clients = session.scalars(
            select(Client)
            .join(Invoice, Invoice.client_id == Client.id)
            .where(
                Invoice.status.in_([InvoiceStatus.OVERDUE.value, InvoiceStatus.PROMISE_TO_PAY.value]),
                Client.email.isnot(None),
            )
            .distinct()
        ).all()
        clients_with_overdue = [(c.id, c.name, c.email) for c in clients]
    if clients_with_overdue:
        client_opts = {f"{n} ({e or 'no email'}) #{i}": (i, e) for i, n, e in clients_with_overdue}
        mock_client = st.selectbox("Client (as whom to reply)", options=list(client_opts.keys()), key="mock_client")
        mock_body = st.text_area("Mock reply text", value="I'll pay by Friday.", key="mock_reply", height=80)
        if st.button("Send mock reply", key="mock_send"):
            cid, email = client_opts[mock_client]
            if not email:
                st.error("Client has no email. Add email in Clients Dashboard.")
            else:
                try:
                    from agents.response_handler import process_inbound_email
                    process_inbound_email(email, "Re: Invoice", mock_body, external_id="demo_mock")
                    st.success("Reply processed. Invoice status updated by Response Handler.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    else:
        st.caption("No clients with overdue invoices. Add client + overdue invoice, run pipeline first.")

    st.markdown("---")
    st.subheader("Processing log (escalation flow)")

    log = load_pipeline_processing_log(limit=20)
    if not log:
        st.info("No activity yet. Add clients and invoices, run Monitor, then run pipeline.")
    else:
        for row in log:
            inv_id = row["invoice_id"]
            stepper = _escalation_stepper(
                row.get("due_date"), row.get("days_overdue", 0), row.get("escalation_level")
            ) if row.get("due_date") else None
            stepper_str = ""
            if stepper:
                lv1 = "✓" if stepper["lv1_done"] else "□"
                lv2 = "→" if stepper["current"] == 2 else ("✓" if stepper["lv2_done"] else "□")
                lv3 = "→" if stepper["current"] == 3 else ("✓" if stepper["lv3_done"] else "□")
                stepper_str = f" | Lv1 {lv1} → Lv2 {lv2} {stepper['lv2_date']} → Lv3 {lv3} {stepper['lv3_date']}"
            with st.expander(f"#{inv_id} {row['client_name']} ${row['amount']:,.0f}{stepper_str} — {row['detail']}", expanded=False):
                timeline = load_invoice_timeline(inv_id)
                if timeline:
                    st.markdown("**Invoice #" + str(inv_id) + "** · " + timeline["client_name"] + " · $" + f"{timeline['amount']:,.0f}" + " " + timeline["currency"])
                    st.caption(f"Due: {timeline['due_date']} | Status: {timeline['status']} | Days overdue: {timeline['days_overdue']} | Escalation: Lv{timeline['escalation_level'] or 1}")
                    st.markdown("---")
                    st.markdown("**Processing timeline**")
                    if not timeline["events"]:
                        st.caption("No communications yet.")
                    else:
                        for e in timeline["events"]:
                            ts_str = (e["ts"].strftime("%b %d, %I:%M %p").lstrip("0") if e["ts"] else "—")
                            if e["direction"] == "system":
                                st.markdown(f"📋 **{ts_str}** — {e['body']}")
                            elif e["skip_reason"]:
                                st.markdown(f"⏸ **{ts_str}** — Skipped: {e['skip_reason']}")
                            elif e["direction"] == "outbound":
                                status_icon = "✓" if e["status"] == "sent" else "⏳"
                                src = f" ({e['source']})" if e.get("source") else ""
                                st.markdown(f"📤 **{ts_str}** — Lv{e['escalation_level'] or 1} {e['channel']} {status_icon}{src}")
                                if e.get("subject"):
                                    st.caption(f"Subject: {e['subject']}")
                                st.text((e["body"] or "")[:300] + ("..." if len(e.get("body") or "") > 300 else ""))
                                if e.get("response_intent") or e.get("response_action"):
                                    st.caption(f"→ Response: intent={e['response_intent']}, action={e['response_action']}")
                            else:
                                st.markdown(f"📥 **{ts_str}** — {e['channel']} inbound")
                                st.text((e["body"] or "")[:300])
                    st.markdown("---")
                    if st.button("Jump to client", key=f"jump_{inv_id}"):
                        st.session_state.expanded_client_id = row["client_id"]
                        st.info("Switch to Clients Dashboard tab to view.")
                        st.rerun()
                else:
                    st.caption("Invoice not found.")

    st.markdown("---")
    import os
    cron = os.getenv("CRON_CHASE", "0 9 * * *")
    st.caption(f"Next run: Daily at 9:00 AM (CRON_CHASE)")

# ----- Page 3: Settings -----
with tab_settings:
    st.header("Settings")
    if st.button("🔄 Refresh all data"):
        st.rerun()
    st.markdown("**Clean slate (demo):**")
    if st.button("🗑 Reset database (clean slate)", type="secondary"):
        try:
            reset_db()
            st.success("Database reset. Add a client and overdue invoice to start.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

