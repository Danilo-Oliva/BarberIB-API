import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
import datetime
import pytz
import os
import json 

# --- CONFIGURACIÓN PARA LA NUBE (RAILWAY) ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Intentamos leer la variable de entorno GOOGLE_CREDS que pegaste en Railway
google_creds_json = os.environ.get("GOOGLE_CREDS")

if google_creds_json:
    # Si estamos en la nube, cargamos desde la variable de entorno
    creds_dict = json.loads(google_creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    # Si estás en tu PC local, sigue buscando el archivo creds.json
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)

client_sheets = gspread.authorize(creds)

app = FastAPI()

# --- ABRIR SHEETS UNA SOLA VEZ AL INICIO ---
archivo = client_sheets.open("Agenda_Barberia")
agenda_sheet = archivo.worksheet("Agenda")
horarios_sheet = archivo.worksheet("Horarios")
conf_sheet = archivo.worksheet("Configuracion")

# MÁQUINA DE ESTADOS
sesiones = {}

# ZONA HORARIA DE ARGENTINA
tz_arg = pytz.timezone('America/Argentina/Buenos_Aires')

# LISTAS DE CONFIGURACIÓN
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_LABORABLES = [0, 1, 2, 3, 4, 5, 6] 

def quitar_tildes(texto):
    return texto.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u')

# --- DETECCIÓN DINÁMICA ---
def obtener_horas_por_dia(datos_horarios, weekday, semana_index):
    """Escanea la columna específica. Si está vacía, devuelve lista vacía."""
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

def extraer_hora(partes):
    for p in partes:
        if ":" in p: return p.strip().zfill(5)
        elif p.isdigit():
            num = int(p)
            if 0 <= num <= 23: return f"{num:02d}:00"
    return None

@app.post("/whatsapp")
async def whatsapp(Body: str = Form(...), From: str = Form(...), ProfileName: str = Form(None)):
    # FORZAR HORA ARGENTINA
    hoy_dt = datetime.datetime.now(tz_arg) 
    
    msg = Body.lower().strip()
    msg_limpio = quitar_tildes(msg)
    partes = msg.split()
    response = MessagingResponse()
    num_telefono = From.replace("whatsapp:", "")
    
    # 1. Ignorar el mensaje de activación del sandbox
    if "join" in msg:
        return Response(content=str(MessagingResponse()), media_type="application/xml; charset=utf-8")
    
    # 2. Manejo de estado
    if num_telefono not in sesiones: 
        sesiones[num_telefono] = {"estado": "inicio"}
    estado_actual = sesiones[num_telefono]["estado"]

    # 3. Print de debug seguro (se verá en los logs de Railway)
    print(f"DEBUG: Tel: {num_telefono} | Msg: {msg} | Estado: {estado_actual}")

    # OBTENER DATOS FRESCOS EN CADA MENSAJE
    datos_horarios = horarios_sheet.get_all_values()
    
    # --- CARGA DE EXCEPCIONES ---
    datos_conf = conf_sheet.get_all_values()
    excepciones = {}
    for fila in datos_conf[1:]: 
        if len(fila) >= 2 and fila[0].strip():
            fecha_exc = fila[0].strip()
            tipo_exc = fila[1].strip().lower()
            if tipo_exc in ["cerrado", "especial"]:
                excepciones[fecha_exc] = {"tipo": tipo_exc, "horas": fila[2].strip() if len(fila) > 2 else "", "motivo": fila[3].strip() if len(fila) > 3 else ""}

    # --- FLUJO DE MENÚ ---
    
    if msg == "2" and estado_actual in ["eligiendo_dia", "viendo_horarios"]:
        estado_actual = "inicio"
        msg = "1" 
        
    if msg == "1" and estado_actual == "viendo_horarios":
        estado_actual = "eligiendo_semana"
        msg = str(sesiones[num_telefono].get("semana", 1)) 
        
    if msg == "1" and estado_actual == "inicio":
        sesiones[num_telefono]["estado"] = "eligiendo_semana"
        res_text = "Tenemos turnos para esta semana y la siguiente. ¿Cuál te gustaría ver?\n\n1️⃣ Esta semana\n2️⃣ La próxima semana"
        response.message(res_text)
        return Response(content=str(response), media_type="application/xml; charset=utf-8")
    
    # PASO 2: SELECCIÓN DE DÍA
    if msg in ["1", "2"] and estado_actual == "eligiendo_semana":
        semana_elegida = int(msg)
        sesiones[num_telefono]["semana"] = semana_elegida
        sesiones[num_telefono]["estado"] = "eligiendo_dia"

        inicio_rango, fin_rango = (0, 7) if semana_elegida == 1 else (7, 14)
        datos_agenda = agenda_sheet.get_all_values()
        dias_disponibles, mapa_dias, avisos_exc = [], {}, [] 
        idx_sem_grilla = 0 if semana_elegida == 1 else 1

        for i in range(inicio_rango, fin_rango):
            fecha_dt = hoy_dt + datetime.timedelta(days=i)
            if fecha_dt.weekday() not in DIAS_LABORABLES: continue

            horas_fijas = obtener_horas_por_dia(datos_horarios, fecha_dt.weekday(), idx_sem_grilla)
            if not horas_fijas: continue 

            fecha_str = fecha_dt.strftime("%d/%m/%Y")
            nombre_dia = DIAS_SEMANA[fecha_dt.weekday()]
            horas_del_dia = horas_fijas.copy()

            if fecha_str in excepciones:
                exc = excepciones[fecha_str]
                m_txt = f" por {exc['motivo']}" if exc['motivo'] else ""
                if exc["tipo"] == "cerrado":
                    avisos_exc.append(f"❌ {nombre_dia.capitalize()} {fecha_str}: Cerrado{m_txt}.")
                    continue 
                elif exc["tipo"] == "especial":
                    avisos_exc.append(f"⚠️ {nombre_dia.capitalize()} {fecha_str}: Horario especial de {exc['horas']}{m_txt}.")
                    if "-" in exc["horas"]:
                        p = exc["horas"].split("-")
                        if len(p) == 2:
                            ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                            horas_del_dia = [h for h in horas_del_dia if ini <= h <= fin]

            ocupados = [f[1].strip().zfill(5) for f in datos_agenda if len(f) >= 2 and f[0] == fecha_str]
            if i == 0:
                h_fut = [h for h in horas_del_dia if h not in ocupados and datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time()]
                if h_fut:
                    dias_disponibles.append(nombre_dia.capitalize())
                    mapa_dias[nombre_dia] = fecha_str
            else:
                if len(ocupados) < len(horas_del_dia):
                    dias_disponibles.append(nombre_dia.capitalize())
                    mapa_dias[nombre_dia] = fecha_str

        sesiones[num_telefono]["mapa_dias"] = mapa_dias
        if dias_disponibles:
            txt_d = ", ".join(dias_disponibles[:-1]) + " o " + dias_disponibles[-1] if len(dias_disponibles) > 1 else dias_disponibles[0]
            res_text = f"Tenemos turnos para el {txt_d}."
            if avisos_exc: res_text += "\n\n" + "\n".join(avisos_exc)
            res_text += "\n\n👉 Elija día para ver horarios (ej: Lunes)\n↩️ *2* para volver"
        else:
            res_text = "No hay turnos disponibles. 😭\n\n↩️ *2* para volver."
        response.message(res_text)
        return Response(content=str(response), media_type="application/xml; charset=utf-8")
    
    # PASO 3: VER HORARIOS
    if estado_actual == "eligiendo_dia" and "cancelar" not in msg:
        mapa = sesiones[num_telefono].get("mapa_dias", {})
        dia_det = next((d for d in mapa.keys() if quitar_tildes(d) in msg_limpio), None)
        if dia_det:
            fecha_str = mapa[dia_det]
            sesiones[num_telefono]["estado"], sesiones[num_telefono]["fecha_seleccionada"] = "viendo_horarios", fecha_str 
            idx_s = 0 if sesiones[num_telefono].get("semana", 1) == 1 else 1
            h_dia = obtener_horas_por_dia(datos_horarios, datetime.datetime.strptime(fecha_str, "%d/%m/%Y").weekday(), idx_s)
            
            if fecha_str in excepciones and excepciones[fecha_str]["tipo"] == "especial":
                if "-" in excepciones[fecha_str]["horas"]:
                    p = excepciones[fecha_str]["horas"].split("-")
                    if len(p) == 2:
                        ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                        h_dia = [h for h in h_dia if ini <= h <= fin]

            ocupadas = [f[1].strip().zfill(5) for f in agenda_sheet.get_all_values() if len(f) >= 2 and f[0] == fecha_str]
            dispo = [f"✅ {h}" for h in h_dia if h not in ocupadas and (fecha_str != hoy_dt.strftime("%d/%m/%Y") or datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time())]

            if dispo:
                res_text = f"Horarios para el {dia_det.capitalize()} ({fecha_str}):\n\n" + "\n".join(dispo)
                res_text += "\n\n👉 Decime hora y nombre (ej: *10 Danilo*)\n↩️ *1* para volver"
            else:
                res_text = "Día lleno. 😭\n\n↩️ *1* para volver"
            response.message(res_text)
            return Response(content=str(response), media_type="application/xml; charset=utf-8")
        else:
            dia_i = next((d for d in DIAS_SEMANA if quitar_tildes(d) in msg_limpio), None)
            res_text = f"El día *{dia_i.capitalize()}* no está disponible." if dia_i else "No entendí el día."
            response.message(res_text + " Revisá la lista arriba. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # PASO 4: RESERVAR
    if estado_actual == "viendo_horarios" and "cancelar" not in msg:
        h_des = extraer_hora(partes)
        if h_des:
            fecha_r = sesiones[num_telefono].get("fecha_seleccionada")
            f_obj = datetime.datetime.strptime(fecha_r, "%d/%m/%Y")
            idx_s = 0 if sesiones[num_telefono].get("semana", 1) == 1 else 1
            h_val = obtener_horas_por_dia(datos_horarios, f_obj.weekday(), idx_s)
            
            if fecha_r in excepciones and excepciones[fecha_r]["tipo"] == "especial":
                if "-" in excepciones[fecha_r]["horas"]:
                    p = excepciones[fecha_r]["horas"].split("-")
                    if len(p) == 2:
                        ini, fin = p[0].strip().zfill(5), p[1].strip().zfill(5)
                        h_val = [h for h in h_val if ini <= h <= fin]

            ocupadas = [f[1].strip().zfill(5) for f in agenda_sheet.get_all_values() if len(f) >= 2 and f[0] == fecha_r]

            if h_des in h_val and h_des not in ocupadas:
                basura = ["reservar", "a", "las", "para", "el", "hoy", "mañana", "turno"] + DIAS_SEMANA
                nom = " ".join([p for p in partes if not (p.isdigit() or ":" in p) and quitar_tildes(p) not in basura]).title()
                if not nom: nom = ProfileName if ProfileName else "Cliente"
                agenda_sheet.append_row([fecha_r, h_des, nom, num_telefono])
                
                try:
                    c_h = (f_obj.weekday() * 2) + 1 
                    c_c = c_h + 1
                    lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                    diff = (f_obj.date() - lun_act.date()).days
                    idx_g = 0 if 0 <= diff <= 6 else 1 if 7 <= diff <= 13 else -1
                    if idx_g != -1:
                        f_o, b_t = None, -1
                        for n_f, f_d in enumerate(datos_horarios, start=1):
                            if "hora" in " ".join([str(c).lower() for c in f_d]) and "estado" in " ".join([str(c).lower() for c in f_d]):
                                b_t += 1
                                continue
                            if b_t == idx_g and len(f_d) > (c_h-1) and str(f_d[c_h-1]).strip().zfill(5) == h_des:
                                f_o = n_f
                                break
                        if f_o: horarios_sheet.update_cell(f_o, c_c, nom)
                except Exception as e: 
                    print(f"Error actualizando celda de Reserva: {e}")
                    
                sesiones[num_telefono]["estado"] = "inicio"
                response.message(f"¡Listo {nom}! Turno para el {fecha_r} a las {h_des}. ✂️")
            else:
                response.message("Horario no disponible. 👆")
            return Response(content=str(response), media_type="application/xml; charset=utf-8")

    # CANCELAR
    if "cancelar" in msg:
        h_c = extraer_hora(partes)
        if h_c:
            datos_a = agenda_sheet.get_all_values()
            f_o, f_c = None, None
            for i, f in enumerate(datos_a):
                if len(f) >= 4 and f[3] == num_telefono and f[1].strip().zfill(5) == h_c:
                    f_o, f_c = i + 1, f[0]
                    break
            if f_o:
                agenda_sheet.delete_rows(f_o)
                try:
                    f_obj = datetime.datetime.strptime(f_c, "%d/%m/%Y")
                    c_h = (f_obj.weekday() * 2) + 1
                    c_c = c_h + 1
                    lun_act = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                    idx_g = 0 if 0 <= (f_obj.date() - lun_act.date()).days <= 6 else 1
                    f_o_g, b_t = None, -1
                    for n_f, f_d in enumerate(datos_horarios, start=1):
                        if "hora" in " ".join([str(c).lower() for c in f_d]):
                            b_t += 1
                            continue
                        if b_t == idx_g and len(f_d) > (c_h-1) and str(f_d[c_h-1]).strip().zfill(5) == h_c:
                            f_o_g = n_f
                            break
                    if f_o_g: horarios_sheet.update_cell(f_o_g, c_c, "") 
                except Exception as e: 
                    print(f"Error actualizando celda de Cancelación: {e}")
                    
                sesiones[num_telefono]["estado"] = "inicio"
                response.message(f"Turno cancelado. 🤝")
            else:
                response.message(f"No encontré el turno.")
        else:
            response.message("Usá: *Cancelar 8*")
        return Response(content=str(response), media_type="application/xml; charset=utf-8")

    sesiones[num_telefono]["estado"] = "inicio"
    response.message("¡Hola! 🤖\n\n👉 *1* - Ver turnos disponibles")
    return Response(content=str(response), media_type="application/xml; charset=utf-8")

@app.get("/")
async def root(): return {"status": "Activo", "logic": "Content-Aware Columns"}