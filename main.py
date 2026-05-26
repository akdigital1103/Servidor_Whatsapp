from fastapi import FastAPI, Request, Response
import json

app = FastAPI()

# Este token lo inventas tú. Debe ser idéntico al que pongas en Meta.
TOKEN_VERIFICACION = "cusco_api_token_2026"

@app.get("/webhook")
async def verificar_token(request: Request):
    """ Meta usa esta ruta para verificar que tu servidor es real """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == TOKEN_VERIFICACION:
        print("¡Webhook verificado con éxito por Meta!")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Token inválido", status_code=403)

@app.post("/webhook")
async def recibir_datos(request: Request):
    """ Aquí llegan los mensajes de WhatsApp en tiempo real """
    try:
        body = await request.json()
        print("RESTRICCIÓN DE MENSAJE RECIBIDO:")
        print(json.dumps(body, indent=2))
        
        # Aquí procesarás la lógica del bot más adelante
        
        return {"status": "ok"}
    except Exception as e:
        return Response(content=str(e), status_code=500)
