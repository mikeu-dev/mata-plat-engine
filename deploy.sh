#!/bin/bash
# ==============================================
# Deploy Script - Mata Plat Engine
# Cara pakai: bash deploy.sh
# ==============================================

set -e  # Stop jika ada error

APP_NAME="smartparking-engine"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================="
echo "🚀 Deploy: $APP_NAME"
echo "📁 Dir: $SCRIPT_DIR"
echo "============================================="

cd "$SCRIPT_DIR"

# 1. Hapus proses PM2 lama (PENTING: jangan pakai restart!)
echo ""
echo "🗑️  [1/3] Menghapus proses PM2 lama..."
pm2 delete "$APP_NAME" 2>/dev/null || echo "   (Tidak ada proses lama, skip)"

# 2. Start fresh dari ecosystem config
echo ""
echo "🟢 [2/3] Memulai proses baru dari ecosystem.config.js..."
pm2 start ecosystem.config.js

# 3. Save PM2 process list
echo ""
echo "💾 [3/3] Menyimpan PM2 process list..."
pm2 save

echo ""
echo "============================================="
echo "✅ Deploy $APP_NAME selesai!"
echo "============================================="
echo ""
echo "📋 Status:"
pm2 show "$APP_NAME" | head -20
echo ""
echo "📜 Untuk melihat log: pm2 logs $APP_NAME --lines 30"
