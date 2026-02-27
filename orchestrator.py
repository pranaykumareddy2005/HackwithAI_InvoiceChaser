"""Central orchestrator: runs agents on schedule via APScheduler.

Invoice monitor runs every 1 minute so invoices flip to overdue as soon as
the due date has passed (within ~1 min of midnight). The chase pipeline
(message gen + dispatch) still runs on a daily cron.
"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")


def run_invoice_monitor_job() -> None:
    """Mark all past-due invoices as overdue (runs every 1 min for near real-time)."""
    from agents.invoice_monitor import run_invoice_monitor
    n = run_invoice_monitor()
    if n:
        logger.info("Invoice Monitor: updated %s overdue invoice(s)", n)


def run_chase_pipeline() -> None:
    """Run Monitor -> Message Generator -> Dispatcher in sequence."""
    from agents.invoice_monitor import run_invoice_monitor
    from agents.message_generator_agent import run_message_generator
    from agents.communication_dispatcher import run_communication_dispatcher

    logger.info("Starting chase pipeline: Monitor -> Generator -> Dispatcher")
    n = run_invoice_monitor()
    logger.info("Invoice Monitor: updated %s overdue invoice(s)", n)
    run_message_generator()
    logger.info("Message Generator: finished")
    run_communication_dispatcher()
    logger.info("Chase pipeline complete.")


def run_analytics_job() -> None:
    """Run Analytics Reporter (daily/weekly)."""
    from agents.analytics_reporter import run_analytics_reporter

    logger.info("Running Analytics Reporter")
    run_analytics_reporter()
    logger.info("Analytics Reporter: finished.")


def run_response_handler_poll() -> None:
    """Poll for inbound email (IMAP) and process responses."""
    from agents.response_handler import process_pending_responses

    logger.info("Running Response Handler (poll)")
    process_pending_responses()
    logger.info("Response Handler poll: finished.")


def main() -> None:
    scheduler = BlockingScheduler()
    # Invoice monitor: every 1 minute so status flips to overdue as soon as due date passes
    monitor_interval_seconds = int(os.getenv("INVOICE_MONITOR_INTERVAL_SECONDS", "60"))
    scheduler.add_job(
        run_invoice_monitor_job,
        IntervalTrigger(seconds=monitor_interval_seconds),
        id="invoice_monitor",
    )
    # Chase pipeline: daily at 9:00 (message gen + dispatch)
    cron_chase = os.getenv("CRON_CHASE", "0 9 * * *")
    scheduler.add_job(
        run_chase_pipeline,
        CronTrigger.from_crontab(cron_chase),
        id="chase_pipeline",
    )
    # Analytics: weekly Monday 8:00
    cron_analytics = os.getenv("CRON_ANALYTICS", "0 8 * * 1")
    scheduler.add_job(
        run_analytics_job,
        CronTrigger.from_crontab(cron_analytics),
        id="analytics",
    )
    # Response handler (IMAP poll): every 15 min
    cron_responses = os.getenv("CRON_RESPONSES", "*/15 * * * *")
    scheduler.add_job(
        run_response_handler_poll,
        CronTrigger.from_crontab(cron_responses),
        id="response_poll",
    )
    logger.info(
        "Scheduler started. Invoice monitor: every %ss, Chase: %s, Analytics: %s, Responses: %s",
        monitor_interval_seconds, cron_chase, cron_analytics, cron_responses,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
