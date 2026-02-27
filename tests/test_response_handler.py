from datetime import date

import pytest
from sqlalchemy import select

import agents.response_handler as rh
from agents.response_handler import (
    ResponseIntent,
    classify_intent,
    process_inbound_email,
    process_inbound_sms,
)
from db.database import init_db, get_session
from db.models import Client, Invoice, InvoiceStatus, Response


def test_classify_intent_with_ollama_stub(monkeypatch):
    def fake_ollama_generate(prompt: str) -> str:
        assert "Classify the following customer message" in prompt
        return '{"intent": "pay", "confidence": 0.9}'

    monkeypatch.setattr(rh, "_ollama_generate", fake_ollama_generate)

    intent, confidence = classify_intent("I just paid this invoice.")
    assert intent == "pay"
    assert confidence == pytest.approx(0.9, rel=1e-3)


def test_wont_pay_not_marked_as_paid(temp_db_path, monkeypatch):
    """Even if LLM wrongly returns 'pay', refusal phrases must not mark invoice as paid."""
    def fake_ollama_generate(prompt: str) -> str:
        return '{"intent": "pay", "confidence": 0.9}'

    monkeypatch.setattr(rh, "_ollama_generate", fake_ollama_generate)

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
        inv_id = inv.id

    process_inbound_email(
        from_addr="c@example.com",
        subject="I won't pay the invoice",
        body="We will not pay this.",
        external_id="refusal-1",
    )

    with get_session() as session:
        inv = session.get(Invoice, inv_id)
        assert inv.status == InvoiceStatus.OVERDUE.value
        responses = session.scalars(select(Response)).all()
        assert len(responses) == 1
        assert responses[0].intent == ResponseIntent.DISPUTE.value
        assert responses[0].action_taken != "marked_paid"


def test_process_inbound_sms_stop_sets_opt_out(temp_db_path):
    init_db()
    with get_session() as session:
        client = Client(
            name="SMS Client",
            phone="+15551239999",
            email=None,
        )
        session.add(client)

    process_inbound_sms("+15551239999", "STOP")

    with get_session() as session:
        client = session.query(Client).filter_by(phone="+15551239999").one()
        assert client.opted_out is True
        assert client.opted_out_at is not None


def test_process_inbound_email_creates_response_and_may_update_invoice(
    temp_db_path, monkeypatch
):
    def fake_ollama_generate(prompt: str) -> str:
        assert "Classify the following customer message" in prompt
        return '{"intent": "pay", "confidence": 0.95}'

    monkeypatch.setattr(rh, "_ollama_generate", fake_ollama_generate)

    init_db()
    with get_session() as session:
        client = Client(
            name="Email Client",
            email="user@example.com",
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

    process_inbound_email(
        from_addr="user@example.com",
        subject="Paid",
        body="We have paid the invoice.",
        external_id="email-1",
    )

    with get_session() as session:
        responses = session.query(Response).all()
        assert len(responses) == 1
        resp = responses[0]
        assert resp.intent == ResponseIntent.PAY.value
        assert resp.intent_confidence == pytest.approx(0.95, rel=1e-3)

        invoices = session.query(Invoice).order_by(Invoice.id).all()
        assert any(inv.status == InvoiceStatus.PAID.value for inv in invoices)

