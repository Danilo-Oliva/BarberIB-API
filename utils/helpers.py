import re
from datetime import datetime, timedelta

def obtener_sesion(sesiones: dict, num_telefono: str) -> dict:
    """
    Devuelve la sesión del usuario de forma segura.
    Si no existe o está corrupta (sin clave 'estado'), la reinicia.
    Esto protege contra reinicios del servidor que borran la RAM.
    """
    sesion = sesiones.get(num_telefono)
    if not isinstance(sesion, dict) or "estado" not in sesion:
        sesiones[num_telefono] = {"estado": "inicio"}
    return sesiones[num_telefono]

# Fix 7: Rate limiting simple en memoria
# Estructura: { num_telefono: [timestamp1, timestamp2, ...] }
_rate_limit_log: dict = {}
RATE_LIMIT_MAX_MSGS = 10      # máximo de mensajes permitidos
RATE_LIMIT_VENTANA_SEG = 60   # en la ventana de N segundos

def verificar_rate_limit(num_telefono: str) -> bool:
    """
    Devuelve True si el usuario está dentro del límite permitido.
    Devuelve False si superó el límite (debe bloquearse el mensaje).
    """
    ahora = datetime.now()
    ventana = timedelta(seconds=RATE_LIMIT_VENTANA_SEG)
    historial = _rate_limit_log.get(num_telefono, [])

    # Filtramos solo los mensajes dentro de la ventana activa
    historial = [t for t in historial if ahora - t < ventana]
    historial.append(ahora)
    _rate_limit_log[num_telefono] = historial

    return len(historial) <= RATE_LIMIT_MAX_MSGS

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

def obtener_inicio_semana_reservas(hoy):
    # .weekday() en Python: 0=Lunes, 6=Domingo
    if hoy.weekday() == 6: 
        # Si es domingo, el 'inicio' para el bot es el lunes que viene
        inicio = hoy + timedelta(days=1)
    else:
        # Si no, es el lunes de esta semana
        inicio = hoy - timedelta(days=hoy.weekday())
    
    return inicio.replace(hour=0, minute=0, second=0, microsecond=0)