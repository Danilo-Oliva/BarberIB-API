# BarberIB-API

Backend desarrollado con **FastAPI** para la automatización de turnos de
barbería.

------------------------------------------------------------------------

## Funcionalidades

-   **FSM (Finite State Machine):** Motor de estados implementado para
    gestionar el flujo conversacional con los clientes.
-   **Dashboard en Google Sheets:** Integración con la API de Google
    Drive para procesar y almacenar turnos.
-   **Validación de Horarios:** Lógica programada para filtrar
    automáticamente horarios disponibles.
-   **Gestión de Agenda Extendida:** Soporte para reservas en la semana
    actual y la siguiente.
-   **Sistema de Cancelación:** Proceso automatizado para eliminar
    turnos tanto de la base de datos como del dashboard.

------------------------------------------------------------------------

## Stack Técnico

-   **Lenguaje:** Python 3.10+
-   **Framework:** FastAPI
-   **APIs:** Twilio Messaging API, Google Sheets API (gspread)
-   **Infraestructura:** Preparado para despliegue en Railway (Procfile
    incluido)

------------------------------------------------------------------------

## Requisitos Previos

1.  Tener una cuenta en Twilio con el Sandbox de WhatsApp configurado.
2.  Generar un archivo `creds.json` desde la Google Cloud Console con
    acceso a la Google Sheets API.
3.  Crear un archivo `.env` o configurar variables de entorno para las
    credenciales necesarias.

------------------------------------------------------------------------

## Instalación

### 1 Clonar el repositorio

``` bash
git clone https://github.com/Danilo-Oliva/BarberIB-API
cd BarberIB-API
```

### 2 Instalar dependencias

``` bash
pip install -r requirements.txt
```

### 3 Ejecutar el servidor localmente

``` bash
uvicorn main:app --reload
```

El servidor estará disponible en:

http://127.0.0.1:8000

Podés acceder a la documentación interactiva en:

http://127.0.0.1:8000/docs

------------------------------------------------------------------------

## Autor

Desarrollado por **Danilo Fausto Oliva**