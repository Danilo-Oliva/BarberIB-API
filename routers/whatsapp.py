from fastapi import APIRouter, Form, Response
from services.graficos import tocar_timbre
from twilio.twiml.messaging_response import MessagingResponse
from handlers.navegacion import manejar_navegacion
from handlers.cancelaciones import manejar_cancelacion
from handlers.reservas import manejar_reservas
from handlers.confirmacion import manejar_confirmacion
import datetime
import pandas as pd

# 1. Importamos la base de datos y memoria desde 'core'
from core.config import (
    agenda_sheet,
    horarios_b1,
    horarios_b2,
    servicios_sheet,
    conf_sheet,
    catalogo_sheet,
    tz_arg,
    DIAS_SEMANA,
    DIAS_LABORABLES,
    sesiones,
)

# 2. Importamos las herramientas desde 'utils'
from utils.helpers import (
    quitar_tildes,
    obtener_horas_por_dia,
    extraer_hora,
    normalizar_telefono,
)

# 3. Creamos el Router
router = APIRouter()


@router.post("/whatsapp")
async def whatsapp(
    Body: str = Form(...), From: str = Form(...), ProfileName: str = Form(None)
):
    hoy_dt = datetime.datetime.now(tz_arg)

    msg = Body.lower().strip()
    msg_limpio = quitar_tildes(msg)
    partes = msg.split()
    response = MessagingResponse()

    # EXTRAEMOS Y NORMALIZAMOS EL NÚMERO
    num_original = From.replace("whatsapp:", "")
    num_telefono = normalizar_telefono(num_original)

    if "join" in msg:
        return Response(
            content=str(MessagingResponse()),
            media_type="application/xml; charset=utf-8",
        )

    if num_telefono not in sesiones:
        sesiones[num_telefono] = {"estado": "inicio"}
    estado_actual = sesiones[num_telefono]["estado"]

    print(f"DEBUG: Tel: {num_telefono} | Msg: {msg} | Estado: {estado_actual}")

    barbero_id = sesiones[num_telefono].get("barbero_id", "1")
    hoja_activa = horarios_b2 if barbero_id == "2" else horarios_b1
    datos_horarios = hoja_activa.get_all_values()

    datos_conf = conf_sheet.get_all_values()
    excepciones = {}
    for fila in datos_conf[1:]:
        if len(fila) >= 2 and fila[0].strip():
            fecha_exc = fila[0].strip()
            tipo_exc = fila[1].strip().lower()
            if tipo_exc in ["cerrado", "especial"]:
                excepciones[fecha_exc] = {
                    "tipo": tipo_exc,
                    "horas": fila[2].strip() if len(fila) > 2 else "",
                    "motivo": fila[3].strip() if len(fila) > 3 else "",
                }

    # ==========================================
    # ENRUTADOR 1: NAVEGACIÓN (0 y b)
    # ==========================================
    if msg in ["0", "b"]:
        nav_response, msg, estado_actual = await manejar_navegacion(
            msg, num_telefono, estado_actual, sesiones
        )
        if nav_response:
            return nav_response

    # ==========================================
    # ENRUTADOR 2: CANCELACIONES
    # ==========================================
    if estado_actual == "eligiendo_turno_cancelar" or (
        msg == "2" and estado_actual == "inicio"
    ):
        canc_response = await manejar_cancelacion(
            msg, num_telefono, estado_actual, sesiones
        )
        if canc_response:
            return canc_response

    # ==========================================
    # ENRUTADOR 3: RESERVAS (Pasos 1 al 6)
    # ==========================================
    res_respuesta = await manejar_reservas(
        msg,
        num_telefono,
        estado_actual,
        sesiones,
        datos_horarios,
        excepciones,
        barbero_id,
    )

    if isinstance(res_respuesta, tuple):
        _, msg, partes = res_respuesta
        estado_actual = sesiones[num_telefono]["estado"]
    elif res_respuesta:
        return res_respuesta

    # ==========================================
    # ENRUTADOR 4: CONFIRMACIÓN Y GUARDADO (Paso 7)
    # ==========================================
    conf_respuesta = await manejar_confirmacion(
        msg,
        num_telefono,
        estado_actual,
        sesiones,
        partes,
        ProfileName,
        datos_horarios,
        hoja_activa,
    )
    if conf_respuesta:
        return conf_respuesta

    # MENSAJE DE INICIO (Fallback)
    sesiones[num_telefono]["estado"] = "inicio"
    response.message(
        "¡Hola! 🤖 Bienvenido a IB Studio. \n Me llamo IBot y soy el esclavo de Nachito, por favor seguí mis instrucciones‼️. \n⚠️ Recordá que el turno tiene máximo 15 min de tolerancia.\n\n👉1️⃣ Para pedir turno \n👉2️⃣ Para cancelar turno \n\nCualquier duda que tengas y yo no te la pueda resolver, escribí un mensaje a este número👉+54 9 11 6046-7963"
    )
    return Response(content=str(response), media_type="application/xml; charset=utf-8")
