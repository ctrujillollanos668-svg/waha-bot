#!/bin/bash
echo "=== INICIANDO BOT PYTHON (SOFÍA CON GROQ) ==="
python3 -u /app/bot.py &

echo "=== INICIANDO SERVIDOR WAHA WHATSAPP ==="
exec /entrypoint.sh
