"""Analytics Reporter Agent: KPIs and reports from DB (CSV/charts)."""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

from db.database import get_session
from db.models import Client, Communication, Invoice, InvoiceStatus, Response


REPORT_DIR = Path(os.getenv("REPORT_DIR", "reports"))


def _run_query(session, stmt):
    return list(session.execute(stmt).all())


def run_analytics_reporter() -> str:
    """
    Compute KPIs, write CSV and optional charts to REPORT_DIR.
    Returns path to the main report file.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = datetime.utcnow().strftime("%Y%m%d_%H%M")
    report_path = REPORT_DIR / f"analytics_{prefix}.csv"

    with get_session() as session:
        # Collection rate: % of chased (overdue at some point) invoices that are now paid
        overdue_count = session.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.status.in_([InvoiceStatus.OVERDUE.value, InvoiceStatus.PAID.value])
            )
        ) or 0
        paid_after_chase = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.PAID.value)
        ) or 0
        collection_rate = (paid_after_chase / overdue_count * 100) if overdue_count else 0.0

        # Outbound communications count by channel and escalation level
        comm_stmt = (
            select(
                Communication.channel,
                Communication.escalation_level,
                func.count(Communication.id).label("count"),
            )
            .where(Communication.direction == "outbound")
            .group_by(Communication.channel, Communication.escalation_level)
        )
        comm_rows = _run_query(session, comm_stmt)

        # Response count by intent
        resp_stmt = (
            select(Response.intent, func.count(Response.id).label("count"))
            .group_by(Response.intent)
        )
        resp_rows = _run_query(session, resp_stmt)

        # Build report DataFrame
        rows = [
            {"metric": "collection_rate_pct", "value": collection_rate},
            {"metric": "invoices_overdue_or_paid", "value": overdue_count},
            {"metric": "invoices_paid", "value": paid_after_chase},
        ]
        for row in comm_rows:
            ch, lvl, cnt = row[0], row[1], row[2]
            rows.append({"metric": f"sent_{ch}_level{lvl or 0}", "value": cnt})
        for row in resp_rows:
            intent, cnt = row[0], row[1]
            rows.append({"metric": f"responses_{intent}", "value": cnt})

        df = pd.DataFrame(rows)
        df.to_csv(report_path, index=False)

        # Optional: simple chart (success by channel if we have sent + response data)
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(6, 4))
            metrics = [r["metric"] for r in rows if r["metric"].startswith("sent_")]
            values = [r["value"] for r in rows if r["metric"].startswith("sent_")]
            if metrics and values:
                ax.bar(metrics, values)
                ax.set_ylabel("Count")
                ax.set_title("Outbound communications by channel and level")
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()
                plt.savefig(REPORT_DIR / f"chart_{prefix}.png", dpi=100)
                plt.close()
        except Exception:
            pass

    return str(report_path)
