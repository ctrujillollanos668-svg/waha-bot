import sys
import os
import requests
import logging
import time
from datetime import datetime
from flask import Flask, request, jsonify

# Redirección segura para ejecución en segundo plano (pythonw)
if sys.stdout is None:
    sys.stdout = open(os.path.join(os.path.dirname(__file__), "bot.log"), "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = open(os.path.join(os.path.dirname(__file__), "bot_error.log"), "a", encoding="utf-8", buffering=1)

# ===========================
# 1. CONFIGURACIÓN
# ===========================
WAHA_URL = "http://localhost:3000"
WAHA_API_KEY = "34ec073c9c6e45738171e5fbd14a7498"
WAHA_SESSION = "default"

# Configuración IA en la nube (Groq - 24/7 y Ultra rápido)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Respaldo Ollama local (opcional)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3:8b"
OLLAMA_VISION_MODEL = "llava"

# Configuración de Horario de Atención (8:00 AM a 8:00 PM)
START_HOUR = 8   # 8:00 AM
END_HOUR = 20    # 8:00 PM (20:00)

SYSTEM_PROMPT = """
Eres Sofía, asesora de atención al cliente de la empresa Fortex por WhatsApp.
Tu misión es hablar como una persona real: educada, empática, coherente y con sentido común. NUNCA hables como un robot ni repitas frases acartonadas.

PAUTAS DE CONVERSACIÓN HUMANA:
1. PRIMER MENSAJE DE LA CONVERSACIÓN:
   - Preséntate amablemente con calidez:
     "¡Hola! Te habla Sofía del equipo de atención de Fortex. 👋 ¿Cómo te encuentras hoy? ¿En qué te puedo colaborar?"
   - Si el cliente ya saludó y fue directo al grano con su necesidad, salúdalo brevemente y atiende lo que te pide sin rodeos.

2. CONVERSACIÓN EN CURSO (MUY IMPORTANTE):
   - Si la conversación ya está iniciada, ¡PROHIBIDO volver a decir 'Hola', 'Bienvenido a Fortex' o presentarte de nuevo!
   - Responde de forma continua, coherente y natural a lo último que te dijo el cliente, usando expresiones comunes como: "Claro que sí", "Entendido", "Con gusto", "Perfecto".

3. FLUJO INTELIGENTE DE RECUPERACIÓN DE CONTRASEÑA:
   - Cuando el cliente mencione que olvidó o quiere recuperar su clave:
     * Si no ha especificado qué cuenta o número es, pregúntale con naturalidad: "¿Claro que sí, me confirmas por favor cuál es el usuario, correo o número de celular registrado en la cuenta que deseas actualizar?"
     * Si el cliente ya te dio el número, usuario o correo:
       Confírmale de manera tranquilizadora y profesional:
       "Listo, ya quedó radicada la solicitud en el sistema para esa cuenta. En un lapso aproximado de 10 a 15 minutos tu contraseña será actualizada. Te estaremos confirmando por este medio. ¿Hay algo más en lo que te pueda ayudar?"
   - PROHIBICIÓN ESTRICTA: NUNCA pidas códigos de verificación, ni menciones códigos SMS o tokens. En Fortex NO se envían códigos de verificación por chat.

4. HORARIO DE ATENCIÓN Y DISPONIBILIDAD:
   - Nuestro horario de atención oficial es de 8:00 a.m. a 8:00 p.m.
   - Si el cliente pregunta sobre nuestros horarios o disponibilidad, indícaselo con amabilidad y naturalidad.

5. ESTILO:
   - Respuestas breves (máximo 2 a 3 líneas), fáciles de leer en el celular.
   - Trato humano, cercano y profesional.

6. FOTOS E IMÁGENES:
   - Tú SÍ PUEDES VER y analizar fotos, comprobantes y capturas de pantalla que envíe el cliente.
   - NUNCA digas que no puedes ver imágenes.
   - Cuando el cliente envíe una imagen, examínala con atención y responde con base en lo que ves (confirmando datos, leyendo comprobantes o solucionando el problema mostrado).
"""

HISTORY_LIMIT = 100
conversations: dict[str, list[dict]] = {}
processed_message_ids: set[str] = set()
notified_chats: set[str] = set()
out_of_hours_notified: dict[str, float] = {}  # chat_id -> timestamp del último mensaje fuera de horario enviado

# Control de intervención humana: chats donde el asesor humano tomó el control
human_handled_chats: dict[str, float] = {}  # chat_id -> timestamp
bot_sent_texts: set[str] = set()

# Tiempo de inactividad para olvidar la conversación (10 minutos = 600 segundos)
INACTIVITY_TIMEOUT = 10 * 60
last_activity_time: dict[str, float] = {}

# Tu número personal para recibir alertas (código país 57 + número)
ADMIN_PHONE = "573117944193@c.us"

def is_business_hours() -> bool:
    """Verifica si la hora actual está dentro del horario de atención (8:00 AM a 8:00 PM)"""
    return START_HOUR <= datetime.now().hour < END_HOUR

def get_out_of_hours_message() -> str:
    """Genera un mensaje cordial y natural cuando se escribe fuera de horario"""
    now = datetime.now()
    saludo_final = "¡Que tengas un excelente día!" if now.hour < START_HOUR else "¡Que pases una feliz noche!"
    return (
        "¡Hola! Te habla Sofía del equipo de atención de Fortex. 👋\n\n"
        "En este momento nos encontramos fuera de nuestro horario de atención (nuestro horario de servicio es de 8:00 a.m. a 8:00 p.m. 🕗).\n\n"
        "Por favor déjanos tu consulta o solicitud detallada por aquí; con mucho gusto te responderemos a primera hora tan pronto iniciemos servicio a las 8:00 a.m. "
        f"{saludo_final}"
    )

def notify_admin_new_client(client_chat_id: str, message_text: str):
    """Notifica al administrador cuando un nuevo cliente inicia conversación"""
    if client_chat_id == ADMIN_PHONE:
        return  # Si estás probando desde tu propio número, no te manda alerta a ti mismo

    clean_number = client_chat_id.replace("@c.us", "").replace("@s.whatsapp.net", "")
    alert = (
        f"🔔 *NUEVO CLIENTE EN FORTEX*\n\n"
        f"👤 *Cliente:* +{clean_number}\n"
        f"💬 *Mensaje:* \"{message_text}\"\n"
        f"🤖 _El bot ya está atendiendo la conversación._"
    )
    try:
        waha_send_text(ADMIN_PHONE, alert)
    except Exception as e:
        log.warning("No se pudo notificar al admin: %s", e)

# ===========================
# 2. LOGGING
# ===========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bot")

# ===========================
# 3. FUNCIONES WAHA
# ===========================
def waha_send_text(chat_id: str, text: str):
    """Enviar mensaje de texto por WAHA"""
    bot_sent_texts.add(text.strip())
    if len(bot_sent_texts) > 500:
        bot_sent_texts.clear()
        bot_sent_texts.add(text.strip())

    print(f"🛠 Enviando mensaje a WAHA con chat_id={chat_id}", flush=True)
    r = requests.post(
        f"{WAHA_URL}/api/sendText",
        headers={
            "X-Api-Key": WAHA_API_KEY,
            "Content-Type": "application/json"
        },
        json={"session": WAHA_SESSION, "chatId": chat_id, "text": text},
        timeout=30,
    )
    r.raise_for_status()
    return r.json() if r.text.strip() else {"status": "ok"}

def waha_typing(chat_id: str, on: bool):
    """Simula escritura en WAHA (desactivado para evitar bloqueos)"""
    pass

# ===========================
# 4. FUNCIONES OLLAMA
# ===========================
def get_image_base64(payload: dict) -> str | None:
    """Extrae o descarga la imagen en base64 enviada por el cliente"""
    media = payload.get("media") or {}
    
    # 1. Si viene con base64 directo
    if isinstance(media, dict) and media.get("data"):
        return media.get("data")
    
    # 2. Si viene con URL de archivo de WAHA
    url = media.get("url") if isinstance(media, dict) else payload.get("mediaUrl")
    if url:
        # Si la URL apunta a host.docker.internal, acceder vía localhost
        url = url.replace("host.docker.internal", "localhost")
        try:
            r = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=20)
            if r.status_code == 200:
                import base64
                return base64.b64encode(r.content).decode("utf-8")
        except Exception as e:
            log.warning("No se pudo descargar la imagen de WAHA: %s", e)
    return None

def ollama_chat(messages: list[dict], image_b64: str | None = None) -> str:
    """Generar respuesta con Groq Cloud (con respaldo en Ollama si falla)"""
    req_messages = []
    for msg in messages:
        req_messages.append({
            "role": msg.get("role", "user"),
            "content": str(msg.get("content", "")),
        })

    # Si el cliente adjuntó foto o comprobante, indicarlo en el contexto
    if image_b64 and req_messages:
        last_msg = req_messages[-1]
        orig_content = last_msg.get("content", "").strip()
        if not orig_content:
            last_msg["content"] = "[El cliente ha enviado una imagen / comprobante de pago]"
        else:
            last_msg["content"] = f"[El cliente adjuntó imagen / comprobante]: {orig_content}"

    # 1. Intentar con Groq Cloud (Respuesta en menos de 1 segundo)
    if GROQ_API_KEY:
        try:
            r = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": req_messages,
                    "temperature": 0.7,
                    "max_tokens": 350,
                },
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                log.warning("Groq respondió con status %s: %s", r.status_code, r.text)
        except Exception as e:
            log.warning("Error conectando con Groq Cloud: %s", e)

    # 2. Respaldo opcional en Ollama local
    try:
        model_to_use = OLLAMA_VISION_MODEL if image_b64 else OLLAMA_MODEL
        ollama_req = []
        for msg in messages:
            ollama_req.append(dict(msg))
        if image_b64 and ollama_req:
            ollama_req[-1]["images"] = [image_b64]

        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model_to_use,
                "messages": ollama_req,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 350,
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"].strip()
    except Exception as e:
        log.error("Fallo tanto Groq como Ollama: %s", e)
        return "Disculpa la demora, en este momento estoy verificando tu solicitud. En un momento te responderé detalladamente."

# ===========================
# 5. HISTORIAL
# ===========================
def get_history(chat_id: str) -> list[dict]:
    now = time.time()
    last_time = last_activity_time.get(chat_id, 0)

    # Si pasaron más de 10 minutos (600 segundos) de inactividad, se reinicia la memoria
    if last_time > 0 and (now - last_time > INACTIVITY_TIMEOUT):
        conversations[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        notified_chats.discard(chat_id)
        human_handled_chats.pop(chat_id, None)
        log.info("⏰ 10 minutos de inactividad cumplidos en %s. Memoria reiniciada para tratar como nuevo chat.", chat_id)

    last_activity_time[chat_id] = now

    if chat_id not in conversations:
        conversations[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return conversations[chat_id]

def trim_history(chat_id: str):
    h = conversations[chat_id]
    if len(h) > HISTORY_LIMIT + 1:
        conversations[chat_id] = [h[0]] + h[-HISTORY_LIMIT:]

# ===========================
# 6. SERVIDOR FLASK
# ===========================
app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "Webhook activo y funcionando correctamente", 200

    data = request.get_json(silent=True) or {}

    event = data.get("event", "")
    payload = data.get("payload", {})

    # Permitir eventos de mensajes
    if event not in ("message", "message.any"):
        return jsonify(status="ignored", reason="not-message-event"), 200

    from_me = payload.get("fromMe")
    body = (payload.get("body") or "").strip()
    chat_id = payload.get("from", "")

    # ============================================================
    # DETECCIÓN DE INTERVENCIÓN HUMANA (CUANDO EL ASESOR RESPONDE)
    # ============================================================
    if from_me:
        target_chat = payload.get("to") or payload.get("chatId") or chat_id

        # 1. Si el mensaje lo envió el bot mismo, lo ignoramos
        if body in bot_sent_texts:
            bot_sent_texts.discard(body)
            return jsonify(status="ignored", reason="bot-own-message"), 200

        # 2. Despedida natural del asesor humano (reactiva el bot de forma 100% invisible para el cliente)
        lower_body = body.lower()
        FAREWELL_PHRASES = [
            "hasta luego", "hasta pronto", "hasta mañana", "nos vemos",
            "que tengas un buen día", "que tenga un buen día", "que tengas buen día",
            "que tengas una buena tarde", "que tenga buena tarde",
            "feliz día", "feliz tarde", "feliz noche", "buena noche",
            "con mucho gusto", "con gusto", "un placer", "a la orden",
            "para servirte", "para servirle", "estamos a la orden", "estamos para servirte",
            "quedo atento", "quedamos atentos", "cualquier duda nos avisas", "cualquier duda me avisas",
            "que te vaya muy bien", "que le vaya muy bien", "gracias por comunicarte", "gracias por escribirnos"
        ]

        if any(phrase in lower_body for phrase in FAREWELL_PHRASES):
            if target_chat in human_handled_chats:
                del human_handled_chats[target_chat]
                log.info("👋 Despedida natural detectada en %s ('%s'). El bot se reactivó automáticamente en secreto.", target_chat, body)
            return jsonify(status="ignored", reason="human-farewell-bot-reactivated"), 200

        # 3. Si el asesor humano sigue conversando, silenciar al bot para este cliente
        if target_chat and target_chat != ADMIN_PHONE:
            human_handled_chats[target_chat] = time.time()
            log.info("👤 Intervención humana detectada en %s. El bot se silencia para este cliente.", target_chat)

        return jsonify(status="ignored", reason="human-message-registered"), 200

    # ============================================================
    # MENSAJE ENTRANTE DEL CLIENTE (from_me == False)
    # ============================================================
    # Ignorar message.any entrante para evitar duplicados con el evento 'message'
    if event == "message.any":
        return jsonify(status="ignored", reason="duplicate-any"), 200

    has_media = bool(payload.get("hasMedia"))

    if not body and not has_media:
        return jsonify(status="ignored", reason="empty"), 200

    if has_media and not body:
        body = "Hola, te acabo de enviar esta imagen / foto para que la revises."

    # 1. Si un humano tomó el control de este chat, el bot respeta y SE QUEDA EN SILENCIO
    if chat_id in human_handled_chats:
        last_interaction = human_handled_chats[chat_id]
        # Silencio durante 2 horas desde el último mensaje del humano
        if time.time() - last_interaction < 2 * 3600:
            log.info("🤐 Chat %s atendido por asesor humano. Bot en silencio respetando la intervención.", chat_id)
            return jsonify(status="ignored", reason="handled-by-human"), 200
        else:
            del human_handled_chats[chat_id]

    # 2. Control de duplicados por ID de mensaje
    raw_id = payload.get("id")
    msg_id = raw_id if isinstance(raw_id, str) else (raw_id.get("_serialized") or raw_id.get("id") if isinstance(raw_id, dict) else None)
    
    if msg_id:
        if msg_id in processed_message_ids:
            log.info("Mensaje duplicado ignorado: %s", msg_id)
            return jsonify(status="ignored", reason="already-processed"), 200
        processed_message_ids.add(msg_id)
        if len(processed_message_ids) > 2000:
            processed_message_ids.clear()

    clean_chat = chat_id.replace("@c.us", "").replace("@s.whatsapp.net", "")
    print(f"\n📩 [{clean_chat}] CLIENTE: {body}", flush=True)

    # 3. Descargar imagen si existe
    image_b64 = None
    if has_media:
        image_b64 = get_image_base64(payload)
        if image_b64:
            print(f"📸 [{clean_chat}] Imagen recibida. Sofía analizando foto...", flush=True)

    # 4. Notificar a tu WhatsApp personal si es un cliente nuevo empezando a hablar
    if chat_id not in notified_chats:
        notified_chats.add(chat_id)
        notify_admin_new_client(chat_id, body)

    # 5. Control de Horario de Atención (8:00 AM a 8:00 PM)
    if not is_business_hours():
        last_ooh = out_of_hours_notified.get(chat_id, 0)
        # Responder cada 30 minutos máximo por chat para no saturar
        if time.time() - last_ooh > 1800:
            out_of_hours_notified[chat_id] = time.time()
            out_msg = get_out_of_hours_message()
            waha_send_text(chat_id, out_msg)
            print(f"🌙 [{clean_chat}] FUERA DE HORARIO: Sofía informó el horario de atención (8:00 AM - 8:00 PM).", flush=True)
        else:
            log.info("🌙 Mensaje fuera de horario de %s recibido (sin re-enviar aviso por cooldown).", clean_chat)
        return jsonify(status="ok", reason="out-of-business-hours"), 200

    try:
        waha_typing(chat_id, on=True)

        history = get_history(chat_id)
        history.append({"role": "user", "content": body})

        reply = ollama_chat(history, image_b64=image_b64)

        history.append({"role": "assistant", "content": reply})
        trim_history(chat_id)

        waha_typing(chat_id, on=False)
        waha_send_text(chat_id, reply)

        print(f"🤖 [{clean_chat}] SOFÍA: {reply}\n", flush=True)

    except Exception as e:
        print(f"❌ ERROR: {e}", flush=True)

    return jsonify(status="ok"), 200

# ===========================
# 7. EJECUCIÓN
# ===========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False)