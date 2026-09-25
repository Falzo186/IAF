"""Configuración centralizada de la plataforma analítica Bike Stores.

Todas las rutas se resuelven respecto a este archivo, de modo que los scripts
funcionan sin importar desde qué directorio se ejecuten.
"""

import os
from pathlib import Path

# --- Rutas -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "bike_stores"
DB_PATH = BASE_DIR / "bikestores.db"

# --- LLM local (Ollama) ------------------------------------------------------
# 127.0.0.1 y no "localhost": en Windows, "localhost" prueba primero IPv6 (::1) y, como Ollama
# solo escucha en IPv4, cada conexión nueva esperaba ~2 s antes de caer a 127.0.0.1 (medido).
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = "qwen2.5:1.5b"
SUPPORTED_MODELS = ["qwen2.5:1.5b", "llama3.2:1b", "deepseek-r1:1.5b"]

# Tiempo que Ollama mantiene el modelo en RAM tras la última petición (su valor por defecto,
# 5 min, lo descargaba si el presentador hablaba un rato entre preguntas).
KEEP_ALIVE = "60m"

# Las consultas verificadas responden con la frase determinística de analytics.insight
# (instantánea). Con True, además redacta la respuesta el LLM (p50 medida: 11 s en CPU con
# qwen2.5:1.5b; ver fase4.md). En el Asistente se puede activar con "Redacción con IA".
VERIFIED_SYNTHESIS = False

# Modo sin IA: lo activa bootstrap.py (--sin-ia o Ollama no disponible). El dashboard y las
# consultas verificadas funcionan; las preguntas libres no.
AI_DISABLED = os.getenv("BIKESTORES_SIN_IA", "") == "1"

# Logs del arranque y de las descargas de modelos en segundo plano.
LOGS_DIR = BASE_DIR / "logs"

# --- Dominio -----------------------------------------------------------------
ORDER_STATUS = {1: "Pendiente", 2: "En proceso", 3: "Rechazada", 4: "Completada"}
