import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import whatsapp
from services.graficos import motor_invisible

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(motor_invisible())
    yield

# Le pasamos el lifespan a la aplicación al crearla
app = FastAPI(lifespan=lifespan)

os.makedirs("static", exist_ok=True) 
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(whatsapp.router)

@app.get("/")
async def root():
    return {"status": "Activo", "logic": "Arquitectura Modular"}