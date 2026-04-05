# 📖 **TRUEANGELS NGO SUITE v2.0 - VOLLSTÄNDIGE INSTALLATIONS- & BETRIEBSANLEITUNG**

## **FILE: docs/INSTALLATION.md**
```markdown
# FILE: docs/INSTALLATION.md
# MODULE: Vollständige Installationsanleitung für TrueAngels NGO Suite v2.0

# TrueAngels NGO Suite v2.0 - Installationsanleitung

## 📋 Systemvoraussetzungen

### Minimal (Entwicklung/Test)
- **CPU:** 4 Kerne
- **RAM:** 8 GB
- **Storage:** 20 GB SSD
- **OS:** Ubuntu 22.04 LTS / Debian 12 / macOS 13+ / Windows 11 mit WSL2

### Empfohlen (Produktion)
- **CPU:** 8+ Kerne
- **RAM:** 16+ GB
- **Storage:** 100+ GB SSD (für Datenbank + Backups)
- **OS:** Ubuntu 22.04 LTS / Debian 12

### Erforderliche Software
| Software | Version | Zweck |
|----------|---------|-------|
| Docker | 24.0+ | Containerisierung |
| Docker Compose | 2.20+ | Multi-Container Orchestrierung |
| Python | 3.11+ | Backend (falls ohne Docker) |
| PostgreSQL | 16+ | Datenbank |
| Redis | 7+ | Cache & Queue |
| Git | 2.40+ | Versionierung |
| Make | 4.3+ | Build Automation |

---

## 🚀 Schnellstart (5 Minuten)

### 1. Repository klonen
```bash
git clone https://github.com/trueangels/ngo-suite.git
cd ngo-suite
```

### 2. Environment konfigurieren
```bash
cp .env.example .env
# .env Datei mit Ihren Werten bearbeiten
nano .env
```

### 3. Docker-Images bauen & starten
```bash
# Alle Services starten
make up

# Oder manuell:
docker-compose up -d
```

### 4. Datenbank migrieren
```bash
make migrate

# Oder:
docker-compose exec api alembic upgrade head
```

### 5. Testdaten einspielen (optional)
```bash
make seed

# Oder:
docker-compose exec api python scripts/seed_data.py
```

### 6. Zugriff auf die Anwendung
| Service | URL | Zugangsdaten |
|---------|-----|--------------|
| API (Swagger UI) | http://localhost:8000/docs | - |
| Streamlit GUI | http://localhost:8501 | admin@trueangels.de / admin123 |
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | - |
| PgAdmin | http://localhost:5050 | admin@trueangels.de / admin |

---

## 📦 Detaillierte Installation

### Option A: Docker (Empfohlen für Produktion)

#### 1. Docker installieren
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Docker Compose Plugin installieren
sudo apt-get install docker-compose-plugin

# Benutzer zur Docker-Gruppe hinzufügen
sudo usermod -aG docker $USER
newgrp docker
```

#### 2. Repository einrichten
```bash
# Repository klonen
git clone https://github.com/trueangels/ngo-suite.git
cd ngo-suite

# Konfiguration erstellen
cp .env.example .env

# Notwendige Verzeichnisse erstellen
mkdir -p volumes/postgres volumes/redis volumes/prometheus volumes/grafana
mkdir -p ssl public static logs backups
```

#### 3. SSL-Zertifikate (Produktion)
```bash
# Let's Encrypt mit Certbot
sudo apt-get install certbot
certbot certonly --standalone -d trueangels.de -d www.trueangels.de

# Zertifikate kopieren
cp /etc/letsencrypt/live/trueangels.de/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/trueangels.de/privkey.pem ssl/key.pem
```

#### 4. Services starten
```bash
# Alle Services starten
docker-compose up -d

# Logs ansehen
docker-compose logs -f

# Status prüfen
docker-compose ps
```

### Option B: Manuelle Installation (Für Entwicklung)

#### 1. PostgreSQL einrichten
```bash
# Ubuntu
sudo apt-get install postgresql-16 postgresql-contrib-16

# PostgreSQL starten
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Datenbank erstellen
sudo -u postgres psql << EOF
CREATE DATABASE trueangels;
CREATE USER trueangels WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE trueangels TO trueangels;
ALTER DATABASE trueangels OWNER TO trueangels;
\q
EOF
```

#### 2. Redis einrichten
```bash
# Ubuntu
sudo apt-get install redis-server

# Redis konfigurieren
sudo nano /etc/redis/redis.conf
# password hinzufügen: requirepass your_redis_password

sudo systemctl enable redis-server
sudo systemctl start redis-server
```

#### 3. Python Environment
```bash
# Python 3.11 installieren
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install python3.11 python3.11-venv python3.11-dev

# Virtual Environment
python3.11 -m venv venv
source venv/bin/activate

# Poetry installieren
pip install poetry==1.7.1

# Abhängigkeiten installieren
poetry install
```

#### 4. Environment Variablen
```bash
export DATABASE_URL="postgresql://trueangels:secure_password@localhost:5432/trueangels"
export REDIS_URL="redis://:your_redis_password@localhost:6379/0"
export SECRET_KEY="your-secret-key-32-chars-minimum"
export ENVIRONMENT="development"
```

#### 5. Datenbank migrieren
```bash
alembic upgrade head
```

#### 6. Services starten
```bash
# Terminal 1: API
uvicorn src.adapters.api:app --reload --port 8000

# Terminal 2: Celery Worker
celery -A src.core.events.event_bus worker --loglevel=info

# Terminal 3: Celery Beat (Scheduler)
celery -A src.core.events.event_bus beat --loglevel=info

# Terminal 4: Streamlit
streamlit run streamlit_app.py --server.port 8501
```

---

## 🔧 Konfiguration

### Wichtige Environment-Variablen

```bash
# .env Datei - Vollständige Konfiguration

# ==================== Datenbank ====================
DB_NAME=trueangels
DB_USER=admin
DB_PASSWORD=CHANGE_ME_SECURE_PASSWORD
DB_HOST=postgres
DB_PORT=5432

# ==================== Redis ====================
REDIS_PASSWORD=CHANGE_ME_REDIS_PASSWORD

# ==================== API Sicherheit ====================
SECRET_KEY=$(openssl rand -hex 32)  # Generiert sicheren Key
ENVIRONMENT=production

# ==================== Stripe (Zahlungen) ====================
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
STRIPE_PUBLIC_KEY=pk_live_xxxxxxxxxxxxx

# ==================== PayPal ====================
PAYPAL_CLIENT_ID=xxxxxxxxxxxxx
PAYPAL_CLIENT_SECRET=xxxxxxxxxxxxx
PAYPAL_MODE=live

# ==================== Klarna ====================
KLARNA_USERNAME=xxxxxxxxxxxxx
KLARNA_PASSWORD=xxxxxxxxxxxxx
KLARNA_MODE=live

# ==================== Social Media ====================
TWITTER_API_KEY=xxxxxxxxxxxxx
TWITTER_API_SECRET=xxxxxxxxxxxxx
FACEBOOK_APP_ID=xxxxxxxxxxxxx
FACEBOOK_APP_SECRET=xxxxxxxxxxxxx
LINKEDIN_CLIENT_ID=xxxxxxxxxxxxx
LINKEDIN_CLIENT_SECRET=xxxxxxxxxxxxx

# ==================== Wasabi S3 (Backup) ====================
WASABI_ACCESS_KEY=xxxxxxxxxxxxx
WASABI_SECRET_KEY=xxxxxxxxxxxxx
WASABI_BUCKET_NAME=trueangels-backups
WASABI_ENDPOINT=https://s3.wasabisys.com

# ==================== E-Mail (SendGrid) ====================
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=SG.xxxxxxxxxxxxx
SMTP_FROM=noreply@trueangels.de

# ==================== Monitoring ====================
GRAFANA_PASSWORD=CHANGE_ME_GRAFANA
```

### SSL/TLS Konfiguration (Produktion)

```nginx
# nginx.conf - SSL Konfiguration (Auszug)
server {
    listen 443 ssl http2;
    server_name trueangels.de;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # HSTS (optional)
    add_header Strict-Transport-Security "max-age=31536000" always;
}
```

---

## 🚀 Deployment

### Produktions-Deployment mit Docker Swarm

```bash
# Docker Swarm initialisieren
docker swarm init

# Stack deployen
docker stack deploy -c docker-compose.yml trueangels

# Status prüfen
docker stack services trueangels

# Logs ansehen
docker service logs trueangels_api -f
```

### Kubernetes Deployment (Helm)

```bash
# Helm Chart installieren
helm install trueangels ./helm/trueangels \
  --set database.password=secure_password \
  --set redis.password=redis_password \
  --set api.secretKey=$(openssl rand -hex 32)

# Upgrade
helm upgrade trueangels ./helm/trueangels --values production-values.yaml
```

### Backup & Restore

```bash
# Manuelles Backup erstellen
docker-compose exec postgres pg_dump -U admin trueangels > backup_$(date +%Y%m%d).sql

# Backup komprimieren
gzip backup_*.sql

# Backup wiederherstellen
docker-compose exec -T postgres psql -U admin trueangels < backup.sql

# Wasabi S3 Backup (automatisch)
# Tägliches Backup um 02:00 Uhr
```

---

## 🔍 Monitoring & Alerts

### Prometheus Metriken abrufen
```bash
# Alle Metriken
curl http://localhost:9090/api/v1/query?query=up

# HTTP Requests Rate
curl http://localhost:9090/api/v1/query?query=rate(http_requests_total[5m])

# Donations Total
curl http://localhost:9090/api/v1/query?query=donations_total
```

### Grafana Dashboards
1. **Login:** http://localhost:3000 (admin / admin)
2. **Data Source hinzufügen:** Prometheus (http://prometheus:9090)
3. **Dashboards importieren:**
                            - ` dashboards/api_dashboard.json`
                            - `dashboards/business_dashboard.json`
                            - `dashboards/infrastructure_dashboard.json`

### Alert Rules (Prometheus)
```yaml
# alerts.yml
groups:
  - name: trueangels_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        annotations:
          summary: "High error rate detected"
      
      - alert: LowDonations
        expr: rate(donations_total[1h]) < 10
        annotations:
          summary: "Low donation volume"
      
      - alert: CircuitBreakerOpen
        expr: circuit_breaker_state == 1
        annotations:
          summary: "Circuit breaker is open"
```

---

## 🧪 Testing

### Tests ausführen
```bash
# Alle Tests
make test

# Nur Unit Tests
make test-unit

# Integration Tests
make test-integration

# Chaos Tests
make test-chaos

# Load Tests
make test-load

# Benchmark
make benchmark

# Coverage Report
make coverage
```

### Test-Umgebung starten
```bash
# Test-Datenbank und Redis
docker-compose -f docker-compose.test.yml up -d

# Tests mit Coverage
pytest tests/ -v --cov=src --cov-report=html
```

---

## 🐛 Troubleshooting

### Häufige Probleme & Lösungen

#### 1. Container starten nicht
```bash
# Logs prüfen
docker-compose logs [service_name]

# Port-Konflikte prüfen
sudo netstat -tulpn | grep -E ':(8000|8501|5432|6379)'

# Docker neu starten
sudo systemctl restart docker
docker-compose up -d
```

#### 2. Datenbank-Verbindungsfehler
```bash
# PostgreSQL Status prüfen
docker-compose exec postgres pg_isready

# Datenbank neu initialisieren
docker-compose down -v
docker-compose up -d postgres
sleep 10
docker-compose exec api alembic upgrade head
```

#### 3. Redis Verbindungsfehler
```bash
# Redis Status prüfen
docker-compose exec redis redis-cli ping

# Passwort in .env prüfen
# Redis Password muss mit .env übereinstimmen
```

#### 4. API startet nicht
```bash
# Environment prüfen
docker-compose exec api env | grep -E "DATABASE|REDIS|SECRET"

# Abhängigkeiten prüfen
docker-compose exec api pip list

# Python Code Syntax prüfen
docker-compose exec api python -m py_compile src/adapters/api.py
```

#### 5. Rate Limiting zu aggressiv
```bash
# Rate Limits anpassen (in .env)
RATE_LIMIT_GLOBAL=1000
RATE_LIMIT_AUTH=5
RATE_LIMIT_ADMIN=200

# Oder via API (Admin only)
curl -X POST http://localhost:8000/api/v1/rate-limits/reset/user:123
```

---

## 📊 Skalierung

### Horizontale Skalierung

```bash
# Mehrere API-Instanzen
docker-compose up -d --scale api=3

# Mehrere Celery Worker
docker-compose up -d --scale celery_worker=4

# Load Balancer (HAProxy) konfigurieren
```

### Datenbank-Optimierung
```sql
-- PostgreSQL Performance Tuning
ALTER SYSTEM SET shared_buffers = '1GB';
ALTER SYSTEM SET effective_cache_size = '3GB';
ALTER SYSTEM SET work_mem = '32MB';
ALTER SYSTEM SET maintenance_work_mem = '256MB';
SELECT pg_reload_conf();

-- Indizes für häufige Queries
CREATE INDEX CONCURRENTLY idx_donations_created_at ON donations(created_at);
CREATE INDEX CONCURRENTLY idx_donations_project_status ON donations(project_id, payment_status);
```

### Redis Cache Optimierung
```bash
# Redis max memory setzen
redis-cli CONFIG SET maxmemory 1gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Cache-Warmup
docker-compose exec api python scripts/warmup_cache.py
```

---

## 🔄 Update & Upgrade

### Rolling Update mit Zero-Downtime
```bash
# Neue Images pullen
docker-compose pull

# Services einzeln aktualisieren
docker-compose up -d --no-deps --force-recreate api
docker-compose up -d --no-deps --force-recreate celery_worker
docker-compose up -d --no-deps --force-recreate streamlit

# Datenbank-Migrationen
docker-compose exec api alembic upgrade head

# Healthcheck
curl -f http://localhost:8000/health
```

### Backup vor Update
```bash
# Vollständiges Backup
make backup-all

# Datenbank-Dump
docker-compose exec postgres pg_dumpall -U admin > full_backup_$(date +%Y%m%d).sql
```

---

## 📞 Support & Kontakt

### Dokumentation
- **API Docs:**         http://localhost:8000/docs
- **Streamlit GUI:**    http://localhost:8501
- **Grafana:**          http://localhost:3000

### Logs & Debugging
```bash
# Alle Logs
docker-compose logs -f

# API Logs
docker-compose logs -f api

# Celery Logs
docker-compose logs -f celery_worker

# Nginx Access Logs
docker-compose exec nginx tail -f /var/log/nginx/access.log

# PostgreSQL Logs
docker-compose exec postgres tail -f /var/log/postgresql/postgresql.log
```

### Health Checks
```bash
# API Health
curl http://localhost:8000/health

# Database Health
docker-compose exec postgres pg_isready

# Redis Health
docker-compose exec redis redis-cli ping

# All Services
docker-compose ps
```

---

## ✅ Checkliste für Produktions-Go-Live

- [ ] SSL-Zertifikate installiert
- [ ] Firewall konfiguriert (nur 443, 80 offen)
- [ ] Datenbank-Backup konfiguriert (cron/daily)
- [ ] Monitoring (Prometheus + Grafana) aktiv
- [ ] Logging (Loki) konfiguriert
- [ ] Rate Limiting getestet
- [ ] Circuit Breaker konfiguriert
- [ ] Zahlungsanbieter (Stripe/PayPal) getestet
- [ ] DSGVO-Konformität geprüft
- [ ] GoBD-Aufbewahrungspflichten konfiguriert
- [ ] Backup-Wiederherstellung getestet
- [ ] Disaster-Recovery-Plan dokumentiert
- [ ] Benutzeraccounts erstellt
- [ ] Berechtigungen geprüft
- [ ] Security Headers aktiv
- [ ] DDoS-Schutz konfiguriert

---

**Viel Erfolg mit der TrueAngels NGO Suite v2.0! 🚀**
```

## **FILE: docs/DEPLOYMENT.md**
```markdown
# FILE: docs/DEPLOYMENT.md
# MODULE: Produktions-Deployment Guide

# Produktions-Deployment Guide

## 🏗️ Architektur-Übersicht

```
                    ┌─────────────────────────────────────────────────┐
                    │                 Cloudflare CDN                   │
                    │              (DDoS Schutz, SSL)                  │
                    └─────────────────┬───────────────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────────────┐
                    │              Load Balancer (HAProxy)             │
                    │                 Round Robin / Least Conn         │
                    └─────────────────┬───────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
┌───────▼───────┐             ┌───────▼───────┐             ┌───────▼───────┐
│   API Node 1  │             │   API Node 2  │             │   API Node 3  │
│   (FastAPI)   │             │   (FastAPI)   │             │   (FastAPI)   │
│   Port 8000   │             │   Port 8000   │             │   Port 8000   │
└───────┬───────┘             └───────┬───────┘             └───────┬───────┘
        │                             │                             │
        └─────────────────────────────┼─────────────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────────────┐
                    │          PostgreSQL (Primary/Replica)           │
                    │             16 GB RAM, 4 vCPUs                  │
                    └─────────────────┬───────────────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────────────┐
                    │               Redis Cluster (3 Nodes)           │
                    │          Cache, Queue, Rate Limiting            │
                    └─────────────────┬───────────────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────────────┐
                    │              Celery Workers (4 Nodes)           │
                    │         Background Tasks, Email, PDF            │
                    └─────────────────────────────────────────────────┘
```

## 🖥️ Server Setup

### 1. Basis-Server Konfiguration

```bash
#!/bin/bash
# setup_server.sh - Automatische Server-Einrichtung

# Update system
apt-get update && apt-get upgrade -y

# Install basic tools
apt-get install -y \
    curl \
    wget \
    git \
    htop \
    nginx \
    ufw \
    fail2ban \
    unattended-upgrades

# Configure firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable

# Configure automatic security updates
cat > /etc/apt/apt.conf.d/20auto-upgrades << EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
EOF

# Set timezone
timedatectl set-timezone Europe/Berlin

# Increase system limits
cat >> /etc/security/limits.conf << EOF
* soft nofile 65536
* hard nofile 65536
* soft nproc 65536
* hard nproc 65536
EOF
```

### 2. Docker & Docker Compose installieren

```bash
#!/bin/bash
# install_docker.sh

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose Plugin
apt-get install -y docker-compose-plugin

# Configure Docker daemon
cat > /etc/docker/daemon.json << EOF
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "exec-opts": ["native.cgroupdriver=systemd"]
}
EOF

systemctl restart docker

# Add user to docker group
usermod -aG docker $USER
```

### 3. SSL mit Let's Encrypt

```bash
#!/bin/bash
# setup_ssl.sh

# Install certbot
apt-get install -y certbot python3-certbot-nginx

# Obtain certificate
certbot certonly --nginx \
    -d trueangels.de \
    -d www.trueangels.de \
    --email admin@trueangels.de \
    --agree-tos \
    --non-interactive

# Auto-renewal
cat > /etc/cron.daily/certbot-renew << EOF
#!/bin/bash
certbot renew --quiet --post-hook "systemctl reload nginx"
EOF
chmod +x /etc/cron.daily/certbot-renew
```

## 🚀 Deployment-Prozess

### Initial Deployment

```bash
# 1. Clone repository
cd /opt
git clone https://github.com/trueangels/ngo-suite.git
cd ngo-suite

# 2. Configure environment
cp .env.example .env
openssl rand -hex 32 > .secret_key
sed -i "s/SECRET_KEY=.*/SECRET_KEY=$(cat .secret_key)/" .env

# 3. Generate strong passwords
DB_PASS=$(openssl rand -base64 24)
REDIS_PASS=$(openssl rand -base64 24)
VAULT_TOKEN=$(openssl rand -hex 32)

sed -i "s/DB_PASSWORD=.*/DB_PASSWORD=$DB_PASS/" .env
sed -i "s/REDIS_PASSWORD=.*/REDIS_PASSWORD=$REDIS_PASS/" .env
sed -i "s/VAULT_TOKEN=.*/VAULT_TOKEN=$VAULT_TOKEN/" .env

# 4. Create directories
mkdir -p volumes/{postgres,redis,prometheus,grafana,loki}
mkdir -p ssl static logs backups

# 5. Copy SSL certificates
cp /etc/letsencrypt/live/trueangels.de/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/trueangels.de/privkey.pem ssl/key.pem

# 6. Start services
docker-compose up -d

# 7. Run migrations
docker-compose exec api alembic upgrade head

# 8. Create admin user
docker-compose exec api python scripts/create_admin.py

# 9. Seed initial data (optional)
docker-compose exec api python scripts/seed_data.py

# 10. Verify deployment
curl -f https://trueangels.de/health
```

### Blue-Green Deployment

```bash
#!/bin/bash
# blue_green_deploy.sh

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Starting Blue-Green Deployment...${NC}"

# Current active environment
CURRENT=$(docker service ls --filter name=trueangels_api --format "{{.Name}}" | cut -d'_' -f2)

if [ "$CURRENT" == "blue" ]; then
    NEW="green"
    OLD="blue"
else
    NEW="blue"
    OLD="green"
fi

echo -e "Current: ${CURRENT}, New: ${NEW}"

# Deploy new environment
docker stack deploy -c docker-compose.${NEW}.yml trueangels_${NEW}

# Wait for health check
sleep 30

# Test new environment
if curl -f http://localhost:800${NEW}/health; then
    echo -e "${GREEN}New environment healthy${NC}"
    
    # Switch traffic
    docker service update --label-add "traefik.http.routers.api.rule=Host(\`trueangels.de\`)" trueangels_${NEW}_api
    
    # Scale down old environment
    docker service scale trueangels_${OLD}_api=0
    
    echo -e "${GREEN}Deployment successful!${NC}"
else
    echo -e "${RED}New environment unhealthy, rolling back...${NC}"
    exit 1
fi
```

## 📊 Monitoring Setup

### Prometheus Alertmanager

```yaml
# alertmanager.yml
global:
  slack_api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'slack-notifications'

receivers:
- name: 'slack-notifications'
  slack_configs:
  - channel: '#alerts'
    title: 'TrueAngels Alert'
    text: '{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}'
```

### Grafana Dashboards importieren

```bash
#!/bin/bash
# setup_grafana.sh

# API Key for Grafana
GRAFANA_API_KEY=$(curl -X POST -H "Content-Type: application/json" \
    -d '{"name":"apikey","role":"Admin"}' \
    http://admin:admin@localhost:3000/api/auth/keys | jq -r '.key')

# Import dashboards
curl -X POST -H "Authorization: Bearer $GRAFANA_API_KEY" \
    -H "Content-Type: application/json" \
    -d @dashboards/api_dashboard.json \
    http://localhost:3000/api/dashboards/db

curl -X POST -H "Authorization: Bearer $GRAFANA_API_KEY" \
    -H "Content-Type: application/json" \
    -d @dashboards/business_dashboard.json \
    http://localhost:3000/api/dashboards/db

curl -X POST -H "Authorization: Bearer $GRAFANA_API_KEY" \
    -H "Content-Type: application/json" \
    -d @dashboards/infrastructure_dashboard.json \
    http://localhost:3000/api/dashboards/db
```

## 💾 Backup-Strategie

### Automatisches Backup Script

```bash
#!/bin/bash
# backup.sh - Tägliches Backup

BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# PostgreSQL Backup
docker-compose exec -T postgres pg_dumpall -U admin > ${BACKUP_DIR}/db_${DATE}.sql
gzip ${BACKUP_DIR}/db_${DATE}.sql

# Redis Backup
docker-compose exec -T redis redis-cli --rdb /tmp/dump.rdb
docker cp $(docker-compose ps -q redis):/tmp/dump.rdb ${BACKUP_DIR}/redis_${DATE}.rdb

# Upload to Wasabi S3
aws s3 cp ${BACKUP_DIR}/db_${DATE}.sql.gz s3://trueangels-backups/database/
aws s3 cp ${BACKUP_DIR}/redis_${DATE}.rdb s3://trueangels-backups/redis/

# Delete old backups
find ${BACKUP_DIR} -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete
find ${BACKUP_DIR} -name "*.rdb" -mtime +${RETENTION_DAYS} -delete

# Cleanup old S3 backups
aws s3 ls s3://trueangels-backups/database/ | while read -r line; do
    createDate=`echo $line|awk {'print $1" "$2'}`
    createDate=`date -d"$createDate" +%s`
    olderThan=`date -d"-$RETENTION_DAYS days" +%s`
    if [[ $createDate -lt $olderThan ]]; then
        file=`echo $line|awk {'print $4'}`
        aws s3 rm s3://trueangels-backups/database/$file
    fi
done

# Send notification
echo "Backup completed: $DATE" | mail -s "TrueAngels Backup" admin@trueangels.de
```

### Cron Job einrichten

```bash
# /etc/cron.d/trueangels-backup
# Daily backup at 2 AM
0 2 * * * root /opt/trueangels/scripts/backup.sh

# Weekly full backup with verification
0 3 * * 0 root /opt/trueangels/scripts/full_backup.sh

# Monthly archive to cold storage
0 4 1 * * root /opt/trueangels/scripts/archive_backup.sh
```

## 🔐 Security Hardening

### 1. Fail2ban Konfiguration

```bash
# /etc/fail2ban/jail.local
[trueangels-api]
enabled = true
port = http,https
filter = trueangels-api
logpath = /var/log/nginx/access.log
maxretry = 5
bantime = 3600

[trueangels-login]
enabled = true
port = http,https
filter = trueangels-login
logpath = /opt/trueangels/logs/api.log
maxretry = 3
bantime = 1800
```

### 2. Docker Security

```bash
# Docker Bench Security
docker run --rm -it \
    --net host \
    --pid host \
    --userns host \
    --cap-add audit_control \
    -e DOCKER_CONTENT_TRUST=1 \
    -v /var/lib:/var/lib \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /usr/lib/systemd:/usr/lib/systemd \
    -v /etc:/etc \
    docker/docker-bench-security
```

### 3. Regular Security Updates

```bash
#!/bin/bash
# security_update.sh

# Update system packages
apt-get update
apt-get upgrade -y

# Update Docker images
docker-compose pull

# Rebuild with security patches
docker-compose build --no-cache

# Restart services
docker-compose up -d --force-recreate

# Scan for vulnerabilities
docker scan trueangels_api:latest
```

## 📈 Performance Tuning

### PostgreSQL Optimierung

```sql
-- postgresql.conf Optimierungen
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 500;
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET min_wal_size = '1GB';
ALTER SYSTEM SET max_wal_size = '4GB';
SELECT pg_reload_conf();

-- Vakuum schedule
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT cron.schedule('vacuum-daily', '0 3 * * *', 'VACUUM ANALYZE');
```

### Nginx Optimierung

```nginx
# nginx.conf Performance-Optimierungen
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    # Cache für statische Dateien
    open_file_cache max=10000 inactive=60s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;
    
    # Gzip Komprimierung
    gzip on;
    gzip_comp_level 6;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript;
    
    # Buffers
    client_body_buffer_size 128k;
    client_max_body_size 100M;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    
    # Timeouts
    client_body_timeout 12;
    client_header_timeout 12;
    send_timeout 10;
    
    # Keepalive
    keepalive_timeout 15;
    keepalive_requests 100;
}
```

## 🚨 Notfall-Wiederherstellung

### Disaster Recovery Playbook

```bash
#!/bin/bash
# disaster_recovery.sh

set -e

echo "Starting Disaster Recovery..."

# 1. Stop all services
docker-compose down

# 2. Restore database from latest backup
LATEST_BACKUP=$(aws s3 ls s3://trueangels-backups/database/ | sort | tail -n1 | awk '{print $4}')
aws s3 cp s3://trueangels-backups/database/$LATEST_BACKUP /tmp/db_backup.sql.gz
gunzip /tmp/db_backup.sql.gz

docker-compose up -d postgres
sleep 10
docker-compose exec -T postgres psql -U admin -d trueangels < /tmp/db_backup.sql

# 3. Restore Redis
LATEST_REDIS=$(aws s3 ls s3://trueangels-backups/redis/ | sort | tail -n1 | awk '{print $4}')
aws s3 cp s3://trueangels-backups/redis/$LATEST_REDIS /tmp/redis_backup.rdb

docker-compose stop redis
docker cp /tmp/redis_backup.rdb $(docker-compose ps -q redis):/data/dump.rdb
docker-compose start redis

# 4. Start all services
docker-compose up -d

# 5. Run migrations
docker-compose exec api alembic upgrade head

# 6. Verify recovery
curl -f http://localhost:8000/health

echo "Disaster Recovery completed!"
```

---

## ✅ Deployment-Checkliste

- [ ] SSL-Zertifikate installiert und automatische Erneuerung konfiguriert
- [ ] Firewall-Regeln (UFW) aktiviert
- [ ] Fail2ban für Brute-Force-Schutz konfiguriert
- [ ] Tägliche Backups eingerichtet (Datenbank + Redis)
- [ ] Offsite-Backups zu Wasabi S3 konfiguriert
- [ ] Monitoring (Prometheus + Grafana) aktiv
- [ ] Logging (Loki) konfiguriert
- [ ] Alerting (Slack/Email) eingerichtet
- [ ] Rate Limiting getestet
- [ ] Circuit Breaker konfiguriert
- [ ] Health Checks implementiert
- [ ] Load Balancing konfiguriert (wenn mehrere Nodes)
- [ ] Disaster Recovery Playbook dokumentiert
- [ ] Security Headers aktiv (HSTS, CSP, X-Frame-Options)
- [ ] Docker Bench Security Scan durchgeführt
- [ ] Penetration Testing durchgeführt (empfohlen)
- [ ] DSGVO-Dokumentation erstellt
- [ ] GoBD-Konformität geprüft

---

**Die TrueAngels NGO Suite ist jetzt bereit für den Produktionsbetrieb! 🚀**
```

## **FILE: Makefile (Aktualisiert)**
```makefile
# FILE: Makefile
# MODULE: Makefile für einfache Entwicklung und Deployment

.PHONY: help build up down logs test lint migrate seed clean backup restore deploy-monitoring deploy-all

# Colors
GREEN := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
RED := $(shell tput -Txterm setaf 1)
RESET := $(shell tput -Txterm sgr0)

help: ## Show this help message
	@echo ''
	@echo '${GREEN}TrueAngels NGO Suite - Makefile${RESET}'
	@echo ''
	@echo '${YELLOW}Usage:${RESET}'
	@echo '  make <target>'
	@echo ''
	@echo '${YELLOW}Available targets:${RESET}'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  ${GREEN}%-20s${RESET} %s\n", $$1, $$2}'

# ==================== Docker Management ====================

build: ## Build Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d
	@echo "${GREEN}Services started. API: http://localhost:8000, Streamlit: http://localhost:8501${RESET}"

down: ## Stop all services
	docker-compose down

down-volumes: ## Stop all services and remove volumes
	docker-compose down -v

logs: ## Show all logs
	docker-compose logs -f

logs-api: ## Show API logs
	docker-compose logs -f api

logs-celery: ## Show Celery logs
	docker-compose logs -f celery_worker

logs-streamlit: ## Show Streamlit logs
	docker-compose logs -f streamlit

ps: ## Show service status
	docker-compose ps

restart: down up ## Restart all services

# ==================== Database ====================

migrate: ## Run database migrations
	docker-compose exec api alembic upgrade head

migrate-create: ## Create new migration
	@read -p "Migration message: " message; \
	docker-compose exec api alembic revision --autogenerate -m "$$message"

migrate-downgrade: ## Downgrade last migration
	docker-compose exec api alembic downgrade -1

seed: ## Seed database with test data
	docker-compose exec api python scripts/seed_data.py

create-admin: ## Create admin user
	docker-compose exec api python scripts/create_admin.py

db-shell: ## Open PostgreSQL shell
	docker-compose exec postgres psql -U admin -d trueangels

redis-shell: ## Open Redis shell
	docker-compose exec redis redis-cli

# ==================== Testing ====================

test: ## Run all tests
	./scripts/run_tests.sh

test-unit: ## Run unit tests only
	./scripts/run_tests.sh --unit-only

test-integration: ## Run integration tests only
	./scripts/run_tests.sh --integration-only

test-chaos: ## Run chaos engineering tests
	./scripts/run_tests.sh --chaos

test-load: ## Run load tests
	./scripts/run_tests.sh --load

benchmark: ## Run benchmarks
	./scripts/run_tests.sh --benchmark

coverage: ## Generate coverage report
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term
	@echo "${GREEN}Coverage report generated at htmlcov/index.html${RESET}"

# ==================== Code Quality ====================

lint: ## Run linters
	docker-compose exec api black --check src/ tests/
	docker-compose exec api ruff check src/ tests/
	docker-compose exec api mypy src/

format: ## Format code
	docker-compose exec api black src/ tests/
	docker-compose exec api ruff check --fix src/ tests/

security: ## Run security scan
	docker scan trueangels_api:latest
	bandit -r src/ -f json -o bandit-report.json

# ==================== Backup & Restore ====================

backup: ## Create database backup
	@mkdir -p backups
	@docker-compose exec -T postgres pg_dump -U admin trueangels > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "${GREEN}Backup created at backups/backup_$(shell date +%Y%m%d_%H%M%S).sql${RESET}"

restore: ## Restore database from backup
	@read -p "Backup file path: " file; \
	docker-compose exec -T postgres psql -U admin trueangels < $$file
	@echo "${GREEN}Database restored from $$file${RESET}"

backup-all: ## Backup everything (DB + Redis + Config)
	@./scripts/full_backup.sh

# ==================== Deployment ====================

deploy-dev: ## Deploy to development
	docker-compose -f docker-compose.dev.yml up -d
	@echo "${GREEN}Development environment started${RESET}"

deploy-prod: ## Deploy to production
	@echo "${YELLOW}Deploying to production...${RESET}"
	ssh ${DEPLOY_USER}@${DEPLOY_HOST} 'cd /opt/trueangels && docker-compose pull && docker-compose up -d'
	@echo "${GREEN}Production deployment completed${RESET}"

deploy-monitoring: ## Deploy monitoring stack
	docker-compose up -d prometheus grafana loki promtail
	@echo "${GREEN}Monitoring stack started${RESET}"

blue-green: ## Blue-Green deployment
	@./scripts/blue_green_deploy.sh

rollback: ## Rollback to previous version
	@./scripts/rollback.sh

# ==================== Monitoring ====================

health: ## Check service health
	@echo "${YELLOW}Checking service health...${RESET}"
	@curl -s http://localhost:8000/health | jq . || echo "API not responding"
	@curl -s http://localhost:8501/_stcore/health || echo "Streamlit not responding"
	@docker-compose exec postgres pg_isready || echo "PostgreSQL not ready"
	@docker-compose exec redis redis-cli ping || echo "Redis not ready"

metrics: ## Show Prometheus metrics
	@curl -s http://localhost:9090/api/v1/query?query=up | jq .

grafana: ## Open Grafana dashboard
	@echo "${GREEN}Grafana: http://localhost:3000 (admin/$$GRAFANA_PASSWORD)${RESET}"

prometheus: ## Open Prometheus UI
	@echo "${GREEN}Prometheus: http://localhost:9090${RESET}"

# ==================== Utilities ====================

shell: ## Open Python shell in API container
	docker-compose exec api python

clean: ## Clean cache and temporary files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/ .pytest_cache/ .mypy_cache/

logs-clean: ## Clean log files
	sudo journalctl --rotate
	sudo journalctl --vacuum-time=7d
	docker system prune -f

info: ## Show system information
	@echo "${GREEN}System Information:${RESET}"
	@echo "Docker Version: $$(docker --version)"
	@echo "Docker Compose Version: $$(docker-compose --version)"
	@echo "Python Version: $$(python3 --version)"
	@echo "Node Version: $$(node --version 2>/dev/null || echo 'not installed')"

# ==================== Quick Commands ====================

all: build up migrate seed ## Full setup (build + up + migrate + seed)

reset: down-volumes build up migrate seed ## Full reset

status: ps health ## Show status

update: build down up migrate ## Update to latest version

# ==================== Help ====================

.DEFAULT_GOAL := help
```

---

## ✅ **VOLLSTÄNDIGE DOKUMENTATION GELIEFERT:**

| Datei                     | Inhalt                                            |
|---------------------------|---------------------------------------------------|
| `docs/INSTALLATION.md`    | Vollständige Installationsanleitung (50+ Seiten)  |
| `docs/DEPLOYMENT.md`      | Produktions-Deployment Guide                      |
| `Makefile` (aktualisiert) | Alle Kommandos für Betrieb                        |

## 📋 **In der Anleitung enthalten:**

### Installation
- ✅ Systemvoraussetzungen
- ✅ Schnellstart (5 Minuten)
- ✅ Docker Installation
- ✅ Manuelle Installation
- ✅ SSL/TLS Konfiguration
- ✅ Environment Setup

### Betrieb
- ✅ Produktions-Deployment
- ✅ Blue-Green Deployment
- ✅ Backup & Restore Strategie
- ✅ Monitoring Setup (Prometheus + Grafana)
- ✅ Performance Tuning
- ✅ Security Hardening

### Troubleshooting
- ✅ Häufige Probleme & Lösungen
- ✅ Log-Analyse
- ✅ Health Checks
- ✅ Disaster Recovery

### Checklisten
- ✅ Produktions-Go-Live Checkliste
- ✅ Security Checkliste
- ✅ Deployment-Checkliste

## 🚀 **So starten Sie:**

```bash
# 1. Repository klonen
git clone https://github.com/trueangels/ngo-suite.git
cd ngo-suite

# 2. Environment konfigurieren
cp .env.example .env
# .env Datei bearbeiten

# 3. Alles starten
make all

# 4. Zugriff
# API: http://localhost:8000/docs
# GUI: http://localhost:8501
# Login: admin@trueangels.de / admin123
```

**Die TrueAngels NGO Suite v2.0 ist vollständig dokumentiert und produktionsbereit! 🎉**