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

# Bitácora de patrones y candidatos a few-shot (fase 7): solo para revisión humana.
LEARNED_PATTERNS_PATH = BASE_DIR / "learned_patterns.jsonl"
FEWSHOT_CANDIDATES_PATH = BASE_DIR / "fewshot_candidates.json"
REVIEWED_PATTERNS_PATH = BASE_DIR / "learned_patterns_reviewed.json"

# --- LLM local (Ollama) ------------------------------------------------------
# 127.0.0.1 y no "localhost": en Windows, "localhost" prueba primero IPv6 (::1) y, como Ollama
# solo escucha en IPv4, cada conexión nueva esperaba ~2 s antes de caer a 127.0.0.1 (medido).
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = "qwen2.5:1.5b"
SUPPORTED_MODELS = ["qwen2.5:1.5b", "llama3.2:1b", "deepseek-r1:1.5b"]

# Intentos de generar SQL por pregunta (el 1.º más los reintentos). 2 = comportamiento del chat
# en producción: un reintento si la SQL falla al validar o ejecutar. El harness de evaluación
# puede pedir más con answer_question(..., max_attempts=N) sin cambiar el chat.
MAX_ATTEMPTS = 2

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

# --- Fase 11: ejemplos resueltos, RAG, harness y modo de red -------------------------------
CACHE_DIR = BASE_DIR / ".cache"                      # ignorado por git
CATALOGO_PATH = BASE_DIR / "necesidades_negativas" / "catalogo.jsonl"
FEWSHOT_K = 3                  # ejemplos recuperados por pregunta
FEWSHOT_MAX_CHARS = 2400       # presupuesto de los ejemplos añadidos (modelos de 1-1.5B, num_ctx 4096)
RAG_K = 3
RAG_MIN_SCORE = 0.30           # coseno TF-IDF mínimo para inyectar un ejemplo recuperado
MODOS_CONTEXTO = ("base", "fewshot", "rag", "harness")

# Modo de red: "offline" (por defecto) no abre ningún socket hacia fuera; solo Ollama en localhost.
# "online" permite el puente opcional a un modelo grande de capa gratuita (bridge.py, cost_guard.py).
MODO_RED = os.getenv("IAF_MODO_RED", "offline").strip().lower() or "offline"
BRIDGE_ENABLED = os.getenv("IAF_BRIDGE_ENABLED", "") == "1"   # desactivado por defecto
BRIDGE_PROVIDERS_PATH = BASE_DIR / "bridge_providers.yaml"
BRIDGE_MAX_PER_MINUTE = 5      # tope local, por debajo de cualquier límite gratuito
BRIDGE_MAX_PER_DAY = 100
BRIDGE_TIMEOUT_S = 20.0
BRIDGE_MAX_RETRIES = 3
