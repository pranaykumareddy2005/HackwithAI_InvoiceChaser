from datetime import date

from message_generator_agent import Invoice, generate_escalation_message


def main() -> None:
    invoice = Invoice(
        invoice_id="TEST-123",
        client_name="Test Client",
        amount=1000.0,
        currency="USD",
        due_date=date(2025, 1, 31),
        days_overdue=5,
        level=1,
        channel="sms",
    )

    msg = generate_escalation_message(invoice)
    print(msg)


if __name__ == "__main__":
    main()

