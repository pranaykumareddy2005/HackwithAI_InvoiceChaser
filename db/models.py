"""SQLAlchemy models for Invoice Chaser shared database."""

from datetime import date, datetime
from typing import Optional

from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""

    pass


# Enums for status and preferences
class InvoiceStatus(str, PyEnum):
    PENDING = "pending"
    OVERDUE = "overdue"
    PROMISE_TO_PAY = "promise_to_pay"
    PAID = "paid"


class ContactPreference(str, PyEnum):
    EMAIL = "email"
    SMS = "sms"
    BOTH = "both"


class CommunicationDirection(str, PyEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class ResponseIntent(str, PyEnum):
    PAY = "pay"
    DISPUTE = "dispute"
    IGNORE = "ignore"
    UNKNOWN = "unknown"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_preference: Mapped[str] = mapped_column(
        String(20), default=ContactPreference.BOTH.value, nullable=False
    )
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="client")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=InvoiceStatus.PENDING.value, nullable=False
    )
    days_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalation_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    human_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    client: Mapped["Client"] = relationship("Client", back_populates="invoices")
    communications: Mapped[list["Communication"]] = relationship(
        "Communication", back_populates="invoice"
    )


class Communication(Base):
    __tablename__ = "communications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email, sms
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # outbound, inbound
    body: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    escalation_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    twilio_sid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="communications")
    responses: Mapped[list["Response"]] = relationship(
        "Response", back_populates="communication", foreign_keys="Response.communication_id"
    )


class Response(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    communication_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("communications.id"), nullable=True
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(
        String(20), default=ResponseIntent.UNKNOWN.value, nullable=False
    )
    intent_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    action_taken: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    communication: Mapped[Optional["Communication"]] = relationship(
        "Communication",
        back_populates="responses",
        foreign_keys=[communication_id],
    )
