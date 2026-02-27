from datetime import date

from sqlalchemy import select

from agents import communication_dispatcher as cd
from agents.communication_dispatcher import run_communication_dispatcher, send_selected_communications
from db.database import init_db, get_session
from db.models import Client, Communication, Invoice, InvoiceStatus


def test_run_communication_dispatcher_sends_email_with_stub(temp_db_path, monkeypatch):
    def fake_send_email(to: str, subject: str, body: str) -> str:
        return f"email-{to}"

    monkeypatch.setattr(cd, "_send_email", fake_send_email)

    init_db()
    with get_session() as session:
        client = Client(
            name="Email Client",
            phone=None,
            email="email@example.com",
        )
        session.add(client)
        session.flush()
        inv = Invoice(
            client_id=client.id,
            amount=200.0,
            currency="USD",
            due_date=date(2025, 1, 1),
            status=InvoiceStatus.OVERDUE.value,
        )
        session.add(inv)
        session.flush()
        comm = Communication(
            invoice_id=inv.id,
            channel="email",
            direction="outbound",
            body="Email body",
            subject="Subject",
        )
        session.add(comm)

    sent = run_communication_dispatcher()
    assert sent == 1

    with get_session() as session:
        comms = session.scalars(select(Communication)).all()
        assert len(comms) == 1
        assert comms[0].sent_at is not None
        assert comms[0].message_id.startswith("email-")


def test_send_selected_communications(temp_db_path, monkeypatch):
    def fake_send_email(to: str, subject: str, body: str) -> str:
        return f"sent-{to}"

    monkeypatch.setattr(cd, "_send_email", fake_send_email)

    init_db()
    with get_session() as session:
        client = Client(name="C", email="c@example.com")
        session.add(client)
        session.flush()
        inv = Invoice(
            client_id=client.id,
            amount=100.0,
            currency="USD",
            due_date=date(2025, 1, 1),
            status=InvoiceStatus.OVERDUE.value,
        )
        session.add(inv)
        session.flush()
        comm = Communication(
            invoice_id=inv.id,
            channel="email",
            direction="outbound",
            body="Body",
        )
        session.add(comm)
        session.flush()
        cid = comm.id

    n = send_selected_communications([cid])
    assert n == 1
    with get_session() as session:
        c = session.get(Communication, cid)
        assert c.sent_at is not None

