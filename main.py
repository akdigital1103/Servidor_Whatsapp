import os
import json
from fastapi import FastAPI, Request, Response
from supabase import create_client, Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import httpx

app = FastAPI()

# Inicializar Supabase
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Inicializar Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']
creds = Credentials.from_service_account_file('bot-dentista-497517-11035b4a7c4c.json', scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=creds)

CALENDAR_ID = "ID_DEL_CALENDARIO_DEL_DENTISTA"
URL_META_SEND = f"https://graph.facebook.com/v19.0/TU_PHONE_NUMBER_ID/messages"
PHONE_NUMBER_ID = "1145556385303391"
META_ACCESS_TOKEN = "EAAS7ZAH8FCoYBRlajUmsUsa8UiPXniF3Pekt2kp2a7fmwTyNQV54oGZBkDlWzbBgLPZB3I1u97CZBKVfIsDOZC3C4RuLZBRpdC1ND5cPkBQV8HZBjfwt37SvVb9rBTcyn1xuXO9vgeDien3kh5QPcVzIFAZCnXC33NDixcRD9tFic0VQMJrfZB41nt69wtzmiOyGVNZCMnP9Ho4XnkTz5neYkJOHqrMDrrTZAMHWQ0fbTQrhZA26nj1inYtfHJt5CSE524sPtTsQR6p7FyFhpI9EalHiQJIp"

# URL ofic
async def enviar_wpp(to: str, texto: str):
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": texto}}
    async with httpx.AsyncClient() as client:
        await client.post(URL_META_SEND, json=payload, headers=headers)

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        if "messages" in value:
            msg = value["messages"][0]
            phone = msg["from"]
            text = msg["text"]["body"].strip()

            # 1. Buscar o Crear Cliente en Supabase
            res = supabase.table("clientes").select("*").eq("telefono", phone).execute()
            if not res.data:
                res = supabase.table("clientes").insert({"telefono": phone, "estado_conversacion": "NUEVO"}).execute()
            
            cliente = res.data[0]
            estado = cliente["estado_conversacion"]

            # 2. Máquina de Estados (Lógica del Flujo)
            if estado == "NUEVO":
                supabase.table("clientes").update({"nombre": text, "estado_conversacion": "ELIGIENG_FECHA"}).eq("telefono", phone).execute()
                await enviar_wpp(phone, f"¡Gracias {text}! ¿Qué día te gustaría agendar? Escribe la fecha en formato: AAAA-MM-DD (Ejemplo: 2026-05-28)")
            
            elif estado == "ELIGIENG_FECHA":
                # Aquí asumimos que el usuario envía una fecha válida por simplicidad del MVP
                fecha_solicitada = text
                
                # Insertar en Google Calendar de forma directa
                evento = {
                    'summary': f'Cita Dental: {cliente["nombre"]}',
                    'start': {'dateTime': f'{fecha_solicitada}T10:00:00', 'timeZone': 'America/Lima'},
                    'end': {'dateTime': f'{fecha_solicitada}T11:00:00', 'timeZone': 'America/Lima'},
                }
                
                ev_res = calendar_service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
                
                # Guardar Cita en Supabase y resetear estado
                supabase.table("citas").insert({"cliente_id": cliente["id"], "fecha_hora": f"{fecha_solicitada} 10:00:00", "google_event_id": ev_res["id"]}).execute()
                supabase.table("clientes").update({"estado_conversacion": "AGENDADO"}).eq("telefono", phone).execute()
                
                await enviar_wpp(phone, f"¡Listo! Tu cita ha sido agendada para el {fecha_solicitada} a las 10:00 AM. ¡Te esperamos!")
            
            elif estado == "AGENDADO":
                await enviar_wpp(phone, "Ya tienes una cita agendada. Si deseas cancelarla, por favor escribe 'CANCELAR'.")
                
        return {"status": "ok"}
    except Exception as e:
        print(f"Error: {e}")
        return Response(content=str(e), status_code=500)
