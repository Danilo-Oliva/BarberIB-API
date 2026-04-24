import datetime
from fastapi import Response
from twilio.twiml.messaging_response import MessagingResponse

from core.config import agenda_sheet, horarios_b1, horarios_b2, tz_arg
from utils.helpers import normalizar_telefono

async def manejar_cancelacion(msg: str, num_telefono: str, estado_actual: str, sesiones: dict):
    response = MessagingResponse()
    hoy_dt = datetime.datetime.now(tz_arg)

    # ==========================================
    # INICIO DE CANCELACIÓN (Apretó el "2" en el menú principal)
    # ==========================================
    if msg == "2" and estado_actual == "inicio":
        datos_a = agenda_sheet.get_all_values()
        turnos_encontrados = []
        for i, f in enumerate(datos_a):
            if len(f) >= 4:
                tel_excel = normalizar_telefono(f[3])
                if tel_excel == num_telefono:
                    f_fecha = f[0]
                    f_hora = f[1].strip().zfill(5)
                    f_barbero = f[6] if len(f) >= 7 else "Nacho"
                    if datetime.datetime.strptime(f_fecha, "%d/%m/%Y").date() >= hoy_dt.date():
                        turnos_encontrados.append(
                            {"fecha": f_fecha, "hora": f_hora, "barbero": f_barbero}
                        )

        if not turnos_encontrados:
            response.message("No encontré ningún turno futuro registrado con tu número. 🤷‍♂️\n\n↩️ *0* para volver")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

        sesiones[num_telefono]["turnos_cancelables"] = turnos_encontrados
        sesiones[num_telefono]["estado"] = "eligiendo_turno_cancelar"

        res_text = "Encontré estos turnos a tu nombre. ¿Cuál querés cancelar?\n\n"
        for idx, t in enumerate(turnos_encontrados, start=1):
            res_text += f"{idx}️⃣ {t['fecha']} a las {t['hora']} con {t['barbero']}\n"
        res_text += "\n👉 Respondé con el número del turno (ej: 1).\n↩️ *0* para volver"
        
        response.message(res_text)
        return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PROCESAMIENTO DE LA CANCELACIÓN (Eligió el turno a borrar)
    # ==========================================
    if estado_actual == "eligiendo_turno_cancelar" and msg != "0":
        turnos_guardados = sesiones[num_telefono].get("turnos_cancelables", [])
        if msg.isdigit() and 1 <= int(msg) <= len(turnos_guardados):
            turno_elegido = turnos_guardados[int(msg) - 1]
            f_c, h_c, barbero_canc = turno_elegido["fecha"], turno_elegido["hora"], turno_elegido["barbero"]

            datos_a_actualizados = agenda_sheet.get_all_values()
            fila_a_borrar = None
            for i, f in enumerate(datos_a_actualizados):
                if len(f) >= 4 and normalizar_telefono(f[3]) == num_telefono and f[0] == f_c and f[1].strip().zfill(5) == h_c:
                    fila_a_borrar = i + 1
                    break

            if fila_a_borrar:
                agenda_sheet.delete_rows(fila_a_borrar)
                try:
                    hoja_canc = horarios_b2 if barbero_canc == "Sebas" else horarios_b1
                    f_obj = datetime.datetime.strptime(f_c, "%d/%m/%Y")
                    c_h, c_c = (f_obj.weekday() * 2) + 1, (f_obj.weekday() * 2) + 2
                    lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                    idx_g = (f_obj.date() - lun_act.date()).days // 7

                    if 0 <= idx_g <= 4:
                        f_o_g, b_t = None, -1
                        for n_f, f_d in enumerate(hoja_canc.get_all_values(), start=1):
                            if "hora" in " ".join([str(c).lower() for c in f_d]):
                                b_t += 1
                                continue
                            if b_t == idx_g and len(f_d) > (c_h - 1) and str(f_d[c_h - 1]).strip().zfill(5) == h_c:
                                f_o_g = n_f
                                break
                        if f_o_g:
                            hoja_canc.update_cell(f_o_g, c_c, "")
                except Exception as e:
                    print(f"Error borrando grilla: {e}")

                sesiones[num_telefono]["estado"] = "inicio"
                response.message("Turno cancelado exitosamente. 🤝\n\nEl espacio ya está libre de nuevo.")
                
            else:
                response.message("Hubo un problema. Quizás ya había sido borrado. 🤷‍♂️\n\n↩️ *0* para empezar de nuevo")
                sesiones[num_telefono]["estado"] = "inicio"
        else:
            response.message("Número inválido. Respondé con un número de la lista (ej: *1*).\n\n↩️ *0* para volver")
            
        return Response(content=str(response), media_type="application/xml; charset=utf-8")

    return None