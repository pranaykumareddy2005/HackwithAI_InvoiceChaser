"""
Demo workflow: init DB, seed sample data, run chase pipeline once (Monitor -> Generator -> Dispatcher), then Analytics.
Usage: python run_demo.py
"""

import sys


def main() -> None:
    from db.database import init_db
    from db.seed_sample_data import seed_sample_data
    from agents.invoice_monitor import run_invoice_monitor
    from agents.message_generator_agent import run_message_generator
    from agents.communication_dispatcher import run_communication_dispatcher
    from agents.analytics_reporter import run_analytics_reporter

    print("1. Initializing DB and seeding sample invoices...")
    init_db()
    seed_sample_data()

    print("2. Running Invoice Monitor (mark overdue, set escalation levels)...")
    n = run_invoice_monitor()
    print(f"   Updated {n} overdue invoice(s).")

    print("3. Running Message Generator (create outbound messages)...")
    created = run_message_generator()
    print(f"   Created {created} message(s) in communications.")

    print("4. Running Communication Dispatcher (send via Twilio/SMTP)...")
    sent = run_communication_dispatcher()
    print(f"   Sent {sent} message(s). (Set TWILIO_* or SMTP_* in .env to actually send.)")

    print("5. Running Analytics Reporter...")
    path = run_analytics_reporter()
    print(f"   Report written to {path}.")

    print("Done. Escalation demo complete.")


if __name__ == "__main__":
    main()
