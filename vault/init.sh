#!/bin/bash
# FILE: vault/init.sh
# MODULE: Vault Initialization Script für Produktion

# Auf Vault warten
until vault status &>/dev/null; do
  echo "Waiting for Vault to start..."
  sleep 2
done

# Prüfen ob bereits initialisiert
if vault status | grep -q "Initialized.*true"; then
  echo "Vault already initialized"
  exit 0
fi

# Vault initialisieren (nur einmal)
vault operator init -key-shares=1 -key-threshold=1 > /vault/data/init-keys.txt

# Unseal Key und Root Token extrahieren
UNSEAL_KEY=$(grep "Unseal Key 1:" /vault/data/init-keys.txt | awk '{print $4}')
ROOT_TOKEN=$(grep "Initial Root Token:" /vault/data/init-keys.txt | awk '{print $4}')

# Vault entsiegeln
vault operator unseal $UNSEAL_KEY

# Mit Root Token einloggen
vault login $ROOT_TOKEN

# KV Secrets Engine aktivieren
vault secrets enable -version=2 kv

# Policies erstellen
vault policy write trueangels - <<EOF
path "kv/data/trueangels/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "kv/metadata/trueangels/*" {
  capabilities = ["list"]
}
EOF

# AppRole Auth aktivieren
vault auth enable approle

# Rolle für API erstellen
vault write auth/approle/role/trueangels-api \
  secret_id_ttl=24h \
  token_ttl=1h \
  token_max_ttl=8h \
  policies=trueangels

# Secrets schreiben
vault kv put kv/trueangels/database \
  host="postgres" \
  port="5432" \
  name="trueangels" \
  user="admin" \
  password="${DB_PASSWORD}"

vault kv put kv/trueangels/redis \
  host="redis" \
  port="6379" \
  password="${REDIS_PASSWORD}"

vault kv put kv/trueangels/stripe \
  secret_key="${STRIPE_SECRET_KEY}" \
  webhook_secret="${STRIPE_WEBHOOK_SECRET}"

echo "Vault initialized successfully!"
echo "Root Token: $ROOT_TOKEN"
echo "Unseal Key: $UNSEAL_KEY"
