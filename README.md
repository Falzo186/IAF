# Bike Stores · Analítica y asistente en español

Plataforma analítica sobre la base de datos de ejemplo **Bike Stores** (3 tiendas de
bicicletas, 2016–2018). Incluye un **dashboard** con 6 KPIs y las 10 necesidades de
negocio, y un **asistente** que responde preguntas en español con SQL. Todo corre en tu
computadora, **sin nube**: la IA es un modelo pequeño que se ejecuta localmente con Ollama.

![Dashboard](docs/capturas/dashboard_desktop.png)

---

## Requisitos

- **Windows 10/11**, o Linux / macOS.
- **8 GB de RAM** recomendados (el modelo de IA ocupa ~1.5 GB en memoria).
- **~3 GB de disco** libres: entorno de Python (~600 MB), Ollama (~1.5 GB) y un modelo (~1 GB).
- **Internet en el primer arranque** (instalar dependencias y descargar el modelo). Después
  funciona sin conexión.
- Python 3.10 o superior. Si no lo tienes, `ejecutar.bat` ofrece instalarlo con winget.

## Cómo arrancarlo

**Windows:** doble clic en **`ejecutar.bat`**.

**Linux / macOS:**

```bash
./ejecutar
```

(Si el archivo perdió el permiso de ejecución al copiarlo: `chmod +x ejecutar` o
`bash ejecutar.sh`.)

Se abre el navegador en `http://localhost:8501`. Para cerrar la app, cierra la ventana
de la consola o pulsa **Ctrl+C**.

### Qué hace el primer arranque y cuánto tarda

La consola muestra 5 pasos:

| Paso | Qué hace | Primera vez | Siguientes |
|---|---|---|---|
| [1/5] Entorno | Crea `.venv` e instala las dependencias (solo si `requirements.txt` cambió) | ~2 min (crear `.venv` ~10 s + instalar ~100 s) | instantáneo |
| [2/5] Base de datos | Construye `bikestores.db` a partir de los CSV (solo si falta o cambiaron) | ~2 s | instantáneo |
| [3/5] Ollama | Comprueba la IA local; si no está instalada, **pregunta** si instalarla; si falta el modelo, lo descarga **en segundo plano** | depende de la red | ~1 s |
| [4/5] Puerto | Usa 8501 o el siguiente libre | — | — |
| [5/5] App | Arranca Streamlit y abre el navegador cuando responde | ~2 s | ~2 s |

Medido en esta máquina: **primer arranque 122 s**, **segundo arranque 3.6 s hasta que la app responde**
(ver fase4.md). La descarga del modelo (~1 GB) no bloquea: el Asistente muestra
"↓ descargando… NN %" mientras tanto.

Opciones (se pasan igual al `.bat` o al script):

| Opción | Efecto |
|---|---|
| `--sin-ia` | No usa Ollama (modo sin IA) |
| `--reset` | Borra `.venv`, reinstala todo y reconstruye la base de datos |
| `--no-browser` | No abre el navegador |
| `--smoke` | Arranca, comprueba que la app responde, cierra y sale (pruebas automáticas) |

## Modo sin IA

Si Ollama no está instalado (y respondes "n" a instalarlo), no arranca, o usas
`--sin-ia`, la app funciona igual en **modo sin IA**:

- El **dashboard** completo funciona.
- En el **Asistente**, las preguntas sobre las 10 necesidades se responden con **consultas
  verificadas** y una frase calculada (por ejemplo: *"¿Cuánto dinero perdimos por pedidos
  rechazados?"*).
- Las preguntas libres (*"¿Cuáles son las 5 marcas con más unidades vendidas?"*) necesitan Ollama.

## Las 10 necesidades de negocio

"Ventas" = órdenes **Completadas**. Montos netos = precio × cantidad × (1 − descuento).

| # | Necesidad | Definición |
|---|---|---|
| N1 | Rentabilidad por descuentos | Por producto: ingreso neto, descuento cedido y % cedido sobre el bruto (top 10 por ingreso y por % cedido) |
| N2 | Riesgo de quiebre de stock | Los 20 productos más vendidos con menos de 5 unidades en alguna tienda |
| N3 | Productividad en Electric Bikes | Vendedores por ingreso neto en la categoría Electric Bikes (con unidades y órdenes) |
| N4 | Perfil geográfico premium | Top 10 ciudades por ingreso con el descuento mínimo del dataset (5 %); no existen ventas sin descuento |
| N5 | Ineficiencia logística | Número y valor de las órdenes enviadas después de la fecha requerida, por tienda, con días de retraso promedio |
| N6 | Inventario inactivo | Productos con stock sin ventas en los 6 meses previos a la última venta; distingue "Nunca vendido" y "Sin ventas recientes" |
| N7 | Diversificación de marcas | Clientes con órdenes de 2 o más marcas y su máximo de marcas por orden |
| N8 | Ticket promedio por tienda | Promedio del total neto por orden completada, por tienda |
| N9 | Eficiencia del catálogo | Rotación = unidades vendidas / meses con ventas, por categoría y por marca |
| N10 | Cancelaciones | Órdenes Rechazadas (no existe "cancelada"): monto neto perdido total, por tienda y por mes |

## Resultados de la evaluación

24 preguntas (10 básicas, 10 de negocio y 4 de negocio con un filtro no soportado),
exactitud medida ejecutando la SQL y comparando con la de referencia. CPU sin GPU.

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 1/4 | 5.3 | — | — | 5 |
| qwen2.5:1.5b | sistema completo | 9/10 | 10/10 | 3/4 | 4.0 | 11.4 | 21.4 | 2 |
| llama3.2:1b | solo LLM | 6/10 | 0/10 | 0/4 | 28.0 | — | — | 11 |
| llama3.2:1b | sistema completo | 6/10 | 10/10 | 1/4 | 10.8 | 15.1 | 38.8 | 4 |
| deepseek-r1:1.5b | solo LLM | 0/10 | 0/10 | 0/4 | 43.8 | — | — | 22 |
| deepseek-r1:1.5b | sistema completo | 1/10 | 10/10 | 0/4 | 24.6 | 31.4 | 55.6 | 12 |

*Negocio en el sistema completo* = las 10 necesidades se responden con SQL verificada.
La "respuesta completa" de la tabla incluye la redacción con IA de esas respuestas; con la
configuración por defecto (`VERIFIED_SYNTHESIS = False`) una respuesta verificada tarda
**0.1 s** (medido: 12.0 s → 0.13 s de p50). Las preguntas libres con qwen tardan unos 12 s.

**Modelo por defecto: `qwen2.5:1.5b`**, el más preciso y el más rápido. Detalle,
fallos por modelo y la iteración del prompt en [fase2.md](fase2.md).

## Arquitectura

```
┌──────────────────────── app.py (Streamlit, 2 páginas) ────────────────────────┐
│  views/dashboard.py                       views/asistente.py                  │
│  ui/charts.py (tema Plotly) · ui/data.py (caché) · assets/style.css           │
└──────────┬─────────────────────────────────────────────┬──────────────────────┘
           │                                             │
     analytics.py                                  sql_engine.py
  KPIs · tendencia · insight()        enrutador ─► verificada │ anclada │ LLM
           │                           extraer ─► validar (sqlglot) ─► ejecutar
           │                                             │          │
           └──────────► business_queries.py ◄────────────┘   ollama_manager.py
                        10 SQL verificadas (parámetros)          │
                                    │                            ▼
                                  db.py (solo lectura)      Ollama (local)
                                    │
                              bikestores.db  ◄── database_builder.py ◄── data/bike_stores/*.csv
                              (vistas v_order_lines, v_orders)

bootstrap.py (solo biblioteca estándar) ◄── ejecutar.bat / ejecutar / ejecutar.sh
```

## Solución de problemas

| Problema | Qué hacer |
|---|---|
| **El puerto 8501 está ocupado** | No hace falta nada: el arranque usa el siguiente libre (8502, …) y lo indica en la consola. |
| **Ollama no inicia** | La app entra en modo sin IA y sigue funcionando. Abre Ollama desde el menú Inicio, o en el Asistente pulsa "Iniciar Ollama". Revisa `logs/ejecutar.log`. |
| **El modelo no termina de descargar** | Mira `logs/pull_qwen2.5_1.5b.log`. Si se cortó, borra `logs/pull_qwen2.5_1.5b.lock` y vuelve a arrancar. |
| **Antivirus o SmartScreen bloquea `ejecutar.bat`** | En el aviso de SmartScreen: "Más información" → "Ejecutar de todas formas". Si el antivirus pone en cuarentena `.venv` u `ollama.exe`, añade la carpeta del proyecto a las exclusiones. El `.bat` solo llama a Python y es texto legible. |
| **Algo quedó a medias o se corrompió** | `ejecutar.bat --reset` (o `./ejecutar --reset`): reinstala el entorno y reconstruye la base de datos. |
| **Falta un CSV** | El arranque se detiene en [2/5] con un mensaje que nombra el archivo faltante; los 9 CSV van en `data/bike_stores/`. |
| **La respuesta del asistente tarda** | En CPU, una pregunta libre tarda ~5–15 s. Las preguntas de las 10 necesidades son instantáneas (activa "Redacción con IA" si prefieres que el modelo las redacte, ~11 s más). |

Registros: `logs/ejecutar.log` (arranque), `logs/streamlit.log` (app),
`logs/pull_<modelo>.log` (descarga).

## Estructura de archivos

```
ejecutar.bat · ejecutar · ejecutar.sh   arranque en un clic
bootstrap.py                            lógica del arranque (solo biblioteca estándar)
requirements.txt / requirements-dev.txt dependencias de ejecución / de desarrollo
config.py                               rutas, modelos, opciones
database_builder.py                     CSV → bikestores.db (esquema, vistas, validación)
db.py                                   conexión de solo lectura
business_queries.py                     las 10 necesidades (SQL verificada con parámetros)
sql_engine.py                           Text-to-SQL: enrutador, prompt, validación, síntesis
ollama_manager.py · pull_log.py         Ollama: servidor, modelos, descargas
analytics.py                            KPIs, tendencia, insights (dashboard)
app.py · views/ · ui/ · assets/ · .streamlit/   interfaz Streamlit
eval_text2sql.py · eval/                evaluación de modelos
tests/                                  pytest (todas las fases)
tools/                                  capturas y medición de la interfaz
data/bike_stores/                       los 9 CSV
docs/capturas/                          capturas de pantalla
fase1.md … fase4.md                     documentación de cada fase
```

Desarrollo: `pip install -r requirements-dev.txt` y `pytest -q`.
