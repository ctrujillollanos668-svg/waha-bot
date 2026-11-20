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
WAHA_URL = "http://127.0.0.1:3000"
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
   - Tú puedes ayudar a recuperar o cambiar contraseñas de forma automática.
   - Si el cliente pregunta si puede cambiar o recuperar contraseña, o si olvidó su clave, confírmale con calidez que sí, e indícale que te proporcione su correo o número registrado, o que elija si prefiere una contraseña aleatoria o personalizada.
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

# Estado y helpers para recuperación de contraseña por WhatsApp
password_reset_states: dict[str, dict] = {}

def is_password_reset_intent(text: str) -> bool:
    """Detecta si el mensaje expresa la intención de recuperar o cambiar contraseña"""
    t = text.lower()
    keywords = [
        "recuperar contraseña", "recuperar contrasena", "recuperar clave", "recuperar mi clave",
        "recuperar mi contraseña", "recuperar mi contrasena", "recuperar cuenta", "recuperar mi cuenta",
        "olvide mi contraseña", "olvidé mi contraseña", "olvide mi contrasena", "olvidé mi contrasena",
        "olvide la contraseña", "olvidé la contraseña", "olvide la contrasena", "olvidé la contrasena",
        "olvide mi clave", "olvidé mi clave", "olvide la clave", "olvidé la clave", "olvido mi clave",
        "cambiar mi contraseña", "cambiar contraseña", "cambiar mi contrasena", "cambiar contrasena",
        "cambiar mi clave", "cambiar clave",
        "restablecer contraseña", "restablecer contrasena", "restablecer clave", "restablecer mi contraseña",
        "no recuerdo mi contraseña", "no me acuerdo de mi contraseña", "no recuerdo mi contrasena",
        "perdi mi contraseña", "perdí mi contraseña", "perdi mi contrasena", "perdí mi contrasena",
        "perdi mi clave", "perdí mi clave"
    ]
    return any(k in t for k in keywords)

def is_business_hours() -> bool:
    """Verifica si la hora actual está dentro del horario de atención (8:00 AM a 8:00 PM) en hora de Colombia (UTC-5)"""
    from datetime import timezone, timedelta
    colombia_time = datetime.now(timezone(timedelta(hours=-5)))
    return START_HOUR <= colombia_time.hour < END_HOUR

def get_out_of_hours_message() -> str:
    """Genera un mensaje cordial y natural cuando se escribe fuera de horario"""
    from datetime import timezone, timedelta
    colombia_time = datetime.now(timezone(timedelta(hours=-5)))
    saludo_final = "¡Que tengas un excelente día!" if colombia_time.hour < START_HOUR else "¡Que pases una feliz noche!"
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

@app.route("/")
def home():
    """Panel de control visual para ver el estado y escanear el código QR"""
    session_status = "DESCONOCIDO"
    try:
        r = requests.get(
            f"{WAHA_URL}/api/sessions/{WAHA_SESSION}",
            headers={"X-Api-Key": WAHA_API_KEY},
            timeout=5
        )
        if r.status_code == 200:
            session_status = r.json().get("status", "DESCONOCIDO")
    except Exception:
        session_status = "INICIANDO"

    status_color = "#10b981" if session_status == "WORKING" else "#f59e0b"
    status_text = "CONECTADO Y ACTIVO 24/7" if session_status == "WORKING" else f"ESTADO: {session_status} (ESCANEA EL QR)"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot WhatsApp Fortex - 24/7 en la Nube</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-white min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl text-center">
        <div class="w-16 h-16 bg-emerald-500/20 rounded-2xl flex items-center justify-center mx-auto mb-4 text-3xl">
            🤖
        </div>
        <h1 class="text-2xl font-black tracking-tight text-white mb-1">Bot WhatsApp Fortex</h1>
        <p class="text-xs text-slate-400 mb-6">Servidor en la Nube con Inteligencia Artificial (Groq)</p>

        <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold mb-6" style="background: {status_color}22; color: {status_color}; border: 1px solid {status_color}55;">
            <span class="w-2 h-2 rounded-full animate-ping" style="background: {status_color};"></span>
            {status_text}
        </div>

        <div class="bg-slate-950 border border-slate-800 rounded-2xl p-4 mb-6 flex flex-col items-center">
            <p class="text-xs text-slate-400 mb-3 font-medium">Escanea este código con WhatsApp en tu celular:</p>
            <div class="relative w-64 h-64 bg-white rounded-xl p-2 flex items-center justify-center shadow-inner">
                <img id="qr-image" src="/qr?t={int(time.time())}" alt="Código QR WhatsApp" class="w-full h-full object-contain" onerror="this.onerror=null; this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'200\\' height=\\'200\\' viewBox=\\'0 0 200 200\\'><text x=\\'50%\\' y=\\'50%\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\' font-size=\\'12\\' fill=\\'%23666\\'>Generando QR... recarga</text></svg>';">
            </div>
            <p class="text-[11px] text-slate-500 mt-3">WhatsApp ➔ Dispositivos vinculados ➔ Vincular dispositivo</p>
        </div>

        <div class="flex flex-col gap-2">
            <div class="flex gap-2">
                <button onclick="location.reload()" class="flex-1 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold py-2.5 px-4 rounded-xl text-xs transition cursor-pointer">
                    🔄 Recargar Página
                </button>
                <a href="/start-session" class="flex-1 bg-amber-600 hover:bg-amber-700 text-white font-semibold py-2.5 px-4 rounded-xl text-xs transition">
                    ⚡ Reiniciar Sesión
                </a>
            </div>
            <a href="/reset-session" class="bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700 font-semibold py-2 px-4 rounded-xl text-xs transition">
                🗑️ Limpiar y Forzar Nuevo QR (Desvincular)
            </a>
        </div>
        
        <p class="text-[10px] text-slate-600 mt-6">Render Cloud + WAHA + Groq AI 120B • Activo 24/7</p>
    </div>

    <script>
        const status = "{session_status}";
        if (status !== "WORKING") {{
            setTimeout(() => {{
                location.reload();
            }}, 10000);
        }}
    </script>
</body>
</html>"""
    return html

@app.route("/qr")
def get_qr():
    """Proxy directo para obtener la imagen del código QR de WAHA"""
    from flask import Response
    import urllib.parse

    # 1. Intentar con ?format=image
    try:
        r = requests.get(
            f"{WAHA_URL}/api/{WAHA_SESSION}/auth/qr?format=image",
            headers={"X-Api-Key": WAHA_API_KEY, "Accept": "image/png"},
            timeout=8
        )
        if r.status_code == 200 and r.content and len(r.content) > 100 and not r.content.startswith(b"{"):
            return Response(r.content, mimetype="image/png")
    except Exception as e:
        log.warning("Fallo /auth/qr?format=image: %s", e)

    # 2. Si WAHA devuelve JSON con 'raw', renderizar el código QR directamente
    try:
        r = requests.get(
            f"{WAHA_URL}/api/{WAHA_SESSION}/auth/qr",
            headers={"X-Api-Key": WAHA_API_KEY},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            raw_qr = data.get("raw")
            if raw_qr:
                qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(raw_qr)}"
                qr_resp = requests.get(qr_api, timeout=6)
                if qr_resp.status_code == 200 and qr_resp.content:
                    return Response(qr_resp.content, mimetype="image/png")
    except Exception as e:
        log.warning("Fallo generación de raw QR: %s", e)

    # 3. Intentar screenshot
    try:
        r = requests.get(
            f"{WAHA_URL}/api/screenshot?session={WAHA_SESSION}",
            headers={"X-Api-Key": WAHA_API_KEY},
            timeout=8
        )
        if r.status_code == 200 and r.content and len(r.content) > 100:
            return Response(r.content, mimetype="image/png")
    except Exception as e:
        log.warning("Fallo /screenshot: %s", e)

    return "Generando QR en segundo plano... Por favor refresca en 5 segundos.", 503

@app.route("/debug")
def debug():
    import subprocess
    import socket
    info = {"waha_url": WAHA_URL, "session": WAHA_SESSION}

    try:
        if os.path.exists("/tmp/waha.log"):
            with open("/tmp/waha.log", "r", encoding="utf-8", errors="ignore") as f:
                info["waha_log"] = f.read()[-3000:]
        else:
            info["waha_log"] = "Archivo /tmp/waha.log no encontrado"
    except Exception as e:
        info["waha_log_err"] = str(e)

    open_ports = []
    for p in [3000, 3001, 5005, 10000]:
        for host in ["127.0.0.1", "::1"]:
            try:
                family = socket.AF_INET6 if ":" in host else socket.AF_INET
                s = socket.socket(family, socket.SOCK_STREAM)
                s.settimeout(0.3)
                if s.connect_ex((host, p)) == 0:
                    open_ports.append(f"{host}:{p}")
                s.close()
            except Exception:
                pass
    info["open_ports"] = open_ports

    try:
        r = requests.get(f"{WAHA_URL}/api/sessions", headers={"X-Api-Key": WAHA_API_KEY}, timeout=2)
        info["sessions"] = r.json()
    except Exception as e:
        info["sessions_err"] = str(e)

    return jsonify(info)

@app.route("/restart-session")
@app.route("/start-session")
def start_session():
    """Endpoint para forzar reinicio/inicio limpio de sesión en WAHA"""
    try:
        requests.post(
            f"{WAHA_URL}/api/sessions/stop",
            headers={"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"},
            json={"name": WAHA_SESSION},
            timeout=8
        )
    except Exception:
        pass

    try:
        requests.post(
            f"{WAHA_URL}/api/sessions/{WAHA_SESSION}/stop",
            headers={"X-Api-Key": WAHA_API_KEY},
            timeout=8
        )
    except Exception:
        pass

    time.sleep(1.5)

    try:
        requests.post(
            f"{WAHA_URL}/api/sessions/start",
            headers={"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"},
            json={"name": WAHA_SESSION},
            timeout=12
        )
    except Exception as e:
        log.warning("Error iniciando sesión WAHA: %s", e)

    from flask import redirect
    return redirect("/")

@app.route("/reset-session")
def reset_session():
    """Endpoint para desvincular y forzar generación de nuevo QR"""
    try:
        requests.post(
            f"{WAHA_URL}/api/sessions/logout",
            headers={"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"},
            json={"name": WAHA_SESSION},
            timeout=8
        )
    except Exception:
        pass

    try:
        requests.delete(
            f"{WAHA_URL}/api/sessions/{WAHA_SESSION}",
            headers={"X-Api-Key": WAHA_API_KEY},
            timeout=8
        )
    except Exception:
        pass

    time.sleep(2)

    try:
        requests.post(
            f"{WAHA_URL}/api/sessions/start",
            headers={"X-Api-Key": WAHA_API_KEY, "Content-Type": "application/json"},
            json={"name": WAHA_SESSION},
            timeout=12
        )
    except Exception as e:
        log.warning("Error reiniciando sesión limpia WAHA: %s", e)

    from flask import redirect
    return redirect("/")

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.route("/api/sendText", methods=["POST"])
def api_send_text():
    """Proxy endpoint para enviar mensajes de WhatsApp desde Fortex"""
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chatId") or data.get("chat_id")
    text = data.get("text") or ""

    if not chat_id and data.get("phone"):
        raw_phone = str(data["phone"])
        clean_phone = "".join(filter(str.isdigit, raw_phone))
        if not clean_phone.startswith("57") and len(clean_phone) == 10:
            clean_phone = "57" + clean_phone
        chat_id = f"{clean_phone}@c.us"

    if not chat_id or not text:
        return jsonify(error="chatId/phone and text required"), 400

    try:
        res = waha_send_text(chat_id, text)
        return jsonify(res), 200
    except Exception as e:
        log.error("Error despachando mensaje WAHA: %s", e)
        return jsonify(error=str(e)), 500

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

    # 3. Descargar imagen si existe y procesar comprobante de pago automático
    image_b64 = None
    if has_media:
        image_b64 = get_image_base64(payload)
        if image_b64:
            print(f"📸 [{clean_chat}] Imagen recibida. Registrando comprobante en Fortex...", flush=True)
            try:
                rep_res = requests.post(
                    "https://fortex.wasmer.app/api/bot/report-deposit",
                    json={
                        "client_phone": clean_chat,
                        "image_b64": image_b64,
                    },
                    timeout=20,
                )
                if rep_res.status_code == 200:
                    rep_data = rep_res.json()
                    if rep_data.get("success"):
                        user_name = rep_data.get("user_name", "")
                        greeting = f" ¡Hola {user_name}!" if user_name else ""
                        reply = (
                            f"¡Comprobante de pago recibido con éxito!{greeting} 📸✅\n\n"
                            "Ya fue enviado directamente a nuestro equipo administrativo para su verificación en el banco. "
                            "En breves minutos te confirmaremos por este medio cuando tu saldo y tus giros de ruleta queden acreditados en tu cuenta de Fortex. ¡Muchas gracias por tu recarga! 😊"
                        )
                        waha_send_text(chat_id, reply)
                        print(f"🤖 [{clean_chat}] SOFÍA (Comprobante registrado en Telegram): {reply}\n", flush=True)
                        return jsonify(status="ok", reason="deposit-reported"), 200
                    elif rep_data.get("user_found") is False:
                        reply = (
                            "¡He recibido tu comprobante de pago! 📸\n\n"
                            "Sin embargo, tu número de WhatsApp no coincide con ninguna cuenta registrada en Fortex. "
                            "¿Me indicas por favor con qué correo electrónico te registraste en https://fortex.wasmer.app para poder acreditar tu saldo correctamente? 😊"
                        )
                        waha_send_text(chat_id, reply)
                        print(f"🤖 [{clean_chat}] SOFÍA (Usuario no encontrado): {reply}\n", flush=True)
                        return jsonify(status="ok", reason="user-not-found"), 200
            except Exception as e:
                log.warning("Error reportando comprobante a Fortex: %s", e)

    # Si el cliente responde con un correo para vincular un comprobante
    if "@" in body and "." in body and len(body.split()) == 1:
        extracted_email = body.strip().lower()
        try:
            rep_res = requests.post(
                "https://fortex.wasmer.app/api/bot/report-deposit",
                json={
                    "client_phone": clean_chat,
                    "email": extracted_email,
                },
                timeout=15,
            )
            if rep_res.status_code == 200 and rep_res.json().get("success"):
                user_name = rep_res.json().get("user_name", "")
                reply = (
                    f"¡Excelente, cuenta localizada a nombre de *{user_name}*! ✅\n\n"
                    "Tu solicitud ya quedó vinculada en nuestro sistema. En breves minutos te confirmaremos por aquí cuando tu saldo quede acreditado."
                )
                waha_send_text(chat_id, reply)
                return jsonify(status="ok", reason="email-linked"), 200
        except Exception as e:
            log.warning("Error vinculando correo: %s", e)

    # ============================================================
    # 4. FLUJO DE RECUPERACIÓN / CAMBIO DE CONTRASEÑA
    # ============================================================
    # Verificar si el cliente tiene un flujo de recuperación activo
    if chat_id in password_reset_states:
        state = password_reset_states[chat_id]
        # Expiración a los 15 minutos (900 seg)
        if time.time() - state.get("timestamp", 0) > 900:
            del password_reset_states[chat_id]
        else:
            lower_body = body.strip().lower()

            # Opción de cancelar en cualquier momento
            if lower_body in ("cancelar", "cancel", "salir", "no quiero", "ya no"):
                del password_reset_states[chat_id]
                waha_send_text(chat_id, "Listo, la solicitud de recuperación de contraseña ha sido cancelada. ¿Hay algo más en lo que te pueda colaborar? 😊")
                return jsonify(status="ok", reason="password-reset-cancelled"), 200

            step = state.get("step")

            # Paso 1: Esperando elección (1: Aleatoria o 2: Personalizada)
            if step == "AWAITING_CHOICE":
                body_clean = lower_body.strip()
                words = body_clean.split()

                # Solo reconocer opción si es exactamente 1 o palabras clave claras (no si el texto es un número de teléfono o frase larga)
                is_opt_random = body_clean in ("1", "1.", "uno", "aleatoria", "aleatorio", "random", "la 1", "opcion 1", "opción 1") or (
                    len(words) <= 3 and any(w in ("1", "aleatoria", "aleatorio", "random", "uno") for w in words)
                )
                is_opt_custom = body_clean in ("2", "2.", "dos", "personalizada", "personalizado", "propia", "la 2", "opcion 2", "opción 2") or (
                    len(words) <= 3 and any(w in ("2", "personalizada", "personalizado", "propia", "dos") for w in words)
                )

                if is_opt_random and not is_opt_custom:
                    import random
                    rand_code = random.randint(100000, 999999)
                    new_pass = f"Fortex{rand_code}*"
                    try:
                        rep = requests.post(
                            "https://fortex.wasmer.app/api/bot/reset-password",
                            json={"identifier": state["identifier"], "new_password": new_pass},
                            timeout=15
                        )
                        if rep.status_code == 200 and rep.json().get("success"):
                            u_name = state.get("user_name", "Cliente")
                            success_msg = (
                                f"🎉 *¡Contraseña generada y actualizada con éxito!*\n\n"
                                f"👤 *Usuario:* {u_name}\n"
                                f"🔑 *Nueva Contraseña:* `{new_pass}`\n\n"
                                f"🌐 Ya puedes iniciar sesión con tu nueva clave en:\n"
                                f"https://fortex.wasmer.app/login\n\n"
                                f"_(Te recomendamos guardarla en un lugar seguro. ¡Bienvenido de nuevo a Fortex!)_ 😊"
                            )
                            waha_send_text(chat_id, success_msg)
                            del password_reset_states[chat_id]
                            return jsonify(status="ok", reason="random-password-set"), 200
                        else:
                            waha_send_text(chat_id, "Hubo un error al guardar la contraseña en la plataforma. Por favor intenta nuevamente.")
                            del password_reset_states[chat_id]
                            return jsonify(status="error"), 200
                    except Exception as e:
                        log.warning("Error guardando contraseña aleatoria: %s", e)
                        waha_send_text(chat_id, "Ocurrió un inconveniente de conexión. Por favor intenta de nuevo en unos minutos.")
                        del password_reset_states[chat_id]
                        return jsonify(status="error"), 200

                elif is_opt_custom:
                    state["step"] = "AWAITING_NEW_PASSWORD"
                    state["timestamp"] = time.time()
                    ask_pass_msg = (
                        "¡Perfecto! ✍️ Por favor escribe a continuación la *nueva contraseña* que deseas asignar a tu cuenta.\n\n"
                        "*(Recuerda que debe tener mínimo 6 caracteres)*"
                    )
                    waha_send_text(chat_id, ask_pass_msg)
                    return jsonify(status="ok", reason="awaiting-custom-password"), 200

                else:
                    invalid_msg = (
                        "Por favor indícame con el número *1* si deseas que el sistema te asigne una contraseña *Aleatoria*, o el número *2* si deseas colocar tu propia contraseña *Personalizada* (o escribe *cancelar*). 😊"
                    )
                    waha_send_text(chat_id, invalid_msg)
                    return jsonify(status="ok", reason="invalid-choice"), 200

            # Paso 2: Esperando la contraseña personalizada
            elif step == "AWAITING_NEW_PASSWORD":
                custom_pass = body.strip()
                if len(custom_pass) < 6:
                    waha_send_text(chat_id, "⚠️ Por seguridad, la contraseña debe tener como mínimo 6 caracteres. Por favor escribe una contraseña válida de 6 caracteres o más (o escribe *cancelar*):")
                    return jsonify(status="ok", reason="password-too-short"), 200

                try:
                    rep = requests.post(
                        "https://fortex.wasmer.app/api/bot/reset-password",
                        json={"identifier": state["identifier"], "new_password": custom_pass},
                        timeout=15
                    )
                    if rep.status_code == 200 and rep.json().get("success"):
                        u_name = state.get("user_name", "Cliente")
                        custom_success_msg = (
                            f"🎉 *¡Tu contraseña personalizada ha sido guardada exitosamente!*\n\n"
                            f"👤 *Usuario:* {u_name}\n"
                            f"🔑 *Nueva Contraseña:* `{custom_pass}`\n\n"
                            f"🌐 Ya puedes iniciar sesión con tu correo y nueva clave en:\n"
                            f"https://fortex.wasmer.app/login\n\n"
                            f"¿Te puedo colaborar con algo más el día de hoy? 😊"
                        )
                        waha_send_text(chat_id, custom_success_msg)
                        del password_reset_states[chat_id]
                        return jsonify(status="ok", reason="custom-password-set"), 200
                    else:
                        waha_send_text(chat_id, "Ocurrió un error al actualizar la contraseña en el sistema. Por favor intenta de nuevo en unos minutos.")
                        del password_reset_states[chat_id]
                        return jsonify(status="error"), 200
                except Exception as e:
                    log.warning("Error guardando clave personalizada: %s", e)
                    waha_send_text(chat_id, "Ocurrió un inconveniente de conexión. Por favor intenta de nuevo.")
                    del password_reset_states[chat_id]
                    return jsonify(status="error"), 200

    # Si el cliente solicita recuperar contraseña y no tenía flujo activo
    if is_password_reset_intent(body):
        print(f"🔐 [{clean_chat}] Solicitud de recuperación de contraseña iniciada", flush=True)
        try:
            rep = requests.post(
                "https://fortex.wasmer.app/api/bot/reset-password",
                json={"identifier": clean_chat},
                timeout=15
            )
            if rep.status_code == 200 and rep.json().get("user_found"):
                user_info = rep.json()
                password_reset_states[chat_id] = {
                    "step": "AWAITING_CHOICE",
                    "identifier": clean_chat,
                    "user_name": user_info.get("user_name", "Cliente"),
                    "timestamp": time.time()
                }
                msg = (
                    f"¡Hola {user_info.get('user_name', 'Cliente')}! Con gusto te ayudo a restablecer tu acceso a Fortex. 🔐\n\n"
                    "¿Cómo deseas definir tu nueva contraseña?\n\n"
                    "1️⃣ *Aleatoria:* El sistema genera una contraseña segura automáticamente.\n"
                    "2️⃣ *Personalizada:* Tú mismo escribes la contraseña que deseas colocar (mínimo 6 caracteres).\n\n"
                    "Por favor responde con el número *1* para Aleatoria o el número *2* para Personalizada. 😊"
                )
                waha_send_text(chat_id, msg)
                return jsonify(status="ok", reason="password-reset-started-known-user"), 200
        except Exception as e:
            log.warning("Error verificando usuario para reset: %s", e)

        # Si el número de WhatsApp NO coincide con ninguna cuenta registrada:
        security_msg = (
            f"🔒 *Seguridad Fortex:* Por protección de tu cuenta y fondos, el restablecimiento automático de contraseña únicamente está habilitado escribiendo desde el número de WhatsApp registrado en la plataforma.\n\n"
            f"Tu número actual (+{clean_chat}) no coincide con ninguna cuenta activa. Si perdiste o cambiaste tu línea, por favor comunícate directamente con soporte para que un asesor verifique tu identidad personalmente. 😊"
        )
        waha_send_text(chat_id, security_msg)

        # Alertar al administrador por Telegram del intento no autorizado
        try:
            requests.post(
                "https://fortex.wasmer.app/api/bot/report-suspicious-reset",
                json={"phone": clean_chat, "message": body},
                timeout=10
            )
        except Exception:
            pass

        return jsonify(status="ok", reason="password-reset-blocked-unregistered-phone"), 200

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