# FILE: scripts/__init__.py
# MODULE: Scripts Package für Backup, Seed, Admin Tools
# Enthält Hilfsskripte für Wartung, Datenbank-Seeding, Backups und Migrationen

from scripts.backup import main as backup_main
from scripts.seed_data import seed_database

__all__ = [
    "backup_main",
    "seed_database",
]