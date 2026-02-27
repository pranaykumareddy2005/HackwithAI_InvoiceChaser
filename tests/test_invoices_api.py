"""Tests for the Invoices CRUD API (Flask)."""

from datetime import date, timedelta

import pytest

from db.database import get_session, init_db
from db.models import Client, Communication, Invoice, InvoiceStatus


@pytest.fixture
def app_client(temp_db_path):
    """Create Flask app test client with isolated DB."""
    init_db()
    from web.app import app
    return app.test_client()


@pytest.fixture
def sample_client(app_client):
    """Create one client via API and return (client_id, client_data)."""
    r = app_client.post(
        "/api/clients",
        json={"name": "ACME CORP", "email": "billing@acme.example.com", "phone": "+15551234001"},
    )
    assert r.status_code == 201
    data = r.get_json()
    return data["id"], data


@pytest.fixture
def sample_invoice(app_client, sample_client):
    """Create one invoice via API (future due_date so status stays pending). Return (invoice_id, invoice_data)."""
    cid, _ = sample_client
    future = (date.today() + timedelta(days=30)).isoformat()
    r = app_client.post(
        "/api/invoices",
        json={
            "client_id": cid,
            "amount": 1500.0,
            "currency": "USD",
            "due_date": future,
            "status": "pending",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    return data["id"], data


def test_list_invoices_empty(app_client):
    r = app_client.get("/api/invoices")
    assert r.status_code == 200
    assert r.get_json() == {"invoices": []}


def test_list_invoices_with_client_filter(app_client, sample_client, sample_invoice):
    cid, _ = sample_client
    inv_id, inv_data = sample_invoice
    r = app_client.get("/api/invoices")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["invoices"]) == 1
    assert data["invoices"][0]["id"] == inv_id
    assert data["invoices"][0]["client_id"] == cid
    assert data["invoices"][0]["amount"] == 1500.0
    assert data["invoices"][0]["due_date"] == inv_data["due_date"]
    assert data["invoices"][0]["status"] == "pending"

    r2 = app_client.get(f"/api/invoices?client_id={cid}")
    assert r2.status_code == 200
    assert len(r2.get_json()["invoices"]) == 1

    r3 = app_client.get("/api/invoices?client_id=99999")
    assert r3.status_code == 200
    assert len(r3.get_json()["invoices"]) == 0


def test_create_invoice(app_client, sample_client):
    cid, _ = sample_client
    future = (date.today() + timedelta(days=14)).isoformat()
    r = app_client.post(
        "/api/invoices",
        json={
            "client_id": cid,
            "amount": 3200.50,
            "currency": "USD",
            "due_date": future,
            "status": "pending",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["client_id"] == cid
    assert data["amount"] == 3200.50
    assert data["currency"] == "USD"
    assert data["due_date"] == future
    assert data["status"] == "pending"
    assert "id" in data
    assert data.get("client_name") == "ACME CORP"


def test_create_invoice_past_due_returns_overdue(app_client, sample_client):
    """Creating an invoice with due_date in the past returns status overdue (immediate monitor)."""
    cid, _ = sample_client
    past = (date.today() - timedelta(days=5)).isoformat()
    r = app_client.post(
        "/api/invoices",
        json={
            "client_id": cid,
            "amount": 100.0,
            "currency": "USD",
            "due_date": past,
            "status": "pending",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["status"] == "overdue"
    assert data["days_overdue"] == 5
    assert data["escalation_level"] == 1


def test_create_invoice_client_id_required(app_client):
    r = app_client.post(
        "/api/invoices",
        json={"amount": 100.0, "due_date": "2025-03-01"},
    )
    assert r.status_code == 400
    assert "client_id" in (r.get_json() or {}).get("error", "").lower()


def test_create_invoice_amount_required(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.post(
        "/api/invoices",
        json={"client_id": cid, "due_date": "2025-03-01"},
    )
    assert r.status_code == 400
    assert "amount" in (r.get_json() or {}).get("error", "").lower()


def test_create_invoice_due_date_required(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.post(
        "/api/invoices",
        json={"client_id": cid, "amount": 100.0},
    )
    assert r.status_code == 400
    assert "due_date" in (r.get_json() or {}).get("error", "").lower()


def test_create_invoice_client_not_found(app_client):
    r = app_client.post(
        "/api/invoices",
        json={
            "client_id": 99999,
            "amount": 100.0,
            "due_date": "2025-03-01",
        },
    )
    assert r.status_code == 404
    assert "not found" in (r.get_json() or {}).get("error", "").lower()


def test_create_invoice_invalid_due_date(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.post(
        "/api/invoices",
        json={
            "client_id": cid,
            "amount": 100.0,
            "due_date": "not-a-date",
        },
    )
    assert r.status_code == 400
    assert "due_date" in (r.get_json() or {}).get("error", "").lower()


def test_get_invoice(app_client, sample_invoice):
    inv_id, inv_data = sample_invoice
    r = app_client.get(f"/api/invoices/{inv_id}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == inv_id
    assert data["amount"] == 1500.0
    assert data["client_name"] == "ACME CORP"


def test_get_invoice_404(app_client):
    r = app_client.get("/api/invoices/99999")
    assert r.status_code == 404


def test_update_invoice(app_client, sample_invoice):
    inv_id, _ = sample_invoice
    r = app_client.put(
        f"/api/invoices/{inv_id}",
        json={
            "amount": 2000.0,
            "currency": "EUR",
            "due_date": "2025-05-01",
            "status": "paid",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["amount"] == 2000.0
    assert data["currency"] == "EUR"
    assert data["due_date"] == "2025-05-01"
    assert data["status"] == "paid"

    r2 = app_client.get(f"/api/invoices/{inv_id}")
    assert r2.get_json()["amount"] == 2000.0
    assert r2.get_json()["status"] == "paid"


def test_update_invoice_404(app_client):
    r = app_client.put(
        "/api/invoices/99999",
        json={"amount": 100.0},
    )
    assert r.status_code == 404


def test_delete_invoice(app_client, sample_invoice):
    inv_id, _ = sample_invoice
    r = app_client.delete(f"/api/invoices/{inv_id}")
    assert r.status_code == 204
    r2 = app_client.get(f"/api/invoices/{inv_id}")
    assert r2.status_code == 404


def test_delete_invoice_404(app_client):
    r = app_client.delete("/api/invoices/99999")
    assert r.status_code == 404


def test_delete_invoice_with_communications_fails(app_client, sample_invoice):
    inv_id, _ = sample_invoice
    with get_session() as session:
        comm = Communication(
            invoice_id=inv_id,
            channel="email",
            direction="outbound",
            body="Please pay.",
        )
        session.add(comm)
    r = app_client.delete(f"/api/invoices/{inv_id}")
    assert r.status_code == 409
    assert "communication" in (r.get_json() or {}).get("error", "").lower()
