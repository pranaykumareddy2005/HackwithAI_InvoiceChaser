from datetime import date, timedelta

from sqlalchemy import select

from db.database import init_db, get_session
from db.models import Client, Invoice, InvoiceStatus
from agents.invoice_monitor import run_invoice_monitor, update_invoice_if_overdue


def test_run_invoice_monitor_updates_overdue_status_and_levels(temp_db_path):
    init_db()
    today = date.today()

    with get_session() as session:
        client = Client(name="Test Client", email="test@example.com")
        session.add(client)
        session.flush()

        inv_level1 = Invoice(
            client_id=client.id,
            amount=100.0,
            currency="USD",
            due_date=today - timedelta(days=3),
        )
        inv_level2 = Invoice(
            client_id=client.id,
            amount=200.0,
            currency="USD",
            due_date=today - timedelta(days=10),
        )
        session.add_all([inv_level1, inv_level2])

    updated = run_invoice_monitor()
    assert updated == 2

    with get_session() as session:
        invoices = session.scalars(select(Invoice).order_by(Invoice.amount)).all()
        assert len(invoices) == 2

        inv1, inv2 = invoices
        assert inv1.status == InvoiceStatus.OVERDUE.value
        assert inv1.days_overdue == 3
        assert inv1.escalation_level == 1

        assert inv2.status == InvoiceStatus.OVERDUE.value
        assert inv2.days_overdue == 10
        assert inv2.escalation_level == 2


def test_update_invoice_if_overdue_marks_past_due(temp_db_path):
    init_db()
    today = date.today()

    with get_session() as session:
        client = Client(name="Test Client", email="test@example.com")
        session.add(client)
        session.flush()
        inv = Invoice(
            client_id=client.id,
            amount=500.0,
            currency="USD",
            due_date=today - timedelta(days=5),
            status=InvoiceStatus.PENDING.value,
        )
        session.add(inv)
        session.flush()
        inv_id = inv.id

    assert update_invoice_if_overdue(inv_id) is True

    with get_session() as session:
        inv = session.get(Invoice, inv_id)
        assert inv.status == InvoiceStatus.OVERDUE.value
        assert inv.days_overdue == 5
        assert inv.escalation_level == 1


def test_update_invoice_if_overdue_skips_future_due(temp_db_path):
    init_db()
    today = date.today()

    with get_session() as session:
        client = Client(name="Test Client", email="test@example.com")
        session.add(client)
        session.flush()
        inv = Invoice(
            client_id=client.id,
            amount=500.0,
            currency="USD",
            due_date=today + timedelta(days=5),
            status=InvoiceStatus.PENDING.value,
        )
        session.add(inv)
        session.flush()
        inv_id = inv.id

    assert update_invoice_if_overdue(inv_id) is False

    with get_session() as session:
        inv = session.get(Invoice, inv_id)
        assert inv.status == InvoiceStatus.PENDING.value
        assert inv.days_overdue == 0

