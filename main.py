import os
import json
from fastapi import FastAPI, Request, Response
from supabase import create_client, Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import httpx

app = FastAPI()

# 1. Cargar variables desde el entorno de Render
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
META_TOKEN = os.getenv("META_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
CALENDAR_ID = os.getenv("CALENDAR_ID")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDS_JSON")

# Logs de control inicial (flush=True obliga a Render a mostrarlos ya)
print("=== VERIFICACIÓN DE VARIABLES EN RENDER ===", flush=True)
print(f"SUPABASE_URL: {'OK' if SUPABASE_URL else 'FALTA ❌'}", flush=True)
print(f"SUPABASE_KEY: {'OK' if SUPABASE_KEY else 'FALTA ❌'}", flush=True)
print(f"META_TOKEN: {'OK' if META_TOKEN else 'FALTA ❌'}", flush=True)
print(f"PHONE_NUMBER_ID: {'OK' if PHONE_NUMBER_ID else 'FALTA ❌'}", flush=True)
print(f"CALENDAR_ID: {'OK' if CALENDAR_ID else 'FALTA ❌'}", flush=True)
print(f"GOOGLE_CREDS_JSON: {'OK' if GOOGLE_CREDS_RAW else 'FALTA ❌'}", flush=True)

# Inicializar clientes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

SCOPES = ['https://www.googleapis.com/auth/calendar']
calendar_service = None
if GOOGLE_CREDS_RAW:
    try:
        creds_info = json.loads(GOOGLE_CREDS_RAW)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        calendar_service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"ERROR CONFIGURANDO GOOGLE CALENDAR: {e}", flush=True)

# Construir la URL dinámica de Meta
URL_META_SEND = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" if PHONE_NUMBER_ID else ""

async def enviar_wpp(to: str, texto: str):
    if not URL_META_SEND or not META_TOKEN:
        print("❌ ERROR: No se puede enviar el mensaje. Faltan credenciales de Meta en Render.", flush=True)
        return

    headers = {
        "Authorization": f"Bearer {META_TOKEN}", 
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp", 
        "to": to, 
        "type": "text", 
        "text": {"body": texto}
    }
    
    async with httpx.AsyncClient() as client:
        print(f"➡️ Intentando enviar mensaje a Meta para el número: {to}...", flush=True)
        response = await client.post(URL_META_SEND, json=payload, headers=headers)
        print(f"↩️ Respuesta de Meta API (Status Code: {response.status_code})", flush=True)
        if response.status_code != 200:
            print(f"🚨 DETALLE DEL ERROR DE META: {response.text}", flush=True)

@app.get("/webhook")
async def verificar_token(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == "cusco_api_token_2026":
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token inválido", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    print("--- PAYLOAD ENTRANTE DESDE META ---", flush=True)
    print(json.dumps(payload, indent=2), flush=True)
    
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        if "messages" in value:
            msg = value["messages"][0]
            phone = msg["from"]
            text = msg["text"]["body"].strip()

            print(f"📝 Procesando texto '{text}' del usuario {phone}", flush=True)

            if not supabase:
                print("❌ Base de datos no inicializada.", flush=True)
                return {"status": "error_db"}

            # Buscar o Crear Cliente en Supabase
            res = supabase.table("clientes").select("*").eq("telefono", phone).execute()
            if not res.data:
                print(f"👤 Cliente nuevo detectado. Insertando {phone} en Supabase...", flush=True)
                res = supabase.table("clientes").insert({"telefono": phone, "estado_conversacion": "NUEVO"}).execute()
            
            cliente = res.data[0]
            estado = cliente["estado_conversacion"]
            print(f"🔄 Estado actual del cliente en DB: {estado}", flush=True)

            # Máquina de Estados
            if estado == "NUEVO":
                supabase.table("clientes").update({"nombre": text, "estado_conversacion": "ELIGIENDO_FECHA"}).eq("telefono", phone).execute()
                await enviar_wpp(phone, f"¡Gracias por escribirnos! ¿Qué día te gustaría agendar? Escribe la fecha en formato: AAAA-MM-DD (Ejemplo: 2026-06-15)")
            
            elif estado == "ELIGIENDO_FECHA":
                if not calendar_service:
                    print("❌ Google Calendar no está disponible.", flush=True)
                    await enviar_wpp(phone, "Lo siento, el sistema de agenda está en mantenimiento.")
                    return {"status": "error_calendar"}
                
                fecha_solicitada = text
                print(f"📅 Intentando insertar cita en Google Calendar para el: {fecha_solicitada}", flush=True)
                
                evento = {
                    'summary': f'Cita Dental: {cliente["nombre"]}',
                    'start': {'dateTime': f'{fecha_solicitada}T10:00:00', 'timeZone': 'America/Lima'},
                    'end': {'dateTime': f'{fecha_solicitada}T11:00:00', 'timeZone': 'America/Lima'},
                }
                
                ev_res = calendar_service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
                print("✅ Evento creado con éxito en Google Calendar", flush=True)
                
                supabase.table("citas").insert({
                    "cliente_id": cliente["id"], 
                    "fecha_hora": f"{fecha_solicitada} 10:00:00", 
                    "google_event_id": ev_res["id"]
                }).execute()
                
                supabase.table("clientes").update({"estado_conversacion": "AGENDADO"}).eq("telefono", phone).execute()
                await enviar_wpp(phone, f"¡Listo! Tu cita ha sido agendada para el {fecha_solicitada} a las 10:00 AM. ¡Te esperamos!")
            
            elif estado == "AGENDADO":
                await enviar_wpp(phone, "Ya tienes una cita agendada de forma activa.")
            else:
                print(f"⚠️ ALERTA: Se detectó un estado no controlado: '{estado}'")
                await enviar_wpp(phone, "Hubo un desfase en el sistema. Escribe de nuevo para reiniciar.")
                
        return {"status": "ok"}
    except Exception as e:
        print(f"💥 ERROR EN EJECUCIÓN DEL WEBHOOK: {e}", flush=True)
        return Response(content=str(e), status_code=500)
