#!/bin/bash
echo "=== INICIANDO WAHA EN 127.0.0.1:3001 (LOCAL INTERNO) ==="
WHATSAPP_API_HOSTNAME=127.0.0.1 PORT=3001 WHATSAPP_API_PORT=3001 node /app/dist/main.js > /tmp/waha.log 2>&1 &

sleep 3

echo "=== INICIANDO BOT PYTHON FLASK EN 0.0.0.0:3000 (PÚBLICO RENDER) ==="
PORT=3000 exec python3 -u /app/bot.py
