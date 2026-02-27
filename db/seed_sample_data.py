"""Seed sample clients and invoices for demo workflow."""

from datetime import date, timedelta

from sqlalchemy import select

from db.database import get_session, init_db
from db.models import Client, ContactPreference, Invoice, InvoiceStatus


def seed_sample_data() -> None:
    """Create sample clients and invoices for escalation demo."""
    init_db()
    with get_session() as session:
        # Avoid duplicate seeds
        if session.scalar(select(Client).limit(1)) is not None:
            print("Data already exists; skipping seed.")
            return

        today = date.today()

        clients = [
            Client(
                name="Acme Corp",
                email="billing@acme.example.com",
                phone="+15551234001",
                contact_preference=ContactPreference.BOTH.value,
            ),
            Client(
                name="Beta Industries",
                email="finance@beta.example.com",
                phone="+15551234002",
                contact_preference=ContactPreference.EMAIL.value,
            ),
            Client(
                name="Gamma LLC",
                email="accounts@gamma.example.com",
                phone="+15551234003",
                contact_preference=ContactPreference.SMS.value,
            ),
        ]
        for c in clients:
            session.add(c)
        session.flush()

        # Invoices: mix of pending, overdue at different levels
        # Level 1: 1-7 days overdue
        # Level 2: 8-14 days overdue
        # Level 3: 15+ days overdue
        invoices = [
            Invoice(
                client_id=clients[0].id,
                amount=1500.00,
                currency="USD",
                due_date=today - timedelta(days=5),
                status=InvoiceStatus.PENDING.value,
                days_overdue=0,
                escalation_level=None,
            ),
            Invoice(
                client_id=clients[1].id,
                amount=3200.50,
                currency="USD",
                due_date=today - timedelta(days=10),
                status=InvoiceStatus.PENDING.value,
                days_overdue=0,
                escalation_level=None,
            ),
            Invoice(
                client_id=clients[2].id,
                amount=875.00,
                currency="USD",
                due_date=today - timedelta(days=20),
                status=InvoiceStatus.PENDING.value,
                days_overdue=0,
                escalation_level=None,
            ),
        ]
        for inv in invoices:
            session.add(inv)

        print("Seeded 3 clients and 3 sample invoices (varying due dates).")


if __name__ == "__main__":
    seed_sample_data()
