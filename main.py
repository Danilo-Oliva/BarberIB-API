import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
import datetime
import dateparser

# --- CONFIGURACIÓN ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client_sheets = gspread.authorize(creds)

app = FastAPI()

# MÁQUINA DE ESTADOS: Memoria del bot
sesiones = {}

# LISTAS DE CONFIGURACIÓN
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_LABORABLES = [0, 1, 2, 3, 4, 5] 

def quitar_tildes(texto):
    return texto.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u')

def obtener_horas_validas(sheet):
    """Extrae las horas de la Columna A y elimina duplicados"""
    valores = sheet.col_values(1)
    horas = [h.strip().zfill(5) for h in valores if ":" in h]
    return list(dict.fromkeys(horas)) # Devuelve lista sin duplicados manteniendo el orden

@app.post("/whatsapp")
async def whatsapp(Body: str = Form(...), From: str = Form(...)):
    msg = Body.lower().strip()
    msg_limpio = quitar_tildes(msg)
    
    partes = msg.split()
    response = MessagingResponse()
    num_telefono = From.replace("whatsapp:", "")

    if num_telefono not in sesiones:
        sesiones[num_telefono] = {"estado": "inicio"}

    estado_actual = sesiones[num_telefono]["estado"]

    archivo = client_sheets.open("Agenda_Barberia")
    agenda_sheet = archivo.worksheet("Agenda")
    horarios_sheet = archivo.worksheet("Horarios")
    conf_sheet = archivo.worksheet("Configuracion")

    # 1. Verificación de estado (Abierto/Cerrado)
    estado_barberia = conf_sheet.acell('A2').value
    estado_local = (estado_barberia or "").strip().lower()

    if estado_local == "cerrado":
        notas = conf_sheet.acell('B2').value
        response.message(f"Lo siento, hoy estamos cerrados. \nMotivo: {notas}")
        return Response(content=str(response), media_type="application/xml")


    # --- INICIO DEL FLUJO DE MENÚ INTERACTIVO ---

    if msg == "2" and estado_actual in ["eligiendo_dia", "viendo_horarios"]:
        estado_actual = "inicio"
        msg = "1" 

    if msg == "1" and estado_actual == "viendo_horarios":
        estado_actual = "eligiendo_semana"
        msg = str(sesiones[num_telefono].get("semana", 1)) 

    # PASO 1: Menú Inicial -> Elegir Semana
    if msg == "1" and estado_actual == "inicio":
        sesiones[num_telefono]["estado"] = "eligiendo_semana"
        res_text = "Tenemos turnos para esta semana y la siguiente. ¿Cuál te gustaría ver?\n\nEsta semana\n La próxima semana"
        response.message(res_text)
        return Response(content=str(response), media_type="application/xml")

    # PASO 2: Entró 1 o 2 -> Mostrar Días
    if msg in ["1", "2"] and estado_actual == "eligiendo_semana":
        semana_elegida = int(msg)
        sesiones[num_telefono]["semana"] = semana_elegida
        sesiones[num_telefono]["estado"] = "eligiendo_dia"

        hoy = datetime.datetime.now()
        inicio_rango = 0 if semana_elegida == 1 else 7
        fin_rango = 7 if semana_elegida == 1 else 14

        horas_fijas = obtener_horas_validas(horarios_sheet)
        datos_agenda = agenda_sheet.get_all_values()

        dias_disponibles = []
        mapa_dias = {}

        for i in range(inicio_rango, fin_rango):
            fecha_dt = hoy + datetime.timedelta(days=i)
            
            if fecha_dt.weekday() not in DIAS_LABORABLES:
                continue

            fecha_str = fecha_dt.strftime("%d/%m/%Y")
            nombre_dia = DIAS_SEMANA[fecha_dt.weekday()]

            # PROTECCIÓN: Verificamos que len(f) >= 2 para evitar IndexErrors con filas vacías
            ocupados = [f[1].strip().zfill(5) for f in datos_agenda if len(f) >= 2 and f[0] == fecha_str]

            if i == 0:
                horas_futuras = 0
                for h in horas_fijas:
                    if h not in ocupados:
                        try:
                            if datetime.datetime.strptime(h, "%H:%M").time() > hoy.time():
                                horas_futuras += 1
                        except: pass
                
                if horas_futuras > 0:
                    dias_disponibles.append(nombre_dia.capitalize())
                    mapa_dias[nombre_dia] = fecha_str
            else:
                if len(ocupados) < len(horas_fijas):
                    dias_disponibles.append(nombre_dia.capitalize())
                    mapa_dias[nombre_dia] = fecha_str

        sesiones[num_telefono]["mapa_dias"] = mapa_dias

        if dias_disponibles:
            texto_dias = ", ".join(dias_disponibles[:-1]) + " o " + dias_disponibles[-1] if len(dias_disponibles) > 1 else dias_disponibles[0]
            res_text = f"Tenemos turnos para el {texto_dias}.\n\n Elija día para ver horarios (ej: Lunes)\ *2* para volver a seleccionar semana"
        else:
            res_text = "Lo siento, esa semana ya está completamente llena o los turnos de hoy ya pasaron. \n\n *2* para volver a seleccionar semana."

        response.message(res_text)
        return Response(content=str(response), media_type="application/xml")

    # PASO 3: Escribió un día -> Mostrar Horarios Libres
    if estado_actual == "eligiendo_dia":
        mapa = sesiones[num_telefono].get("mapa_dias", {})
        
        dia_detectado = next((d for d in mapa.keys() if quitar_tildes(d) in msg_limpio), None)

        if dia_detectado:
            fecha_str = mapa[dia_detectado]
            sesiones[num_telefono]["estado"] = "viendo_horarios"
            sesiones[num_telefono]["fecha_seleccionada"] = fecha_str 

            horas_fijas = obtener_horas_validas(horarios_sheet)
            datos_agenda = agenda_sheet.get_all_values()
            
            # PROTECCIÓN contra filas vacías
            horas_ocupadas = [fila[1].strip().zfill(5) for fila in datos_agenda if len(fila) >= 2 and fila[0] == fecha_str]

            hoy_dt = datetime.datetime.now()
            es_hoy = (fecha_str == hoy_dt.strftime("%d/%m/%Y"))

            disponibles = []
            for h in horas_fijas:
                if h not in horas_ocupadas:
                    if es_hoy:
                        try:
                            if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time():
                                disponibles.append(f" {h}")
                        except: pass
                    else:
                        disponibles.append(f" {h}")

            if disponibles:
                res_text = f"Horarios libres para el {dia_detectado.capitalize()} ({fecha_str}):\n\n" + "\n".join(disponibles)
                res_text += "\n\n👉 Para reservar, decime la hora y tu nombre:\nEjemplo: *10:00 Danilo*\n\n *1* para volver a seleccionar día\n *2* para seleccionar semana"
            else:
                res_text = f"El {dia_detectado.capitalize()} ya no tiene horarios disponibles. \n\n *1* para seleccionar otro día"

            response.message(res_text)
            return Response(content=str(response), media_type="application/xml")

    # PASO 4: Está viendo horarios y reserva DIRECTAMENTE
    # Evitamos que entre acá si el cliente escribió "cancelar"
    if estado_actual == "viendo_horarios" and "cancelar" not in msg:
        hora_deseada = next((p.strip().zfill(5) for p in partes if ":" in p), None)
        
        if hora_deseada:
            fecha_reserva = sesiones[num_telefono].get("fecha_seleccionada")
            horas_fijas = obtener_horas_validas(horarios_sheet)
            datos_agenda = agenda_sheet.get_all_values()
            
            # PROTECCIÓN contra filas vacías
            horas_ocupadas_ese_dia = [fila[1].strip().zfill(5) for fila in datos_agenda if len(fila) >= 2 and fila[0] == fecha_reserva]

            if hora_deseada in horas_fijas and hora_deseada not in horas_ocupadas_ese_dia:
                hoy_dt = datetime.datetime.now()
                es_hoy = (fecha_reserva == hoy_dt.strftime("%d/%m/%Y"))
                hora_valida = True
                
                if es_hoy:
                    try:
                        if datetime.datetime.strptime(hora_deseada, "%H:%M").time() <= hoy_dt.time():
                            hora_valida = False
                    except: pass
                
                if hora_valida:
                    basura = ["reservar", "a", "las", "para", "el", "hoy", "mañana", hora_deseada] + DIAS_SEMANA
                    nombre_limpio = " ".join([p for p in partes if quitar_tildes(p) not in basura and ":" not in p]).title()
                    if not nombre_limpio: nombre_limpio = "Cliente"

                    agenda_sheet.append_row([fecha_reserva, hora_deseada, nombre_limpio, num_telefono])
                    
                    try:
                        fecha_obj = datetime.datetime.strptime(fecha_reserva, "%d/%m/%Y")
                        lunes_actual = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                        diferencia_dias = (fecha_obj.date() - lunes_actual.date()).days
                        
                        indice_semana = 0 if 0 <= diferencia_dias <= 6 else 1 if 7 <= diferencia_dias <= 13 else -1
                        
                        if indice_semana != -1:
                            columna_cliente = (fecha_obj.weekday() * 2) + 2
                            celdas_hora = horarios_sheet.findall(hora_deseada, in_column=1)
                            
                            if len(celdas_hora) > indice_semana:
                                fila_objetivo = celdas_hora[indice_semana].row
                                horarios_sheet.update_cell(fila_objetivo, columna_cliente, nombre_limpio)
                    except Exception as e:
                        print(f"Error actualizando grilla visual: {e}")
                    
                    sesiones[num_telefono]["estado"] = "inicio"
                    response.message(f"¡Listo {nombre_limpio}! Turno confirmado para el {fecha_reserva} a las {hora_deseada}. ✂️")
                else:
                    response.message(f"El horario {hora_deseada} ya pasó. Elegí una hora futura de la lista. ")
            else:
                response.message(f"El horario {hora_deseada} no está disponible. Revisá la lista de arriba. ")
            
            return Response(content=str(response), media_type="application/xml")

    # LÓGICA DE CANCELACIÓN (Con borrado en la Grilla 2D)
    if "cancelar" in msg:
        hora_a_cancelar = next((p.strip().zfill(5) for p in partes if ":" in p), None)
        if hora_a_cancelar:
            datos_agenda = agenda_sheet.get_all_values()
            fila_objetivo = None
            for i, fila in enumerate(datos_agenda):
                # MEGA PROTECCIÓN: Aseguramos que la fila tenga al menos 4 columnas de datos
                if len(fila) >= 4 and fila[3] == num_telefono and fila[1].strip().zfill(5) == hora_a_cancelar:
                    fila_objetivo = i + 1
                    fecha_cancelada = fila[0]
                    break
            
            if fila_objetivo:
                agenda_sheet.delete_rows(fila_objetivo)
                
                try:
                    fecha_obj = datetime.datetime.strptime(fecha_cancelada, "%d/%m/%Y")
                    hoy_dt = datetime.datetime.now()
                    lunes_actual = hoy_dt - datetime.timedelta(days=hoy_dt.weekday())
                    diferencia_dias = (fecha_obj.date() - lunes_actual.date()).days
                    
                    indice_semana = 0 if 0 <= diferencia_dias <= 6 else 1 if 7 <= diferencia_dias <= 13 else -1
                    
                    if indice_semana != -1:
                        columna_cliente = (fecha_obj.weekday() * 2) + 2
                        celdas_hora = horarios_sheet.findall(hora_a_cancelar, in_column=1)
                        if len(celdas_hora) > indice_semana:
                            fila_obj_grilla = celdas_hora[indice_semana].row
                            horarios_sheet.update_cell(fila_obj_grilla, columna_cliente, "") 
                except: pass
                
                sesiones[num_telefono]["estado"] = "inicio"
                response.message(f"Turno del {fecha_cancelada} a las {hora_a_cancelar} cancelado.")
            else:
                response.message(f"No encontré un turno a tu nombre a las {hora_a_cancelar}.")
        else:
            response.message("Usá: *Cancelar 08:00*")
        return Response(content=str(response), media_type="application/xml")

    # SI CAE ACÁ, se reinicia al inicio.
    sesiones[num_telefono]["estado"] = "inicio"
    response.message("¡Hola! ¿Cómo estás? \n\n *1* - Ver turnos disponibles")
    
    return Response(content=str(response), media_type="application/xml")

@app.get("/")
async def root():
    return {"status": "Servidor de Barbería Activo", "modo": "Mapeo de Matriz 2D Activo"}