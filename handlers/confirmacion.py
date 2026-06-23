import datetime
from fastapi import Response
from twilio.twiml.messaging_response import MessagingResponse
from utils.helpers import obtener_inicio_semana_reservas
from core.config import agenda_sheet, catalogo_sheet, tz_arg
from services.graficos import tocar_timbre


async def manejar_confirmacion(
    msg: str,
    num_telefono: str,
    estado_actual: str,
    sesiones: dict,
    partes: list,
    ProfileName: str,
    datos_horarios: list,
    hoja_activa,
):
    response = MessagingResponse()
    hoy_dt = datetime.datetime.now(tz_arg)

    if estado_actual == "ingresando_datos_turnos":
        lista_servicios = sesiones[num_telefono].get("lista_servicios", [])
        bloque_horas = sesiones[num_telefono].get("bloque_horas", [])
        idx_actual = sesiones[num_telefono].get("indice_turno_actual", 0)
        cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)

        # ==========================================
        # MAGIA: PROCESADOR DE MÚLTIPLES TURNOS
        # ==========================================
        # Reemplazamos conectores comunes por comas para facilitar el corte
        msg_limpio = msg.replace(" y ", ", ").replace(" - ", ", ")

        # Cortamos el mensaje en varios pedazos usando la coma
        turnos_raw = [t.strip() for t in msg_limpio.split(",") if t.strip()]

        for texto_turno in turnos_raw:
            if idx_actual >= cantidad_turnos:
                break  # Si mandó de más, ignoramos y cortamos acá

            partes_turno = texto_turno.split()
            id_servicio = next((p for p in partes_turno if p.isdigit()), None)
            nombre_cliente = " ".join(
                [p for p in partes_turno if p != id_servicio]
            ).title()

            if not nombre_cliente:
                nombre_cliente = ProfileName if ProfileName else "Cliente"

            # Limpieza final (por si le quedó alguna coma pegada al nombre)
            nombre_cliente = nombre_cliente.replace(",", "").strip()

            servicio_elegido = next(
                (s for s in lista_servicios if s["id"] == id_servicio), None
            )

            if not id_servicio or not servicio_elegido:
                response.message(
                    f"⚠️ No entendí qué servicio querés para '{texto_turno}'.\n\nPor favor, escribí el *Nombre* y el *Número* de la lista para el Turno {idx_actual + 1} ({bloque_horas[idx_actual]})."
                )
                return Response(
                    content=str(response), media_type="application/xml; charset=utf-8"
                )

            # Guardar en la memoria temporal
            sesiones[num_telefono]["turnos_a_guardar"].append(
                {
                    "hora": bloque_horas[idx_actual],
                    "nombre": nombre_cliente,
                    "servicio": servicio_elegido["nombre"],
                    "precio": servicio_elegido["precio"],
                }
            )

            idx_actual += 1
            sesiones[num_telefono]["indice_turno_actual"] = idx_actual

        # Si mandó menos nombres de los que había pedido, le avisamos cuántos faltan
        if idx_actual < cantidad_turnos:
            res_text = f"✅ Anotado. \n\n👉 Ahora faltan {cantidad_turnos - idx_actual} turno/s. Para el **Turno {idx_actual + 1} ({bloque_horas[idx_actual]})**, decime el *Nombre* y el *Número de Servicio*."
            response.message(res_text)
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )

        # ==========================================
        # SI YA COMPLETÓ TODOS LOS TURNOS, GUARDAMOS EN SHEETS
        # ==========================================
        fecha_r = sesiones[num_telefono].get("fecha_seleccionada")
        barbero_nom = sesiones[num_telefono].get("barbero_nombre", "Nacho")
        barbero_id = sesiones[num_telefono].get("barbero_id", "1")

        f_obj = datetime.datetime.strptime(fecha_r, "%d/%m/%Y")
        lun_act = obtener_inicio_semana_reservas(hoy_dt)
        idx_g = (f_obj.date() - lun_act.date()).days // 7
        c_h = (f_obj.weekday() * 2) + 1
        c_c = c_h + 1

        resumen_txt = (
            f"¡Todo listo! ✂️ Turnos confirmados el {fecha_r} con {barbero_nom}:\n\n"
        )

        for turno in sesiones[num_telefono]["turnos_a_guardar"]:
            precio_num = int(turno["precio"]) if turno["precio"].isdigit() else 0

            agenda_sheet.append_row(
                [
                    fecha_r,
                    turno["hora"],
                    turno["nombre"],
                    num_telefono,
                    turno["servicio"],
                    precio_num,
                    barbero_nom,
                ],
                value_input_option="USER_ENTERED",
            )

            resumen_txt += (
                f"🔹 {turno['hora']} - {turno['nombre']} ({turno['servicio']})\n"
            )

            try:
                if 0 <= idx_g <= 4:
                    f_o, b_t = None, -1
                    for n_f, f_d in enumerate(datos_horarios, start=1):
                        if "hora" in " ".join(
                            [str(c).lower() for c in f_d]
                        ) and "estado" in " ".join([str(c).lower() for c in f_d]):
                            b_t += 1
                            continue
                        if (
                            b_t == idx_g
                            and len(f_d) > (c_h - 1)
                            and str(f_d[c_h - 1]).strip().zfill(5) == turno["hora"]
                        ):
                            f_o = n_f
                            break
                    if f_o:
                        hoja_activa.update_cell(f_o, c_c, turno["nombre"])
            except Exception as e:
                print(f"Error actualizando grilla múltiple: {e}")

        resumen_txt += "\n⚠️ Recordá que tenemos *15 min de tolerancia*. En caso de no presentarse o de *cancelar en las 24 horas previas* al turno, se deberá abonar el *50% del costo del servicio solicitado*.\n\n"

        semana_turno = sesiones[num_telefono].get("semana", 1)
        try:
            tocar_timbre(barbero_id, semana_turno, barbero_nom)
        except Exception as e:
            # Fix 9: el turno quedó guardado en Sheets, pero la foto de la agenda
            # quedará desactualizada hasta el próximo ciclo del motor (15 min).
            print(
                f"🔴 ALERTA tocar_timbre: falló para {barbero_nom} sem={semana_turno}. La foto se actualizará en el próximo ciclo del motor. Error: {e}"
            )

        try:
            datos_catalogo = catalogo_sheet.get_all_values()
            texto_catalogo = "🛍️ *Aprovechá y mirá nuestros productos disponibles:*\n"
            hay_productos = False
            for fila in datos_catalogo[1:]:
                if len(fila) >= 4:
                    n_prod, p_prod, stock, mostrar = (
                        fila[0].strip(),
                        fila[1].strip(),
                        fila[2].strip().lower(),
                        fila[3].strip().lower(),
                    )
                    if stock in ["si", "sí"] and mostrar in ["si", "sí"]:
                        texto_catalogo += f"🔹 {n_prod} - ${p_prod}\n"
                        hay_productos = True
            if hay_productos:
                resumen_txt += (
                    texto_catalogo
                    + "\n👉 Si querés alguno, avisale a tu barbero. \n\n Si te interesan otros emprendimientos de la empresa, podés visitar @mates.craziness en Instagram"
                )
        except Exception as e:
            print(f"Error leyendo catálogo: {e}")

        sesiones[num_telefono]["estado"] = "inicio"
        response.message(resumen_txt)
        return Response(
            content=str(response), media_type="application/xml; charset=utf-8"
        )

    return None
