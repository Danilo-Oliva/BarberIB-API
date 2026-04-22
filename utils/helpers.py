import re

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
    tel_solo_numeros = re.sub(r"\D", "", telefono)
    return tel_solo_numeros[-10:] if len(tel_solo_numeros) >= 10 else tel_solo_numeros