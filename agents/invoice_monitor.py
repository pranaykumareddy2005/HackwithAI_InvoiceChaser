"""Invoice Monitor Agent: marks invoices overdue as soon as due date has passed.

Runs in two ways for best responsiveness:
- On a short interval (e.g. every 1 min) via orchestrator – catches all overdue
  invoices within ~1 minute of the calendar day rolling over.
- Immediately after create/update of an invoice (API/dashboard) – so past-due
  invoices are marked overdue without waiting for the next scheduled run.
"""

from datetime import date
from pathlib import Path
from typing import List, Tuple

from sqlalchemy import select

from db.database import get_session
from db.models import Invoice, InvoiceStatus

# Default escalation: 1-7 -> 1, 8-14 -> 2, 15+ -> 3
DEFAULT_ESCALATION = [(7, 1), (14, 2), (999, 3)]


def _load_escalation_rules() -> List[Tuple[int, int]]:
    """Load (max_days, level) from config/escalation_rules.yaml."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "escalation_rules.yaml"
    if not config_path.exists():
        return DEFAULT_ESCALATION
    try:
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f)
        levels = data.get("levels", [])
        return [(r["max_days"], r["level"]) for r in levels]
    except Exception:
        return DEFAULT_ESCALATION


def _level_for_days_overdue(days: int, rules: List[Tuple[int, int]]) -> int:
    for max_days, level in rules:
        if days <= max_days:
            return level
    return rules[-1][1] if rules else 3


def run_invoice_monitor() -> int:
    """
    Find all invoices that are past due (due_date < today), not paid, and not
    human-overridden; set status to overdue, days_overdue, and escalation_level.
    Returns count of invoices updated.
    """
    rules = _load_escalation_rules()
    today = date.today()
    updated = 0
    with get_session() as session:
        stmt = select(Invoice).where(
            Invoice.due_date < today,
            Invoice.status.notin_([InvoiceStatus.PAID.value, InvoiceStatus.PROMISE_TO_PAY.value]),
            Invoice.human_override.is_(False),
        )
        rows = session.scalars(stmt).all()
        for inv in rows:
            days = (today - inv.due_date).days
            level = _level_for_days_overdue(days, rules)
            inv.status = InvoiceStatus.OVERDUE.value
            inv.days_overdue = days
            inv.escalation_level = level
            updated += 1
    return updated


def update_invoice_if_overdue(invoice_id: int) -> bool:
    """
    If the given invoice is past due (due_date < today), not paid, and not
    human-overridden, update it to overdue and set days_overdue and
    escalation_level. Call this right after creating or updating an invoice
    so status flips to overdue immediately when due date has passed.
    Returns True if the invoice was updated, False otherwise.
    """
    rules = _load_escalation_rules()
    today = date.today()
    with get_session() as session:
        inv = session.get(Invoice, invoice_id)
        if not inv:
            return False
        if inv.status in (InvoiceStatus.PAID.value, InvoiceStatus.PROMISE_TO_PAY.value) or inv.human_override:
            return False
        if inv.due_date >= today:
            return False
        days = (today - inv.due_date).days
        level = _level_for_days_overdue(days, rules)
        inv.status = InvoiceStatus.OVERDUE.value
        inv.days_overdue = days
        inv.escalation_level = level
    return True
