# FILE: docs/dr-playbook.md
# MODULE: Disaster Recovery Playbook - 3-2-1 Backup Strategie
# RTO: 4 Stunden | RPO: 15 Minuten

# 🚨 Disaster Recovery Playbook - TrueAngels NGO Suite

## 📋 Überblick

| Metrik | Ziel |
|--------|------|
| **RTO** (Recovery Time Objective) | 4 Stunden |
| **RPO** (Recovery Point Objective) | 15 Minuten |
| **Backup-Strategie** | 3-2-1 Regel |
| **Verantwortlich** | DevOps / Systemadministrator |

## 💾 3-2-1 Backup-Strategie

## 📦 Backup-Komponenten

### 1. PostgreSQL (Datenbank)

# WAL-Archivierung (Point-in-Time Recovery)
archive_mode = on
archive_command = 'test ! -f /mnt/wal_archive/%f && cp %p /mnt/wal_archive/%f'

# Tägliche Full Backups
0 2 * * * /opt/trueangels/scripts/pg_backup.sh

# Backup zu Wasabi synchronisieren
0 3 * * * aws s3 sync /mnt/backups/ s3://trueangels-backups/database/

### 2. Redis (Cache & Queue)

# RDB Snapshots alle 15 Minuten
save 900 1
save 300 10
save 60 10000

# AOF für Point-in-Time
appendonly yes
appendfsync everysec

### 3. Wasabi S3 (Object Storage)

# Backup-Bucket Struktur
trueangels-backups/
├── database/
│   ├── full_20240115.sql.gz
│   └── wal/
├── redis/
│   └── dump_20240115.rdb
├── uploads/
│   └── (Benutzer-Uploads)
└── transparenz-pdfs/
    └── merkle_202401.pdf

### 4. Konfigurationen

# Verschlüsselte Config-Backups
tar -czf config_$(date +%Y%m%d).tar.gz \
    /opt/trueangels/.env \
    /opt/trueangels/docker-compose.yml \
    /etc/nginx/nginx.conf

### 🔄 Wiederherstellungs-Prozeduren
Szenario A: Datenbank-Korruption
RTO: 1 Stunde | RPO: 15 Minuten

#!/bin/bash
# restore_db.sh - Point-in-Time Recovery

# 1. Stop application
docker-compose stop api celery_worker

# 2. Restore latest full backup
aws s3 cp s3://trueangels-backups/database/full_latest.sql.gz /tmp/
gunzip /tmp/full_latest.sql.gz
docker-compose exec -T postgres psql -U admin < /tmp/full_latest.sql

# 3. Apply WAL up to specific time
aws s3 sync s3://trueangels-backups/database/wal/ /tmp/wal/
docker-compose exec postgres bash -c "
    pg_restore --wal-segsize=16 --target-gtid=2024-01-15-14:30:00
"

# 4. Verify integrity
docker-compose exec api alembic upgrade head
docker-compose exec api python scripts/verify_integrity.py

# 5. Start application
docker-compose up -d

#!/bin/bash
# restore_db.sh - Point-in-Time Recovery

# 1. Stop application
docker-compose stop api celery_worker

# 2. Restore latest full backup
aws s3 cp s3://trueangels-backups/database/full_latest.sql.gz /tmp/
gunzip /tmp/full_latest.sql.gz
docker-compose exec -T postgres psql -U admin < /tmp/full_latest.sql

# 3. Apply WAL up to specific time
aws s3 sync s3://trueangels-backups/database/wal/ /tmp/wal/
docker-compose exec postgres bash -c "
    pg_restore --wal-segsize=16 --target-gtid=2024-01-15-14:30:00
"

# 4. Verify integrity
docker-compose exec api alembic upgrade head
docker-compose exec api python scripts/verify_integrity.py

# 5. Start application
docker-compose up -d

# Szenario B: Vollständiger Server-Ausfall
RTO: 4 Stunden | RPO: 15 Minuten

#!/bin/bash
# full_recovery.sh - Disaster Recovery

# 1. Provision new server (Terraform)
cd /opt/terraform
terraform apply -auto-approve

# 2. Install Docker & dependencies
ansible-playbook -i inventory/production.yml playbooks/docker.yml

# 3. Clone repository
git clone https://github.com/trueangels/ngo-suite.git /opt/trueangels
cd /opt/trueangels

# 4. Restore configuration
aws s3 cp s3://trueangels-backups/config/latest.tar.gz /tmp/
tar -xzf /tmp/latest.tar.gz -C /opt/trueangels/

# 5. Start database (restore from backup)
docker-compose up -d postgres
./scripts/restore_db.sh

# 6. Start all services
docker-compose up -d

# 7. Verify all services
./scripts/health_check.sh

# 8. Update DNS (if needed)
aws route53 change-resource-record-sets --hosted-zone-id Z123456 --change-batch file://dns_update.json

# Szenario C: Einzelne Datei/Spende wiederherstellen
RTO: 30 Minuten | RPO: Variabel

#!/bin/bash
# restore_single_donation.sh - Restore specific donation

DONATION_ID=$1

# 1. Extract donation from WAL
docker-compose exec postgres bash -c "
    pg_waldump /mnt/wal_archive/ | grep $DONATION_ID > /tmp/donation_wal.log
"

# 2. Generate SQL for restore
python scripts/generate_restore_sql.py --donation-id $DONATION_ID --output /tmp/restore.sql

# 3. Apply restore
docker-compose exec -T postgres psql -U admin < /tmp/restore.sql

# 4. Verify
curl -f "https://api.trueangels.de/donations/$DONATION_ID"

### 📊 Backup-Monitoring & Alerts
Prometheus Metrics

yaml
yaml
# Backup success rate
- alert: BackupFailed
  expr: backup_success{job="trueangels"} == 0
  annotations:
    summary: "Database backup failed"

# Backup age
- alert: BackupTooOld
  expr: time() - backup_last_success_timestamp > 86400
  annotations:
    summary: "No successful backup in last 24 hours"

# WAL lag
- alert: HighWALLag
  expr: pg_wal_lag_bytes > 1073741824  # 1GB
  annotations:
    summary: "WAL replication lag exceeds 1GB"

### Slack Alerts
yaml

# .github/workflows/backup-monitor.yml
name: Backup Monitor
on:
  schedule:
    - cron: '0 */6 * * *'

jobs:
  check-backups:
    runs-on: ubuntu-latest
    steps:
      - name: Check latest backup
        run: |
          LATEST=$(aws s3 ls s3://trueangels-backups/database/ | sort | tail -n1)
          echo "Latest backup: $LATEST"
          
          # Check if backup is older than 25 hours
          if [ $(date -d "$LATEST" +%s) -lt $(date -d '25 hours ago' +%s) ]; then
            curl -X POST -H 'Content-type: application/json' \
              --data '{"text":"⚠️ Database backup is older than 24 hours!"}' \
              ${{ secrets.SLACK_WEBHOOK }}
          fi

### 🧪 Regelmäßige Wiederherstellungs-Tests
Monatlicher DR-Test

bash
#!/bin/bash
# monthly_dr_test.sh - Automatisierter DR-Test

# 1. Start isolated test environment
docker-compose -f docker-compose.dr-test.yml up -d

# 2. Restore latest backup
./scripts/restore_db.sh --target test

# 3. Run integrity checks
pytest tests/test_integrity.py

# 4. Measure recovery time
START_TIME=$(date +%s)
./scripts/restore_db.sh --target prod
END_TIME=$(date +%s)
RTO=$((END_TIME - START_TIME))

# 5. Report results
echo "DR Test Results:" > dr_report.txt
echo "RTO: $RTO seconds (target: 14400)" >> dr_report.txt
echo "RPO: 15 minutes" >> dr_report.txt

if [ $RTO -le 14400 ]; then
    echo "✅ DR test PASSED" >> dr_report.txt
else
    echo "❌ DR test FAILED" >> dr_report.txt
fi

# 6. Send report
mail -s "Monthly DR Test Results" admin@trueangels.de < dr_report.txt

### 📋 Quick Reference Card
bash
# ==================== QUICK COMMANDS ====================

# Manual backup
make backup

# Restore latest backup
make restore

# Check backup status
make backup-status

# Verify integrity
make verify

# DR test
make dr-test

# View backup metrics
make backup-metrics

# Emergency: Point-in-Time recovery
./scripts/pitr.sh "2024-01-15 14:30:00"

# ==================== EMERGENCY CONTACTS ====================

# 24/7 On-Call: +49 123 4567890
# Backup Admin: backup@trueangels.de
# Security: security@trueangels.de

# ==================== RTO/RPO TRACKING ====================

# Last successful backup: $(date)
# Next scheduled backup: $(date -d "+1 day")
# Backup size: $(du -sh /mnt/backups/)
# WAL archive size: $(du -sh /mnt/wal_archive/)

✅ DR-Readiness Checklist
Wöchentlicher DR-Test durchgeführt

Backups verschlüsselt und in Wasabi S3

WAL-Archivierung aktiv

Monitoring-Alerts konfiguriert

On-Call Rotation definiert

Dokumentation aktualisiert

Berechtigungen geprüft

Verschlüsselungsschlüssel sicher verwahrt

Wiederherstellung in Test-Umgebung getestet

RTO/RPO Ziele erreicht

Letzte Aktualisierung: $(date)
Verantwortlich: DevOps Team
Nächster Test: $(date -d "+1 month")


---

## 🐳 **DOCKER-COMPOSE UPDATE**

```yaml
# FILE: docker-compose.yml (Ergänzung)
# MODULE: Neue Services für Transparenz & Monitoring

services:
  # ... existing services ...

  # ==================== MinIO (Wasabi Alternative für Entwicklung) ====================
  minio:
    image: minio/minio:latest
    container_name: trueangels_minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    networks:
      - trueangels_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s

  # ==================== Traefik (Reverse Proxy) ====================
  traefik:
    image: traefik:v3.0
    container_name: trueangels_traefik
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@trueangels.de"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./letsencrypt:/letsencrypt"
    networks:
      - trueangels_network
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dashboard.rule=Host(`traefik.trueangels.de`)"
      - "traefik.http.routers.dashboard.service=api@internal"

  # ==================== API mit Traefik Labels ====================
  api:
    # ... existing config ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.api.rule=Host(`api.trueangels.de`)"
      - "traefik.http.services.api.loadbalancer.server.port=8000"
      - "traefik.http.routers.api.entrypoints=websecure"
      - "traefik.http.routers.api.tls.certresolver=letsencrypt"

  # ==================== Streamlit mit Traefik ====================
  streamlit:
    # ... existing config ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.streamlit.rule=Host(`transparenz.trueangels.de`)"
      - "traefik.http.services.streamlit.loadbalancer.server.port=8501"
      - "traefik.http.routers.streamlit.entrypoints=websecure"
      - "traefik.http.routers.streamlit.tls.certresolver=letsencrypt"

volumes:
  # ... existing volumes ...
  minio_data:
    driver: local

### ✅ ZUSAMMENFASSUNG DER ÄNDERUNGEN AN BESTEHENDEN MODULEN

Modul 4 (Inventory) - Erweiterung
python

# Änderung: Neue Entity ProjectNeed
# Datei: src/core/entities/needs.py (NEU)

class ProjectNeed(Base):
    """Bedarfe für Projekte"""
    __tablename__ = "project_needs"
    # ... Felder: name, category, priority, quantity_target, etc.

### Modul 8 (WordPress) - Erweiterung
php

// Neue Shortcodes in wp-plugin/shortcodes/transparenz.php
add_shortcode('transparenz_dashboard', '...');
add_shortcode('trueangels_projekteliste', '...');
add_shortcode('trueangels_bedarfeliste', '...');

### Modul 12 (Compliance) - Erweiterung
python

# Neue Datei: src/core/compliance/merkle.py
# Täglicher Merkle-Hash für Transparenz-Daten

### Modul 9 (Backup) - Erweiterung
bash

# Neue Backup-Strategie in docs/dr-playbook.md
# 3-2-1 Backup mit Wasabi S3

### 🚀 NÄCHSTE SCHRITTE FÜR PRODUKTION
bash

# 1. Migration ausführen
docker-compose exec api alembic upgrade head

# 2. Cron-Job für Merkle-Tree einrichten
echo "55 23 * * * root docker-compose exec api python -m src.core.compliance.merkle" >> /etc/crontab

# 3. Backup-Script einrichten
chmod +x scripts/backup.sh
echo "0 2 * * * root /opt/trueangels/scripts/backup.sh" >> /etc/crontab

# 4. WordPress Plugin aktivieren
wp plugin activate trueangels-ngo-suite
wp trueangels sync-projects

# 5. Services neu starten
docker-compose up -d --force-recreate

# 6. Transparenz-Seite testen
curl https://api.trueangels.de/api/v1/transparenz?jahr=2024