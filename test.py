from datetime import date

from message_generator_agent import Invoice, generate_escalation_message

msg = generate_escalation_message(
    Invoice(
        invoice_id="123",
        client_name="Acme Corp",
        amount=1000.0,
        currency="USD",
        due_date=date(2025, 1, 31),
        days_overdue=10,
        level=2,
        channel="sms",
    )
)