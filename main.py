import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
import datetime
import pytz
import os
import json
import re

# --- CONFIGURACIÓN PARA LA NUBE (RAILWAY/RENDER) ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

google_creds_json = os.environ.get("GOOGLE_CREDS")

if google_creds_json:
    creds_dict = json.loads(google_creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)

client_sheets = gspread.authorize(creds)

app = FastAPI()

# --- ABRIR SHEETS UNA SOLA VEZ AL INICIO ---
archivo = client_sheets.open("Agenda_Barberia")
agenda_sheet = archivo.worksheet("Agenda")
horarios_b1 = archivo.worksheet("Nacho")
horarios_b2 = archivo.worksheet("Sebas")
servicios_sheet = archivo.worksheet("Servicios")
conf_sheet = archivo.worksheet("Configuracion")
catalogo_sheet = archivo.worksheet("Catalogo")

sesiones = {}
tz_arg = pytz.timezone("America/Argentina/Buenos_Aires")

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_LABORABLES = [0, 1, 2, 3, 4, 5, 6]

def quitar_tildes(texto):
    return (
        texto.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )

def obtener_horas_por_dia(datos_horarios, weekday, semana_index):
    col_idx = weekday * 2
    horas = []
    bloque_actual = -1

    for fila in datos_horarios:
        fila_str = " ".join([str(c).lower() for c in fila])
        if "hora" in fila_str and "estado" in fila_str:
            bloque_actual += 1
            continue

        if bloque_actual == semana_index:
            if len(fila) > col_idx:
                celda = str(fila[col_idx]).strip()
                if ":" in celda:
                    horas.append(celda.zfill(5))

    return list(dict.fromkeys(horas))

def extraer_hora(msg):
    match = re.search(r"(\d{1,2})(?:[:.](\d{2}))?(?:\s*(?:hs|h|hrs|horas))?", msg)
    if match:
        hora = int(match.group(1))
        minuto = match.group(2) if match.group(2) else "00"
        if 0 <= hora <= 23:
            return f"{hora:02d}:{minuto}"
    return None

def normalizar_telefono(telefono):
    """
    Toma cualquier formato de teléfono de Twilio y devuelve solo los últimos 10 dígitos.
    Ej: '+5491112345678' -> '1112345678'
        '541112345678' -> '1112345678'
    """
    # Dejar solo los números
    tel_solo_numeros = re.sub(r'\D', '', telefono)
    # Devolver siempre los últimos 10 dígitos (el código de área + el número local)
    return tel_solo_numeros[-10:] if len(tel_solo_numeros) >= 10 else tel_solo_numeros

@app.post("/whatsapp")
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

    # BOTÓN DE PÁNICO
    if msg == "0" and estado_actual != "inicio":
        sesiones[num_telefono] = {"estado": "inicio"}
        estado_actual = "inicio"
        msg = "1" # Forzamos a que vuelva a pedir turno

    # ==========================================
    # PASO 1: ELEGIR CANTIDAD DE TURNOS
    # ==========================================
    if msg == "1" and estado_actual == "inicio":
        sesiones[num_telefono]["estado"] = "eligiendo_barbero"
        response.message("¡Perfecto! ¿Con quién te querés atender?\n\n1️⃣ Nacho\n2️⃣ Sebas\n\n👉 Respondé con 1 o 2.\n↩️ *0* para volver a empezar")
        return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # CANCELACIÓN (Sin cambios, funciona perfecto)
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
                        turnos_encontrados.append({"fecha": f_fecha, "hora": f_hora, "barbero": f_barbero})
        
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

    # ==========================================
    # PASO 2: ELEGIR BARBERO
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
    # PASO 4: ELEGIR DÍA (Filtro por bloques)
    # ==========================================
    if estado_actual == "eligiendo_semana":
        if msg in ["1", "2", "3", "4", "8"]:
            if msg != "8":
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
                    m_txt = f" por {exc['motivo']}" if exc['motivo'] else ""
                    if exc["tipo"] == "cerrado":
                        avisos_exc.append(f"❌ {nombre_dia.capitalize()}: Cerrado{m_txt}.")
                        continue
                    elif exc["tipo"] == "especial":
                        avisos_exc.append(f"⚠️ {nombre_dia.capitalize()}: Horario {exc['horas']}{m_txt}.")
                        if "-" in exc["horas"]:
                            p = exc["horas"].split("-")
                            if len(p) == 2:
                                ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                                horas_del_dia = [h for h in horas_del_dia if ini <= h <= fin]

                ocupados = [f[1].strip().zfill(5) for f in datos_agenda if len(f) >= 7 and f[0] == fecha_str and f[6] == sesiones[num_telefono]["barbero_nombre"]]

                # LÓGICA DE BLOQUES CONSECUTIVOS
                horas_disp_reales = []
                for h in horas_del_dia:
                    if h not in ocupados:
                        if fecha_dt.date() == hoy_dt.date():
                            if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time():
                                horas_disp_reales.append(h)
                        else:
                            horas_disp_reales.append(h)

                hay_bloque = False
                for idx_h in range(len(horas_fijas)):
                    if idx_h + cantidad_turnos <= len(horas_fijas):
                        bloque = horas_fijas[idx_h : idx_h + cantidad_turnos]
                        if all(h in horas_disp_reales for h in bloque):
                            hay_bloque = True
                            break

                dia_visual = f"{nombre_dia.capitalize()} ({fecha_dt.strftime('%d/%m')})"
                if hay_bloque:
                    dias_disponibles.append(dia_visual)
                    mapa_dias[nombre_dia] = fecha_str

            sesiones[num_telefono]["mapa_dias"] = mapa_dias
            if dias_disponibles:
                txt_d = ", ".join(dias_disponibles[:-1]) + " o " + dias_disponibles[-1] if len(dias_disponibles) > 1 else dias_disponibles[0]
                res_text = f"Tengo bloques de {cantidad_turnos} turnos seguidos para el {txt_d}."
                if avisos_exc: res_text += "\n\n" + "\n".join(avisos_exc)
                res_text += "\n\n👉 Escribí el día (ej: Lunes)\n↩️ *8* para otra semana\n↩️ *0* para empezar de cero"
            else:
                res_text = f"No hay {cantidad_turnos} turnos seguidos disponibles esa semana. 😭\n\n↩️ *8* para elegir otra semana\n↩️ *0* para menú principal"
                
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        
        else:
            response.message("Por favor, respondé con un número del 1 al 4 para elegir la semana. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        

    # ==========================================
    # PASO 5: VER HORARIOS DE INICIO
    # ==========================================
    if estado_actual == "eligiendo_dia" and "cancelar" not in msg:
        if msg == "8":
            sesiones[num_telefono]["estado"] = "eligiendo_semana"
            barbero = sesiones[num_telefono].get("barbero_nombre", "Barbero")
            response.message(f"Ok, volvemos atrás. Estás agendando con {barbero}.\n\n¿Para cuándo buscan turno?\n1️⃣ Esta semana\n2️⃣ La próxima semana\n3️⃣ En 15 días\n4️⃣ En 3 semanas\n\n👉 Respondé del 1 al 4.")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

        mapa = sesiones[num_telefono].get("mapa_dias", {})
        dia_det = next((d for d in mapa.keys() if quitar_tildes(d) in msg_limpio), None)
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
                        if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time():
                            horas_disp_reales.append(h)
                    else:
                        horas_disp_reales.append(h)

            # Extraemos SOLO los inicios que permiten el bloque completo
            inicios_validos = []
            for idx_h in range(len(h_dia)):
                if idx_h + cantidad_turnos <= len(h_dia):
                    bloque = h_dia[idx_h : idx_h + cantidad_turnos]
                    if all(h in horas_disp_reales for h in bloque):
                        inicios_validos.append(bloque[0])

            sesiones[num_telefono]["horas_fijas_del_dia"] = h_dia

            if inicios_validos:
                dispo = [f"✅ {h}" for h in inicios_validos]
                res_text = f"Horarios de INICIO disponibles para el {dia_det.capitalize()} ({fecha_str}):\n\n" + "\n".join(dispo)
                res_text += f"\n\n👉 Decime a qué hora quieren arrancar (ej: *{inicios_validos[0]}*)\n↩️ *8* para cambiar de día"
            else:
                res_text = "Día sin bloques libres. 😭\n\n↩️ *8* para elegir otro día\n↩️ *0* para menú principal"
                
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("No entendí el día. Revisá la lista arriba. 👆\n↩️ *8* para elegir otra semana")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 6: INICIAR LOOP DE NOMBRES Y SERVICIOS
    # ==========================================
    if estado_actual == "viendo_horarios" and "cancelar" not in msg:
        h_des = extraer_hora(msg)
        
        if msg == "8":
            sesiones[num_telefono]["estado"] = "eligiendo_semana"
            response.message("Ok, volvemos a elegir día. Por favor mandá un *8* nuevamente para ver tu semana, o un *0* para reiniciar todo.")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

        if h_des:
            cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)
            h_dia = sesiones[num_telefono].get("horas_fijas_del_dia", [])
            
            if h_des in h_dia:
                idx_arranque = h_dia.index(h_des)
                if idx_arranque + cantidad_turnos <= len(h_dia):
                    bloque_horas = h_dia[idx_arranque : idx_arranque + cantidad_turnos]
                    
                    # Preparar el terreno para el Loop
                    sesiones[num_telefono]["bloque_horas"] = bloque_horas
                    sesiones[num_telefono]["turnos_a_guardar"] = []
                    sesiones[num_telefono]["indice_turno_actual"] = 0
                    sesiones[num_telefono]["estado"] = "ingresando_datos_turnos"
                    
                    # Cargar lista de servicios para mostrársela al cliente
                    datos_servicios = servicios_sheet.get_all_values()
                    lista_servicios = []
                    texto_menu = "💇‍♂️ *Lista de Servicios:*\n"
                    for i, fila in enumerate(datos_servicios[1:], start=1):
                        if len(fila) >= 2 and fila[0].strip():
                            lista_servicios.append({"id": str(i), "nombre": fila[0].strip(), "precio": fila[1].strip()})
                            texto_menu += f"💈 *{i}* - {fila[0].strip()} (${fila[1].strip()})\n"
                    
                    sesiones[num_telefono]["lista_servicios"] = lista_servicios

                    res_text = f"¡Genial! Bloqueamos desde las {bloque_horas[0]}. ⏱️\n\n{texto_menu}\n\n👉 Para el **Turno 1 ({bloque_horas[0]})**, escribime el *Nombre* y el *Número de Servicio* (Ej: *Nacho 1*)."
                    response.message(res_text)
                    return Response(content=str(response), media_type="application/xml; charset=utf-8")
                
            response.message("Ese horario no permite la cantidad de turnos que pediste. Revisá la lista arriba e intentá de nuevo. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            response.message("No entendí la hora. Escribí el horario de inicio (ej: *10* o *10:30*).")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # ==========================================
    # PASO 7: LOOP DE RECOLECCIÓN Y GUARDADO FINAL
    # ==========================================
    if estado_actual == "ingresando_datos_turnos":
        lista_servicios = sesiones[num_telefono].get("lista_servicios", [])
        bloque_horas = sesiones[num_telefono].get("bloque_horas", [])
        idx_actual = sesiones[num_telefono].get("indice_turno_actual", 0)
        cantidad_turnos = sesiones[num_telefono].get("cantidad_turnos", 1)

        # Separar el número de servicio del nombre del cliente
        id_servicio = next((p for p in partes if p.isdigit()), None)
        nombre_cliente = " ".join([p for p in partes if p != id_servicio]).title()
        
        if not nombre_cliente:
            nombre_cliente = ProfileName if ProfileName else "Cliente"

        servicio_elegido = next((s for s in lista_servicios if s["id"] == id_servicio), None)

        if not id_servicio or not servicio_elegido:
            response.message("⚠️ No entendí qué servicio querés.\n\nPor favor, escribí el *Nombre* y el *Número* de la lista (Ej: *Nacho 2*).")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

        # Guardar en la memoria temporal
        sesiones[num_telefono]["turnos_a_guardar"].append({
            "hora": bloque_horas[idx_actual],
            "nombre": nombre_cliente,
            "servicio": servicio_elegido["nombre"],
            "precio": servicio_elegido["precio"]
        })

        idx_actual += 1
        sesiones[num_telefono]["indice_turno_actual"] = idx_actual

        # Si faltan turnos, volvemos a preguntar
        if idx_actual < cantidad_turnos:
            res_text = f"✅ Anotado. \n\n👉 Ahora para el **Turno {idx_actual + 1} ({bloque_horas[idx_actual]})**, decime el *Nombre* y el *Número de Servicio*."
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        
        # SI YA COMPLETÓ TODOS LOS TURNOS, GUARDAMOS EN SHEETS
        fecha_r = sesiones[num_telefono].get("fecha_seleccionada")
        barbero_nom = sesiones[num_telefono].get("barbero_nombre", "Nacho")
        f_obj = datetime.datetime.strptime(fecha_r, "%d/%m/%Y")
        lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
        idx_g = (f_obj.date() - lun_act.date()).days // 7
        c_h = (f_obj.weekday() * 2) + 1
        c_c = c_h + 1

        resumen_txt = f"¡Todo listo! ✂️ Turnos confirmados el {fecha_r} con {barbero_nom}:\n\n"

        for turno in sesiones[num_telefono]["turnos_a_guardar"]:
            precio_num = int(turno["precio"]) if turno["precio"].isdigit() else 0
            
            # Escribir en la Agenda (Se crea una fila nueva por cada uno, clonando la burbuja de Buzz Lightyear)
            agenda_sheet.append_row([
                fecha_r, turno["hora"], turno["nombre"], num_telefono, 
                turno["servicio"], precio_num, barbero_nom
            ], value_input_option="USER_ENTERED")

            resumen_txt += f"🔹 {turno['hora']} - {turno['nombre']} ({turno['servicio']})\n"

            # Tachar en la grilla visual del barbero
            try:
                if 0 <= idx_g <= 4:
                    f_o, b_t = None, -1
                    for n_f, f_d in enumerate(datos_horarios, start=1):
                        if "hora" in " ".join([str(c).lower() for c in f_d]) and "estado" in " ".join([str(c).lower() for c in f_d]):
                            b_t += 1
                            continue
                        if b_t == idx_g and len(f_d) > (c_h - 1) and str(f_d[c_h - 1]).strip().zfill(5) == turno["hora"]:
                            f_o = n_f
                            break
                    if f_o:
                        hoja_activa.update_cell(f_o, c_c, turno["nombre"])
            except Exception as e:
                print(f"Error actualizando grilla múltiple: {e}")

        resumen_txt += "\n⚠️ Recordá que tenemos 15 min de tolerancia. En caso de no presentarse o de cancelar en las 24 horas previas al turno, se deberá abonar el 50% del costo del servicio solicitado.\n\n"

        # Pegar el Catálogo al final
        try:
            datos_catalogo = catalogo_sheet.get_all_values()
            texto_catalogo = "🛍️ *Aprovechá y mirá nuestros productos disponibles:*\n"
            hay_productos = False
            for fila in datos_catalogo[1:]:
                if len(fila) >= 4:
                    n_prod, p_prod, stock, mostrar = fila[0].strip(), fila[1].strip(), fila[2].strip().lower(), fila[3].strip().lower()
                    if stock in ["si", "sí"] and mostrar in ["si", "sí"]:
                        texto_catalogo += f"🔹 {n_prod} - ${p_prod}\n"
                        hay_productos = True
            if hay_productos:
                resumen_txt += texto_catalogo + "\n👉 Si querés alguno, avisale a tu barbero."
        except Exception as e:
            print(f"Error leyendo catálogo: {e}")

        sesiones[num_telefono]["estado"] = "inicio"
        response.message(resumen_txt)
        return Response(content=str(response), media_type="application/xml; charset=utf-8")


    # MENSAJE DE INICIO (Fallback)
    sesiones[num_telefono]["estado"] = "inicio"
    response.message(
        "¡Hola! 🤖 Bienvenido a IB Studio. \n Me llamo IBot y soy el esclavo de Nachito, por favor seguí mis instrucciones‼️. \n⚠️ Recordá que el turno tiene máximo 15 min de tolerancia.\n\n👉1️⃣ Para pedir turno \n👉2️⃣ Para cancelar turno \n\nCualquier duda que tengas y yo no te la pueda resolver, escribí un mensaje a este número👉+54 9 11 6046-7963"
    )
    return Response(content=str(response), media_type="application/xml; charset=utf-8")


@app.get("/")
async def root():
    return {"status": "Activo", "logic": "Content-Aware Columns"}