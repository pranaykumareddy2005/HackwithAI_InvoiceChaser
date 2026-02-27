"""Tests for the Clients CRUD API (Flask)."""

from datetime import date

import pytest

from db.database import get_session, init_db
from db.models import Client, Communication, ContactPreference, Invoice, InvoiceStatus


@pytest.fixture
def app_client(temp_db_path):
    """Create Flask app test client with isolated DB."""
    init_db()
    from web.app import app
    return app.test_client()


@pytest.fixture
def sample_client(app_client):
    """Create one client via API and return its id and the client."""
    r = app_client.post(
        "/api/clients",
        json={"name": "ACME CORP", "email": "billing@acme.example.com", "phone": "+15551234001"},
    )
    assert r.status_code == 201
    data = r.get_json()
    return data["id"], data


def test_list_clients_empty(app_client):
    r = app_client.get("/api/clients")
    assert r.status_code == 200
    assert r.get_json() == {"clients": []}


def test_create_client(app_client):
    r = app_client.post(
        "/api/clients",
        json={
            "name": "Beta Inc",
            "email": "b@beta.com",
            "phone": "+15550001111",
            "contact_preference": "email",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["name"] == "Beta Inc"
    assert data["email"] == "b@beta.com"
    assert data["phone"] == "+15550001111"
    assert data["contact_preference"] == "email"
    assert "id" in data
    assert data["opted_out"] is False


def test_create_client_name_required(app_client):
    r = app_client.post("/api/clients", json={"email": "x@y.com"})
    assert r.status_code == 400
    assert "name" in (r.get_json() or {}).get("error", "").lower()


def test_get_client(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.get(f"/api/clients/{cid}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["name"] == "ACME CORP"
    assert data["invoice_count"] == 0
    assert data["paid_count"] == 0
    assert data["last_contact"] is None


def test_get_client_404(app_client):
    r = app_client.get("/api/clients/99999")
    assert r.status_code == 404


def test_list_clients_search(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.get("/api/clients?q=ACME")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["clients"]) == 1
    assert data["clients"][0]["name"] == "ACME CORP"

    r2 = app_client.get("/api/clients?q=15551234001")
    assert r2.status_code == 200
    assert len(r2.get_json()["clients"]) == 1

    r3 = app_client.get("/api/clients?q=nobody")
    assert r3.status_code == 200
    assert len(r3.get_json()["clients"]) == 0


def test_update_client(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.put(
        f"/api/clients/{cid}",
        json={"name": "ACME Corp Updated", "phone": "+15559999999"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["name"] == "ACME Corp Updated"
    assert data["phone"] == "+15559999999"

    r2 = app_client.get(f"/api/clients/{cid}")
    assert r2.get_json()["name"] == "ACME Corp Updated"


def test_block_client(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.post(f"/api/clients/{cid}/block")
    assert r.status_code == 200
    data = r.get_json()
    assert data["opted_out"] is True
    assert data["opted_out_at"] is not None


def test_client_communications_empty(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.get(f"/api/clients/{cid}/communications")
    assert r.status_code == 200
    assert r.get_json() == {"communications": []}


def test_client_communications_with_data(app_client, sample_client):
    cid, _ = sample_client
    with get_session() as session:
        inv = Invoice(
            client_id=cid,
            amount=100.0,
            currency="USD",
            due_date=date(2025, 2, 1),
            status=InvoiceStatus.PENDING.value,
        )
        session.add(inv)
        session.flush()
        comm = Communication(
            invoice_id=inv.id,
            channel="sms",
            direction="outbound",
            body="Please pay your invoice.",
            escalation_level=2,
        )
        session.add(comm)
    r = app_client.get(f"/api/clients/{cid}/communications")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["communications"]) == 1
    assert data["communications"][0]["channel"] == "SMS"
    assert data["communications"][0]["level"] == "L2"


def test_delete_client_without_invoices(app_client, sample_client):
    cid, _ = sample_client
    r = app_client.delete(f"/api/clients/{cid}")
    assert r.status_code == 204
    r2 = app_client.get(f"/api/clients/{cid}")
    assert r2.status_code == 404


def test_delete_client_with_invoices_fails(app_client, sample_client):
    cid, _ = sample_client
    with get_session() as session:
        inv = Invoice(
            client_id=cid,
            amount=50.0,
            currency="USD",
            due_date=date(2025, 3, 1),
            status=InvoiceStatus.PENDING.value,
        )
        session.add(inv)
    r = app_client.delete(f"/api/clients/{cid}")
    assert r.status_code == 409
    assert "invoice" in (r.get_json() or {}).get("error", "").lower()
