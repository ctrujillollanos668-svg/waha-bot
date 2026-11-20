#!/bin/bash
echo "=== INICIANDO WAHA EN 127.0.0.1:3000 (LOCAL INTERNO) ==="
WHATSAPP_API_HOSTNAME=127.0.0.1 PORT=3000 WHATSAPP_API_PORT=3000 node /app/dist/main.js > /tmp/waha.log 2>&1 &

sleep 2

echo "=== INICIANDO BOT PYTHON FLASK EN 0.0.0.0:5005 (PÚBLICO) ==="
PORT=5005 exec python3 -u /app/bot.py
