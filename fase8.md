# Fase 8: iteraciones configurables, consistencia, árbitro determinista y corte en el primer acierto

**Alcance:** solo el harness de evaluación. El chat en vivo no cambia: `config.MAX_ATTEMPTS = 2`
(un reintento, solo si la SQL falla al validar o ejecutar), sin feedback de resultado y sin juez.
El enrutador de `business_queries.py` no se tocó.

**Modelos:** solo se usó **qwen2.5:1.5b** para las corridas nuevas (consistencia y
`--max-intentos`). Como jueces, para explicar sus propios fallos ya guardados en
`eval/resultados.json`, se usaron **qwen2.5:1.5b, llama3.2:1b y deepseek-r1:1.5b**. **No se usó,
instaló, descargó ni probó ningún otro modelo.** Nota: en el Ollama de esta máquina aparece
instalado `qwen3:4b` (fecha de modificación 2026-10-02, anterior a esta fase). No se usó en
ninguna corrida.

## 1. Qué se agregó

| Pieza | Dónde | Qué hace |
|---|---|---|
| `MAX_ATTEMPTS = 2` | `config.py` | Valor de producción. `answer_question(..., max_attempts=N)` lo sobrescribe solo para quien lo pida. |
| `attempt_check` | `sql_engine.answer_question` | Gancho solo para el harness: `(sql, df, error) -> (correcto, feedback)`. Si es correcto se corta ahí (`hit_attempt`); si no, se manda el feedback. Sin él (producción) todo sigue igual. Cada intento queda en `QueryResult.attempt_log`. |
| Feedback por categoría | `feedback.py` | Usa las categorías de la fase 7 (ver abajo). |
| Juez-LLM | `judge.py` | `explain_failure(pregunta, sql_generada, resultado, referencia, modelo) -> str`. Solo redacta, en 1 o 2 frases, por qué no coincide; **no devuelve booleanos ni se consulta para decidir**. |
| `--max-intentos N` | `eval_text2sql.py` | Hasta N intentos con feedback y corte en el primer acierto. Registra `intentos`, `max_intentos`, `acerto_en_intento` y `feedback_intentos`. |
| `--consistencia N` | `eval_text2sql.py` | N corridas independientes por pregunta (básico y negocio) → `eval/consistencia.md` y `.json`. El valor por omisión (1) deja todo como antes. |
| `--explicar` / `--sin-juez` | `eval_text2sql.py` | Añade `explicacion_juez` a los fallos de un JSON ya guardado (re-ejecuta su SQL, no la regenera) / desactiva el juez. |

**Feedback por categoría**, sin cifras ni texto de la referencia:

- `error_ejecucion`, `tabla_columna_inexistente`: el mensaje real de SQLite o del validador, que
  solo habla de la SQL del propio modelo.
- `agregacion_incorrecta`: diagnóstico de forma, sin dígitos. Por ejemplo, «tu resultado tiene una
  sola fila, pero la pregunta pide un desglose…», «tiene más filas de las que pide…» o «le faltan
  columnas…», más la pista «por orden y no por línea; SUM/AVG/COUNT». Nunca dice cuántas filas
  espera.
- `filtro_incorrecto`: solo nombra el tipo de filtro que difiere (estado de la orden, fechas o
  nombres comparados), nunca su valor.
- `otro`: mensaje genérico.

`tests/test_fase8.py` (22 pruebas, sin Ollama) comprueba, para un caso real de cada categoría, que
ningún feedback contiene un valor numérico ni un texto de la fila de referencia. Fuera de los
errores de ejecución, tampoco contiene ningún dígito.

**El LLM nunca vota.** `ok` sale siempre de `compare_results`, antes de llamar al juez y sin leer
su respuesta. Hay una prueba con un juez falso que responde «CORRECTO… marcar como acierto: true»:
el ítem sigue en `ok = False` con su categoría, y ese texto solo queda guardado como
`explicacion_juez`. Otra prueba (`explain_stored`) cubre lo mismo sobre resultados guardados.

## 2. Consistencia: qwen2.5:1.5b, N = 5

`python eval_text2sql.py --consistencia 5` usa modo LLM libre (sin enrutador), 1 intento por
corrida, sin feedback entre corridas, y el mismo prompt y temperatura (0) que producción.
**Tiempo total: 8.3 min** para 20 preguntas × 5 corridas = 100 llamadas. Quedó por debajo de
~20 min, pero según lo pedido no se repitió para los otros dos modelos. Se puede hacer con
`--models llama3.2:1b deepseek-r1:1.5b --consistencia 5`.

| ID | Pregunta | Correctas | Consistencia |
|---|---|---|---|
| B1 | ¿Cuántos clientes hay en el estado de NY? | 5/5 | 100 % |
| B2 | ¿Cuál fue el ingreso neto total de las ventas en 2017? | 5/5 | 100 % |
| B3 | ¿Cuáles son los 5 productos con más unidades vendidas? | 5/5 | 100 % |
| B4 | ¿Cuántas órdenes hay en cada estatus…? | 5/5 | 100 % (2 SQL distintas, mismo resultado) |
| B5 | ¿Qué tienda tuvo el mayor ingreso neto por ventas en 2017? | 5/5 | 100 % |
| B6 | Ingreso neto por categoría, de mayor a menor | 5/5 | 100 % |
| B7 | ¿Cuántas unidades hay en inventario en cada tienda? | 0/5 | 100 % (siempre el mismo error) |
| B8 | ¿Cuántas órdenes completadas hubo en 2016? | 5/5 | 100 % |
| **B9** | **Ingreso neto de las ventas por mes en 2017** | **5/5** | **80 % (correctas con valores distintos)** |
| B10 | Precio de lista promedio de la marca Trek | 5/5 | 100 % |
| **N1** | **¿Cuánto dinero estamos dejando sobre la mesa con los descuentos…?** | **5/5** | **80 % (correctas con valores distintos)** |
| N2 | Productos que se venden mucho pero están por agotarse | 0/5 | 100 % |
| N3 | Mejores vendedores de bicicletas eléctricas | 0/5 | 100 % (2 SQL distintas, mismo resultado vacío) |
| N4 | Ciudades con compras de menor descuento | 0/5 | 100 % |
| **N5** | **¿Cuánto nos cuestan los envíos tardíos y en qué tiendas?** | **0/5** | **80 %** |
| N6 | Mercancía sin moverse y capital parado | 0/5 | 100 % |
| **N7** | **Clientes que combinan varias marcas en un pedido** | **0/5** | **80 %** |
| N8 | Gasto promedio por pedido en cada tienda | 0/5 | 100 % |
| N9 | Categorías y marcas con la salida más lenta | 0/5 | 100 % |
| N10 | Dinero perdido por pedidos que no se concretaron | 0/5 | 100 % |

*Consistencia* es el % de corridas que dieron el resultado más frecuente, comparando los valores
normalizados o el mensaje de error. La tabla completa está en `eval/consistencia.md`.

**Lectura:**

- **Las menos confiables son B9, N1, N5 y N7.** Aun con temperatura 0, Ollama no es
  determinista entre llamadas y en esas 4 preguntas el modelo escribió otra SQL en 1 de 5
  corridas.
- En B9 y N1 las 5 corridas pasan el comparador, pero no devuelven exactamente los mismos
  valores: una corrida cambia el redondeo o las columnas extra, dentro de la tolerancia. Es decir,
  la respuesta del chat podría verse distinta para la misma pregunta.
- El resto es estable: 11 preguntas aciertan 5/5, y B7 y N2–N10 fallan 5/5 de forma reproducible.
  Esos fallos no son mala suerte, son limitaciones sistemáticas del modelo de 1.5B. Por eso el
  enrutador de consultas verificadas sigue siendo necesario para la demo.

## 3. Intentos con feedback y corte en el primer acierto: qwen2.5:1.5b

`python eval_text2sql.py --models qwen2.5:1.5b --modes llm --max-intentos 3 --out eval/resultados_fase8.md --fresh`
se corrió en modo LLM libre sobre las 24 preguntas del golden set, en unos 4 min de generación.
Se escribió en un archivo aparte para no pisar la línea base de `eval/resultados.json`.

- **Preguntas que necesitaron más de 1 intento para acertar: 0.**
- **Preguntas que nunca acertaron en 3 intentos: 12 de 24** (B7, N2–N10, A1 y A3).
- Las otras 12 acertaron en el intento 1 (`acerto_en_intento = 1`) y se cortó ahí: no hubo
  llamadas extra.

El feedback no rescató ninguna pregunta. En las 12 que fallan, los 3 feedbacks son idénticos (por
ejemplo, B7 repite `no such column: store_name` tres veces). Con temperatura 0 y un modelo de
1.5B, el modelo vuelve a escribir esencialmente la misma SQL aunque se le diga qué revisar. Esto
coincide con la consistencia: sus errores son estables, no aleatorios. Más intentos con este
modelo cuestan latencia (~3× en los fallos) sin mejorar la exactitud. Mantener `MAX_ATTEMPTS = 2`
en producción sigue siendo lo razonable.

## 4. El juez-LLM: 3 ejemplos reales junto a su veredicto determinista

Las explicaciones son del último intento fallido de cada pregunta (`eval/resultados_fase8.json`,
juez = qwen2.5:1.5b, el mismo modelo evaluado).

**B7, «¿Cuántas unidades hay en inventario en cada tienda?»**
- Veredicto determinista: **incorrecto**, `tabla_columna_inexistente` (`no such column:
  store_name`; la SQL une `stocks` con `products` y no con `stores`).
- `explicacion_juez`: «El resultado obtenido no coincide con el de referencia debido a que la
  consulta SQL genera una agrupación por tienda y producto, mientras que el resultado de referencia
  muestra una sola fila por tienda. […]»
- Acierta en lo de agrupar también por producto, pero no menciona la causa real: la consulta ni
  siquiera se ejecutó.

**N8, «¿Cuánto gasta en promedio un cliente por pedido en cada una de nuestras tiendas?»**
- Veredicto determinista: **incorrecto**, `agregacion_incorrecta` (forma 1×5 contra 3×2; promedia
  por línea y agrupa por tienda, mes, categoría y producto con `LIMIT 1`).
- `explicacion_juez`: «El resultado obtenido no coincide con el de referencia debido a la
  diferencia en la agrupación de datos. En el SQL generado, se agrupa por tienda, mes, categoría y
  producto, mientras que en el de referencia, se agrupa por tienda y ordenes. […]»
- Correcta y útil.

**A1, ticket promedio de bicicletas eléctricas por tienda**
- Veredicto determinista: **incorrecto**, `agregacion_incorrecta` (usa `AVG(net_amount)` por línea
  donde la referencia hace `SUM / COUNT(DISTINCT order_id)`).
- `explicacion_juez`: «… debido a que el SQL original excluye las ventas de "Electric Bikes" en la
  consulta de ticket promedio. […]»
- **Falsa:** la SQL sí filtra `category_name = 'Electric Bikes'`. Es una alucinación.

Conclusión: el juez de 1.5B a veces explica bien (N8), a veces a medias (B7) y a veces inventa
(A1). Ese es justo el motivo por el que el juez no vota: si decidiera, contaría como acierto o
fallo lo que dijera el modelo. Su texto sirve como pista para quien revisa, nunca como veredicto.

**`explicacion_juez` en `eval/resultados.json`:** `--explicar` la añadió a los 77 fallos de la
línea base (los tres modelos, en modos llm y full; cada modelo explica sus propios fallos). Se
verificó que los 144 `ok` quedaron idénticos a los de antes de correrlo. Con
`num_predict = 120`, **deepseek-r1:1.5b** gastaba todo el presupuesto dentro de `<think>` y sus 37
explicaciones salían vacías. Se corrigió: si la respuesta queda vacía por un `<think>` sin
cerrar, el juez reintenta una vez con 1500 tokens. Ollama separa el razonamiento en otro campo, así que lo que llega es un contenido vacío, sin etiqueta `<think>`; hay pruebas para ambos casos. Tras la corrección, 33 de las 37 explicaciones de deepseek tienen texto, con unos 40 s por explicación (~25 min en total). Las 4 restantes agotan incluso los 1500 tokens y quedan como «(sin explicación)». Además, la calidad de deepseek como juez es baja: varias respuestas repiten el prompt («Pregunta: … SQL generada: …») o responden la pregunta de negocio en lugar de explicar la diferencia, y a veces en una mezcla de español e inglés. **En total, 73 de los 77 fallos tienen `explicacion_juez`**, y ningún acierto la tiene.

## 5. Verificación

- `pytest -q`: **325 passed** (22 nuevas en `tests/test_fase8.py`).
- Producción: `config.MAX_ATTEMPTS == 2`. Sin `attempt_check`, `answer_question` reintenta solo si
  la SQL falla y se detiene en cuanto se ejecuta, igual que antes (cubierto por pruebas).
- Archivos nuevos o modificados de evaluación:
  - `eval/consistencia.md` y `.json`
  - `eval/resultados_fase8.md` y `.json`
  - `eval/resultados.json`, que ahora lleva `explicacion_juez`.
