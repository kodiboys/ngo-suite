# FILE: tests/test_integration/test_api.py
# MODULE: Integration Tests für API Endpoints
# Testet vollständige API-Flows mit echter Datenbank

from uuid import uuid4

import pytest


class TestAuthAPI:
    """Tests für Authentication API"""

    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        """Test erfolgreicher Login"""
        response = client.post(
            "/api/v1/auth/login", json={"email": "test@trueangels.de", "password": "test123"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@trueangels.de"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client):
        """Test Login mit falschen Credentials"""
        response = client.post(
            "/api/v1/auth/login", json={"email": "wrong@example.com", "password": "wrong"}
        )

        assert response.status_code == 401
        assert "Invalid credentials" in response.text

    @pytest.mark.asyncio
    async def test_rate_limit_login(self, client):
        """Test Rate Limiting für Login"""
        # 5 schnelle Login-Versuche
        for i in range(6):
            response = client.post(
                "/api/v1/auth/login", json={"email": "test@trueangels.de", "password": "wrong"}
            )

            if i < 5:
                assert response.status_code == 401
            else:
                # 6. Versuch sollte rate limit treffen
                assert response.status_code == 429


class TestDonationAPI:
    """Tests für Donation API"""

    @pytest.mark.asyncio
    async def test_create_donation(self, client, auth_headers, test_project):
        """Test Spenden-Erstellung"""
        response = client.post(
            "/api/v1/payments/create-donation",
            json={
                "amount": 100.00,
                "currency": "EUR",
                "payment_method": "credit_card",
                "donor_email": "donor@example.com",
                "project_id": str(test_project.id),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "donation_id" in data
        assert "payment_intent_id" in data

    @pytest.mark.asyncio
    async def test_get_donations(self, client, auth_headers, test_donation):
        """Test Abrufen von Spenden"""
        response = client.get("/api/v1/donations", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_donation_by_id(self, client, auth_headers, test_donation):
        """Test Abrufen einer Spende nach ID"""
        response = client.get(f"/api/v1/donations/{test_donation.id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_donation.id)
        assert data["amount"] == 100.00


class TestProjectAPI:
    """Tests für Project API"""

    @pytest.mark.asyncio
    async def test_get_projects(self, client, auth_headers, test_project):
        """Test Abrufen aller Projekte"""
        response = client.get("/api/v1/projects", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_project_stats(self, client, auth_headers, test_project):
        """Test Projekt-Statistiken"""
        response = client.get(f"/api/v1/projects/{test_project.id}/stats", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "total_donations" in data
        assert "progress_percentage" in data


class TestInventoryAPI:
    """Tests für Inventory API"""

    @pytest.mark.asyncio
    async def test_create_inventory_item(self, client, auth_headers, test_project):
        """Test Erstellung eines Lagerartikels"""
        response = client.post(
            "/api/v1/inventory/items",
            json={
                "name": "Test Item",
                "sku": "TEST-001",
                "category": "food",
                "quantity": 100,
                "project_id": str(test_project.id),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["name"] == "Test Item"

    @pytest.mark.asyncio
    async def test_get_low_stock_items(self, client, auth_headers, test_inventory_item):
        """Test Abrufen von Artikeln mit niedrigem Bestand"""
        response = client.get("/api/v1/inventory/items/low-stock", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # test_inventory_item hat quantity=100, min_stock_level=10 -> nicht low stock
        assert isinstance(data, list)


class TestComplianceAPI:
    """Tests für Compliance API"""

    @pytest.mark.asyncio
    async def test_four_eyes_request(self, client, auth_headers):
        """Test 4-Augen-Freigabe Anforderung"""
        response = client.post(
            "/api/v1/compliance/four-eyes/request",
            json={
                "entity_type": "donation",
                "entity_id": str(uuid4()),
                "amount": 7500.00,
                "reason": "Test transaction",
                "approver_1_id": str(uuid4()),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "approval_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_money_laundering_check(self, client, auth_headers):
        """Test Geldwäscheprüfung"""
        response = client.post(
            "/api/v1/compliance/money-laundering/check",
            json={
                "entity_type": "donation",
                "entity_id": str(uuid4()),
                "amount": 25000.00,
                "donor_country": "RU",
                "payment_method": "crypto",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "risk_level" in data
        assert "risk_score" in data
        assert data["risk_level"] in ["high", "critical"]


class TestExportAPI:
    """Tests für Export API"""

    @pytest.mark.asyncio
    async def test_export_donations(self, client, auth_headers):
        """Test Spendenexport"""
        response = client.get(
            "/api/v1/export/donations",
            params={"start_date": "2024-01-01", "end_date": "2024-12-31", "format": "csv"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
