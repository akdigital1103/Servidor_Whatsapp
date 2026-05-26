import os
import json
from fastapi import FastAPI, Request, Response
from supabase import create_client, Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import httpx
from datetime import datetime

app = FastAPI()

# 1. Inicializar Supabase con variables de entorno de Render
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. Inicializar Google Calendar limpiando los saltos de línea de la firma RSA
SCOPES = ['https://www.googleapis.com/auth/calendar']
google_creds_raw = os.getenv("GOOGLE_CREDS_JSON")

if not google_creds_raw:
    print("🚨 ERROR CRÍTICO: No se encontró la variable GOOGLE_CREDS_JSON en Render")
    calendar_service = None
else:
    creds_info = json.loads(google_creds_raw)
    # FIX CRÍTICO: Corrige el formateo de Render para cadenas de claves RSA privadas
    if "private_key" in creds_info:
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    calendar_service = build('calendar', 'v3', credentials=creds)

# 3. Configuraciones globales jaladas desde las variables de Render
CALENDAR_ID = os.getenv("CALENDAR_ID")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
META_TOKEN = os.getenv("META_TOKEN")

URL_META_SEND = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

async def enviar_wpp(to: str, texto: str):
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
        response = await client.post(URL_META_SEND, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"🚨 Error enviando a Meta: {response.text}")

@app.get("/webhook")
async def verificar_token(request: Request):
    params = request.query_params
    # Recuerda poner 'cusco_api_token_2026' en el campo "Token de verificación" en Meta Developers
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == "cusco_api_token_2026":
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token inválido", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    print("--- PAYLOAD ENTRANTE DESDE META ---")
    print(json.dumps(payload, indent=2))
    
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        if "messages" in value:
            msg = value["messages"][0]
            phone = msg["from"]
            text = msg["text"]["body"].strip()

            print(f"📝 Procesando texto '{text}' del usuario {phone}")

            # Buscar o Crear Cliente en Supabase
            res = supabase.table("clientes").select("*").eq("telefono", phone).execute()
            if not res.data:
                res = supabase.table("clientes").insert({"telefono": phone, "estado_conversacion": "NUEVO"}).execute()
            
            cliente = res.data[0]
            estado = cliente["estado_conversacion"]
            print(f"🔄 Estado actual del cliente en DB: {estado}")

            # MÁQUINA DE ESTADOS (Lógica del Flujo)
            if estado == "NUEVO":
                supabase.table("clientes").update({"nombre": text, "estado_conversacion": "ELIGIENDO_FECHA"}).eq("telefono", phone).execute()
                await enviar_wpp(phone, f"¡Gracias {text}! ¿Qué día te gustaría agendar? Escribe la fecha en formato: AAAA-MM-DD (Ejemplo: 2026-06-15)")
            
            elif estado == "ELIGIENDO_FECHA":
                # BLINDAJE LOGÍSTICO: Validamos si el texto realmente cumple el formato de fecha
                try:
                    # Intenta parsear el texto. Si no es fecha (ej: escribieron "Hola"), saltará al ValueError
                    datetime.strptime(text, "%Y-%m-%d")
                    fecha_solicitada = text
                    
                    print(f"📅 Intentando insertar cita en Google Calendar para el: {fecha_solicitada}")
                    
                    # Insertar el evento en Google Calendar
                    evento = {
                        'summary': f'Cita Dental: {cliente["nombre"]}',
                        'start': {'dateTime': f'{fecha_solicitada}T10:00:00', 'timeZone': 'America/Lima'},
                        'end': {'dateTime': f'{fecha_solicitada}T11:00:00', 'timeZone': 'America/Lima'},
                    }
                    
                    ev_res = calendar_service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
                    
                    # Guardar registro de la Cita en Supabase
                    supabase.table("citas").insert({
                        "cliente_id": cliente["id"], 
                        "fecha_hora": f"{fecha_solicitada} 10:00:00", 
                        "google_event_id": ev_res["id"]
                    }).execute()
                    
                    # Actualizar estado para cerrar el ciclo
                    supabase.table("clientes").update({"estado_conversacion": "AGENDADO"}).eq("telefono", phone).execute()
                    await enviar_wpp(phone, f"¡Listo! Tu cita ha sido agendada para el {fecha_solicitada} a las 10:00 AM. ¡Te esperamos!")
                
                except ValueError:
                    # Manejo defensivo si el usuario envía texto basura en lugar de una fecha válida
                    print(f"⚠️ Formato de fecha rechazado: '{text}'")
                    await enviar_wpp(phone, "Por favor, introduce una fecha válida usando el formato AAAA-MM-DD.\n\nEjemplo: 2026-06-15")
            
            elif estado == "AGENDADO":
                if text.lower() == "reiniciar":
                    supabase.table("clientes").update({"estado_conversacion": "NUEVO"}).eq("telefono", phone).execute()
                    await enviar_wpp(phone, "Historial reseteado. Escribe 'Hola' para agendar una nueva cita.")
                else:
                    await enviar_wpp(phone, "Ya cuentas con una cita programada activa de forma exitosa.\n\nEscribe 'reiniciar' si deseas volver a empezar.")
            
            else:
                print(f"⚠️ Alerta: Estado huérfano detectado: '{estado}'")
                await enviar_wpp(phone, "Hubo un desfase en el sistema. Escribe de nuevo para reiniciar.")
                
        return {"status": "ok"}
    except Exception as e:
        print(f"💥 ERROR EN EJECUCIÓN DEL WEBHOOK: {e}")
        return Response(content=str(e), status_code=500)
