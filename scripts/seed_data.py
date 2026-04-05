# FILE: scripts/seed_data.py
# MODULE: Seed Data für Entwicklung und Testing

import asyncio
import random
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.services.auth import get_password_hash

from src.core.entities.base import (
    Base,
    Donation,
    PaymentStatus,
    Project,
    SKR42Account,
    TransactionType,
    User,
    UserRole,
)


async def seed_database():
    """Seedet die Datenbank mit Testdaten"""

    DATABASE_URL = "postgresql+asyncpg://dev:dev_password@localhost:5432/trueangels_dev"
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        print("Creating seed data...")

        # Create SKR42 Accounts
        skr42_accounts = [
            SKR42Account(
                account_number="12000",
                account_name="Bank",
                account_type="AKTIVA",
                current_hash="test"
            ),
            SKR42Account(
                account_number="40000",
                account_name="Spenden allgemein",
                account_type="ERTRAEGE",
                current_hash="test"
            ),
            SKR42Account(
                account_number="70000",
                account_name="Projektausgaben",
                account_type="AUFWENDUNGEN",
                current_hash="test"
            )
        ]
        session.add_all(skr42_accounts)
        await session.commit()

        # Create Users
        admin = User(
            email="admin@trueangels.de",
            password_hash=get_password_hash("admin123"),
            role=UserRole.ADMIN,
            email_verified=True
        )

        accountant = User(
            email="accountant@trueangels.de",
            password_hash=get_password_hash("accountant123"),
            role=UserRole.ACCOUNTANT,
            email_verified=True
        )

        session.add_all([admin, accountant])
        await session.commit()

        # Create Projects
        projects = [
            Project(
                name="Bildungsinitiative",
                description="Unterstützung von Schulen in Entwicklungsländern",
                cost_center="PROJ_001",
                skr42_account_id=skr42_accounts[1].id,
                budget_total=Decimal("50000"),
                start_date=datetime(2024, 1, 1),
                status="active"
            ),
            Project(
                name="Medizinische Hilfe",
                description="Mobile Kliniken für entlegene Regionen",
                cost_center="PROJ_002",
                skr42_account_id=skr42_accounts[1].id,
                budget_total=Decimal("40000"),
                start_date=datetime(2024, 2, 1),
                status="active"
            ),
            Project(
                name="Umweltschutz",
                description="Aufforstung und Meeresschutz",
                cost_center="PROJ_003",
                skr42_account_id=skr42_accounts[1].id,
                budget_total=Decimal("30000"),
                start_date=datetime(2024, 3, 1),
                status="active"
            )
        ]
        session.add_all(projects)
        await session.commit()

        # Create Donations (letzte 90 Tage)
        import hashlib

        start_date = datetime.utcnow() - timedelta(days=90)

        for i in range(500):
            days_ago = random.randint(0, 90)
            donation_date = start_date + timedelta(days=days_ago)
            amount = Decimal(str(random.randint(10, 500)))
            project = random.choice(projects)

            # Pseudonymized donor email
            donor_email = f"donor_{random.randint(1, 100)}@example.com"
            donor_email_hash = hashlib.sha256(donor_email.encode()).hexdigest()

            donation = Donation(
                donor_email_pseudonym=donor_email_hash,
                project_id=project.id,
                skr42_account_id=skr42_accounts[1].id,
                cost_center=project.cost_center,
                amount=amount,
                transaction_type=TransactionType.SPENDE,
                payment_provider=random.choice(["stripe", "paypal"]),
                payment_intent_id=f"pi_{uuid4().hex[:12]}",
                payment_status=PaymentStatus.SUCCEEDED.value,
                created_by=admin.id,
                created_at=donation_date,
                current_hash="test"
            )
            session.add(donation)

        await session.commit()

        # Update project totals
        for project in projects:
            from sqlalchemy import func, select
            stmt = select(func.sum(Donation.amount)).where(Donation.project_id == project.id)
            result = await session.execute(stmt)
            total = result.scalar() or 0
            project.donations_total = total

        await session.commit()

        print(f"Seed data created: {len(projects)} projects, 500 donations")
        print("Admin user: admin@trueangels.de / admin123")
        print("Accountant: accountant@trueangels.de / accountant123")

if __name__ == "__main__":
    asyncio.run(seed_database())
