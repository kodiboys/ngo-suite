# FILE: scripts/create_admin.py
# MODULE: Admin User Creation Script
# Erstellt einen Administrator-Benutzer für die TrueAngels NGO Suite

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import getpass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.core.config import settings
from src.core.entities.base import User, UserRole, AuditLog
from src.services.auth import AuthService, PasswordManager


async def create_admin(
    email: str = None,
    password: str = None,
    name: str = None,
    make_super_admin: bool = True
) -> User:
    """
    Erstellt einen Admin-Benutzer.

    Args:
        email: E-Mail-Adresse (wird interaktiv abgefragt wenn None)
        password: Passwort (wird interaktiv abgefragt wenn None)
        name: Name des Admins
        make_super_admin: Ob der Benutzer Super-Admin Rechte bekommen soll

    Returns:
        User: Der erstellte Admin-Benutzer
    """
    if email is None:
        email = input("Admin E-Mail: ").strip()

    if password is None:
        password = getpass.getpass("Admin Passwort: ")
        password_confirm = getpass.getpass("Passwort bestätigen: ")

        if password != password_confirm:
            print("❌ Passwörter stimmen nicht überein!")
            return None

    if name is None:
        name = input("Admin Name (optional): ").strip() or "Administrator"

    if not email or "@" not in email:
        print(f"❌ Ungültige E-Mail-Adresse: {email}")
        return None

    if len(password) < 8:
        print("❌ Passwort muss mindestens 8 Zeichen lang sein!")
        return None

    engine = create_async_engine(settings.DATABASE_URL_ASYNC, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        redis_client = await redis.from_url(settings.REDIS_URL)
    except Exception as e:
        print(f"⚠️ Redis nicht verfügbar: {e}")
        redis_client = None

    try:
        async with session_factory() as session:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"⚠️ Benutzer mit E-Mail {email} existiert bereits!")

                if existing_user.role != UserRole.ADMIN:
                    print(f"   Aktuelle Rolle: {existing_user.role.value}")
                    upgrade = input("   Zum Admin upgraden? (j/n): ").strip().lower()
                    if upgrade in ['j', 'ja', 'y', 'yes']:
                        existing_user.role = UserRole.ADMIN
                        existing_user.updated_at = datetime.now(timezone.utc)
                        await session.commit()
                        print(f"✅ Benutzer {email} wurde zum Admin upgraded!")
                    return existing_user
                else:
                    print(f"✅ Benutzer {email} ist bereits Admin!")
                    return existing_user

            auth_service = AuthService(session_factory, redis_client, None)
            user = await auth_service.register(email, password, name)

            user.role = UserRole.ADMIN if make_super_admin else UserRole.PROJECT_MANAGER
            user.email_verified = True

            audit = AuditLog(
                user_id=user.id,
                action="ADMIN_CREATED",
                entity_type="user",
                entity_id=user.id,
                new_values={
                    "email": user.email,
                    "role": user.role.value,
                    "name": name
                },
                ip_address="script",
                retention_until=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 10)
            )
            session.add(audit)
            await session.commit()
            await session.refresh(user)

            print(f"\n✅ Admin-Benutzer erfolgreich erstellt!")
            print(f"   📧 E-Mail: {user.email}")
            print(f"   👤 Name: {user.name_encrypted or name}")
            print(f"   🔑 Rolle: {user.role.value}")
            print(f"   🆔 ID: {user.id}")
            print(f"\n🔐 Das Passwort wurde sicher gehasht gespeichert.")

            return user

    except Exception as e:
        print(f"❌ Fehler beim Erstellen des Admin-Benutzers: {e}")
        raise
    finally:
        await engine.dispose()
        if redis_client:
            await redis_client.close()


async def list_admins():
    """Listet alle vorhandenen Admin-Benutzer auf"""
    engine = create_async_engine(settings.DATABASE_URL_ASYNC, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stmt = select(User).where(User.role.in_([UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER]))
            result = await session.execute(stmt)
            admins = result.scalars().all()

            if not admins:
                print("📋 Keine Admin-Benutzer gefunden.")
                return

            print("\n📋 Vorhandene Admin-Benutzer:")
            print("-" * 80)
            for admin in admins:
                print(f"   📧 {admin.email}")
                print(f"      👤 {admin.name_encrypted or 'kein Name'}")
                print(f"      🔑 Rolle: {admin.role.value}")
                print(f"      🕐 Erstellt: {admin.created_at.strftime('%d.%m.%Y %H:%M')}")
                print(f"      🔄 Letzter Login: {admin.last_login_at.strftime('%d.%m.%Y %H:%M') if admin.last_login_at else 'nie'}")
                print("-" * 40)

    finally:
        await engine.dispose()


async def delete_admin(email: str, confirm: bool = False):
    """Löscht einen Admin-Benutzer (DSGVO-konform)"""
    if not confirm:
        print(f"⚠️ Achtung: Sie sind dabei den Benutzer {email} zu LÖSCHEN!")
        confirm_input = input("   Wirklich löschen? (j/n): ").strip().lower()
        if confirm_input not in ['j', 'ja', 'y', 'yes']:
            print("❌ Löschung abgebrochen.")
            return False

    engine = create_async_engine(settings.DATABASE_URL_ASYNC, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                print(f"❌ Benutzer {email} nicht gefunden.")
                return False

            stmt = select(User).where(User.role == UserRole.ADMIN)
            result = await session.execute(stmt)
            admin_count = len(result.scalars().all())

            if admin_count <= 1 and user.role == UserRole.ADMIN:
                print("❌ Kann den letzten Admin-Benutzer nicht löschen!")
                return False

            user.is_pseudonymized = True
            user.email = f"deleted_{user.id}@deleted.trueangels.de"
            user.role = UserRole.DONOR
            user.updated_at = datetime.now(timezone.utc)

            audit = AuditLog(
                user_id=None,
                action="ADMIN_DELETED",
                entity_type="user",
                entity_id=user.id,
                old_values={"email": email, "role": user.role.value},
                new_values={"email": user.email, "role": "deleted"},
                ip_address="script",
                retention_until=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 10)
            )
            session.add(audit)
            await session.commit()

            print(f"✅ Admin-Benutzer {email} wurde pseudonymisiert (DSGVO-konform).")
            return True

    finally:
        await engine.dispose()


async def reset_admin_password(email: str):
    """Setzt das Passwort eines Admin-Benutzers zurück"""
    engine = create_async_engine(settings.DATABASE_URL_ASYNC, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                print(f"❌ Benutzer {email} nicht gefunden.")
                return False

            new_password = getpass.getpass("Neues Passwort: ")
            password_confirm = getpass.getpass("Passwort bestätigen: ")

            if new_password != password_confirm:
                print("❌ Passwörter stimmen nicht überein!")
                return False

            if len(new_password) < 8:
                print("❌ Passwort muss mindestens 8 Zeichen lang sein!")
                return False

            password_manager = PasswordManager()
            user.password_hash = password_manager.hash_password(new_password)
            user.updated_at = datetime.now(timezone.utc)

            audit = AuditLog(
                user_id=user.id,
                action="PASSWORD_RESET",
                entity_type="user",
                entity_id=user.id,
                ip_address="script",
                retention_until=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 10)
            )
            session.add(audit)
            await session.commit()

            print(f"✅ Passwort für {email} wurde zurückgesetzt!")
            return True

    finally:
        await engine.dispose()


async def main():
    """Main entry point with CLI interface"""
    import argparse

    parser = argparse.ArgumentParser(description="TrueAngels Admin Management")
    parser.add_argument("--email", "-e", type=str, help="Admin E-Mail")
    parser.add_argument("--password", "-p", type=str, help="Admin Passwort")
    parser.add_argument("--name", "-n", type=str, help="Admin Name")
    parser.add_argument("--list", "-l", action="store_true", help="Liste alle Admins")
    parser.add_argument("--delete", "-d", type=str, help="Lösche Admin (E-Mail)")
    parser.add_argument("--reset-password", "-r", type=str, help="Reset Passwort (E-Mail)")
    parser.add_argument("--force", "-f", action="store_true", help="Force delete ohne Bestätigung")

    args = parser.parse_args()

    if args.list:
        await list_admins()
    elif args.delete:
        await delete_admin(args.delete, confirm=args.force)
    elif args.reset_password:
        await reset_admin_password(args.reset_password)
    else:
        await create_admin(
            email=args.email,
            password=args.password,
            name=args.name,
            make_super_admin=True
        )


if __name__ == "__main__":
    asyncio.run(main())