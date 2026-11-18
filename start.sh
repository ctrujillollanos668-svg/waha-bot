#!/bin/bash
export WHATSAPP_API_PORT=3000
echo "=== INICIANDO BOT PYTHON (SOFÍA CON GROQ) EN PUERTO 5005 ==="
python3 -u /app/bot.py &

echo "=== INICIANDO SERVIDOR WAHA WHATSAPP EN PUERTO 3000 ==="
exec /entrypoint.sh
