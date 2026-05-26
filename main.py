import os
import json
from fastapi import FastAPI, Request, Response
from supabase import create_client, Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import httpx

app = FastAPI()

# 1. Inicializar Supabase con variables de entorno de Render
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# 2. Inicializar Google Calendar de forma segura desde la variable de entorno
SCOPES = ['https://www.googleapis.com/auth/calendar']
google_creds_raw = os.getenv("GOOGLE_CREDS_JSON")

if not google_creds_raw:
    print("ERROR CRÍTICO: No se encontró la variable GOOGLE_CREDS_JSON en Render")
    creds = None
    calendar_service = None
else:
    creds_info = json.loads(google_creds_raw)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    calendar_service = build('calendar', 'v3', credentials=creds)

# 3. Configuraciones globales (Asegúrate de tenerlas en Environment de Render o pégalas aquí)
CALENDAR_ID = "TU_ID_DE_CALENDARIO_DE_GOOGLE" # Ej: tu_correo@gmail.com
PHONE_NUMBER_ID = "TU_PHONE_NUMBER_ID_DE_META"
META_TOKEN = os.getenv("META_TOKEN", "TU_TOKEN_DE_META_POR_SI_NO_USAS_ENV")

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
            print(f"Error enviando a Meta: {response.text}")

@app.get("/webhook")
async def verificar_token(request: Request):
    params = request.query_params
    # Reemplaza 'cusco_api_token_2026' con el token de verificación que pusiste en el panel de Meta
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == "cusco_api_token_2026":
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token inválido", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    print("--- RESTRICCIÓN: PAYLOAD ENTRANTE DESDE META ---")
    print(json.dumps(payload, indent=2))
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        if "messages" in value:
            msg = value["messages"][0]
            phone = msg["from"]
            text = msg["text"]["body"].strip()

            # Buscar o Crear Cliente en Supabase
            res = supabase.table("clientes").select("*").eq("telefono", phone).execute()
            if not res.data:
                res = supabase.table("clientes").insert({"telefono": phone, "estado_conversacion": "NUEVO"}).execute()
            
            cliente = res.data[0]
            estado = cliente["estado_conversacion"]

            # Máquina de Estados (Lógica del Flujo)
            if estado == "NUEVO":
                supabase.table("clientes").update({"nombre": text, "estado_conversacion": "ELIGIENDO_FECHA"}).eq("telefono", phone).execute()
                await enviar_wpp(phone, f"¡Gracias {text}! ¿Qué día te gustaría agendar? Escribe la fecha en formato: AAAA-MM-DD (Ejemplo: 2026-05-28)")
            
            elif estado == "ELIGIENDO_FECHA":
                fecha_solicitada = text
                
                # Insertar en Google Calendar de forma directa
                evento = {
                    'summary': f'Cita Dental: {cliente["nombre"]}',
                    'start': {'dateTime': f'{fecha_solicitada}T10:00:00', 'timeZone': 'America/Lima'},
                    'end': {'dateTime': f'{fecha_solicitada}T11:00:00', 'timeZone': 'America/Lima'},
                }
                
                ev_res = calendar_service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
                
                # Guardar Cita en Supabase y resetear estado de conversación
                supabase.table("citas").insert({
                    "cliente_id": cliente["id"], 
                    "fecha_hora": f"{fecha_solicitada} 10:00:00", 
                    "google_event_id": ev_res["id"]
                }).execute()
                
                supabase.table("clientes").update({"estado_conversacion": "AGENDADO"}).eq("telefono", phone).execute()
                
                await enviar_wpp(phone, f"¡Listo! Tu cita ha sido agendada para el {fecha_solicitada} a las 10:00 AM. ¡Te esperamos!")
            
            elif estado == "AGENDADO":
                await enviar_wpp(phone, "Ya tienes una cita agendada de forma activa.")
                
        return {"status": "ok"}
    except Exception as e:
        print(f"Error en ejecución del webhook: {e}")
        return Response(content=str(e), status_code=500)
