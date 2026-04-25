import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pytz

# --- ZONA HORARIA GLOBAL ---
tz_arg = pytz.timezone("America/Argentina/Buenos_Aires")

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

# --- ABRIR SHEETS UNA SOLA VEZ AL INICIO ---
archivo = client_sheets.open("Agenda_Barberia")
agenda_sheet = archivo.worksheet("Agenda")
horarios_b1 = archivo.worksheet("Nacho")
horarios_b2 = archivo.worksheet("Sebas")
servicios_sheet = archivo.worksheet("Servicios")
conf_sheet = archivo.worksheet("Configuracion")
catalogo_sheet = archivo.worksheet("Catalogo")
deudores_sheet = archivo.worksheet("Deudores")

# --- CONSTANTES GLOBALES ---
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_LABORABLES = [0, 1, 2, 3, 4, 5, 6]

# --- VARIABLES EN MEMORIA ---
# (Las sesiones de usuario viven acá para que todos los archivos puedan acceder)
sesiones = {}