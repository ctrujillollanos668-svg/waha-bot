FROM devlikeapro/waha:latest

# Instalar Python 3 y paquetes requeridos para bot.py
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-requests \
    python3-flask \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Aplicar parche de WAHA
COPY patch_waha.js /app/patch_waha.js
RUN node /app/patch_waha.js

# Copiar archivos del bot y arranque
COPY bot.py /app/bot.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Configuración de variables
ENV WHATSAPP_HOOK_URL=http://localhost:5005/webhook
ENV WHATSAPP_HOOK_EVENTS=message,message.any
ENV WAHA_BASE_URL=http://localhost:3000
ENV WAHA_API_KEY=34ec073c9c6e45738171e5fbd14a7498
ENV WAHA_DASHBOARD_ENABLED=True
ENV WAHA_DASHBOARD_USERNAME=admin
ENV WAHA_DASHBOARD_PASSWORD=admin
ENV WHATSAPP_DEFAULT_ENGINE=WEBJS
ENV WHATSAPP_START_SESSION=default
ENV WHATSAPP_RESTART_ALL_SESSIONS=True
ENV GROQ_MODEL=openai/gpt-oss-120b

EXPOSE 3000 5005

CMD ["/app/start.sh"]
