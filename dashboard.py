"""
Streamlit dashboard to visually test the Invoice Chaser application.
Run: streamlit run dashboard.py
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.database import get_session, init_db
from db.models import (
    Client,
    Communication,
    ContactPreference,
    Invoice,
    InvoiceStatus,
    Response,
    ResponseIntent,
)

st.set_page_config(
    page_title="Invoice Chaser – Test Dashboard",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clearer sections and status messages
st.markdown("""
<style>
  .kpi { font-size: 1.8rem; font-weight: 600; color: #1f77b4; }
  .step-result { padding: 0.75rem 1rem; border-radius: 8px; margin: 0.5rem 0; }
  .step-ok { background: #d4edda; border-left: 4px solid #28a745; }
  .step-warn { background: #fff3cd; border-left: 4px solid #ffc107; }
  .step-err { background: #f8d7da; border-left: 4px solid #dc3545; }
  div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; }
  .timeline { position: relative; padding-left: 1.5rem; border-left: 3px solid #1f77b4; margin-left: 0.5rem; color: #1a1a1a; }
  .timeline-step { position: relative; margin-bottom: 1.25rem; padding: 0.75rem 1rem; background: #f0f4f8; border-radius: 8px; border: 1px solid #dee2e6; color: #1a1a1a; }
  .timeline-step::before { content: ""; position: absolute; left: -1.6rem; top: 0.5rem; width: 12px; height: 12px; border-radius: 50%; background: #28a745; }
  .timeline-step.err::before { background: #dc3545; }
  .timeline-step .step-num { font-weight: 700; color: #1f77b4; margin-bottom: 0.25rem; }
  .timeline-step div { color: #1a1a1a; }
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
    """Load communication history for one client (for history table)."""
    with get_session() as session:
        stmt = (
            select(Communication, Response.raw_content, Response.intent, Response.processed_at)
            .join(Invoice, Communication.invoice_id == Invoice.id)
            .outerjoin(Response, Response.communication_id == Communication.id)
            .where(Invoice.client_id == client_id)
            .order_by(Communication.sent_at.desc().nullslast(), Communication.created_at.desc())
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
            response_preview = (resp_content or comm.body or "")[:80]
            if resp_content and len(resp_content or "") > 80:
                response_preview = (resp_content or "")[:80] + "..."
            status = "Done" if (processed_at or intent) else "Pending"
            result.append({
                "date": date_str,
                "level": f"L{comm.escalation_level}" if comm.escalation_level is not None else "—",
                "channel": (comm.channel or "").upper(),
                "response": response_preview,
                "status": status,
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


# ----- Sidebar navigation -----
st.sidebar.title("📬 Invoice Chaser")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    [
        "Overview",
        "Orchestrator",
        "Invoices",
        "Clients",
        "Invoice Monitoring Activity",
        "Message Generator",
        "Send email to selected",
        "Response handling",
        "Data browser",
        "Pipeline (run agents)",
        "Voice call test",
        "Simulate inbound",
    ],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh all data"):
    st.rerun()

# ----- Invoices -----
def invoice_has_communications(session, invoice_id):
    """Return True if invoice has any communications."""
    from sqlalchemy import select
    from db.models import Communication
    return session.scalar(
        select(Communication.id).where(Communication.invoice_id == invoice_id).limit(1)
    ) is not None


if page == "Invoices":
    st.header("Invoices")
    st.caption("Create and manage invoices for clients.")

    if "show_add_invoice" not in st.session_state:
        st.session_state.show_add_invoice = False
    if "invoice_edit_id" not in st.session_state:
        st.session_state.invoice_edit_id = None

    # Create invoice
    if st.button("Create Invoice +", type="primary"):
        st.session_state.show_add_invoice = not st.session_state.show_add_invoice
        st.session_state.invoice_edit_id = None
        st.rerun()
    if st.session_state.show_add_invoice:
        with st.form("add_invoice_form", clear_on_submit=True):
            st.subheader("New invoice")
            with get_session() as session:
                clients = session.scalars(select(Client).order_by(Client.name)).all()
                client_options = {f"{c.name} (ID {c.id})": c.id for c in clients}
            if not client_options:
                st.warning("No clients in database. Add a client first.")
            else:
                client_choice = st.selectbox("Client *", options=list(client_options.keys()))
                client_id = client_options[client_choice]
                add_amount = st.number_input("Amount *", value=0.0, min_value=0.0, step=10.0, format="%.2f")
                add_currency = st.text_input("Currency", value="USD", max_chars=10)
                add_due_date = st.date_input("Due date *", value=date.today())
                add_status = st.selectbox(
                    "Status",
                    ["pending", "overdue", "paid"],
                    format_func=lambda x: x.capitalize(),
                )
                submitted = st.form_submit_button("Create invoice")
                if submitted:
                    if not client_id or add_amount < 0:
                        st.warning("Client and a non-negative amount are required.")
                    else:
                        try:
                            with get_session() as session:
                                inv = Invoice(
                                    client_id=client_id,
                                    amount=add_amount,
                                    currency=add_currency.strip() or "USD",
                                    due_date=add_due_date,
                                    status=add_status,
                                )
                                session.add(inv)
                                session.flush()
                                new_inv_id = inv.id
                            from agents.invoice_monitor import update_invoice_if_overdue
                            update_invoice_if_overdue(new_inv_id)
                            st.success("Invoice created.")
                            st.session_state.show_add_invoice = False
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

    # List invoices with client filter (build options inside session to avoid DetachedInstanceError)
    with get_session() as session:
        clients_for_filter = [(c.id, c.name) for c in session.scalars(select(Client).order_by(Client.name)).all()]
    client_filter_options = ["All clients"] + [f"{name} (ID {cid})" for cid, name in clients_for_filter]
    filter_choice = st.selectbox("Filter by client", client_filter_options, label_visibility="collapsed")
    selected_client_id = None
    if filter_choice != "All clients" and clients_for_filter:
        idx = client_filter_options.index(filter_choice)
        if idx > 0:
            selected_client_id = clients_for_filter[idx - 1][0]

    stmt = (
        select(Invoice, Client.name.label("client_name"))
        .join(Client, Invoice.client_id == Client.id)
        .order_by(Invoice.due_date.desc(), Invoice.id)
    )
    if selected_client_id is not None:
        stmt = stmt.where(Invoice.client_id == selected_client_id)
    with get_session() as session:
        rows = session.execute(stmt).all()
        # Build list inside session so ORM attributes are accessed before session closes
        invoices_list = [
            {
                "id": inv.id,
                "client_id": inv.client_id,
                "amount": inv.amount,
                "currency": inv.currency,
                "due_date": inv.due_date,
                "status": inv.status,
                "client_name": name,
            }
            for inv, name in rows
        ]

    if not invoices_list:
        st.info("No invoices found. Create one or adjust the filter.")
    else:
        st.subheader("Invoice list")
        for item in invoices_list:
            inv_id, client_name = item["id"], item["client_name"]
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**#{inv_id}** · {client_name} · {item['amount']} {item['currency']} · Due {item['due_date']} · **{item['status']}**")
                with col2:
                    edit_btn = st.button("Edit", key=f"inv_edit_{inv_id}")
                    if edit_btn:
                        st.session_state.invoice_edit_id = inv_id if st.session_state.invoice_edit_id != inv_id else None
                        st.session_state.show_add_invoice = False
                        st.rerun()
                with col3:
                    with get_session() as session:
                        can_delete = not invoice_has_communications(session, inv_id)
                    if can_delete:
                        del_btn = st.button("Delete", key=f"inv_del_{inv_id}")
                        if del_btn:
                            try:
                                with get_session() as session:
                                    session.delete(session.get(Invoice, inv_id))
                                st.success(f"Invoice #{inv_id} deleted.")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    else:
                        st.caption("Has comms")
                # Edit form (expander when this invoice is selected for edit)
                if st.session_state.invoice_edit_id == inv_id:
                    with st.expander("Edit invoice", expanded=True):
                        with st.form(f"edit_invoice_{inv_id}"):
                            edit_amount = st.number_input("Amount", value=float(item["amount"]), min_value=0.0, step=10.0, format="%.2f", key=f"ea_{inv_id}")
                            edit_currency = st.text_input("Currency", value=item["currency"] or "USD", key=f"ec_{inv_id}")
                            edit_due_date = st.date_input("Due date", value=item["due_date"], key=f"ed_{inv_id}")
                            edit_status = st.selectbox(
                                "Status",
                                ["pending", "overdue", "paid"],
                                index=["pending", "overdue", "paid"].index(item["status"]) if item["status"] in ("pending", "overdue", "paid") else 0,
                                format_func=lambda x: x.capitalize(),
                                key=f"es_{inv_id}",
                            )
                            submitted_save = st.form_submit_button("Save")
                            if submitted_save:
                                try:
                                    with get_session() as session:
                                        inv_obj = session.get(Invoice, inv_id)
                                        if inv_obj:
                                            inv_obj.amount = edit_amount
                                            inv_obj.currency = edit_currency.strip() or "USD"
                                            inv_obj.due_date = edit_due_date
                                            inv_obj.status = edit_status
                                    st.success("Invoice updated.")
                                    st.session_state.invoice_edit_id = None
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))
                        if st.button("Cancel edit", key=f"cancel_edit_{inv_id}"):
                            st.session_state.invoice_edit_id = None
                            st.rerun()
                st.divider()

# ----- Overview -----
if page == "Overview":
    st.header("Overview")
    counts = overview_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Clients", counts["clients"])
    c2.metric("Invoices", counts["invoices"], f"{counts['overdue']} overdue")
    c3.metric("Overdue", counts["overdue"], f"{counts['paid']} paid")
    c4.metric("Communications", counts["communications"], f"{counts['pending_send']} pending send")
    c5.metric("Responses", counts["responses"])
    st.markdown("---")
    st.markdown("""
    **Pipeline order:**  
    1. **Invoice Monitor** – Mark overdue invoices and set escalation levels.  
    2. **Message Generator** – Create outbound email/SMS per client preference (uses Ollama).  
    3. **Communication Dispatcher** – Send pending messages (Twilio/SMTP).  
    4. **Analytics Reporter** – Write CSV/charts to `reports/`.  

    Use **Data browser** to inspect tables, **Pipeline** to run each step, and **Simulate inbound** to test the response handler.
    """)

# ----- Orchestrator (full demo) -----
elif page == "Orchestrator":
    import os

    demo_email = os.getenv("DEMO_CLIENT_EMAIL", "laharimyada14@gmail.com").strip()
    demo_name = os.getenv("DEMO_CLIENT_NAME", "Demo Client").strip() or demo_email.split("@")[0]

    st.header("Orchestrator Agent")
    st.caption("One-click demo: create client from env, add invoices, generate message, then simulate dispute reply. Change DEMO_CLIENT_EMAIL / DEMO_CLIENT_NAME in .env to use any email.")
    st.markdown(f"**Config:** Client email = `{demo_email}` · Name = `{demo_name}`")

    if st.button("Run full demo", type="primary"):
        import html
        progress = st.progress(0, text="Running…")
        st.markdown("---")
        st.subheader("Timeline")
        timeline_placeholder = st.empty()
        steps_html = ['<div class="timeline">']

        def push_step(num, title, body, is_err=False):
            cls = "timeline-step err" if is_err else "timeline-step"
            body_esc = html.escape(body).replace("\n", "<br>")
            steps_html.append(f'<div class="{cls}"><div class="step-num">Step {num}: {title}</div><div>{body_esc}</div></div>')
            timeline_placeholder.markdown("".join(steps_html) + "</div>", unsafe_allow_html=True)

        try:
            # Step 1: Create or get client
            with get_session() as session:
                existing = session.scalars(select(Client).where(Client.email == demo_email)).first()
                if existing:
                    client_id = existing.id
                    push_step(1, "Client", f"Using existing client {existing.name} ({demo_email})")
                else:
                    c = Client(name=demo_name, email=demo_email, contact_preference=ContactPreference.EMAIL.value)
                    session.add(c)
                    session.flush()
                    client_id = c.id
                    push_step(1, "Client", f"Created client {demo_name} ({demo_email})")
            progress.progress(15, text="Step 1 done")

            # Step 2: Create 2 invoices (1 overdue with level so generator finds it, 1 normal)
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
            push_step(2, "Invoices", f"Created 2 invoices: #{inv_overdue_id} (overdue, level 1), #{inv_normal_id} (pending)")
            progress.progress(30, text="Step 2 done")

            # Step 3: Invoice monitor
            from agents.invoice_monitor import run_invoice_monitor
            n_monitor = run_invoice_monitor()
            push_step(3, "Invoice Monitor", f"Updated {n_monitor} overdue invoice(s) (status + escalation level)")
            progress.progress(45, text="Step 3 done")

            # Step 4: Message generator
            from agents.message_generator_agent import run_message_generator
            n_msg = run_message_generator(invoice_ids=[inv_overdue_id])
            push_step(4, "Message Generator", f"Generated {n_msg} message(s) for overdue invoice")
            progress.progress(55, text="Step 4 done")

            # Step 5: Message to mail – only for the overdue invoice we created this run
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
                body_str = (msg_body_preview or "")[:500] + ("..." if len(msg_body_preview or "") > 500 else "")
                push_step(5, "Message to mail", f"Subject: {msg_subject or '(none)'}\n\nBody (will be mailed to {demo_email}):\n\n{body_str}")
            else:
                push_step(5, "Message to mail", f"No pending message for invoice #{inv_overdue_id} (generator created 0 this run).")
            progress.progress(65, text="Step 5 done")

            # Step 6: Process email (dispute)
            from agents.response_handler import process_inbound_email
            dispute_subject = "Re: Invoice"
            dispute_body = "I dispute this invoice. I won't pay."
            process_inbound_email(demo_email, dispute_subject, dispute_body, external_id="orchestrator-demo")
            push_step(6, "Process email (manual)", f"Processed inbound from {demo_email}: subject \"{dispute_subject}\", body \"{dispute_body}\"")
            progress.progress(85, text="Step 6 done")

            # Step 7: Result (read intent/action_taken inside session to avoid DetachedInstanceError)
            with get_session() as session:
                row = session.execute(
                    select(Response.intent, Response.action_taken).order_by(Response.id.desc()).limit(1)
                ).first()
            if row:
                intent, action_taken = row
                push_step(7, "Result", f"Dispute raised. Intent = {intent}, action_taken = {action_taken or '—'}")
            else:
                push_step(7, "Result", "Response recorded; intent = dispute (refusal to pay).")
            progress.progress(100, text="Done")
        except Exception as e:
            push_step(0, "Error", str(e), is_err=True)

        st.balloons()

# ----- Clients -----
elif page == "Clients":
    st.header("Clients")
    st.caption("Manage clients, view invoice and communication history, send messages, and block clients.")

    # Session state for add form, selected client for history, block confirm
    if "client_search_q" not in st.session_state:
        st.session_state.client_search_q = ""
    if "show_add_client" not in st.session_state:
        st.session_state.show_add_client = False
    if "client_history_id" not in st.session_state:
        st.session_state.client_history_id = None

    # Add Client + and Search row
    row1, row2 = st.columns([1, 3])
    with row1:
        if st.button("Add Client +", type="primary"):
            st.session_state.show_add_client = not st.session_state.show_add_client
            st.rerun()
    with row2:
        search_q = st.text_input(
            "Search",
            value=st.session_state.client_search_q,
            placeholder="name, phone, or email",
            key="client_search_input",
            label_visibility="collapsed",
        )
        if search_q != st.session_state.client_search_q:
            st.session_state.client_search_q = search_q
            st.rerun()

    # Add Client form
    if st.session_state.show_add_client:
        with st.form("add_client_form", clear_on_submit=True):
            st.subheader("New client")
            add_name = st.text_input("Name *", placeholder="ACME Corp")
            add_email = st.text_input("Email", placeholder="billing@acme.example.com")
            add_phone = st.text_input("Phone", placeholder="+15551234001")
            add_pref = st.selectbox(
                "Contact preference",
                ["both", "email", "sms"],
                format_func=lambda x: {"both": "Both", "email": "Email", "sms": "SMS"}[x],
            )
            submitted = st.form_submit_button("Create client")
            if submitted and add_name.strip():
                try:
                    with get_session() as session:
                        c = Client(
                            name=add_name.strip(),
                            email=add_email.strip() or None,
                            phone=add_phone.strip() or None,
                            contact_preference=add_pref,
                        )
                        session.add(c)
                    st.success(f"Client «{add_name.strip()}» created.")
                    st.session_state.show_add_client = False
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            elif submitted and not add_name.strip():
                st.warning("Name is required.")

    # Load clients with stats
    clients_data = load_clients_with_stats(st.session_state.client_search_q)

    if not clients_data:
        st.info("No clients found. Add a client or adjust the search.")
    else:
        st.subheader("Client cards")
        for rec in clients_data:
            is_top = rec["invoice_count"] > 0 and rec["paid_pct"] >= 80
            with st.container():
                card_col1, card_col2 = st.columns([3, 1])
                with card_col1:
                    name_display = rec["name"].upper()
                    if is_top:
                        name_display += " ✨ Top Performer"
                    st.markdown(f"**{name_display}**")
                    inv_line = f"Invoices: {rec['invoice_count']} | Paid: {rec['paid_count']}/{rec['invoice_count']} ({rec['paid_pct']}%)"
                    if rec["invoice_count"] == 0:
                        inv_line = "Invoices: 0"
                    st.caption(f"{inv_line} | Last Contact: {rec['last_contact']}")
                with card_col2:
                    view_hist = st.button("View History", key=f"vh_{rec['id']}")
                    send_msg = st.button("Send Message", key=f"sm_{rec['id']}")
                    block_btn = st.button("Block Client", key=f"bl_{rec['id']}")
                    if view_hist:
                        st.session_state.client_history_id = rec["id"] if st.session_state.client_history_id != rec["id"] else None
                        st.rerun()
                    if send_msg:
                        st.session_state.client_send_message_id = rec["id"]
                        st.rerun()
                    if block_btn:
                        try:
                            with get_session() as session:
                                client = session.get(Client, rec["id"])
                                if client:
                                    client.opted_out = True
                                    client.opted_out_at = datetime.now(timezone.utc)
                            st.success(f"«{rec['name']}» blocked.")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                st.divider()

        # Send Message flow (when client_send_message_id set)
        if st.session_state.get("client_send_message_id"):
            cid = st.session_state.client_send_message_id
            with st.expander("Send escalation message", expanded=True):
                with get_session() as session:
                    invs = session.scalars(select(Invoice).where(Invoice.client_id == cid).order_by(Invoice.id)).all()
                if not invs:
                    st.warning("This client has no invoices.")
                else:
                    inv_options = {f"#{inv.id} – {inv.amount} {inv.currency} (due {inv.due_date}, {inv.status})": inv.id for inv in invs}
                    chosen = st.selectbox("Invoice", list(inv_options.keys()))
                    channel = st.radio("Channel", ["sms", "email"], horizontal=True)
                    if st.button("Generate and show message"):
                        try:
                            from agents.message_generator_agent import InvoiceInput, generate_escalation_message
                            inv = next((i for i in invs if i.id == inv_options[chosen]), None)
                            if not inv:
                                st.error("Please select an invoice.")
                            else:
                                client_name = next((r["name"] for r in clients_data if r["id"] == cid), "Unknown")
                                inv_input = InvoiceInput(
                                    invoice_id=str(inv.id),
                                    client_name=client_name,
                                    amount=inv.amount,
                                    currency=inv.currency,
                                    due_date=inv.due_date,
                                    days_overdue=inv.days_overdue or 0,
                                    level=inv.escalation_level or 1,
                                    channel=channel,
                                    additional_context=None,
                                )
                                msg = generate_escalation_message(inv_input)
                                st.success("Message generated.")
                                st.text_area("Body", value=msg.body, height=120, disabled=True)
                        except Exception as e:
                            st.error(str(e))
                    if st.button("Close", key="close_send_msg"):
                        st.session_state.pop("client_send_message_id", None)
                        st.rerun()

        # Communication History table (when a client is selected for history)
        if st.session_state.client_history_id:
            st.subheader("Communication history")
            comms = load_client_communications(st.session_state.client_history_id)
            client_name = next((r["name"] for r in clients_data if r["id"] == st.session_state.client_history_id), "")
            st.caption(f"Showing history for **{client_name}**.")
            if not comms:
                st.info("No communications yet.")
            else:
                df_comm = pd.DataFrame(comms)
                # Show ✅ for Done in status
                df_display = df_comm.copy()
                df_display["status"] = df_display["status"].apply(lambda s: "✅ Done" if s == "Done" else s)
                st.dataframe(df_display, use_container_width=True, hide_index=True)

# ----- Invoice Monitoring Activity -----
elif page == "Invoice Monitoring Activity":
    st.header("Invoice Monitoring Agent Activity")
    st.caption("Invoices marked overdue and their escalation levels. Run the monitor to update from pending → overdue.")

    activity_list = load_overdue_invoices_activity()
    if st.button("Run Invoice Monitor", type="primary"):
        try:
            from agents.invoice_monitor import run_invoice_monitor
            n = run_invoice_monitor()
            st.success(f"Updated **{n}** invoice(s) to overdue (or refreshed days/level).")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    if not activity_list:
        st.info("No overdue invoices. The monitor marks invoices overdue when due date has passed; run it from the orchestrator or above.")
    else:
        st.subheader("Overdue invoices (current state)")
        df_act = pd.DataFrame([
            {
                "Invoice": a["id"],
                "Client": a["client_name"],
                "Amount": f"{a['amount']} {a['currency']}",
                "Due date": str(a["due_date"]),
                "Days overdue": a["days_overdue"],
                "Level": a["escalation_level"],
            }
            for a in activity_list
        ])
        st.dataframe(df_act, use_container_width=True, hide_index=True)

# ----- Message Generator -----
elif page == "Message Generator":
    st.header("Message Generator")
    st.caption("Generate escalation messages for overdue invoices using Ollama. Run batch for all eligible or generate for a single invoice.")

    import os
    ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
    st.markdown(f"**Config:** `OLLAMA_API_URL` → `{ollama_url}` · Model: **{ollama_model}**")

    eligible = load_eligible_overdue_invoices()
    pending = load_pending_outbound_communications()

    st.subheader("1. Run batch generator")
    st.caption("Generate outbound email for all eligible overdue invoices. Messages are saved as pending; send them from **Send email to selected**.")
    run_all_btn = st.button("Run Message Generator (all eligible)", type="primary")
    if run_all_btn:
        try:
            from agents.message_generator_agent import run_message_generator
            created = run_message_generator()
            st.success(f"Created **{created}** communication(s). Send from **Send email to selected**.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    st.subheader("2. Eligible overdue invoices")
    if not eligible:
        st.info("No eligible overdue invoices. Run **Invoice Monitoring Activity** first.")
    else:
        df_eligible = pd.DataFrame([
            {"Invoice": e["id"], "Client": e["client_name"], "Amount": f"{e['amount']} {e['currency']}", "Due date": str(e["due_date"]), "Days overdue": e["days_overdue"], "Level": e["escalation_level"]}
            for e in eligible
        ])
        st.dataframe(df_eligible, use_container_width=True, hide_index=True)
        selected_ids = st.multiselect(
            "Select invoice IDs",
            options=[e["id"] for e in eligible],
            format_func=lambda i: next(f"#{i} – {e['client_name']} ({e['amount']} {e['currency']})" for e in eligible if e["id"] == i),
            key="msg_gen_selected_invoices",
        )
        if selected_ids and st.button("Generate for selected invoices"):
            try:
                from agents.message_generator_agent import run_message_generator
                created = run_message_generator(invoice_ids=selected_ids)
                st.success(f"Created **{created}** communication(s).")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.subheader("3. Generate single message (preview)")
    if "last_generated_msg" not in st.session_state:
        st.session_state.last_generated_msg = None
    if not eligible:
        st.session_state.last_generated_msg = None
    else:
        inv_options = {f"#{e['id']} – {e['client_name']} · {e['amount']} {e['currency']} · L{e['escalation_level']}": e for e in eligible}
        single_choice = st.selectbox("Invoice", options=list(inv_options.keys()), key="msg_single_inv")
        chosen = inv_options[single_choice] if single_choice else None
        if chosen:
            channel = st.radio("Channel", ["email", "sms"], horizontal=True, key="msg_single_channel")
            additional_context = st.text_area("Additional context (optional)", height=60, key="msg_single_ctx")
            if st.button("Generate message (preview)"):
                try:
                    from agents.message_generator_agent import InvoiceInput, generate_escalation_message
                    inv_input = InvoiceInput(
                        invoice_id=str(chosen["id"]), client_name=chosen["client_name"], amount=chosen["amount"],
                        currency=chosen["currency"], due_date=chosen["due_date"], days_overdue=chosen["days_overdue"],
                        level=chosen["escalation_level"], channel=channel, additional_context=additional_context.strip() or None,
                    )
                    msg = generate_escalation_message(inv_input)
                    st.session_state.last_generated_msg = {"msg": msg, "chosen": chosen}
                    st.success("Message generated.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        if st.session_state.last_generated_msg:
            lg = st.session_state.last_generated_msg
            msg, saved_chosen = lg["msg"], lg["chosen"]
            with st.expander("Last generated message (preview)", expanded=True):
                if msg.subject:
                    st.text_input("Subject", value=msg.subject or "", disabled=True, key="preview_subj")
                st.text_area("Body", value=msg.body, height=180, disabled=True, key="preview_body")
                if st.button("Save to communications (pending send)", key="save_comm_btn"):
                    with get_session() as session:
                        comm = Communication(
                            invoice_id=saved_chosen["id"], channel=msg.channel, direction="outbound",
                            body=msg.body, subject=msg.subject, escalation_level=msg.level, sent_at=None,
                        )
                        session.add(comm)
                    st.session_state.last_generated_msg = None
                    st.success("Saved. Send from **Send email to selected**.")
                    st.rerun()
                if st.button("Clear preview", key="clear_preview_btn"):
                    st.session_state.last_generated_msg = None
                    st.rerun()

    st.subheader("4. Pending outbound")
    pending = load_pending_outbound_communications()
    if not pending:
        st.info("No pending outbound communications.")
    else:
        st.dataframe(pd.DataFrame([
            {"ID": p["id"], "Invoice": p["invoice_id"], "Client": p["client_name"], "Channel": p["channel"].upper(), "Level": f"L{p['escalation_level']}" if p["escalation_level"] else "—", "Preview": p["body_preview"]}
            for p in pending
        ]), use_container_width=True, hide_index=True)

# ----- Send email to selected -----
elif page == "Send email to selected":
    st.header("Send email to selected")
    st.caption("Choose pending outbound messages and send them via SMTP (Gmail).")

    pending = load_pending_outbound_communications()
    if not pending:
        st.info("No pending messages. Generate messages from **Message Generator** first.")
    else:
        options = [f"#{p['id']} – {p['client_name']} · Invoice #{p['invoice_id']} · {p['channel'].upper()}" for p in pending]
        selected = st.multiselect("Select communications to send", options=options, key="send_sel_comms")
        if selected:
            selected_ids = [pending[i]["id"] for i in [options.index(s) for s in selected]]
            if st.button("Send selected via SMTP", type="primary"):
                try:
                    from agents.communication_dispatcher import send_selected_communications
                    n = send_selected_communications(selected_ids)
                    st.success(f"Sent **{n}** email(s).")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        st.markdown("---")
        st.subheader("Pending list")
        st.dataframe(pd.DataFrame([
            {"ID": p["id"], "Invoice": p["invoice_id"], "Client": p["client_name"], "Channel": p["channel"].upper(), "Preview": p["body_preview"]}
            for p in pending
        ]), use_container_width=True, hide_index=True)

# ----- Response handling -----
elif page == "Response handling":
    st.header("Response Handling")
    st.caption("Process inbound email: poll IMAP (Gmail) or submit manually. Responses are classified (pay/dispute/ignore) and can mark invoices paid.")

    if st.button("Poll IMAP for new emails", type="primary"):
        try:
            from agents.response_handler import process_pending_responses
            n = process_pending_responses()
            st.success(f"Processed **{n}** new email(s) from inbox.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    st.subheader("Process one email manually")
    with st.form("response_manual_email"):
        from_addr = st.text_input("From email", placeholder="client@example.com", help="Must match a client email in DB")
        subject = st.text_input("Subject", value="Re: Invoice")
        body = st.text_area("Message body", value="We have paid the invoice. Thank you.", height=120)
        if st.form_submit_button("Process email"):
            if from_addr and from_addr.strip():
                try:
                    from agents.response_handler import process_inbound_email
                    process_inbound_email(from_addr.strip(), subject.strip(), body.strip(), external_id="dashboard-email")
                    st.success("Email processed. See latest responses below.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("From email is required.")

    st.subheader("Latest responses")
    df = load_responses_df()
    if df.empty:
        st.info("No responses yet. Poll IMAP or submit an email above.")
    else:
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

# ----- Data browser -----
elif page == "Data browser":
    st.header("Data browser")
    tab1, tab2, tab3, tab4 = st.tabs(["Clients", "Invoices", "Communications", "Responses"])
    with tab1:
        df = load_clients_df()
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab2:
        df = load_invoices_df()
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab3:
        df = load_communications_df()
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab4:
        df = load_responses_df()
        st.dataframe(df, use_container_width=True, hide_index=True)

# ----- Pipeline -----
elif page == "Pipeline (run agents)":
    st.header("Pipeline – run agents step by step")
    st.caption("Run each step and see the effect in the UI. Use **Data browser** or **Overview** after each step.")

    # Seed
    with st.expander("1. Seed sample data", expanded=True):
        if st.button("Seed sample data (init DB + 3 clients, 3 invoices)"):
            try:
                init_db()
                from db.seed_sample_data import seed_sample_data
                seed_sample_data()
                st.markdown('<div class="step-result step-ok">✅ DB initialized and sample data seeded (or already present).</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div class="step-result step-err">❌ {e}</div>', unsafe_allow_html=True)
            st.rerun()

    # Monitor
    with st.expander("2. Invoice Monitor (mark overdue, set escalation)"):
        if st.button("Run Invoice Monitor"):
            try:
                from agents.invoice_monitor import run_invoice_monitor
                n = run_invoice_monitor()
                st.markdown(f'<div class="step-result step-ok">✅ Updated {n} overdue invoice(s).</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div class="step-result step-err">❌ {e}</div>', unsafe_allow_html=True)
            st.rerun()

    # Message Generator
    with st.expander("3. Message Generator (Ollama – create outbound messages)"):
        st.caption("Requires Ollama running with qwen2.5:7b-instruct-q4_K_M (e.g. ollama run qwen2.5:7b-instruct-q4_K_M).")
        if st.button("Run Message Generator"):
            try:
                from agents.message_generator_agent import run_message_generator
                created = run_message_generator()
                st.markdown(f'<div class="step-result step-ok">✅ Created {created} communication(s) (outbound, not yet sent).</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div class="step-result step-err">❌ {e}</div>', unsafe_allow_html=True)
            st.rerun()

    # Dispatcher
    with st.expander("4. Communication Dispatcher (send via SMTP)"):
        st.caption("Set SMTP_* in .env (Gmail: smtp.gmail.com:587, app password). Or use **Send email to selected**.")
        if st.button("Run Communication Dispatcher"):
            try:
                from agents.communication_dispatcher import run_communication_dispatcher
                sent = run_communication_dispatcher()
                st.markdown(f'<div class="step-result step-ok">✅ Sent {sent} message(s).</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div class="step-result step-err">❌ {e}</div>', unsafe_allow_html=True)
            st.rerun()

    # Analytics
    with st.expander("5. Analytics Reporter (CSV + chart)"):
        if st.button("Run Analytics Reporter"):
            try:
                from agents.analytics_reporter import run_analytics_reporter
                path = run_analytics_reporter()
                st.markdown(f'<div class="step-result step-ok">✅ Report written to: <code>{path}</code></div>', unsafe_allow_html=True)
                if Path(path).exists():
                    st.download_button("Download CSV", data=Path(path).read_text(encoding="utf-8"), file_name=Path(path).name, mime="text/csv")
            except Exception as e:
                st.markdown(f'<div class="step-result step-err">❌ {e}</div>', unsafe_allow_html=True)
            st.rerun()

    # Run full pipeline
    st.markdown("---")
    if st.button("▶ Run full pipeline (Monitor → Generator → Dispatcher)", type="primary"):
        progress = st.progress(0, text="Running pipeline…")
        try:
            from agents.invoice_monitor import run_invoice_monitor
            from agents.message_generator_agent import run_message_generator
            from agents.communication_dispatcher import run_communication_dispatcher
            progress.progress(25, text="Invoice Monitor…")
            n_monitor = run_invoice_monitor()
            progress.progress(50, text="Message Generator…")
            n_gen = run_message_generator()
            progress.progress(75, text="Communication Dispatcher…")
            n_sent = run_communication_dispatcher()
            progress.progress(100, text="Done.")
            st.success(f"Monitor: {n_monitor} updated · Generator: {n_gen} created · Dispatcher: {n_sent} sent. Use **Refresh all data** in the sidebar to update tables.")
        except Exception as e:
            progress.progress(100)
            st.error(str(e))

# ----- Voice call test -----
elif page == "Voice call test":
    st.header("Voice call test")
    st.caption("Place a test Twilio voice call using your configured credentials. This does not depend on any specific invoice.")

    import os

    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    default_to = (os.environ.get("ESCALATION_CALL_TO") or "8019213363").strip()

    col1, col2 = st.columns(2)
    with col1:
        to_number = st.text_input(
            "Destination phone number",
            value=default_to,
            help="Use full E.164 format where possible (e.g. +18019213363).",
        )
    with col2:
        st.markdown("**Twilio configuration**")
        if not sid or not token or not from_num:
            st.error("Missing Twilio credentials. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in .env and restart the dashboard.")
        else:
            st.success(f"Ready – calls will be placed from `{from_num}`.")

    if st.button("Place test voice call", type="primary"):
        if not sid or not token or not from_num:
            st.error("Twilio is not configured. Please set credentials in .env first.")
        elif not to_number.strip():
            st.error("Enter a destination phone number.")
        else:
            try:
                from twilio.rest import Client as TwilioClient  # type: ignore[import]
            except Exception as e:
                st.error(f"Twilio client library not available: {e}")
            else:
                try:
                    client = TwilioClient(sid, token)
                    call = client.calls.create(
                        url="http://demo.twilio.com/docs/voice.xml",
                        to=to_number.strip(),
                        from_=from_num,
                    )
                    sid_str = getattr(call, "sid", "") or "(no SID returned)"
                    st.success(f"Call placed to {to_number.strip()}. Call SID: {sid_str}")
                except Exception as e:
                    st.error(f"Failed to place call: {e}")

# ----- Simulate inbound -----
elif page == "Simulate inbound":
    st.header("Simulate inbound message")
    st.caption("Simulate an SMS or email reply. The response handler will classify intent and optionally update invoice status (e.g. mark paid).")

    mode = st.radio("Channel", ["SMS", "Email"], horizontal=True)

    if mode == "SMS":
        from_phone = st.text_input("From phone", value="+15551234001", help="Must match a client phone in DB to link invoice.")
        body = st.text_area("Message body", value="I have paid the invoice.", height=100)
        if st.button("Process inbound SMS"):
            try:
                from agents.response_handler import process_inbound_sms
                process_inbound_sms(from_phone, body.strip(), external_id="dashboard-sms")
                st.success("SMS processed. Check **Data browser → Responses** and **Invoices** (status may have changed).")
            except Exception as e:
                st.error(str(e))
            st.rerun()
    else:
        from_addr = st.text_input("From email", value="billing@acme.example.com", help="Must match a client email in DB.")
        subject = st.text_input("Subject", value="Re: Invoice")
        body = st.text_area("Message body", value="We have paid the invoice. Thank you.", height=100)
        if st.button("Process inbound email"):
            try:
                from agents.response_handler import process_inbound_email
                process_inbound_email(from_addr.strip(), subject.strip(), body.strip(), external_id="dashboard-email")
                st.success("Email processed. Check **Data browser → Responses** and **Invoices**.")
            except Exception as e:
                st.error(str(e))
            st.rerun()

    st.markdown("---")
    st.subheader("Latest responses")
    df = load_responses_df()
    if df.empty:
        st.info("No responses yet. Simulate an inbound message above.")
    else:
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)
