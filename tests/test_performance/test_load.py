# FILE: tests/test_performance/test_load.py
# MODULE: Load Tests mit Locust
# Performance-Tests für kritische Endpunkte

import asyncio

import pytest
from locust import HttpUser, between, task


class TrueAngelsUser(HttpUser):
    """Simulierter Benutzer für Load Tests"""

    wait_time = between(1, 3)

    def on_start(self):
        """Login beim Start"""
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "loadtest@trueangels.de", "password": "loadtest123"},
        )
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def get_projects(self):
        """Projekt-Liste abrufen"""
        self.client.get("/api/v1/projects", headers=self.headers)

    @task(2)
    def get_donations(self):
        """Spenden-Liste abrufen"""
        self.client.get("/api/v1/donations", headers=self.headers)

    @task(1)
    def create_donation(self):
        """Spende erstellen"""
        self.client.post(
            "/api/v1/payments/create-donation",
            json={
                "amount": 50.00,
                "currency": "EUR",
                "payment_method": "credit_card",
                "donor_email": f"load_{self.user_id}@example.com",
                "project_id": "test-project-id",
            },
            headers=self.headers,
        )

    @task(1)
    def get_dashboard_stats(self):
        """Dashboard Statistiken"""
        self.client.get("/api/v1/reports/dashboard/kpis", headers=self.headers)


@pytest.mark.load
class TestLoadPerformance:
    """Load Performance Tests"""

    @pytest.mark.asyncio
    async def test_api_response_time(self, async_client, auth_headers):
        """Test API Response Times"""
        import time

        endpoints = [
            "/api/v1/projects",
            "/api/v1/donations",
            "/api/v1/inventory/items/low-stock",
            "/api/v1/compliance/dashboard",
        ]

        response_times = []

        for endpoint in endpoints:
            start = time.time()
            response = await async_client.get(endpoint, headers=auth_headers)
            elapsed = time.time() - start

            response_times.append(elapsed)
            assert response.status_code == 200
            assert elapsed < 1.0  # Sollte unter 1 Sekunde sein

        avg_time = sum(response_times) / len(response_times)
        print(f"Average response time: {avg_time:.3f}s")
        assert avg_time < 0.5  # Durchschnitt unter 500ms

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, async_client, auth_headers):
        """Test Concurrent Request Handling"""

        async def make_request(i):
            response = await async_client.get("/api/v1/projects", headers=auth_headers)
            return response.status_code

        # 100 gleichzeitige Requests
        results = await asyncio.gather(*[make_request(i) for i in range(100)])

        success_count = sum(1 for r in results if r == 200)
        assert success_count >= 95  # Mindestens 95% erfolgreich

    @pytest.mark.benchmark
    def test_database_query_performance(self, benchmark, db_session, test_donation):
        """Benchmark: Datenbank Query Performance"""

        def query_donations():
            from sqlalchemy import select

            from src.core.entities.base import Donation

            stmt = select(Donation).where(Donation.payment_status == "succeeded")
            result = db_session.execute(stmt)
            return result.scalars().all()

        result = benchmark(query_donations)
        assert len(result) >= 1
