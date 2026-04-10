#!/bin/bash
# FILE: cleanup.sh

echo "🧹 Stopping and removing all containers..."
docker compose down -v --rmi all 2>/dev/null

echo "🧹 Removing all trueangels containers..."
docker ps -a --filter "name=trueangels" -q | xargs -r docker rm -f
docker ps -a --filter "name=ngo-suite" -q | xargs -r docker rm -f

echo "🧹 Removing all trueangels images..."
docker images --filter "reference=trueangels*" -q | xargs -r docker rmi -f
docker images --filter "reference=*ngo-suite*" -q | xargs -r docker rmi -f

echo "🧹 Removing all trueangels volumes..."
docker volume ls --filter "name=trueangels" -q | xargs -r docker volume rm
docker volume ls --filter "name=ngo-suite" -q | xargs -r docker volume rm

echo "🧹 Pruning system..."
docker system prune -a -f --volumes

echo "✅ Cleanup complete!"
