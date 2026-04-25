from fastapi import Response
from twilio.twiml.messaging_response import MessagingResponse

async def manejar_navegacion(msg: str, num_telefono: str, estado_actual: str, sesiones: dict):
    response = MessagingResponse()
    
    # ==========================================
    # BOTÓN DE PÁNICO (0)
    # ==========================================
    if msg == "0" and estado_actual != "inicio":
        sesiones[num_telefono] = {"estado": "inicio"}
        # Dejamos el mensaje en "0" para que pase de largo todos los pasos y caiga en el saludo inicial
        return None, "0", "inicio"

    # ==========================================
    # BOTÓN VOLVER (b)
    # ==========================================
    if msg == "b":
        if estado_actual in ["viendo_horarios", "ingresando_datos_turnos"]:
            # Cambiamos el estado en el aire y lo dejamos seguir bajando
            sesiones[num_telefono]["estado"] = "eligiendo_semana"
            return None, "b", "eligiendo_semana"

        elif estado_actual == "eligiendo_dia":
            sesiones[num_telefono]["estado"] = "eligiendo_semana"
            res_text = "Ok, volvemos atrás.\n\n¿Para cuándo buscan turno?\n\n1️⃣ Esta semana\n2️⃣ La próxima semana\n3️⃣ En 15 días\n4️⃣ En 3 semanas\n\n👉 Respondé con un número del 1 al 4.\n↩️ *b* para cambiar cantidad de turnos\n↩️ *0* para menú principal"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8"), msg, sesiones[num_telefono]["estado"]

        elif estado_actual == "eligiendo_semana":
            sesiones[num_telefono]["estado"] = "eligiendo_cantidad_turnos"
            barbero_nom = sesiones[num_telefono].get("barbero_nombre", "Nacho")
            res_text = f"Ok, volvemos atrás.\n\n¿Cuántos turnos seguidos querés sacar?\n*(Aclaración: Si sacás más de un turno, serán consecutivos con {barbero_nom})*\n\n1️⃣ Un turno\n2️⃣ Dos turnos seguidos\n3️⃣ Tres turnos seguidos\n\n👉 Respondé con 1, 2 o 3.\n↩️ *b* para cambiar de barbero\n↩️ *0* para menú principal"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8"), msg, sesiones[num_telefono]["estado"]

        elif estado_actual == "eligiendo_cantidad_turnos":
            sesiones[num_telefono]["estado"] = "eligiendo_barbero"
            res_text = "Ok, volvemos atrás.\n\n¿Con quién te querés atender?\n\n1️⃣ Nacho\n2️⃣ Sebas\n\n👉 Respondé con 1 o 2.\n↩️ *0* para menú principal"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8"), msg, sesiones[num_telefono]["estado"]

    # Si no apretó ni "0" ni "b", devolvemos todo intacto para que siga la ruta normal
    return None, msg, estado_actual