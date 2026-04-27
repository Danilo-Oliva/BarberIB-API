import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import datetime
import asyncio
from utils.helpers import obtener_inicio_semana_reservas
from core.config import agenda_sheet, horarios_b1, horarios_b2, conf_sheet, tz_arg, DIAS_SEMANA, DIAS_LABORABLES
from utils.helpers import obtener_horas_por_dia

def generar_foto_semana(barbero_id, semana_elegida, barbero_nom, datos_horarios, datos_agenda, excepciones):
    hoy_dt = datetime.datetime.now(tz_arg)
    lun_act = obtener_inicio_semana_reservas(hoy_dt)
    inicio_rango = (semana_elegida - 1) * 7
    fin_rango = semana_elegida * 7
    
    matriz_semana = {}
    horas_totales_semana = set()
    
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
            if exc["tipo"] == "cerrado":
                matriz_semana[nombre_dia.capitalize()] = "CERRADO"
                continue
            elif exc["tipo"] == "especial" and "-" in exc["horas"]:
                ini, fin = exc["horas"].split("-")[0].strip().zfill(5), exc["horas"].split("-")[1].strip().zfill(5)
                horas_del_dia = [h for h in horas_del_dia if ini <= h <= fin]
                
        ocupados = [f[1].strip().zfill(5) for f in datos_agenda if len(f) >= 7 and f[0] == fecha_str and f[6] == barbero_nom]
        
        horas_disp_reales = []
        for h in horas_del_dia:
            if h not in ocupados:
                if fecha_dt.date() == hoy_dt.date():
                    if datetime.datetime.strptime(h, "%H:%M").time() > hoy_dt.time():
                        horas_disp_reales.append(h)
                else:
                    horas_disp_reales.append(h)
                    
        estado_horas_dia = {}
        for h in horas_del_dia:
            horas_totales_semana.add(h)
            if h in horas_disp_reales: estado_horas_dia[h] = "Libre"
            else: estado_horas_dia[h] = "Ocupado"
                
        matriz_semana[nombre_dia.capitalize()] = estado_horas_dia
        
    if not horas_totales_semana:
        print(f"ℹ️ FOTO: Sin horarios para barbero_id={barbero_id} sem={semana_elegida}. No se genera imagen.")
        return None
    
    lista_horas = sorted(list(horas_totales_semana))
    data = {"Hora": lista_horas}
    
    for dia_nom, estados in matriz_semana.items():
        col_data = []
        if estados == "CERRADO":
            col_data = ["Cerrado"] * len(lista_horas)
        else:
            for h in lista_horas:
                col_data.append(estados.get(h, "---"))
        data[dia_nom] = col_data
        
    df = pd.DataFrame(data)
    ancho_fig = max(4, len(df.columns) * 0.9)
    alto_fig = max(2, len(df) * 0.3)
    fig, ax = plt.subplots(figsize=(ancho_fig, alto_fig))
    ax.axis("off")
    
    tabla = ax.table(cellText=df.values, colLabels=df.columns, loc="center", cellLoc="center")
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(10)
    tabla.scale(1, 1.5)
    
    for (row, col), cell in tabla.get_celld().items():
        if row == 0:
            cell.set_facecolor("#343a40"); cell.set_text_props(color="white", fontweight="bold")
        else:
            val = df.values[row - 1][col]
            if val == "Libre": cell.set_facecolor("#28a745"); cell.set_text_props(color="white")
            elif val == "Ocupado": cell.set_facecolor("#6c757d"); cell.set_text_props(color="white")
            elif val == "Cerrado": cell.set_facecolor("#dc3545"); cell.set_text_props(color="white")
            elif val == "---": cell.set_facecolor("#e9ecef"); cell.set_text_props(color="black")
            
    # El archivo ahora se guarda con el ID del barbero y el N° de semana
    ruta_imagen = f"static/agenda_{barbero_id}_sem{semana_elegida}.png"
    plt.savefig(ruta_imagen, bbox_inches="tight", dpi=150, transparent=False)
    plt.close(fig)
    return True

async def motor_invisible():
    """Se ejecuta cada 15 min para tener todo pre-dibujado"""
    while True:
        try:
            print("👨‍🍳 MOTORCITO LABUBU DE PAUL: Dibujando todas las agendas de la vitrina...")
            datos_agenda = agenda_sheet.get_all_values()
            datos_b1 = horarios_b1.get_all_values()
            datos_b2 = horarios_b2.get_all_values()
            datos_conf = conf_sheet.get_all_values()
            
            excepciones = {}
            for fila in datos_conf[1:]:
                if len(fila) >= 2 and fila[0].strip():
                    excepciones[fila[0].strip()] = { "tipo": fila[1].strip().lower(), "horas": fila[2].strip() if len(fila) > 2 else "" }
            
            # Dibujamos las 4 semanas de Nacho y las 4 de Sebas (8 fotos en total)
            fotos_vacias = []
            for semana in range(1, 5):
                resultado_nacho = generar_foto_semana("1", semana, "Nacho", datos_b1, datos_agenda, excepciones)
                resultado_sebas = generar_foto_semana("2", semana, "Sebas", datos_b2, datos_agenda, excepciones)
                # Fix 8: generar_foto_semana devuelve None si no hay horas — lo registramos
                if resultado_nacho is None:
                    fotos_vacias.append(f"Nacho Sem{semana}")
                if resultado_sebas is None:
                    fotos_vacias.append(f"Sebas Sem{semana}")

            if fotos_vacias:
                print(f"⚠️ MOTOR: Las siguientes fotos quedaron vacías (sin horarios cargados): {', '.join(fotos_vacias)}")
            else:
                print("👨‍🍳 MOTOR: ¡Las 8 fotos están listas!")
        except Exception as e:
            print(f"Error en el motor de fotos: {e}")
            
        await asyncio.sleep(900) # Duerme 15 minutos exactos

def tocar_timbre(barbero_id, semana_elegida, barbero_nom):
    """Fuerza la actualización de UNA sola foto al instante"""
    try:
        print(f"🔔 TIMBRE: Alguien sacó turno. Actualizando foto de {barbero_nom} Sem {semana_elegida}...")
        datos_agenda = agenda_sheet.get_all_values()
        datos_horarios = horarios_b2.get_all_values() if barbero_id == "2" else horarios_b1.get_all_values()
        
        datos_conf = conf_sheet.get_all_values()
        excepciones = {}
        for fila in datos_conf[1:]:
            if len(fila) >= 2 and fila[0].strip():
                excepciones[fila[0].strip()] = { "tipo": fila[1].strip().lower(), "horas": fila[2].strip() if len(fila) > 2 else "" }
                
        generar_foto_semana(barbero_id, semana_elegida, barbero_nom, datos_horarios, datos_agenda, excepciones)
    except Exception as e:
        print(f"Error tocando el timbre: {e}")