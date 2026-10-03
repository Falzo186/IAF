# Fase 7: clasificación de fallas, experimento de contexto y caché de patrones

**Alcance:** instrumentación y herramientas de análisis. No cambia el comportamiento del chat
(`answer_question` en su camino normal, `KEEP_ALIVE`, el enrutador y el Asistente en vivo siguen
igual). Se corre aparte, no en la demo.

## 1. Clasificador de fallas

`eval_text2sql.classify_failure` se aplica solo a los ítems incorrectos (los aciertos quedan con
`fallo_categoria: null`). Cada resultado de `eval/resultados.json` lleva `fallo_categoria` y
`fallo_detalle`; `eval/resultados.md` tiene la sección **Categorías de falla** (conteo por
categoría × modelo × modo y un ejemplo real con pregunta y SQL generada).

Orden de decisión:

1. **`error_ejecucion`**: el validador o SQLite rechazaron la consulta (sintaxis, función inexistente,
   columna ambigua…). **`tabla_columna_inexistente`** es el caso particular en que el error nombra una
   tabla o columna que no existe (`no such column`, `La tabla ... no existe`); se separa primero
   porque es más específico. Es una interpretación mía del orden pedido: sin ella la segunda
   categoría nunca tendría casos.
2. **`agregacion_incorrecta`**: se ejecuta, pero la forma (filas × columnas) no coincide con la
   referencia, o las funciones de agregación / número de `GROUP BY` difieren de la SQL de referencia.
3. **`filtro_incorrecto`**: misma forma, pero distinto `order_status`, fecha o nombre comparado.
   Un resultado vacío se trata como síntoma de filtro, no de agregación.
4. **`otro`**: con el motivo para revisión manual.

Límite conocido: la firma de agregación compara estructura, no semántica; una formulación
equivalente pero distinta en un ítem que además falló se etiqueta `agregacion_incorrecta`.

`python eval_text2sql.py --reclasificar` añade las categorías a un `resultados.json` existente sin
Ollama (vuelve a ejecutar la SQL guardada de cada fallo, que es determinista). Así se clasificaron
los 77 fallos de las corridas de la fase 5.

### Fallas por categoría, modelo y modo (77 fallos, `eval/resultados.json`)

| Categoría | qwen2.5:1.5b · LLM | qwen2.5:1.5b · completo | llama3.2:1b · LLM | llama3.2:1b · completo | deepseek-r1:1.5b · LLM | deepseek-r1:1.5b · completo | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| `error_ejecucion` | 1 | 0 | 4 | 2 | 13 | 6 | 26 |
| `tabla_columna_inexistente` | 4 | 2 | 5 | 1 | 8 | 5 | 25 |
| `agregacion_incorrecta` | 6 | 0 | 6 | 2 | 1 | 1 | 16 |
| `filtro_incorrecto` | 0 | 0 | 3 | 2 | 1 | 0 | 6 |
| `otro` | 2 | 0 | 0 | 0 | 1 | 1 | 4 |

Los ejemplos reales (pregunta + SQL) están en `eval/resultados.md`. Lectura: qwen falla sobre todo
por columnas inventadas o por agregar mal; deepseek-r1 por SQL que no se ejecuta; el enrutador del
modo completo elimina casi todo lo demás.

## 2. Experimento de contexto

`python context_experiment.py` (qwen2.5:1.5b, golden básico + negocio = 20 ítems, solo LLM, sin
enrutador). Solo cambia el bloque "Esquema" del prompt; reglas y ejemplos son iguales.
`sql_engine.build_system_prompt(context_level="actual")` acepta el parámetro y no cambia nada si se
omite. El experimento lo enlaza solo durante cada corrida. Detalle completo en
`eval/experimento_contexto.md`.

| Nivel | Básico | Negocio | Total | Tokens del esquema | Tokens del prompt |
|---|---|---|---|---:|---:|
| A · sin_contexto (solo nombres de tablas) | 9/10 | 3/10 | **12/20 (60 %)** | 46 | 787 |
| B · actual (producción) | 9/10 | 1/10 | **10/20 (50 %)** | 827 | 1,568 |
| C · describe_completo (PRAGMA) | 9/10 | 1/10 | **10/20 (50 %)** | 891 | 1,632 |

Distribución de fallas:

| Categoría | A | B | C |
|---|---:|---:|---:|
| `error_ejecucion` | 0 | 0 | 2 |
| `tabla_columna_inexistente` | 6 | 4 | 5 |
| `agregacion_incorrecta` | 2 | 6 | 3 |
| `filtro_incorrecto` | 0 | 0 | 0 |
| `otro` | 0 | 0 | 0 |

### Conclusión

- **`describe_completo` NO se adopta**: 10/20 frente a 10/20 del contexto actual, con más tokens
  (891 frente a 827 de esquema). Producción no cambia.
- Sí cambia **qué** falla: con `describe_completo` aparecen 2 `error_ejecucion` que B no tenía, y
  las `agregacion_incorrecta` bajan de 6 a 3 a cambio de más columnas inventadas.
- Resultado incómodo: **sin contexto acertó más (12/20)**. No lo adopto tampoco: con n = 20 la
  diferencia de 2 ítems es ruido, y los ejemplos y reglas del prompt siguen nombrando columnas de
  las vistas, así que A no es realmente "sin esquema". Lo que sí sugiere es que, para un modelo de
  1.5B, más esquema no es el cuello de botella; lo son las consultas de negocio (1/10 en B y C).
  Una corrida única a temperatura 0; conviene repetir con más preguntas antes de concluir más.

## 3. Bitácora y revisión de patrones

- `learned_patterns.py`: `log_pattern(result)` anota en `learned_patterns.jsonl` (append-only,
  ignorado por git) pregunta, SQL, modelo, fuente, timestamp y hash de la BD, **solo** si la ruta fue
  `llm` o `llm_anclada` y no hubo error. Que se ejecute no implica que sea correcta. Lo llama
  `views/asistente.py` tras responder; `answer_question` no se tocó, y un fallo al escribir nunca
  afecta al chat. Nada de la app lee ese archivo.
- `review_patterns.py`: **no es aprendizaje automático ni se activa solo.** Agrupa preguntas
  parecidas (similitud de texto ≥ 0.8, sin LLM) y pregunta por grupo.

  ```bash
  python review_patterns.py --resumen   # cuántos grupos están pendientes
  python review_patterns.py             # menú: p / pN / d / s / q
  ```

  `p` (o `pN` para elegir la variante de SQL N) agrega el par a `fewshot_candidates.json`, que
  `sql_engine.FEWSHOT_CANDIDATES` carga al importar. Es una lista aparte de `FEW_SHOTS` y **ningún
  código la usa**: si el equipo decide usar un candidato, lo mueve a mano a `FEW_SHOTS`. `d` descarta;
  las decisiones quedan en `learned_patterns_reviewed.json` para no volver a preguntar.
- **Pendientes de revisión hoy: 0.** `learned_patterns.jsonl` aún no existe (nadie ha usado el
  chat con esta versión). Se llenará con el uso normal del Asistente.

## 4. Pruebas

`pytest -q`: 291 pasan y 12 fallan. Esos 12 (11 en `tests/test_app.py`, 1 en
`tests/test_reference_report.py`) fallaban igual **antes** de esta fase en este equipo (la versión de
Streamlit instalada rompe `ButtonGroup` en `AppTest`, y kaleido/Chrome en el PDF); comprobé que el
conjunto de fallos es idéntico. Nuevas: `tests/test_eval.py` (una consulta sintética por categoría con
un LLM falso, prioridad, tabla del reporte, reclasificación) y `tests/test_fase7.py` (niveles de
contexto, experimento, bitácora, agrupado de dos preguntas casi idénticas y promoción sin tocar el
prompt). `tests/conftest.py` aísla los archivos de la fase en carpetas temporales.
