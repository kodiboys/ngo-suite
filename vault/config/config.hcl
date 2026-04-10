# FILE: vault/config.hcl
# MODULE: Vault Production Configuration

# Storage Backend (Raft für HA, File für Single Node)
storage "raft" {
  path = "/vault/data"
  node_id = "node1"
  
  # Für Single Node:
  retry_join {
    leader_api_addr = "http://vault:8200"
  }
}

# Oder für Entwicklung/Test mit Persistenz:
# storage "file" {
#   path = "/vault/data"
# }

# Listener
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true  # In Produktion: false + TLS Zertifikate
}

# API Address
api_addr = "http://vault:8200"
cluster_addr = "https://vault:8201"

# UI aktivieren
ui = true

# Log Level
log_level = "info"
