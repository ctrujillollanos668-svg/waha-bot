#!/bin/bash
export PORT=3000
export WHATSAPP_API_PORT=3000
export WAHA_API_HOSTNAME=0.0.0.0
export WHATSAPP_API_HOSTNAME=0.0.0.0

echo "=== INICIANDO WAHA EN PUERTO 3000 ==="
/entrypoint.sh > /tmp/waha.log 2>&1 &

sleep 5

export PORT=5005
echo "=== INICIANDO BOT PYTHON EN PUERTO 5005 ==="
exec python3 -u /app/bot.py
