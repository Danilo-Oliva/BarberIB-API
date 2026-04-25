import datetime
from fastapi import Response
from twilio.twiml.messaging_response import MessagingResponse

from core.config import agenda_sheet, servicios_sheet, tz_arg, DIAS_SEMANA, DIAS_LABORABLES
from utils.helpers import quitar_tildes, obtener_horas_por_dia, extraer_hora

async def manejar_reservas(msg: str, num_telefono: str, estado_actual: str, sesiones: dict, datos_horarios: list, excepciones: dict, barbero_id: str):
    response = MessagingResponse()
    hoy_dt = datetime.datetime.now(tz_arg)
    partes = msg.split()

    # ==========================================
    # PASO 1: ELEGIR BARBERO
    # ==========================================
    if msg == "1" and estado_actual == "inicio":
        sesiones[num_telefono]["estado"] = "eligiendo_barbero"
        response.message("¡Perfecto! ¿Con quién te querés atender?\n\n1️⃣ Nacho\n2️⃣ Sebas\n\n👉 Respondé con 1 o 2.\n↩️ *0* para volver a empezar")
        return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 2: ELEGIR CANTIDAD DE TURNOS
    # ==========================================
    if estado_actual == "eligiendo_barbero":
        if msg in ["1", "2"]:
            sesiones[num_telefono]["barbero_id"] = msg
            barbero_nom = "Nacho" if msg == "1" else "Sebas"
            sesiones[num_telefono]["barbero_nombre"] = barbero_nom
            sesiones[num_telefono]["estado"] = "eligiendo_cantidad_turnos"

            res_text = f"Elegiste a {barbero_nom}. ✂️\n\n¿Cuántos turnos seguidos querés sacar?\n*(Aclaración: Si sacás más de un turno, serán todos consecutivos con {barbero_nom})*\n\n1️⃣ Un turno\n2️⃣ Dos turnos seguidos\n3️⃣ Tres turnos seguidos\n\n👉 Respondé con 1, 2 o 3.\n↩️ *0* para volver a empezar"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("Por favor, respondé con 1 o 2. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 3: ELEGIR SEMANA
    # ==========================================
    if estado_actual == "eligiendo_cantidad_turnos":
        if msg in ["1", "2", "3"]:
            sesiones[num_telefono]["cantidad_turnos"] = int(msg)
            sesiones[num_telefono]["estado"] = "eligiendo_semana"

            res_text = "¿Para cuándo buscan turno?\n\n1️⃣ Esta semana\n2️⃣ La próxima semana\n3️⃣ En 15 días\n4️⃣ En 3 semanas\n\n👉 Respondé con un número del 1 al 4.\n↩️ *0* para volver"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("Por favor, respondé con 1, 2 o 3. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 4: ELEGIR DÍA (Muestra Foto Estática)
    # ==========================================
    if estado_actual == "eligiendo_semana":
        if msg in ["1", "2", "3", "4"]:
            sesiones[num_telefono]["semana"] = int(msg)
            semana_elegida = sesiones[num_telefono].get("semana", 1)
            cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)
            sesiones[num_telefono]["estado"] = "eligiendo_dia"

            inicio_rango = (semana_elegida - 1) * 7
            fin_rango = semana_elegida * 7

            datos_agenda = agenda_sheet.get_all_values()
            dias_disponibles, mapa_dias, avisos_exc = [], {}, []
            lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())

            for i in range(inicio_rango, fin_rango):
                fecha_dt = lun_act + datetime.timedelta(days=i)
                if fecha_dt.date() < hoy_dt.date() or fecha_dt.weekday() not in DIAS_LABORABLES:
                    continue

                idx_g = i // 7
                if idx_g > 4: continue

                horas_fijas = obtener_horas_por_dia(datos_horarios, fecha_dt.weekday(), idx_g)
                if not horas_fijas: continue

                fecha_str = fecha_dt.strftime("%d/%m/%Y")
                nombre_dia = DIAS_SEMANA[fecha_dt.weekday()]
                horas_del_dia = horas_fijas.copy()

                if fecha_str in excepciones:
                    exc = excepciones[fecha_str]
                    m_txt = f" por {exc['motivo']}" if exc["motivo"] else ""
                    if exc["tipo"] == "cerrado":
                        avisos_exc.append(f"❌ {nombre_dia.capitalize()}: Cerrado{m_txt}.")
                        continue
                    elif exc["tipo"] == "especial" and "-" in exc["horas"]:
                        ini, fin = exc["horas"].split("-")[0].strip().zfill(5), exc["horas"].split("-")[1].strip().zfill(5)
                        horas_del_dia = [h for h in horas_del_dia if ini <= h <= fin]
                        avisos_exc.append(f"⚠️ {nombre_dia.capitalize()}: Horario {exc['horas']}{m_txt}.")

                ocupados = [f[1].strip().zfill(5) for f in datos_agenda if len(f) >= 7 and f[0] == fecha_str and f[6] == sesiones[num_telefono]["barbero_nombre"]]

                horas_disp_reales = []
                for h in horas_del_dia:
                    if h not in ocupados:
                        if fecha_dt.date() == hoy_dt.date():
                            if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time(): horas_disp_reales.append(h)
                        else: horas_disp_reales.append(h)

                hay_bloque = False
                for idx_h in range(len(horas_fijas)):
                    if idx_h + cantidad_turnos <= len(horas_fijas):
                        bloque = horas_fijas[idx_h : idx_h + cantidad_turnos]
                        if all(h in horas_disp_reales for h in bloque):
                            hay_bloque = True
                            break

                if hay_bloque:
                    dias_disponibles.append(f"{nombre_dia.capitalize()} ({fecha_dt.strftime('%d/%m')})")
                    mapa_dias[nombre_dia] = fecha_str

            sesiones[num_telefono]["mapa_dias"] = mapa_dias

            if dias_disponibles:
                txt_d = ", ".join(dias_disponibles[:-1]) + " o " + dias_disponibles[-1] if len(dias_disponibles) > 1 else dias_disponibles[0]
                res_text = f"Tengo bloques de {cantidad_turnos} turnos seguidos para el {txt_d}."
                if avisos_exc: res_text += "\n\n" + "\n".join(avisos_exc)

                try:
                    datos_servicios = servicios_sheet.get_all_values()
                    texto_menu = "\n\n💇‍♂️ *Lista de Servicios:*\n"
                    for i, fila in enumerate(datos_servicios[1:], start=1):
                        if len(fila) >= 2 and fila[0].strip():
                            texto_menu += f"💈 *{i}* - {fila[0].strip()} (${fila[1].strip()})\n"
                    res_text += texto_menu
                except Exception as e:
                    print(f"Error cargando servicios en PASO 4: {e}")

                res_text += "\n👉 Escribí el *DÍA, HORA, NOMBRE y N° SERVICIO*."
                if cantidad_turnos > 1:
                    res_text += f"\n*(Como sacaste {cantidad_turnos} turnos, podés mandar todos los nombres juntos separados por coma. Ej: Lunes 16:00 Sebas 1, Nacho 2)*"
                else:
                    res_text += "\n*(Ej: Lunes 16:00 Nachito 1)*"
                res_text += "\n\n↩️ *b* para otra semana\n↩️ *0* para empezar de cero"

                msg_obj = response.message(res_text)
                url_publica = f"https://barberib-bot.onrender.com/static/agenda_{barbero_id}_sem{semana_elegida}.png"
                msg_obj.media(url_publica)

                return Response(content=str(response), media_type="application/xml; charset=utf-8")
            else:
                res_text = f"No hay {cantidad_turnos} turnos seguidos disponibles esa semana. 😭\n\n↩️ *b* para elegir otra semana\n↩️ *0* para menú principal"
                response.message(res_text)
                return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("Por favor, respondé con un número del 1 al 4 para elegir la semana. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 5: VER HORARIOS DE INICIO (El Interceptor)
    # ==========================================
    if estado_actual == "eligiendo_dia" and "cancelar" not in msg:
        mapa = sesiones[num_telefono].get("mapa_dias", {})
        dia_det = next((d for d in mapa.keys() if quitar_tildes(d) in quitar_tildes(msg)), None)
        cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)

        if dia_det:
            fecha_str = mapa[dia_det]
            sesiones[num_telefono]["estado"] = "viendo_horarios"
            sesiones[num_telefono]["fecha_seleccionada"] = fecha_str

            f_obj = datetime.datetime.strptime(fecha_str, "%d/%m/%Y")
            lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
            idx_g = (f_obj.date() - lun_act.date()).days // 7

            h_dia = obtener_horas_por_dia(datos_horarios, f_obj.weekday(), idx_g)

            if fecha_str in excepciones and excepciones[fecha_str]["tipo"] == "especial":
                if "-" in excepciones[fecha_str]["horas"]:
                    p = excepciones[fecha_str]["horas"].split("-")
                    if len(p) == 2:
                        ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                        h_dia = [h for h in h_dia if ini <= h <= fin]

            ocupadas = [f[1].strip().zfill(5) for f in agenda_sheet.get_all_values() if len(f) >= 7 and f[0] == fecha_str and f[6] == sesiones[num_telefono]["barbero_nombre"]]

            horas_disp_reales = []
            for h in h_dia:
                if h not in ocupadas:
                    if fecha_str == hoy_dt.strftime("%d/%m/%Y"):
                        if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time(): horas_disp_reales.append(h)
                    else: horas_disp_reales.append(h)

            inicios_validos = []
            for idx_h in range(len(h_dia)):
                if idx_h + cantidad_turnos <= len(h_dia):
                    bloque = h_dia[idx_h : idx_h + cantidad_turnos]
                    if all(h in horas_disp_reales for h in bloque): inicios_validos.append(bloque[0])

            sesiones[num_telefono]["horas_fijas_del_dia"] = h_dia
            sesiones[num_telefono]["inicios_validos"] = inicios_validos
            sesiones[num_telefono]["fecha_seleccionada"] = fecha_str

            h_des = extraer_hora(msg)
            if h_des:
                if h_des in inicios_validos:
                    partes_extra = []
                    dia_removido = False
                    hora_removida = False
                    
                    for p in partes:
                        if not dia_removido and quitar_tildes(dia_det) in quitar_tildes(p):
                            dia_removido = True
                            continue
                        
                        if not hora_removida and extraer_hora(p) == h_des:
                            hora_removida = True
                            continue
                            
                        partes_extra.append(p)
                        
                    texto_restante = " ".join(partes_extra)
                    tiene_numero = any(p.isdigit() for p in partes_extra)

                    if texto_restante and tiene_numero:
                        idx_arranque = h_dia.index(h_des)
                        sesiones[num_telefono]["bloque_horas"] = h_dia[idx_arranque : idx_arranque + cantidad_turnos]
                        sesiones[num_telefono]["turnos_a_guardar"] = []
                        sesiones[num_telefono]["indice_turno_actual"] = 0

                        datos_servicios = servicios_sheet.get_all_values()
                        sesiones[num_telefono]["lista_servicios"] = [{"id": str(i), "nombre": f[0].strip(), "precio": f[1].strip()} for i, f in enumerate(datos_servicios[1:], start=1) if len(f) >= 2 and f[0].strip()]

                        sesiones[num_telefono]["estado"] = "ingresando_datos_turnos"
                        msg = texto_restante
                        partes = msg.split()
                        return None, msg, partes # Deja pasar al Paso 7
                    else:
                        sesiones[num_telefono]["estado"] = "viendo_horarios"
                        msg = h_des
                        partes = msg.split()
                else:
                    response.message(f"⚠️ La hora {h_des} no está disponible o no hay bloques contiguos. Elegí una válida.")
                    return Response(content=str(response), media_type="application/xml; charset=utf-8")

            if sesiones[num_telefono]["estado"] == "eligiendo_dia":
                if inicios_validos:
                    dispo = [f"✅ {h}" for h in inicios_validos]
                    res_text = f"Horarios de INICIO disponibles para el {dia_det.capitalize()} ({fecha_str}):\n\n" + "\n".join(dispo)
                    res_text += f"\n\n👉 Decime a qué hora quieren arrancar (ej: *{inicios_validos[0]}*)\n↩️ *b* para cambiar de día"
                else:
                    res_text = "Día sin bloques libres. 😭\n\n↩️ *b* para elegir otro día\n↩️ *0* para menú principal"
                response.message(res_text)
                return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("No entendí el día. Revisá la lista arriba. 👆\n↩️ *b* para elegir otra semana")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 6: INICIAR LOOP DE NOMBRES Y SERVICIOS
    # ==========================================
    if estado_actual == "viendo_horarios" and "cancelar" not in msg:
        h_des = extraer_hora(msg)

        if h_des:
            cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)
            h_dia = sesiones[num_telefono].get("horas_fijas_del_dia", [])
            inicios_validos = sesiones[num_telefono].get("inicios_validos", [])

            if h_des in inicios_validos:
                idx_arranque = h_dia.index(h_des)
                bloque_horas = h_dia[idx_arranque : idx_arranque + cantidad_turnos]

                sesiones[num_telefono]["bloque_horas"] = bloque_horas
                sesiones[num_telefono]["turnos_a_guardar"] = []
                sesiones[num_telefono]["indice_turno_actual"] = 0
                sesiones[num_telefono]["estado"] = "ingresando_datos_turnos"

                datos_servicios = servicios_sheet.get_all_values()
                lista_servicios = []
                texto_menu = "💇‍♂️ *Lista de Servicios:*\n"
                for i, fila in enumerate(datos_servicios[1:], start=1):
                    if len(fila) >= 2 and fila[0].strip():
                        lista_servicios.append({"id": str(i), "nombre": fila[0].strip(), "precio": fila[1].strip()})
                        texto_menu += f"💈 *{i}* - {fila[0].strip()} (${fila[1].strip()})\n"

                sesiones[num_telefono]["lista_servicios"] = lista_servicios

                res_text = f"¡Genial! Bloqueamos desde las {bloque_horas[0]}. ⏱️\n\n{texto_menu}\n\n👉 Escribí el *Nombre* y el *Número de Servicio* para los turnos."
                if cantidad_turnos > 1:
                    res_text += f"\n*(Podés mandar todos juntos separados por coma. Ej: Danilo 1, Juan 2)*"
                response.message(res_text)
                return Response(content=str(response), media_type="application/xml; charset=utf-8")
            else:
                response.message("⚠️ Ese horario no está disponible o no permite la cantidad de turnos que pediste. Revisá la lista arriba y escribí uno de los horarios marcados con ✅ (ej: *16:00*).")
                return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("No entendí la hora. Escribí el horario de inicio (ej: *10* o *10:30*).")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # Si no entró en nada de reservas, devuelve None
    return None