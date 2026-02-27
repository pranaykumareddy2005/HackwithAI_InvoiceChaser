"""Backward-compatible entry point: re-exports from agents.message_generator_agent."""

from agents.message_generator_agent import (
    EscalationMessage,
    InvoiceInput as Invoice,
    generate_escalation_message,
    run_message_generator,
)

__all__ = ["Invoice", "EscalationMessage", "generate_escalation_message", "run_message_generator"]
