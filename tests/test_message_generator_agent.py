from datetime import date

from agents import message_generator_agent as mga
from agents.message_generator_agent import (
    EscalationMessage,
    InvoiceInput,
    generate_escalation_message,
    run_message_generator,
)
from db.database import init_db, get_session
from db.models import Client, Communication, Invoice, InvoiceStatus


def test_generate_escalation_message_uses_ollama_stub(monkeypatch):
    def fake_ollama_generate(prompt: str) -> str:
        assert "Generate a" in prompt
        return "Test SMS message from Ollama"

    monkeypatch.setattr(mga, "_ollama_generate", fake_ollama_generate)

    invoice = InvoiceInput(
        invoice_id="INV-1",
        client_name="Test Client",
        amount=100.0,
        currency="USD",
        due_date=date(2025, 1, 31),
        days_overdue=5,
        level=1,
        channel="sms",
    )

    msg = generate_escalation_message(invoice)

    assert isinstance(msg, EscalationMessage)
    assert msg.channel == "sms"
    assert "Test SMS message from Ollama" in msg.body


def test_run_message_generator_creates_communications(temp_db_path, monkeypatch):
    def fake_generate(invoice: InvoiceInput) -> EscalationMessage:
        return EscalationMessage(
            invoice_id=invoice.invoice_id,
            level=invoice.level,
            channel=invoice.channel,
            subject="Reminder",
            body=f"Dear {invoice.client_name}, invoice {invoice.invoice_id} is overdue.",
        )

    monkeypatch.setattr(mga, "generate_escalation_message", fake_generate)

    init_db()
    with get_session() as session:
        client = Client(
            name="Acme Corp",
            email="billing@acme.example.com",
            phone="+15551234001",
        )
        session.add(client)
        session.flush()

        inv = Invoice(
            client_id=client.id,
            amount=150.0,
            currency="USD",
            due_date=date(2025, 1, 1),
            status=InvoiceStatus.OVERDUE.value,
            days_overdue=10,
            escalation_level=2,
        )
        session.add(inv)

    created = run_message_generator()
    assert created > 0

    with get_session() as session:
        comms = session.query(Communication).all()
        assert len(comms) == created
        for c in comms:
            assert c.direction == "outbound"
            assert c.body

