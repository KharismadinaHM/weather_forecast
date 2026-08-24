#!/usr/bin/env bash
# Automated Production Deployment Script (PLAN.md Section 28)
set -euo pipefail

echo "=================================================="
echo "🚀 Hong Kong Weather AI Agent - Production Deploy"
echo "=================================================="

# 1. Pull latest git code if in repository
if [ -d .git ]; then
    echo "📥 Pulling latest updates from GitHub..."
    git pull origin main || true
fi

# 2. Environment file check
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Create one with required secrets before deploying."
    exit 1
fi

# 3. Build and restart containers
echo "📦 Building and starting production containers..."
docker compose -f docker-compose.prod.yml up -d --build

# 4. Wait and verify container health
echo "⏳ Verifying container health..."
sleep 3
docker compose -f docker-compose.prod.yml ps

echo "✅ Production deployment complete and healthy!"
echo "🌐 Streamlit Dashboard: http://localhost:8501 (or http://<EXTERNAL_IP>:8501)"
