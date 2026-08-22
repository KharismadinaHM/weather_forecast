#!/usr/bin/env bash
# Automated Production Deployment Script (PLAN.md Section 28)
set -euo pipefail

echo "=================================================="
echo "🚀 Hong Kong Weather AI Agent - Production Deploy"
echo "=================================================="

# 1. Environment file check
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Create one with required secrets before deploying."
    exit 1
fi

# 2. Build and restart containers
echo "📦 Building and starting production containers..."
docker compose -f docker-compose.prod.yml down --remove-orphans || true
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 3. Wait for PostgreSQL and Agent healthcheck
echo "⏳ Verifying container health..."
docker compose -f docker-compose.prod.yml ps

echo "✅ Production deployment complete and healthy!"
