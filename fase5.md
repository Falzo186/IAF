# Fase 5: preparación para el congreso (robustez de la demo)

**Objetivo:** que la demo en vivo no falle. El modelo debe estar listo y seguir cargado,
la app debe funcionar sin internet, las preguntas deben estar validadas, tiene que
existir un video de respaldo y las cifras deben estar a mano.

---

## 1. Control de versiones

- `git init -b main` en `C:\Users\alexp\IAF`, con la identidad global de git
  (`Falzo186 <144605151+Falzo186@users.noreply.github.com>`).
- **`.gitignore`** deja fuera `.venv/`, `logs/`, `bikestores.db`, `*.lock`, `__pycache__/`,
  `.pytest_cache/`, `*.tmp` y los journals de SQLite. Se comprobó con `git check-ignore`.
  **Incluye** `data/bike_stores/*.csv` (9 archivos; el repositorio pesa 2.5 MB en total).
- **`.gitattributes`** (nuevo): tu git tiene `core.autocrlf=true`, así que sin reglas
  `ejecutar` y `ejecutar.sh` saldrían con CRLF en un clon de Windows y fallarían en bash.
  Reglas: `ejecutar` y `*.sh` → `eol=lf`; `*.bat` → `eol=crlf`; `data/**/*.csv` → `-text`
  (se versionan byte a byte); imágenes y video → `binary`. Se verificó con
  `git ls-files --eol`.
- `git update-index --chmod=+x ejecutar ejecutar.sh` → modo `100755` en el índice.
- **Commits:** no hubo git durante las fases 1–4, así que no se puede reconstruir un
  historial fiel por fase. Hay un **commit inicial único** que lo explica, seguido de
  un commit por bloque de la Fase 5 (`git log --oneline`).
- **No se hizo push.** Para publicarlo en GitHub (usuario JesusMurillo186), crea antes un
  repositorio **vacío** llamado `bike-stores-analitica` en https://github.com/new (sin
  README ni licencia) y ejecuta:

  ```bash
  git remote add origin https://github.com/JesusMurillo186/bike-stores-analitica.git
  git push -u origin main
  ```

  El nombre del repositorio es una sugerencia; ajusta la URL si usas otro. Si tienes la
  CLI de GitHub, también sirve:
  `gh repo create JesusMurillo186/bike-stores-analitica --private --source . --push`.
  Los commits usan la identidad `Falzo186`. Si quieres que aparezcan como JesusMurillo186,
  cámbiala antes de publicar con `git commit --amend --reset-author` o reconfigura
  `user.name` y `user.email`.

## 2. Precalentamiento y permanencia del modelo

- **`config.KEEP_ALIVE = "60m"`** se aplica en todas las llamadas `chat()` (hay prueba). El valor
  por defecto de Ollama, 5 min, descargaba el modelo si el presentador hablaba un rato
  entre preguntas.
- **`warmup.py`** precalienta con el **system prompt real** y el mismo `num_ctx` del chat
  (`num_predict=1`). `bootstrap.py` lo lanza en segundo plano al final de [5/5], solo si
  el modelo está descargado y no hay una descarga en curso; no lo lanza con `--smoke`.
  Una petición mínima de precalentamiento **no sirve**:
  - Si `num_ctx` es distinto, Ollama recarga el modelo.
  - Lo caro de la primera pregunta es procesar los ~1,500 tokens del system prompt, que
    Ollama deja en caché si el prefijo coincide.
- **Indicador del Asistente:** muestra "● listo" solo si `/api/ps` (`ollama_manager.loaded_models`)
  tiene el modelo en RAM, y "◐ cargando…" mientras tanto (se refresca cada 3 s con un
  `st.fragment`). Si la app se abrió sin bootstrap, o se cambió de modelo, la página lanza
  el precalentamiento en un hilo, una sola vez por proceso.

**Medición** (`tools/medir_primera_respuesta.py`; pregunta D4, que va por la ruta LLM con
síntesis; qwen2.5:1.5b; CPU):

| Escenario | Modelo en RAM al preguntar | Primera respuesta |
|---|---|---:|
| **Antes:** arranque sin precalentar (frío), 2 corridas | no | **35.6 s / 46.9 s** |
| Precalentamiento mínimo (sin system prompt, `num_ctx` por defecto) | sí | 33.7 s |
| **Después:** precalentamiento con system prompt real, 2 corridas | sí | **15.0 s / 15.3 s** |
| **Antes:** 5.5 min sin usar el modelo, `keep_alive` 5 min | no (se descargó) | **32.9 s** |
| **Después:** 5.5 min sin usar el modelo, `KEEP_ALIVE` 60 min | sí | **14.8 s** |

El precalentamiento tarda unos 18 s en segundo plano. Cabe de sobra mientras el
presentador muestra el dashboard: la app responde a los ~6 s del arranque y la primera
pregunta con LLM llega mucho después. Las respuestas **verificadas no usan el LLM** y son
instantáneas en cualquier caso.

## 3. Prueba sin conexión

**Método.** No desactivé el adaptador de red, porque eso es configuración del sistema.
Simulé la falta de conexión con un proxy inexistente (`tools/prueba_sin_red.py`):
- La app y todo lo que lanza reciben `HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:9` (nadie
  escucha ahí), `NO_PROXY=127.0.0.1,localhost` (el tráfico local sigue directo) y
  `PIP_INDEX_URL=http://127.0.0.1:9/simple`.
- Ollama se reinició con el mismo proxy, para que no pudiera llegar a su registro de modelos:
  ```powershell
  Get-Process *ollama* | Stop-Process -Force
  $env:HTTPS_PROXY="http://127.0.0.1:9"; $env:NO_PROXY="127.0.0.1,localhost"
  Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve -WindowStyle Hidden
  ```
  Al terminar se restauró el Ollama normal, sin proxy y con su app de bandeja.
- Se comprobó que la simulación funciona: `pypi.org` queda **rechazado** y
  `ollama pull smollm:135m` falla con `proxyconnect tcp: dial tcp 127.0.0.1:9` en 0.06 s.

**Resultado** (`demo/prueba_sin_red.json`; los 3 modelos ya estaban descargados):

| Comprobación | Resultado |
|---|---|
| `ejecutar.bat --no-browser` sin red | **Sin intentos de pip ni de pull** ("Dependencias al día", "Modelo qwen2.5:1.5b disponible"); se lanzó el precalentamiento; health 200 a los **5.5 s** del arranque. Usó el puerto 8502 porque el 8501 estaba ocupado |
| Asistente sin red | "● listo"; **D1 (verificada) en 0.4 s** y **D4 (IA) en 14.9 s** con las cifras correctas (Trek $2,124,167.94). Captura: `docs/capturas/sin_red_chat.png` |
| ¿Se cuelga? | No. Todas las llamadas locales usan `127.0.0.1` sin proxy |
| Camino forzado 1: `requirements.txt` con un paquete nuevo (`tabulate`) | pip falla rápido (`--timeout 10 --retries 1`), aparece el **AVISO** "no se pudieron actualizar las dependencias (¿sin conexión?)" y la app **arranca igual** (código 0, 12.3 s). El hash no se actualiza, así que se reintenta en el siguiente arranque con red |
| Camino forzado 2: descarga en segundo plano de un modelo que falta | `bootstrap.py --_pull` falla en **0.3 s**, registra el error en su log y **libera el `.lock`**, así que el indicador de la app no se queda en "descargando" |

Cambios que hicieron falta para tolerar la falta de red: timeout y reintentos cortos en
pip, y continuar con las dependencias ya instaladas si pip falla y ya existía una
instalación. El resto ya era tolerante: la descarga de modelos es en segundo plano y los
chequeos de Ollama tienen timeouts de 2–5 s.

## 4. Rotación de logs

`bootstrap.py` llama a `rotate_log()` al iniciar el registro: si `logs/ejecutar.log`
supera 1 MB (`LOG_MAX_BYTES = 1_000_000`), lo renombra a `logs/ejecutar.log.1` con
`os.replace`, que sustituye el `.1` anterior; así se conserva uno solo. Prueba:
`test_log_rotation_keeps_a_single_backup` (no rota si es pequeño, rota al superar el
límite y reemplaza el respaldo anterior).

## 5. Validación de las preguntas de la demo

`demo/preguntas_demo.json` define D1–D7 con su ruta esperada, su SQL de referencia (D3–D5
escritas a mano; D1, D2 y D6 son la consulta verificada con sus filtros) y el criterio de
seguridad de D7. `tools/validar_demo.py` ejecuta **cada repetición como una conversación
completa D1→D7** a través de `sql_engine.answer_question`, con el historial como en la app:
**5 veces con qwen2.5:1.5b y 2 con llama3.2:1b**. En D7 compara el SHA-256 del archivo de la
BD antes y después. Detalle, respuestas textuales y fallos en **`demo/validacion_demo.md`**.

### Resultado final

| ID | Pregunta | Origen esperado | Origen obtenido (qwen) | qwen aciertos | qwen p50 / máx (s) | llama aciertos | llama p50 / máx (s) | ¿Apta? |
|---|---|---|---|---:|---:|---:|---:|---|
| D1 | ¿Qué productos se venden mucho pero están a punto de agotarse? | verificada | verificada | 5/5 | 0.2 / 0.2 | 2/2 | 0.1 / 0.1 | **Sí** |
| D2 | ¿Cuál es el ticket promedio por tienda en 2017? | verificada | verificada | 5/5 | 0.1 / 0.2 | 2/2 | 0.1 / 0.1 | **Sí** |
| D3 | Ticket promedio por tienda, pero solo en Electric Bikes | llm_anclada | llm_anclada | 0/5 | 10.6 / 11.5 | 0/2 | 23.9 / 24.6 | No |
| D4 | ¿Cuáles son las 5 marcas con más ingreso neto en 2017? | llm | llm | 5/5 | 10.7 / 12.1 | 0/2 | 13.2 / 13.5 | **Sí** |
| D5 | ¿Y en 2016? | llm | llm | 5/5 | 11.9 / 12.9 | 0/2 | 14.6 / 20.8 | **Sí** |
| D6 | ¿Cuánto dinero tenemos parado en inventario que nunca se vendió? | verificada | verificada | 5/5 | 0.1 / 0.2 | 2/2 | 0.2 / 0.2 | **Sí** |
| D7 | Borra todos los clientes de la base de datos | cualquiera | solo_lectura | 5/5 | 0.0 / 0.0 | 2/2 | 0.0 / 0.0 | **Sí** |

Formulaciones alternativas para D3 (validadas en la misma conversación, después de D1 y D2):

| ID | Formulación | Origen (qwen) | qwen aciertos | qwen p50 / máx (s) | llama aciertos | ¿Apta? |
|---|---|---|---:|---:|---:|---|
| D3 | Por tienda, ¿cuál es el ingreso neto de Electric Bikes dividido entre el número de órdenes que lo incluyen? | llm | 0/5 | 8.6 / 8.9 | 0/2 | No |
| D3 | ¿Cuánto gastan en promedio por orden los clientes de Electric Bikes en cada tienda? | llm_anclada | 0/5 | 15.2 / 15.5 | 0/2 | No |
| D3 | Dame el top 3 de vendedores de bicicletas eléctricas por ingreso neto | llm_anclada | 5/5 | 13.8 / 19.0 | 2/2 | **Sí** |
| D3 | ¿Cuánto dinero perdimos por órdenes rechazadas de clientes de Texas? | llm_anclada | 5/5 | 9.2 / 11.5 | 0/2 | **Sí** |

**Decisión: en la demo, D3 se reemplaza por "Dame el top 3 de vendedores de bicicletas
eléctricas por ingreso neto"** (IA anclada; 5/5 con qwen y 2/2 con llama). La secuencia
recomendada queda con **7/7 preguntas aptas**.

### Lo que encontró la validación y cómo se corrigió

| Hallazgo | Corrección | Efecto |
|---|---|---|
| **El historial se enviaba en todas las preguntas.** qwen copiaba filtros y tablas de la respuesta anterior: en D3 aparecía el "2017" de D2 | El historial solo acompaña a **preguntas de seguimiento** ("¿Y en 2016?", "Ahora solo Baldwin", "¿Cuáles de esas…?"; `sql_engine.is_follow_up`), que es lo que pedía la especificación de la Fase 2. Ninguna pregunta del golden set es de seguimiento | Desaparece la fuga del año. D5 sigue funcionando (5/5) |
| En D3 qwen filtra `category_name` sobre `v_orders`, que no la tiene, igual que en el ítem A1 de la evaluación | Nota de esquema: "v_orders NO tiene category_name, brand_name ni product_name…" | No bastó: qwen sigue fallando D3 con un **error controlado** |
| Intento descartado: una regla de reescritura en el ancla (`SUM(net_amount)/COUNT(DISTINCT order_id)`) | Se **revirtió** | qwen pasaba a `v_order_lines` pero calculaba `AVG(net_amount)`, que es el promedio por línea: **cifras plausibles pero incorrectas**, peor que un error |
| `sqlglot.TokenError` (SQL mal formada de llama) se saltaba el reintento | Se traduce a `SQLValidationError`, con reintento | — |
| D7 era seguro pero torpe ("El resultado (mensaje error) es No se puede borrar clientes."; 29 s con llama) | **Guarda previa al LLM** para órdenes de escritura (`is_write_request`: "Borra…", "Elimina…", "Actualiza…") → respuesta fija de solo lectura y distintivo "Solo lectura" | D7 en **0.0 s**, sin LLM ni SQL; la BD queda byte a byte igual |

**Sin regresiones:** qwen se re-evaluó con el golden set y el prompt final
(`eval/resultados_fase5.md`): básico 9/10 en solo LLM y 9/10 en el sistema completo, negocio
10/10 en el sistema completo y anclada 3/4; **idéntico** a la Fase 2B. La p50 de la
respuesta completa en el sistema completo bajó de 11.4 s a **3.0 s**, porque las
verificadas ya no pasan por el LLM.

**Nota sobre llama3.2:1b:** D4 y D5 pasan de 2/2 (primera corrida) a 0/2. Sin historial,
llama omite el filtro de 2017 y copia el ejemplo "3 marcas con más ingreso neto"; antes
acertaba solo porque el historial de D2 le "prestaba" el año. qwen acierta en ambos casos.
Coincide con el 6/10 de llama en la evaluación, y la demo usa qwen.

## 6. Plan B: video de respaldo

**`demo/respaldo_demo.webm`**: 1366×768, **2 min 57 s** (177 s), 10.1 MB. Se grabó con
`python tools/grabar_demo.py --url http://localhost:8502` (Playwright, `record_video_dir`)
sobre la app arrancada con `bootstrap.py`. Recorrido:

1. Dashboard: KPIs y tendencia, desplazamiento por las 4 secciones y "Ver datos" de **N6**,
   con la tabla "Nunca vendido".
2. Asistente: D1 (verificada), D2 (verificada, chip "Periodo 2017"), **D3 de reemplazo**
   (IA anclada, top 3 de vendedores de eléctricas) y D7 ("Solo lectura", "<0.1 s · sin LLM").
3. Clic en "+" (toast "Próximamente") y cambio de modelo a **llama3.2:1b**: toast "Modelo
   llama3.2:1b activo; conversación reiniciada" y saludo inicial.

Se verificó reproduciéndolo en Chromium y revisando fotogramas.

- **No hay `.mp4`:** ffmpeg no está instalado en este equipo. Para convertirlo:
  `ffmpeg -i demo/respaldo_demo.webm -c:v libx264 -pix_fmt yuv420p demo/respaldo_demo.mp4`.
  El `.webm` se abre en Chrome, Edge, Firefox y VLC.
- **En el video, D3 tarda ~34 s** en responder, frente a una p50 de 13.8 s en la
  validación: la grabación comparte la CPU con el modelo. En vivo, sin grabar, se espera
  ~14 s.

## 7. Cifras clave

`demo/cifras_clave.md`, generado con `python tools/cifras_clave.py` desde
`eval/resultados.json` y la base de datos. Incluye el acierto por modelo × modo ×
nivel, las latencias p50 por ruta y las 6 cifras de negocio más fuertes con su
definición:

| Cifra | Valor |
|---|---|
| Capital inmovilizado en productos que **nunca se vendieron** (N6) | **$1,891,217.66** en 29 productos (1,234 unidades) |
| Valor de órdenes entregadas tarde (N5) | **$2,042,907.07** en 458 órdenes (31.7 % de las completadas) |
| Productos top en riesgo de quiebre (N2) | **7 de los 20 más vendidos** bajo 5 unidades en alguna tienda; 3 agotados |
| Ingreso perdido por rechazos (N10) | **$208,579.45** en 45 órdenes |
| Descuento cedido (N1) | **$289,142.15** en los 10 productos de más ingreso; 10.4 % del bruto |
| Concentración en Electric Bikes (N3) | Marcelene Boyer, **37 %** del ingreso de la categoría |

## 8. Entrega

- **`pytest -q`: 271 passed** (todas las fases, sin Ollama).
- **Commits** (`git log --oneline`), sin push: estado inicial de las fases 1–4 →
  precalentamiento, `keep_alive` y arranque tolerante → robustez del chat → artefactos de
  la demo y documentación.
- **Archivos nuevos:** `warmup.py`, `.gitattributes`, `tools/medir_primera_respuesta.py`,
  `tools/validar_demo.py`, `tools/prueba_sin_red.py`, `tools/grabar_demo.py`,
  `tools/cifras_clave.py`, `demo/` (preguntas, validación, alternativas, prueba sin red,
  cifras clave y video) y `eval/resultados_fase5.md`.

### Guion recomendado para el congreso

1. Doble clic en `ejecutar.bat` **unos minutos antes**. Lo ideal es que el Asistente ya
   muestre "● listo" antes de empezar.
2. Dashboard: KPIs, N6 ("$1.89 M en productos que nunca se vendieron"), N5 y N2.
3. Asistente: D1 → D2 → **D3 de reemplazo** → D4 → D5 ("¿Y en 2016?") → D6 → D7. Las
   verificadas son instantáneas; las de IA tardan unos 10–15 s en CPU.
4. **Plan B:** `demo/respaldo_demo.webm`.

### Problemas conocidos

- **"Ticket promedio por tienda solo en Electric Bikes" no es fiable con modelos de
  1–1.5B**: falla con un error controlado. Si alguien del público la pide, el sistema no
  inventa cifras. Mejora posible: soportar categoría y marca como filtros verificados en
  las consultas por orden (N5, N7, N8, N10) calculándolas sobre `v_order_lines`; con los
  filtros vacíos el resultado sería idéntico.
- **Tu app de ayer en el puerto 8501:** al limpiar procesos de prueba detuve por error
  el `cmd` y el `bootstrap.py` de esa sesión. Su Streamlit sigue sirviendo en el 8501,
  pero con el código de ayer y sin ventana de consola. Conviene cerrarla y volver a
  arrancar con `ejecutar.bat` para usar esta versión:
  ```powershell
  Get-NetTCPConnection -LocalPort 8501 -State Listen | % { Stop-Process -Id $_.OwningProcess }
  ```
- **La latencia de la IA depende de la CPU:** en otro equipo más lento, el primer arranque y
  las respuestas con LLM tardarán más. Las verificadas no dependen de la CPU.
