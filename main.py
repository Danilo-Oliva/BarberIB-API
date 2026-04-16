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
horarios_b1 = archivo.worksheet("Horarios_Barbero1")
horarios_b2 = archivo.worksheet("Horarios_Barbero2")
servicios_sheet = archivo.worksheet("Servicios")
conf_sheet = archivo.worksheet("Configuracion")

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

@app.post("/whatsapp")
async def whatsapp(
    Body: str = Form(...), From: str = Form(...), ProfileName: str = Form(None)
):
    hoy_dt = datetime.datetime.now(tz_arg)

    msg = Body.lower().strip()
    msg_limpio = quitar_tildes(msg)
    partes = msg.split()
    response = MessagingResponse()
    num_telefono = From.replace("whatsapp:", "")

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
        estado_actual = "inicio"
        msg = "1"

    # PASO 1: MOSTRAR SERVICIOS
    if msg == "1" and estado_actual == "inicio":
        sesiones[num_telefono]["estado"] = "eligiendo_servicio"
        datos_servicios = servicios_sheet.get_all_values()

        lista_servicios = []
        for i, fila in enumerate(datos_servicios[1:], start=1):
            if len(fila) >= 2 and fila[0].strip():
                lista_servicios.append(
                    {"id": str(i), "nombre": fila[0].strip(), "precio": fila[1].strip()}
                )

        sesiones[num_telefono]["lista_servicios"] = lista_servicios

        texto_menu = "¿Qué servicio te querés hacer?\n\n"
        for serv in lista_servicios:
            texto_menu += f"💈 *{serv['id']}* - {serv['nombre']} (${serv['precio']})\n"

        response.message(
            texto_menu
            + "\n👉 Respondé con el número del servicio.\n↩️ *0* para volver a empezar"
        )
        return Response(
            content=str(response), media_type="application/xml; charset=utf-8"
        )
    if msg == "2" and estado_actual == "inicio":
        h_c = extraer_hora(partes)
        if h_c:
            datos_a = agenda_sheet.get_all_values()
            f_o, f_c, barbero_canc = None, None, None

            for i, f in enumerate(datos_a):
                if (
                    len(f) >= 4
                    and f[3] == num_telefono
                    and f[1].strip().zfill(5) == h_c
                ):
                    f_o, f_c = i + 1, f[0]
                    barbero_canc = f[6] if len(f) >= 7 else "Nacho"
                    break

            if f_o:
                agenda_sheet.delete_rows(f_o)
                try:
                    hoja_canc = (
                        horarios_b2 if barbero_canc == "Seba" else horarios_b1
                    )
                    datos_horarios_canc = hoja_canc.get_all_values()

                    f_obj = datetime.datetime.strptime(f_c, "%d/%m/%Y")
                    c_h = (f_obj.weekday() * 2) + 1
                    c_c = c_h + 1
                    lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                    diff = (f_obj.date() - lun_act.date()).days
                    idx_g = diff // 7 

                    if 0 <= idx_g <= 4:
                        f_o_g, b_t = None, -1
                        for n_f, f_d in enumerate(datos_horarios_canc, start=1):
                            if "hora" in " ".join([str(c).lower() for c in f_d]):
                                b_t += 1
                                continue
                            if (
                                b_t == idx_g
                                and len(f_d) > (c_h - 1)
                                and str(f_d[c_h - 1]).strip().zfill(5) == h_c
                            ):
                                f_o_g = n_f
                                break
                        if f_o_g:
                            hoja_canc.update_cell(f_o_g, c_c, "")
                except Exception as e:
                    print(f"Error actualizando grilla de Cancelación: {e}")

                sesiones[num_telefono]["estado"] = "inicio"
                response.message(f"Turno cancelado exitosamente. 🤝")
            else:
                response.message(f"No encontré tu turno a esa hora.")
        else:
            response.message(
                "Para cancelar, escribí la hora (ej: *Cancelar 10* o *Cancelar 15:30*)"
            )
        return Response(
            content=str(response), media_type="application/xml; charset=utf-8"
        )


    # PASO 2: ELEGIR BARBERO
    if estado_actual == "eligiendo_servicio":
        lista_guardada = sesiones[num_telefono].get("lista_servicios", [])
        servicio_elegido = next((s for s in lista_guardada if s["id"] == msg), None)

        if servicio_elegido:
            sesiones[num_telefono]["servicio_nombre"] = servicio_elegido["nombre"]
            sesiones[num_telefono]["servicio_precio"] = servicio_elegido["precio"]
            sesiones[num_telefono]["estado"] = "eligiendo_barbero"

            res_text = f"Elegiste *{servicio_elegido['nombre']}*.\n\n¿Con quién te querés atender?\n\n1️⃣ Nacho\n2️⃣ Sebas\n\n👉 Respondé con 1 o 2.\n↩️ *0* para volver a empezar"
            response.message(res_text)
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )
        else:
            response.message("Por favor, elegí un número válido de la lista. 👆")
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )

    # PASO 3: ELEGIR SEMANA
    if estado_actual == "eligiendo_barbero":
        if msg in ["1", "2"]:
            sesiones[num_telefono]["barbero_id"] = msg
            sesiones[num_telefono]["barbero_nombre"] = (
                "Nacho" if msg == "1" else "Sebas"
            )
            sesiones[num_telefono]["estado"] = "eligiendo_semana"

            hoja_activa = horarios_b2 if msg == "2" else horarios_b1
            datos_horarios = hoja_activa.get_all_values()

            res_text = f"¡Perfecto! ¿Para cuándo buscás turno?\n\n1️⃣ Esta semana\n2️⃣ La próxima semana\n3️⃣ En 15 días\n4️⃣ En 3 semanas\n\n👉 Respondé con un número del 1 al 4.\n↩️ *0* para volver a empezar"
            response.message(res_text)
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )
        else:
            response.message("Por favor, respondé con 1 o 2. 👆")
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )

    # PASO 4: SELECCIÓN DE DÍA (Lectura dinámica sin importar en qué semana cae)
    if msg in ["1", "2", "3", "4"] and estado_actual == "eligiendo_semana":
        semana_elegida = int(msg)
        sesiones[num_telefono]["semana"] = semana_elegida
        sesiones[num_telefono]["estado"] = "eligiendo_dia"

        inicio_rango = (semana_elegida - 1) * 7
        fin_rango = semana_elegida * 7

        datos_agenda = agenda_sheet.get_all_values()
        dias_disponibles, mapa_dias, avisos_exc = [], {}, []
        
        # Referencia para calcular en qué bloque de Excel cae el día
        lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())

        for i in range(inicio_rango, fin_rango):
            fecha_dt = hoy_dt + datetime.timedelta(days=i)
            if fecha_dt.weekday() not in DIAS_LABORABLES:
                continue

            diff = (fecha_dt.date() - lun_act.date()).days
            idx_g = diff // 7
            
            # Si el cálculo se pasa de la Semana 5 (índice 4), ignoramos
            if idx_g > 4: 
                continue

            horas_fijas = obtener_horas_por_dia(
                datos_horarios, fecha_dt.weekday(), idx_g
            )
            if not horas_fijas:
                continue

            fecha_str = fecha_dt.strftime("%d/%m/%Y")
            nombre_dia = DIAS_SEMANA[fecha_dt.weekday()]
            horas_del_dia = horas_fijas.copy()

            if fecha_str in excepciones:
                exc = excepciones[fecha_str]
                m_txt = f" por {exc['motivo']}" if exc["motivo"] else ""
                if exc["tipo"] == "cerrado":
                    avisos_exc.append(
                        f"❌ {nombre_dia.capitalize()} {fecha_str}: Cerrado{m_txt}."
                    )
                    continue
                elif exc["tipo"] == "especial":
                    avisos_exc.append(
                        f"⚠️ {nombre_dia.capitalize()} {fecha_str}: Horario especial de {exc['horas']}{m_txt}."
                    )
                    if "-" in exc["horas"]:
                        p = exc["horas"].split("-")
                        if len(p) == 2:
                            ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                            horas_del_dia = [
                                h for h in horas_del_dia if ini <= h <= fin
                            ]

            ocupados = [
                f[1].strip().zfill(5)
                for f in datos_agenda
                if len(f) >= 7
                and f[0] == fecha_str
                and f[6] == sesiones[num_telefono]["barbero_nombre"]
            ]

            dia_visual = f"{nombre_dia.capitalize()} ({fecha_dt.strftime('%d/%m')})"

            if i == 0:
                h_fut = [
                    h
                    for h in horas_del_dia
                    if h not in ocupados
                    and datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time()
                ]
                if h_fut:
                    dias_disponibles.append(dia_visual)
                    mapa_dias[nombre_dia] = fecha_str
            else:
                if len(ocupados) < len(horas_del_dia):
                    dias_disponibles.append(dia_visual)
                    mapa_dias[nombre_dia] = fecha_str

        sesiones[num_telefono]["mapa_dias"] = mapa_dias
        if dias_disponibles:
            txt_d = (
                ", ".join(dias_disponibles[:-1]) + " o " + dias_disponibles[-1]
                if len(dias_disponibles) > 1
                else dias_disponibles[0]
            )
            res_text = f"Tenemos turnos para el {txt_d}."
            if avisos_exc:
                res_text += "\n\n" + "\n".join(avisos_exc)
            res_text += "\n\n👉 Elija día para ver horarios (ej: Lunes)\n↩️ *0* para volver a empezar"
        else:
            res_text = "No hay turnos disponibles para esta semana. 😭\n\n↩️ *0* para volver a empezar."
        response.message(res_text)
        return Response(
            content=str(response), media_type="application/xml; charset=utf-8"
        )

    # PASO 5: VER HORARIOS
    if estado_actual == "eligiendo_dia" and "cancelar" not in msg:
        mapa = sesiones[num_telefono].get("mapa_dias", {})
        dia_det = next((d for d in mapa.keys() if quitar_tildes(d) in msg_limpio), None)
        if dia_det:
            fecha_str = mapa[dia_det]
            (
                sesiones[num_telefono]["estado"],
                sesiones[num_telefono]["fecha_seleccionada"],
            ) = ("viendo_horarios", fecha_str)
            
            # Recalculamos el índice exacto para asegurarnos de leer el bloque correcto
            f_obj = datetime.datetime.strptime(fecha_str, "%d/%m/%Y")
            lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
            diff = (f_obj.date() - lun_act.date()).days
            idx_g = diff // 7
            
            h_dia = obtener_horas_por_dia(
                datos_horarios,
                f_obj.weekday(),
                idx_g,
            )

            if (
                fecha_str in excepciones
                and excepciones[fecha_str]["tipo"] == "especial"
            ):
                if "-" in excepciones[fecha_str]["horas"]:
                    p = excepciones[fecha_str]["horas"].split("-")
                    if len(p) == 2:
                        ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                        h_dia = [h for h in h_dia if ini <= h <= fin]

            ocupadas = [
                f[1].strip().zfill(5)
                for f in agenda_sheet.get_all_values()
                if len(f) >= 7
                and f[0] == fecha_str
                and f[6] == sesiones[num_telefono]["barbero_nombre"]
            ]
            dispo = [
                f"✅ {h}"
                for h in h_dia
                if h not in ocupadas
                and (
                    fecha_str != hoy_dt.strftime("%d/%m/%Y")
                    or datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time()
                )
            ]

            if dispo:
                res_text = (
                    f"Horarios para el {dia_det.capitalize()} ({fecha_str}):\n\n"
                    + "\n".join(dispo)
                )
                res_text += "\n\n👉 Decime hora y nombre (ej: *10 Nachito*)\n↩️ *0* para volver a empezar"
            else:
                res_text = "Día lleno. 😭\n\n↩️ *0* para volver a empezar"
            response.message(res_text)
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )
        else:
            dia_i = next(
                (d for d in DIAS_SEMANA if quitar_tildes(d) in msg_limpio), None
            )
            res_text = (
                f"El día *{dia_i.capitalize()}* no está disponible."
                if dia_i
                else "No entendí el día."
            )
            response.message(
                res_text + " Revisá la lista arriba. 👆\n↩️ *0* para volver a empezar"
            )
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )

    # PASO 6: RESERVAR
    if estado_actual == "viendo_horarios" and "cancelar" not in msg:
        h_des = extraer_hora(msg)

        if h_des:
            fecha_r = sesiones[num_telefono].get("fecha_seleccionada")
            f_obj = datetime.datetime.strptime(fecha_r, "%d/%m/%Y")
            
            lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
            diff = (f_obj.date() - lun_act.date()).days
            idx_g = diff // 7
            
            h_val = obtener_horas_por_dia(datos_horarios, f_obj.weekday(), idx_g)

            if fecha_r in excepciones and excepciones[fecha_r]["tipo"] == "especial":
                if "-" in excepciones[fecha_r]["horas"]:
                    p = excepciones[fecha_r]["horas"].split("-")
                    if len(p) == 2:
                        ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                        h_val = [h for h in h_val if ini <= h <= fin]

            ocupadas = [
                f[1].strip().zfill(5)
                for f in agenda_sheet.get_all_values()
                if len(f) >= 7
                and f[0] == fecha_r
                and f[6] == sesiones[num_telefono]["barbero_nombre"]
            ]

            if h_des in h_val and h_des not in ocupadas:

                msg_sin_hora = re.sub(
                    r"\d{1,2}(?:[:.]\d{2})?(?:\s*(?:hs|h|hrs|horas))?", "", msg
                )
                basura = [
                    "reservar",
                    "a",
                    "las",
                    "para",
                    "el",
                    "hoy",
                    "mañana",
                    "turno",
                ] + DIAS_SEMANA
                nom = " ".join(
                    [p for p in msg_sin_hora.split() if quitar_tildes(p) not in basura]
                ).title()
                if not nom:
                    nom = ProfileName if ProfileName else "Cliente"

                serv_nom = sesiones[num_telefono].get("servicio_nombre", "General")
                serv_precio = sesiones[num_telefono].get("servicio_precio", "0")
                barbero_nom = sesiones[num_telefono].get("barbero_nombre", "Barbero 1")
                precio_num = int(serv_precio) if serv_precio.isdigit() else 0

                agenda_sheet.append_row(
                    [
                        fecha_r,
                        h_des,
                        nom,
                        num_telefono,
                        serv_nom,
                        precio_num,
                        barbero_nom,
                    ],
                    value_input_option="USER_ENTERED",
                )

                # Tachamos en la grilla del barbero correcto permitiendo hasta la SEMANA 5
                try:
                    c_h = (f_obj.weekday() * 2) + 1
                    c_c = c_h + 1

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
                                and str(f_d[c_h - 1]).strip().zfill(5) == h_des
                            ):
                                f_o = n_f
                                break
                        if f_o:
                            hoja_activa.update_cell(f_o, c_c, nom)
                except Exception as e:
                    print(f"Error actualizando grilla de Reserva: {e}")

                sesiones[num_telefono]["estado"] = "inicio"
                response.message(
                    f"¡Listo {nom}! Turno confirmado para el {fecha_r} a las {h_des} con {barbero_nom}. ✂️\n\n⚠️ Recordá que tenemos 15 min de tolerancia."
                )
            else:
                response.message(
                    "Ese horario no está disponible o lo escribiste mal. Revisá la lista arriba e intentá de nuevo (ej: *10 Nachito*). 👆\n↩️ *0* para volver"
                )
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )
        else:
            response.message(
                "No entendí la hora. Por favor, escribila junto a tu nombre (ej: *10 Nachito* o *10:30 Nachito*).\n↩️ *0* para volver"
            )
            return Response(
                content=str(response), media_type="application/xml; charset=utf-8"
            )

    sesiones[num_telefono]["estado"] = "inicio"
    response.message(
        "¡Hola! 🤖 Bienvenido a IB Studio. \n Me llamo IBot y soy el esclavo de Nachito, por favor seguí mis instrucciones‼️. \n⚠️ Recordá que el turno tiene máximo 15 min de tolerancia.\n\n👉1️⃣ Para pedir turno \n👉2️⃣ Para cancelar turno"
    )
    return Response(content=str(response), media_type="application/xml; charset=utf-8")


@app.get("/")
async def root():
    return {"status": "Activo", "logic": "Content-Aware Columns"}