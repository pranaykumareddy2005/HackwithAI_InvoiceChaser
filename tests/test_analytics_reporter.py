from datetime import date
from pathlib import Path

from agents.analytics_reporter import run_analytics_reporter
from db.database import init_db, get_session
from db.models import Communication, Invoice, InvoiceStatus, Response


def test_run_analytics_reporter_creates_csv_report(temp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))

    init_db()
    with get_session() as session:
        inv1 = Invoice(
            client_id=1,
            amount=100.0,
            currency="USD",
            due_date=date(2025, 1, 1),
            status=InvoiceStatus.OVERDUE.value,
        )
        inv2 = Invoice(
            client_id=2,
            amount=200.0,
            currency="USD",
            due_date=date(2025, 1, 2),
            status=InvoiceStatus.PAID.value,
        )
        session.add_all([inv1, inv2])
        session.flush()

        comm = Communication(
            invoice_id=inv1.id,
            channel="sms",
            direction="outbound",
            body="Test body",
            escalation_level=1,
        )
        resp = Response(
            communication_id=None,
            raw_content="OK",
            intent="pay",
        )
        session.add_all([comm, resp])

    report_path_str = run_analytics_reporter()
    report_path = Path(report_path_str)

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "collection_rate_pct" in content
    assert "invoices_overdue_or_paid" in content
    assert "responses_pay" in content

