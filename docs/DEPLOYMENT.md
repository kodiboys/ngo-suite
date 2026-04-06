Viel Erfolg mit der TrueAngels NGO Suite v2.0! 🚀

text

## **FILE: docs/DEPLOYMENT.md**
```markdown
# FILE: docs/DEPLOYMENT.md
# MODULE: Produktions-Deployment Guide

# Produktions-Deployment Guide

## 🏗️ Architektur-Übersicht
┌─────────────────────────────────────────────────┐
│ Cloudflare CDN │
│ (DDoS Schutz, SSL) │
└─────────────────┬───────────────────────────────┘
│
┌─────────────────▼───────────────────────────────┐
│ Load Balancer (HAProxy) │
│ Round Robin / Least Conn │
└─────────────────┬───────────────────────────────┘
│
┌─────────────────────────────┼─────────────────────────────┐
│ │ │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│ API Node 1 │ │ API Node 2 │ │ API Node 3 │
│ (FastAPI) │ │ (FastAPI) │ │ (FastAPI) │
│ Port 8000 │ │ Port 8000 │ │ Port 8000 │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
│ │ │
└─────────────────────────────┼─────────────────────────────┘
│
┌─────────────────▼───────────────────────────────┐
│ PostgreSQL (Primary/Replica) │
│ 16 GB RAM, 4 vCPUs │
└─────────────────┬───────────────────────────────┘
│
┌─────────────────▼───────────────────────────────┐
│ Redis Cluster (3 Nodes) │
│ Cache, Queue, Rate Limiting │
└─────────────────┬───────────────────────────────┘
│
┌─────────────────▼───────────────────────────────┐
│ Celery Workers (4 Nodes) │
│ Background Tasks, Email, PDF │
└─────────────────────────────────────────────────┘

text

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
2. Docker & Docker Compose installieren
bash
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
3. SSL mit Let's Encrypt
bash
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
🚀 Deployment-Prozess
Initial Deployment
bash
# 1. Clone repository
cd /opt
git clone https://github.com/kodiboys/ngo-suite.git
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
Blue-Green Deployment
bash
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
📊 Monitoring Setup
Prometheus Alertmanager
yaml
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
Grafana Dashboards importieren
bash
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
💾 Backup-Strategie
Automatisches Backup Script
bash
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
Cron Job einrichten
bash
# /etc/cron.d/trueangels-backup
# Daily backup at 2 AM
0 2 * * * root /opt/trueangels/scripts/backup.sh

# Weekly full backup with verification
0 3 * * 0 root /opt/trueangels/scripts/full_backup.sh

# Monthly archive to cold storage
0 4 1 * * root /opt/trueangels/scripts/archive_backup.sh
🔐 Security Hardening
1. Fail2ban Konfiguration
bash
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
2. Docker Security
bash
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
3. Regular Security Updates
bash
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
📈 Performance Tuning
PostgreSQL Optimierung
sql
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
Nginx Optimierung
nginx
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
🚨 Notfall-Wiederherstellung
Disaster Recovery Playbook
bash
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
✅ Deployment-Checkliste
SSL-Zertifikate installiert und automatische Erneuerung konfiguriert

Firewall-Regeln (UFW) aktiviert

Fail2ban für Brute-Force-Schutz konfiguriert

Tägliche Backups eingerichtet (Datenbank + Redis)

Offsite-Backups zu Wasabi S3 konfiguriert

Monitoring (Prometheus + Grafana) aktiv

Logging (Loki) konfiguriert

Alerting (Slack/Email) eingerichtet

Rate Limiting getestet

Circuit Breaker konfiguriert

Health Checks implementiert

Load Balancing konfiguriert (wenn mehrere Nodes)

Disaster Recovery Playbook dokumentiert

Security Headers aktiv (HSTS, CSP, X-Frame-Options)

Docker Bench Security Scan durchgeführt

Penetration Testing durchgeführt (empfohlen)

DSGVO-Dokumentation erstellt

GoBD-Konformität geprüft