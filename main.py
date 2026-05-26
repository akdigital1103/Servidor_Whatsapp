from fastapi import FastAPI, Request, Response
import httpx
import json

app = FastAPI()

# CONFIGURACIÓN (Remplaza con tus datos de Meta)
TOKEN_VERIFICACION = "cusco_api_token_2026"
PHONE_NUMBER_ID = "1145556385303391"
META_ACCESS_TOKEN = "EAAS7ZAH8FCoYBRlajUmsUsa8UiPXniF3Pekt2kp2a7fmwTyNQV54oGZBkDlWzbBgLPZB3I1u97CZBKVfIsDOZC3C4RuLZBRpdC1ND5cPkBQV8HZBjfwt37SvVb9rBTcyn1xuXO9vgeDien3kh5QPcVzIFAZCnXC33NDixcRD9tFic0VQMJrfZB41nt69wtzmiOyGVNZCMnP9Ho4XnkTz5neYkJOHqrMDrrTZAMHWQ0fbTQrhZA26nj1inYtfHJt5CSE524sPtTsQR6p7FyFhpI9EalHiQJIp"

# URL oficial de la API de Meta para enviar mensajes
URL_META_SEND = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

async def enviar_mensaje_texto(telefono_destino: str, texto: str):
    """ Función auxiliar para enviar un texto plano por WhatsApp """
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono_destino,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": texto
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(URL_META_SEND, json=payload, headers=headers)
        if response.status_code == 200:
            print(f"Mensaje enviado con éxito a {telefono_destino}")
        else:
            print(f"Error al enviar a Meta: {response.status_code} - {response.text}")

@app.get("/webhook")
async def verificar_token(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == TOKEN_VERIFICACION:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token inválido", status_code=403)

@app.post("/webhook")
async def recibir_datos(request: Request):
    try:
        body = await request.json()
        
        # 1. Extraer de forma segura el mensaje y el teléfono del cliente
        value = body["entry"][0]["changes"][0]["value"]
        
        if "messages" in value:
            mensaje = value["messages"][0]
            telefono_cliente = mensaje["from"] # Ej: "51999888777"
            
            # Validamos qué tipo de mensaje llegó
            if mensaje["type"] == "text":
                texto_recibido = mensaje["text"]["body"].strip().lower()
                print(f"El cliente {telefono_cliente} escribió: {texto_recibido}")
                
                # 2. LÓGICA DE RESPUESTA INICIAL (El Eco Automatizado)
                if texto_recibido in ["hola", "buenas", "inicio"]:
                    respuesta = "¡Hola! Bienvenido al asistente virtual del consultorio. ¿En qué te puedo ayudar hoy?\n\nEscribe '1' para ver los horarios disponibles."
                elif texto_recibido == "1":
                    respuesta = "Perfecto. Los horarios disponibles para mañana son:\n- 09:00 AM\n- 11:30 AM\n- 04:00 PM\n\n(Pronto podrás seleccionarlos con botones interactivos)"
                else:
                    respuesta = "Lo siento, todavía estoy aprendiendo. Escribe 'Hola' para reiniciar el menú."
                
                # 3. Enviar la respuesta de vuelta por la tubería de Meta
                await enviar_mensaje_texto(telefono_cliente, respuesta)
                
        return {"status": "ok"}
    except Exception as e:
        print(f"Error procesando el webhook: {str(e)}")
        return Response(content=str(e), status_code=500)
