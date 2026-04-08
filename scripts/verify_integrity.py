# FILE: scripts/verify_integrity.py
# MODULE: Integrity Verification Script for Merkle-Tree & GoBD Compliance
# Prüft die manipulationssichere Integrität der Transparenz-Daten

import asyncio
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
import argparse
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func, text

from src.core.config import settings
from src.core.compliance.merkle import MerkleTreeService
from src.core.entities.base import Donation, Project
from src.core.entities.transparency import TransparencyHash


class IntegrityVerifier:
    """
    Integritätsprüfer für Merkle-Tree und Transparenz-Daten
    Prüft ob die gespeicherten Hashes mit den berechneten übereinstimmen
    """
    
    def __init__(self):
        self.engine = create_async_engine(settings.database_url_async, echo=False)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.merkle_service = None
    
    async def initialize(self):
        """Initialisiert den MerkleTreeService"""
        async with self.session_factory() as session:
            self.merkle_service = MerkleTreeService(session)
    
    async def verify_single_day(self, target_date: date) -> Dict[str, Any]:
        """
        Verifiziert einen einzelnen Tag
        
        Args:
            target_date: Zu prüfendes Datum
            
        Returns:
            Dict mit Prüfergebnissen
        """
        async with self.session_factory() as session:
            result = {
                "date": target_date.isoformat(),
                "is_valid": False,
                "stored_root": None,
                "computed_root": None,
                "donation_count": 0,
                "error": None
            }
            
            try:
                # Lade gespeicherten Hash
                stmt = select(TransparencyHash).where(TransparencyHash.date == target_date)
                db_result = await session.execute(stmt)
                stored = db_result.scalar_one_or_none()
                
                if not stored:
                    result["error"] = "No hash stored for this date"
                    return result
                
                result["stored_root"] = stored.merkle_root
                result["donation_count"] = stored.record_count
                
                # Berechne aktuellen Hash neu
                computed_root = await self.merkle_service.generate_daily_hash(target_date)
                result["computed_root"] = computed_root
                
                # Vergleiche
                result["is_valid"] = stored.merkle_root == computed_root
                
                if not result["is_valid"]:
                    result["error"] = "Hash mismatch - data may be corrupted!"
                    
            except Exception as e:
                result["error"] = str(e)
            
            return result
    
    async def verify_date_range(
        self,
        start_date: date,
        end_date: date,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Verifiziert einen Datumsbereich
        
        Args:
            start_date: Startdatum
            end_date: Enddatum
            verbose: Detaillierte Ausgabe
            
        Returns:
            Dict mit Prüfergebnissen
        """
        results = []
        all_valid = True
        current_date = start_date
        
        while current_date <= end_date:
            if verbose:
                print(f"  Prüfe {current_date.isoformat()}...")
            
            result = await self.verify_single_day(current_date)
            results.append(result)
            
            if not result["is_valid"]:
                all_valid = False
                if verbose:
                    print(f"    ❌ FEHLER: {result.get('error', 'Hash mismatch')}")
            elif verbose:
                print(f"    ✅ OK")
            
            current_date += timedelta(days=1)
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_days": len(results),
            "valid_days": sum(1 for r in results if r["is_valid"]),
            "invalid_days": sum(1 for r in results if not r["is_valid"]),
            "all_valid": all_valid,
            "results": results if verbose else None
        }
    
    async def verify_all(self, limit: int = 365) -> Dict[str, Any]:
        """
        Verifiziert alle vorhandenen Hashes (letzte X Tage)
        
        Args:
            limit: Maximale Anzahl zu prüfender Tage
            
        Returns:
            Dict mit Prüfergebnissen
        """
        async with self.session_factory() as session:
            # Hole alle vorhandenen Hashes
            stmt = select(TransparencyHash).order_by(TransparencyHash.date.desc()).limit(limit)
            result = await session.execute(stmt)
            hashes = result.scalars().all()
            
            if not hashes:
                return {
                    "total_days": 0,
                    "valid_days": 0,
                    "invalid_days": 0,
                    "all_valid": True,
                    "message": "No hashes found in database"
                }
            
            results = []
            all_valid = True
            
            for hash_record in hashes:
                print(f"  Prüfe {hash_record.date.isoformat()}...")
                
                result = await self.verify_single_day(hash_record.date)
                results.append(result)
                
                if not result["is_valid"]:
                    all_valid = False
                    print(f"    ❌ FEHLER: {result.get('error', 'Hash mismatch')}")
                else:
                    print(f"    ✅ OK")
            
            return {
                "total_days": len(results),
                "valid_days": sum(1 for r in results if r["is_valid"]),
                "invalid_days": sum(1 for r in results if not r["is_valid"]),
                "all_valid": all_valid,
                "results": results
            }
    
    async def verify_chain_integrity(self) -> Dict[str, Any]:
        """
        Verifiziert die Integrität der gesamten Hash-Kette
        Prüft ob die previous_hash Referenzen korrekt sind
        """
        async with self.session_factory() as session:
            stmt = select(TransparencyHash).order_by(TransparencyHash.date)
            result = await session.execute(stmt)
            hashes = result.scalars().all()
            
            chain_valid = True
            broken_links = []
            
            for i in range(1, len(hashes)):
                current = hashes[i]
                previous = hashes[i - 1]
                
                # Prüfe ob current auf previous verweist
                # (Die Chain wird durch die generate_daily_hash Methode gebildet)
                if current.previous_root and current.previous_root != previous.merkle_root:
                    chain_valid = False
                    broken_links.append({
                        "date": current.date.isoformat(),
                        "expected_previous": previous.merkle_root[:16] + "...",
                        "actual_previous": current.previous_root[:16] + "..."
                    })
            
            return {
                "chain_valid": chain_valid,
                "total_links": len(hashes) - 1,
                "broken_links": broken_links,
                "first_date": hashes[0].date.isoformat() if hashes else None,
                "last_date": hashes[-1].date.isoformat() if hashes else None
            }
    
    async def generate_integrity_report(self, year: int) -> str:
        """
        Generiert einen detaillierten Integritätsbericht
        
        Args:
            year: Jahr für den Bericht
            
        Returns:
            Bericht als String
        """
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"INTEGRITÄTSBERICHT - TrueAngels NGO Suite")
        report_lines.append(f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        report_lines.append(f"Zeitraum: {start_date.isoformat()} - {end_date.isoformat()}")
        report_lines.append("=" * 80)
        report_lines.append("")
        
        # 1. Tägliche Hashes prüfen
        report_lines.append("📋 1. TÄGLICHE HASHES")
        report_lines.append("-" * 40)
        
        range_result = await self.verify_date_range(start_date, end_date, verbose=False)
        
        report_lines.append(f"   Geprüfte Tage: {range_result['total_days']}")
        report_lines.append(f"   ✅ Gültig: {range_result['valid_days']}")
        report_lines.append(f"   ❌ Ungültig: {range_result['invalid_days']}")
        report_lines.append(f"   Status: {'✅ OK' if range_result['all_valid'] else '❌ FEHLER'}")
        report_lines.append("")
        
        # 2. Chain-Integrität
        report_lines.append("🔗 2. CHAIN-INTEGRITÄT")
        report_lines.append("-" * 40)
        
        chain_result = await self.verify_chain_integrity()
        
        report_lines.append(f"   Geprüfte Links: {chain_result['total_links']}")
        report_lines.append(f"   Status: {'✅ OK' if chain_result['chain_valid'] else '❌ UNTERBROCHEN'}")
        
        if chain_result['broken_links']:
            report_lines.append("   Unterbrochene Links:")
            for link in chain_result['broken_links']:
                report_lines.append(f"     - {link['date']}: erwartet {link['expected_previous']}, erhalten {link['actual_previous']}")
        report_lines.append("")
        
        # 3. Datenbank-Statistiken
        report_lines.append("📊 3. DATENBANK-STATISTIKEN")
        report_lines.append("-" * 40)
        
        async with self.session_factory() as session:
            # Anzahl Spenden
            stmt = select(func.count()).select_from(Donation)
            result = await session.execute(stmt)
            total_donations = result.scalar() or 0
            
            # Anzahl Transparenz-Hashes
            stmt = select(func.count()).select_from(TransparencyHash)
            result = await session.execute(stmt)
            total_hashes = result.scalar() or 0
            
            # Letzte Aktualisierung
            stmt = select(TransparencyHash).order_by(TransparencyHash.created_at.desc()).limit(1)
            result = await session.execute(stmt)
            last_hash = result.scalar_one_or_none()
            
            report_lines.append(f"   Gesamt Spenden: {total_donations:,}")
            report_lines.append(f"   Gesamt Hashes: {total_hashes}")
            report_lines.append(f"   Letzter Hash: {last_hash.date.isoformat() if last_hash else 'keiner'}")
        report_lines.append("")
        
        # 4. Fazit
        report_lines.append("✅ 4. FAZIT")
        report_lines.append("-" * 40)
        
        if range_result['all_valid'] and chain_result['chain_valid']:
            report_lines.append("   ALLE PRÜFUNGEN BESTANDEN - Die Daten sind manipulationssicher!")
        else:
            report_lines.append("   ⚠️ PRÜFUNGEN FEHLGESCHLAGEN - Bitte überprüfen Sie die Daten!")
        
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("Ende des Berichts")
        
        return "\n".join(report_lines)
    
    async def close(self):
        """Schließt die Datenbankverbindung"""
        await self.engine.dispose()


async def main():
    """Main entry point with CLI interface"""
    
    parser = argparse.ArgumentParser(description="TrueAngels Integrity Verifier")
    parser.add_argument("--date", "-d", type=str, help="Prüfe einen bestimmten Tag (YYYY-MM-DD)")
    parser.add_argument("--start", "-s", type=str, help="Startdatum für Bereich (YYYY-MM-DD)")
    parser.add_argument("--end", "-e", type=str, help="Enddatum für Bereich (YYYY-MM-DD)")
    parser.add_argument("--all", "-a", action="store_true", help="Prüfe alle vorhandenen Hashes")
    parser.add_argument("--chain", "-c", action="store_true", help="Prüfe nur die Chain-Integrität")
    parser.add_argument("--report", "-r", type=int, help="Generiere Jahresbericht (Jahr)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detaillierte Ausgabe")
    
    args = parser.parse_args()
    
    verifier = IntegrityVerifier()
    await verifier.initialize()
    
    try:
        # Einzelner Tag
        if args.date:
            target_date = date.fromisoformat(args.date)
            print(f"🔍 Prüfe {target_date.isoformat()}...")
            result = await verifier.verify_single_day(target_date)
            
            print(f"\n📋 Ergebnis:")
            print(f"   Datum: {result['date']}")
            print(f"   Gültig: {'✅ Ja' if result['is_valid'] else '❌ Nein'}")
            print(f"   Gespeicherter Root: {result['stored_root'][:32]}...")
            print(f"   Neu berechneter Root: {result['computed_root'][:32]}...")
            if result['donation_count']:
                print(f"   Anzahl Spenden: {result['donation_count']}")
            if result['error']:
                print(f"   Fehler: {result['error']}")
        
        # Datumsbereich
        elif args.start and args.end:
            start_date = date.fromisoformat(args.start)
            end_date = date.fromisoformat(args.end)
            print(f"🔍 Prüfe Bereich {start_date.isoformat()} - {end_date.isoformat()}...")
            
            result = await verifier.verify_date_range(start_date, end_date, verbose=args.verbose)
            
            print(f"\n📋 Ergebnis:")
            print(f"   Geprüfte Tage: {result['total_days']}")
            print(f"   ✅ Gültig: {result['valid_days']}")
            print(f"   ❌ Ungültig: {result['invalid_days']}")
            print(f"   Status: {'✅ OK' if result['all_valid'] else '❌ FEHLER'}")
        
        # Alle Hashes
        elif args.all:
            print(f"🔍 Prüfe alle vorhandenen Hashes...")
            result = await verifier.verify_all(limit=3650)  # 10 Jahre
            
            print(f"\n📋 Ergebnis:")
            print(f"   Geprüfte Tage: {result['total_days']}")
            print(f"   ✅ Gültig: {result['valid_days']}")
            print(f"   ❌ Ungültig: {result['invalid_days']}")
            print(f"   Status: {'✅ OK' if result['all_valid'] else '❌ FEHLER'}")
        
        # Chain-Integrität
        elif args.chain:
            print(f"🔍 Prüfe Chain-Integrität...")
            result = await verifier.verify_chain_integrity()
            
            print(f"\n📋 Ergebnis:")
            print(f"   Geprüfte Links: {result['total_links']}")
            print(f"   Status: {'✅ OK' if result['chain_valid'] else '❌ UNTERBROCHEN'}")
            if result['broken_links']:
                print(f"\n   Unterbrochene Links:")
                for link in result['broken_links']:
                    print(f"     - {link['date']}")
        
        # Jahresbericht
        elif args.report:
            year = args.report
            print(f"📄 Generiere Integritätsbericht für {year}...")
            report = await verifier.generate_integrity_report(year)
            
            # Speichere Bericht
            filename = f"integrity_report_{year}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(report)
            
            print(f"✅ Bericht gespeichert: {filename}")
            print("\n" + report[:500] + "...\n")
        
        # Keine Argumente - Hilfe anzeigen
        else:
            parser.print_help()
    
    finally:
        await verifier.close()


if __name__ == "__main__":
    asyncio.run(main())