#!/bin/bash
echo "=== INICIANDO WAHA EN PUERTO 3000 ==="
PORT=3000 WHATSAPP_API_PORT=3000 node /app/dist/main.js > /tmp/waha.log 2>&1 &

sleep 5

echo "=== INICIANDO BOT PYTHON EN PUERTO 5005 ==="
PORT=5005 exec python3 -u /app/bot.py
