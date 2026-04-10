#!/bin/bash
# FILE: scripts/validate_compose.sh
# Komplette Validierung aller Aspekte

echo "========================================="
echo "   Docker Compose Validierung"
echo "========================================="

ERRORS=0
WARNINGS=0

# 1. Syntax Check
echo -n "1. YAML Syntax: "
if docker compose -f docker-compose.neu.yml config --no-interpolate > /dev/null 2>&1; then
    echo "✅"
else
    echo "❌"
    ERRORS=$((ERRORS+1))
fi

# 2. Service Count
echo -n "2. Services (14 erwartet): "
COUNT=$(grep -c "^  [a-z_]*:$" docker-compose.neu.yml)
if [ "$COUNT" -eq 14 ]; then
    echo "✅ $COUNT"
else
    echo "❌ $COUNT (sollte 14 sein)"
    ERRORS=$((ERRORS+1))
fi

# 3. Container Names
echo -n "3. Container Names: "
NAMES=$(grep -c "container_name:" docker-compose.neu.yml)
if [ "$NAMES" -eq 13 ]; then
    echo "✅ $NAMES"
else
    echo "⚠️ $NAMES (erwartet 13)"
    WARNINGS=$((WARNINGS+1))
fi

# 4. Healthchecks
echo -n "4. Healthchecks: "
HC=$(grep -c "healthcheck:" docker-compose.neu.yml)
if [ "$HC" -ge 10 ]; then
    echo "✅ $HC"
else
    echo "⚠️ $HC (weniger als 10)"
    WARNINGS=$((WARNINGS+1))
fi

# 5. Image Pinning
echo -n "5. Images gepinnt: "
PINNED=$(grep "image:" docker-compose.neu.yml | grep -c -E ":[0-9]")
TOTAL=$(grep "image:" docker-compose.neu.yml | wc -l)
if [ "$PINNED" -eq "$TOTAL" ]; then
    echo "✅ $PINNED/$TOTAL"
else
    echo "⚠️ $PINNED/$TOTAL"
    WARNINGS=$((WARNINGS+1))
fi

# 6. Vault Mode
echo -n "6. Vault Production Mode: "
if grep -q "VAULT_DEV_" docker-compose.neu.yml; then
    echo "❌ Dev Mode aktiv!"
    ERRORS=$((ERRORS+1))
else
    echo "✅"
fi

# 7. Networks
echo -n "7. Netzwerk 'proxy': "
if grep -q "proxy:" docker-compose.neu.yml; then
    echo "✅"
else
    echo "❌"
    ERRORS=$((ERRORS+1))
fi

# 8. Volumes
echo -n "8. Volumes: "
VOLUMES=$(grep -c "^  [a-z_]+_data:$" docker-compose.neu.yml)
if [ "$VOLUMES" -ge 7 ]; then
    echo "✅ $VOLUMES"
else
    echo "⚠️ $VOLUMES"
    WARNINGS=$((WARNINGS+1))
fi

echo ""
echo "========================================="
echo "📊 Ergebnis: $ERRORS Fehler, $WARNINGS Warnungen"
echo "========================================="

if [ $ERRORS -gt 0 ]; then
    exit 1
fi
