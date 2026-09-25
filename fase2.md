# Fase 2: motor Text-to-SQL (ollama_manager + sql_engine) y evaluación

**Objetivo:** convertir preguntas en español en SQL sobre `bikestores.db` usando
modelos locales pequeños (1–1.5B) mediante Ollama, con salvaguardas de seguridad,
un reintento automático, una respuesta ejecutiva y una evaluación honesta. Esta
fase no incluye `app.py` ni scripts de arranque.

> **Estado: evaluación con modelos reales COMPLETADA (Fase 2B).** Ollama 0.34.4 instalado con
> winget; 3 modelos × 2 modos × 24 preguntas en CPU. qwen2.5:1.5b cumple ambos criterios
> (básico solo LLM 9/10, negocio sistema completo 10/10) y es el modelo por defecto
> recomendado. Resultados en §5.4, fallos reales en §8 y el trabajo de la Fase 2B en §10.

---

## 0. Ajuste pendiente de la Fase 1

- `database_builder.py` ahora guarda en `db_metadata` la clave
  `last_completed_date` = `MAX(order_date) WHERE order_status = 4`, que vale **2018-03-31**.
- Nueva prueba: `tests/test_database.py::test_last_completed_date`. Compara el valor
  con pandas y verifica que no sea posterior a `reference_date`.
- Se ejecutó `python database_builder.py --force` y la validación salió OK.

**Por qué importa:** `reference_date` es 2018-12-28, pero la última venta completada
es del 2018-03-31. Después de esa fecha solo hay 13 órdenes, ninguna completada.
Cualquier análisis de "últimos N meses de ventas" debe anclarse en
`last_completed_date` y no en `reference_date`.

## 1. Dependencias

`requirements.txt`:

```
pandas>=2.2
ollama>=0.4
sqlglot>=25
pytest>=8        # desarrollo
```

Versiones instaladas: pandas 3.0.1, ollama 0.6.2, sqlglot 30.19.0, pytest 9.1.1.
Ollama (el servidor) **no está instalado**; ver el aviso al inicio.

---

## 2. `ollama_manager.py`

No depende de Streamlit, así que puede usarse desde cualquier UI.

| Función | Comportamiento |
|---|---|
| `get_client()` | Único `ollama.Client(host=config.OLLAMA_HOST, timeout=120)` (singleton con `lru_cache`) |
| `is_server_up()` | `GET /api/version` con timeout de 2 s. Nunca lanza excepción |
| `try_start_server()` | Busca el binario (PATH o ruta por defecto en Windows), lanza `ollama serve` sin consola (`CREATE_NO_WINDOW`) y espera hasta 15 s |
| `list_local_models()` / `is_model_available(name)` | Acepta `name` y `name:latest` |
| `pull_model(name)` | Generador de `{status, completed, total, percent}`. Lanza `ModelNotFound` si el nombre no existe y `OllamaError` si no hay internet |
| `unload_model(name)` | `generate(keep_alive=0)` para liberar la RAM; es la desactivación dinámica al cambiar de modelo |
| `chat(model, messages, *, temperature, num_ctx=4096, num_predict)` | Devuelve el texto de la respuesta |

Jerarquía de errores: `OllamaError` es la base, con `OllamaUnavailable` (errores de
conexión y timeouts) y `ModelNotFound` (modelo no descargado o nombre inválido).
Todos los mensajes están en español.

---

## 3. `sql_engine.py`

API pública:

```python
answer_question(question, model, history=None, llm=None, *,
                db_path=config.DB_PATH, use_router=True, synthesize_answer=True) -> QueryResult
```

`QueryResult` contiene `question`, `model`, `sql`, `df`, `answer`, `attempts`, `error`,
`timings` (`sql_gen`, `exec`, `synth`) y además `source` (`"verificada"` o `"llm"`)
y `business_query_id`. `attempts = 0` significa que la respuesta vino del enrutador
y no se generó SQL.

El módulo no tiene estado global mutable. Lo único que guarda es una caché
`lru_cache` del contexto de esquema y de la lista de objetos, indexada por la ruta
de la BD. `answer_question` **nunca lanza excepciones**: todo error se convierte en
`QueryResult.error` más un mensaje amable en `answer`.

### 3.1 Flujo

```
pregunta ─► plan_route: match_business_query + extract_filters
   ├─ coincide y filtros soportados ─► SQL verificada con parámetros ─► ejecutar ─► síntesis   (verificada)
   ├─ coincide + filtro no soportado ─► LLM con la SQL verificada como ancla ─┐                  (llm_anclada)
   └─ no coincide ────────────────────► LLM (temperature 0, num_predict 400) ─┤                  (llm)
                                                                              ▼
                     extract_sql ─► validate_sql ─► execute_sql (solo lectura, 5 s)
                                     │ falla (validación, SQLite o timeout)
                                     ▼
                 1 reintento: se reenvía la SQL y el error pidiendo corrección
                                     │ vuelve a fallar
                                     ▼
            QueryResult(error=..., answer="No logré construir una consulta válida… reformula…")
```

Si el LLM de síntesis falla (por ejemplo, Ollama apagado), las consultas verificadas
responden con la frase determinística de `analytics.insight`; ver fase3.md.

### 3.2 Contexto de esquema compacto

- Se genera una sola vez desde la BD con `PRAGMA table_info` y se guarda en caché.
- Las vistas van primero (`v_order_lines`, `v_orders`), con una línea `-- nota` por
  cada columna calculada. Después vienen `products`, `stocks`, `stores`, `staffs`,
  `customers`, `categories` y `brands`.
- Se omiten `order_items`, `orders`, `order_status_lookup` y `db_metadata`.
- Los valores válidos se leen de la BD: categorías, marcas, tiendas, estatus con su
  etiqueta, estados CA/NY/TX, `reference_date` y `last_completed_date`.
- **Tamaño: 2,652 caracteres, unos 758 tokens** (límite de 1,200; la prueba lo imprime).
  El system prompt completo, con reglas y 5 ejemplos, ronda los 1,374 tokens y
  cabe con holgura en `num_ctx = 4096`.

### 3.3 Extracción y validación

- `extract_sql` quita `<think>…</think>` (incluidos los bloques sin cerrar de
  deepseek-r1). Toma el primer bloque ```` ```sql ````, si no hay usa un bloque
  ```` ``` ```` genérico y, como último recurso, el texto desde el primer
  `SELECT`/`WITH` hasta un `;` o una línea en blanco. Después elimina comentarios
  `--` y `/* */` y el `;` final.
- `validate_sql` hace cuatro comprobaciones:
  1. Tokeniza con sqlglot y rechaza INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
     ATTACH, DETACH, PRAGMA, VACUUM y REPLACE **en cualquier posición**. Los
     literales entre comillas se ignoran, así que `LIKE '%delete%'` es válido.
     *Excepción documentada:* se permite `replace(` porque es la función de texto
     de SQLite; `REPLACE INTO` se rechaza.
  2. `sqlglot.parse(read="sqlite")` debe dar exactamente 1 sentencia de tipo
     `Select`, `Union`, `Intersect` o `Except`. En sqlglot, `WITH … SELECT` es un
     `Select`. Además se revisa el AST en busca de nodos de escritura.
  3. Cada tabla referenciada, sin contar los CTE, debe existir en `sqlite_master`.
     No se permiten esquemas distintos de `main`.
  4. Si la consulta externa no tiene LIMIT, se añade `LIMIT 500`. Se agrega al texto
     original en lugar de regenerar la SQL con sqlglot, para no alterar lo que el
     modelo escribió.
- `execute_sql` usa `file:…?mode=ro` (con `Path.as_uri()` para que funcione con
  rutas de Windows), activa `PRAGMA query_only = ON` y usa `set_progress_handler`
  para cortar la consulta a los 5 s, en cuyo caso lanza `QueryTimeout`.

### 3.4 Historial

Se incluyen como máximo los 2 últimos turnos, cada uno como un par pregunta y
SQL (`user` y luego `assistant` con ```` ```sql ````). Así se resuelven preguntas
de seguimiento como "¿y en 2017?".

### 3.5 Síntesis ejecutiva

- Es una segunda llamada con temperature 0.3 y num_predict 250. Recibe la pregunta,
  la SQL y las primeras 15 filas en markdown junto con el total de filas.
- La instrucción pide 2 a 4 frases, tono directivo, solo cifras presentes en el
  resultado, formato $1,234.56 y ninguna mención a SQL.
- Casos que no llaman al LLM: si hay 0 filas, responde "No se encontraron
  registros para esa consulta."; si el resultado es 1×1, usa la plantilla "El
  resultado (ingreso neto) es $X", con formato de dinero, porcentaje o entero
  según el nombre de la columna.
- Si la síntesis falla, devuelve una respuesta genérica y **conserva el DataFrame**.

### 3.6 Prompt final completo (system)

Se genera con `sql_engine.build_system_prompt()` y es la versión **final tras la iteración 1**
(ver §10.5): reglas 3 y 4 reforzadas, nota sobre `stocks.store_id` y un 6.º few-shot.
Se añadió una regla 8 a las 7 pedidas: "Usa solo las tablas y columnas del esquema".
Tamaño: unos 1,524 tokens el system prompt y unos 783 el contexto de esquema.

````text
Eres un experto en SQL que responde preguntas de negocio sobre la base Bike Stores.

Esquema:
v_order_lines(order_id INT, item_id INT, order_date TEXT, order_status INT, status_label TEXT, store_id INT, store_name TEXT, staff_id INT, staff_name TEXT, customer_id INT, customer_city TEXT, customer_state TEXT, product_id INT, product_name TEXT, brand_name TEXT, category_name TEXT, quantity INT, list_price REAL, discount REAL, gross_amount REAL, discount_amount REAL, net_amount REAL)
  -- status_label: texto del estado (Completada, Rechazada...)
  -- staff_name: nombre completo del vendedor
  -- gross_amount: list_price*quantity (bruto)
  -- discount_amount: list_price*quantity*discount (descuento cedido)
  -- net_amount: list_price*quantity*(1-discount) (ingreso neto de la línea)
v_orders(order_id INT, order_date TEXT, required_date TEXT, shipped_date TEXT, order_status INT, status_label TEXT, store_id INT, store_name TEXT, staff_id INT, staff_name TEXT, customer_id INT, customer_city TEXT, customer_state TEXT, n_items INT, total_quantity INT, n_brands INT, gross_total REAL, discount_total REAL, net_total REAL, is_shipped INT, is_late INT, days_late INT)
  -- n_items: número de líneas de la orden
  -- total_quantity: unidades de la orden
  -- n_brands: marcas distintas en la orden
  -- gross_total: suma de gross_amount
  -- discount_total: suma de discount_amount
  -- net_total: suma de net_amount (ingreso neto de la orden)
  -- is_shipped: 1 si shipped_date no es NULL
  -- is_late: 1 si se envió después de required_date
  -- days_late: días de retraso (0 a tiempo, NULL sin enviar)
products(product_id INT, product_name TEXT, brand_id INT, category_id INT, model_year INT, list_price REAL)
stocks(store_id INT, product_id INT, quantity INT)
  -- store_id: no hay store_name aquí: JOIN stores ON stores.store_id = stocks.store_id
stores(store_id INT, store_name TEXT, phone TEXT, email TEXT, street TEXT, city TEXT, state TEXT, zip_code TEXT)
staffs(staff_id INT, first_name TEXT, last_name TEXT, email TEXT, phone TEXT, active INT, store_id INT, manager_id INT)
customers(customer_id INT, first_name TEXT, last_name TEXT, phone TEXT, email TEXT, street TEXT, city TEXT, state TEXT, zip_code TEXT)
categories(category_id INT, category_name TEXT)
brands(brand_id INT, brand_name TEXT)

Valores válidos:
- category_name: Children Bicycles, Comfort Bicycles, Cruisers Bicycles, Cyclocross Bicycles, Electric Bikes, Mountain Bikes, Road Bikes
- brand_name: Electra, Haro, Heller, Pure Cycles, Ritchey, Strider, Sun Bicycles, Surly, Trek
- store_name: Baldwin Bikes, Rowlett Bikes, Santa Cruz Bikes
- order_status/status_label: 1=Pendiente, 2=En proceso, 3=Rechazada, 4=Completada
- state (clientes y tiendas): CA, NY, TX
- reference_date (hoy): 2018-12-28
- last_completed_date (última venta completada): 2018-03-31

Reglas:
1. Dialecto SQLite. Devuelve UNA sola consulta SELECT dentro de ```sql ... ```, sin explicación.
2. Para dinero usa SIEMPRE net_amount (v_order_lines) o net_total (v_orders), que ya aplican (list_price*quantity)*(1-discount). Nunca recalcules montos.
3. Toda pregunta de ventas, ingresos, ticket o unidades vendidas DEBE filtrar order_status = 4, salvo que se pida otro estado. Rechazadas = order_status = 3.
4. Las fechas son texto ISO. Si la pregunta menciona un año, filtra strftime('%Y', order_date) = 'AAAA'. Para "por mes" agrupa por strftime('%Y-%m', order_date) en una sola columna. "Hoy" = 2018-12-28.
5. Compara nombres exactamente con los valores válidos listados.
6. Usa alias legibles en español (AS ingreso_neto) y ROUND(x, 2) para dinero.
7. Rankings: ORDER BY ... DESC LIMIT n (por defecto 10).
8. Usa solo las tablas y columnas del esquema.

Ejemplos:
Pregunta: ¿Cuánto ingreso neto generó la categoría Mountain Bikes en 2016?
```sql
SELECT ROUND(SUM(net_amount), 2) AS ingreso_neto
FROM v_order_lines
WHERE order_status = 4 AND category_name = 'Mountain Bikes'
  AND strftime('%Y', order_date) = '2016'
```

Pregunta: ¿Cuáles son las 3 marcas con más ingreso neto?
```sql
SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto
FROM v_order_lines
WHERE order_status = 4
GROUP BY brand_name
ORDER BY ingreso_neto DESC
LIMIT 3
```

Pregunta: ¿Qué productos no tienen stock en Baldwin Bikes?
```sql
SELECT p.product_name AS producto, st.quantity AS stock
FROM stocks st
JOIN products p ON p.product_id = st.product_id
JOIN stores s ON s.store_id = st.store_id
WHERE s.store_name = 'Baldwin Bikes' AND st.quantity = 0
ORDER BY producto
```

Pregunta: ¿Qué porcentaje de las órdenes enviadas en 2017 llegó tarde?
```sql
SELECT ROUND(100.0 * SUM(is_late) / COUNT(*), 2) AS pct_tarde
FROM v_orders
WHERE is_shipped = 1 AND strftime('%Y', order_date) = '2017'
```

Pregunta: Compara el número de órdenes y el ingreso neto por tienda en 2018.
```sql
SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(SUM(net_total), 2) AS ingreso_neto
FROM v_orders
WHERE order_status = 4 AND strftime('%Y', order_date) = '2018'
GROUP BY store_name
ORDER BY ingreso_neto DESC
```

Pregunta: ¿Cuántas unidades de la marca Electra se vendieron por mes en 2016?
```sql
SELECT strftime('%Y-%m', order_date) AS mes, SUM(quantity) AS unidades
FROM v_order_lines
WHERE order_status = 4 AND brand_name = 'Electra'
  AND strftime('%Y', order_date) = '2016'
GROUP BY mes
ORDER BY mes
```
````

Los mensajes que se envían son: `system` con el prompt anterior, luego hasta 2
turnos de historial y al final `user` con la pregunta. En el reintento se añaden
`assistant` con la SQL fallida y `user` con el texto: "Esa consulta falló con este
error: … Corrígela usando solo el esquema dado. Devuelve solo la consulta SQL
corregida dentro de ```sql ... ```."

---

## 4. Consultas de negocio verificadas (`business_queries.py`)

Hay 10 entradas `BusinessQuery(id, titulo, definicion, sql, keywords, min_score, exclude)`.
Son la fuente única de esta SQL para el chat y para el dashboard de la Fase 3.
Todas usan las vistas y toman "ventas" = `order_status = 4`.

### 4.1 Hallazgo de calidad de datos: productos duplicados

**29 nombres de producto aparecen con 2 o 3 `product_id` distintos.** Es el mismo
producto, con el mismo precio, año y marca, dado de alta en varias categorías. Por
ejemplo, "Electra Cruiser 1 (24-Inch) - 2016" existe en Cruisers y en Children.
Si se agrupa por `product_id`, ese producto aparece dos veces y su ranking queda
partido: en el top 5 de unidades cae del 1.er lugar (290 u.) a posiciones
separadas. **Decisión:** en las necesidades por producto (N1, N2 y N6, y en B3)
se agrupa por `product_name`, y el stock se suma entre los ids duplicados. Las
ventas no se duplican porque cada línea apunta a un solo `product_id`.

### 4.2 Definiciones y cifras clave (verificadas ejecutando cada SQL)

| ID | Necesidad | Definición operativa | Cifras clave |
|---|---|---|---|
| N1 | Rentabilidad por descuentos | Por producto, en líneas completadas con discount > 0: ingreso neto, descuento cedido y % cedido = cedido / bruto. Top 10 por ingreso neto y top 10 por % cedido. La "pérdida marginal" es el ingreso cedido, porque no hay costos | Descuento cedido total en ventas: **$775,394.82** sobre $7,438,010.06 brutos (10.4 %). El 1.º por ingreso es Trek Slash 8 27.5 - 2016: $544,318.64 netos y $59,679.85 cedidos (9.88 %). Los 10 primeros suman $289,142.15 cedidos. El top por % cedido lo forman modelos 2018 vendidos solo al 20 % |
| N2 | Riesgo de quiebre | Top 20 productos por unidades vendidas; se muestran las tiendas donde su stock es menor que 5 | **10 casos**, 3 con stock 0: Surly Ice Cream Truck Frameset (Santa Cruz, el producto n.º 5 en ventas con 162 u.), Trek Remedy 29 Carbon Frameset (Santa Cruz) y Surly Wednesday Frameset (Rowlett) |
| N3 | Productividad en Electric Bikes | Vendedores por ingreso neto en 'Electric Bikes', con unidades y órdenes | Marcelene Boyer $271,184.17 (92 u., 55 órdenes) y Venita Daniel $261,795.84, ambas de Baldwin. Rowlett tiene la cifra más baja: Layla Terrell con $28,901.90 |
| N4 | Perfil geográfico premium | No hay ventas sin descuento: el mínimo es 0.05, con 1,205 líneas. Top 10 ciudades por ingreso neto con descuento mínimo, más su descuento promedio | 1.ª Floral Park, NY: $30,858.72 (descuento promedio 10.06 %). **9 de las 10 ciudades están en NY**; San Angelo, TX, es la excepción |
| N5 | Ineficiencia logística | Órdenes con is_late = 1: número, monto neto y días de retraso promedio, total y por tienda | **458 órdenes tarde ($2,042,907.07)**, con 1.33 días de retraso promedio. Baldwin concentra 317 órdenes ($1,430,618.99) |
| N6 | Inventario inactivo | Stock > 0 sin ventas completadas en [2017-10-02, 2018-03-31] (6 meses antes de `last_completed_date`); `estado_inventario` = Nunca vendido / Sin ventas recientes; unidades y valor a precio de lista | **29 productos, 1,234 unidades y $1,891,217.66 inmovilizados, los 29 "Nunca vendido"** (ver §10.4). El primero es Trek Domane SLR 6 Disc Women's - 2018 con $241,999.56 |
| N7 | Diversificación | Clientes con órdenes completadas de n_brands >= 2: número de esas órdenes y máximo de marcas | **1,064 clientes**; ninguno tiene más de una orden multimarca. 6 clientes combinaron 5 marcas en una orden. El resultado se corta en 500 filas en el chat |
| N8 | Ticket promedio | AVG(net_total) por tienda en órdenes completadas | Rowlett $4,971.23 (142 órdenes), Baldwin $4,613.55 (1,019), Santa Cruz $4,420.75 (284) |
| N9 | Eficiencia del catálogo | Rotación = unidades / meses con ventas, por categoría y por marca, de menor a mayor | Categoría más lenta: Electric Bikes con 9.69 u./mes (la más rápida es Cruisers con 69.07). Marcas más lentas: Strider 4.33 (solo 3 meses con ventas), Heller 5.20 y Ritchey 5.32 |
| N10 | Cancelaciones | No existe el estado "cancelada"; se usa Rechazada (3). Monto neto perdido total, por tienda y por mes | **45 órdenes, $208,579.45**. Rowlett es la tienda con más rechazos: 19 órdenes y $86,018.94 |

### 4.3 Enrutador (`match_business_query`)

- Normaliza la pregunta: minúsculas, sin acentos y sin signos de puntuación.
- Cada `BusinessQuery.keywords` es una tupla de **grupos de raíces** (por ejemplo,
  `("agot", "stock", …)` y `("popular", "vend", …)`). Una raíz cuenta si aparece
  como prefijo de una palabra. El puntaje es el número de grupos cubiertos, y
  `min_score` vale 2 por defecto.
- Desempate: primero más raíces coincidentes y luego más caracteres coincidentes.
  Si el empate persiste, **no se enruta**. `exclude` descarta una consulta: N10 no
  se activa si la pregunta menciona otros estatus, como "¿cuántas órdenes hay en
  cada estatus (Pendiente, …, Rechazada, …)?".
- Pruebas: 30 formulaciones (3 por necesidad) enrutan bien; 6 preguntas fuera de
  tema no se enrutan; las 10 preguntas de negocio del golden set enrutan bien y
  **ninguna de las 10 básicas se enruta**.

---

## 5. Evaluación (`eval/golden.json` + `eval_text2sql.py`)

### 5.1 Golden set

- **Nivel básico (B1–B10):** las escribí yo, porque la tarea original de la sección 5
  fue reemplazada y no recibí esas 10 preguntas. Son preguntas directas: clientes en
  NY, ingreso de 2017, top 5 productos por unidades, órdenes por estatus, mejor
  tienda de 2017, ingreso por categoría, stock por tienda, órdenes completadas de
  2016, ingreso mensual de 2017 y precio promedio de Trek. Ninguna coincide con los
  5 ejemplos few-shot.
- **Nivel negocio (N1–N10):** una pregunta por necesidad, redactada como la haría un
  directivo y sin copiar las formulaciones de prueba del enrutador. Por ejemplo, para
  N6: "¿Qué mercancía lleva meses en bodega sin moverse y cuánto capital tenemos
  ahí parado?". La referencia es la SQL de `business_queries.py`.

### 5.2 Cómo se compara

La exactitud se mide **por ejecución**: se ejecutan la SQL generada y la de
referencia y se comparan los resultados. No importan el orden de las columnas, sus
alias ni las columnas extra. Los números se aceptan con una tolerancia de 0.5 % o
0.01. Cada ítem define un `check`:
- `exact`: mismo número de filas, y cada fila de referencia (en sus `key_columns`)
  aparece en una fila distinta del resultado.
- `subset` con `k`: las primeras k filas de referencia aparecen en el resultado. Se
  usa en las necesidades de varias partes (N1, N5, N9 y N10), para las que exigir la
  tabla completa sería irreal.

El comparador tiene controles propios (`tests/test_eval.py`). Acepta SQL equivalente
escrita de otra forma: otra vista, columnas reordenadas o extra, subconjunto. Rechaza
5 errores típicos: olvidar el filtro de estatus, calcular en bruto en vez de neto,
devolver demasiadas filas, usar el estatus equivocado y responder con datos que no
corresponden.

### 5.3 Modos

- **Solo LLM** (`use_router=False`): mide la capacidad Text-to-SQL real del modelo.
- **Sistema completo** (`use_router=True`): enrutador más LLM, que es lo que verá el usuario.

La latencia mide generación, validación y ejecución, sin la síntesis. Entre un
modelo y otro se llama a `unload_model` para liberar la RAM.

### 5.4 Resultados

**Evaluación real** (`eval/resultados.md` y `eval/resultados.json`, con la SQL de cada
intento). Prompt final, Ollama 0.34.4, CPU sin GPU. El golden set tiene 24 ítems: 10
básico, 10 negocio y 4 anclada.

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 1/4 | 5.3 | — | — | 5 |
| qwen2.5:1.5b | sistema completo | 9/10 | 10/10 | 3/4 | 4.0 | 11.4 | 21.4 | 2 |
| llama3.2:1b | solo LLM | 6/10 | 0/10 | 0/4 | 28.0 | — | — | 11 |
| llama3.2:1b | sistema completo | 6/10 | 10/10 | 1/4 | 10.8 | 15.1 | 38.8 | 4 |
| deepseek-r1:1.5b | solo LLM | 0/10 | 0/10 | 0/4 | 43.8 | — | — | 22 |
| deepseek-r1:1.5b | sistema completo | 1/10 | 10/10 | 0/4 | 24.6 | 31.4 | 55.6 | 12 |

**Criterios de aceptación (qwen2.5:1.5b):**

- Básico, solo LLM >= 8/10: **9/10** CUMPLE
- Negocio, sistema completo = 10/10: **10/10** CUMPLE
- Negocio en solo LLM (dato honesto para la presentación, sin umbral): **qwen 1/10,
  llama 0/10, deepseek 0/10.** Los modelos de 1–1.5B no resuelven solos preguntas
  directivas de varias partes; el enrutador con SQL verificada es lo que lleva el
  sistema a 10/10.

**Latencia de la respuesta completa por ruta** (sistema completo, incluye síntesis;
mediana en segundos). Es lo que esperará el usuario en la demo:

| Modelo | Verificada | Generada por IA | IA anclada |
|---|---:|---:|---:|
| qwen2.5:1.5b | 11.0 | 12.4 | 14.8 |
| llama3.2:1b | 11.4 | 19.6 | 23.1 |
| deepseek-r1:1.5b | 16.2 | 43.0 | 49.4 |

Notas de medición:
- La latencia de la ruta verificada es casi toda síntesis: la SQL tarda 0.1–0.3 s.
- La primera pregunta de cada modelo incluye la carga en RAM (unos 15–25 s); por eso el
  p95 se aleja de la mediana.
- La fila de llama3.2 en modo solo LLM se volvió a medir de forma aislada, porque la
  primera corrida coincidió con capturas de pantalla que usaban qwen. Dio el mismo
  acierto y 28.0 s de latencia media frente a 29.9 s: la contención era menor. Se
  conserva la corrida aislada.
- **Esta tabla mide la ruta verificada CON síntesis del LLM** (p50 de qwen de 11.0 s). En
  la Fase 4 se decidió `config.VERIFIED_SYNTHESIS = False`: la ruta verificada responde
  con la frase determinística y su p50 baja a **0.13 s** (medido con
  `tools/medir_sintesis.py`: 12.0 s → 0.13 s; ver fase4.md). La síntesis sigue
  disponible con el toggle "Redacción con IA".

**Verificación del arnés** (`eval/resultados_oraculo.md`): el oráculo (LLM = SQL de
referencia) obtiene 24/24 en ambos modos, y los controles negativos de
`tests/test_eval.py` rechazan SQL incorrecta.

### 5.5 Recomendación de modelo por defecto

**`qwen2.5:1.5b`** (ya es `config.DEFAULT_MODEL`). Es el único que cumple el criterio
de básico y, además, el más rápido: la mejor relación entre acierto y latencia en los
tres niveles.
- `llama3.2:1b` acierta menos (6/10 en básico) y su SQL necesita más reintentos, sin
  ser más rápido en la práctica.
- `deepseek-r1:1.5b` no sirve para Text-to-SQL con `num_predict = 400`: su bloque
  `<think>` consume el presupuesto y muchas respuestas llegan sin SQL o truncadas.
  Además es el más lento.

Con el sistema completo, los tres modelos dan 10/10 en negocio porque esas preguntas
no pasan por el LLM para generar la SQL. El modelo solo cambia la calidad de las
preguntas libres y ancladas y la redacción de la síntesis.

---

## 6. Pruebas

`pytest -q` da **242 passed**, incluidas las Fases 1 y 3, y ninguna necesita Ollama.

| Archivo | Cubre |
|---|---|
| `tests/test_database.py` | Fase 1 más `last_completed_date` |
| `tests/test_sql_engine.py` | `extract_sql` (think, fences, texto alrededor, `;`, comentarios); `validate_sql` (DELETE, 2 sentencias, PRAGMA, tabla inexistente, DML dentro de un CTE, REPLACE INTO, ATTACH, otra BD; acepta WITH y añade LIMIT; palabras prohibidas dentro de literales); escritura rechazada por la conexión de solo lectura; CTE recursiva infinita cortada por timeout; tamaño del contexto (imprime unos 758 tokens); los 5 few-shot se ejecutan; historial de 2 turnos; reintento (SQL rota y luego correcta da attempts == 2); dos fallos dan un error amable sin excepción; LLM caído sin excepción; 1×1 sin segunda llamada; 0 filas sin LLM; síntesis y su fallback; enrutador (30 formulaciones y 6 fuera de tema); las 10 consultas verificadas se ejecutan |
| `tests/test_ollama_manager.py` | Contra un puerto cerrado: `is_server_up` devuelve False en menos de 3 s, las 4 operaciones lanzan `OllamaUnavailable` y el cliente es singleton |
| `tests/test_eval.py` | Golden set coherente; el comparador acepta SQL equivalente y rechaza la incorrecta; el oráculo obtiene 20/20 en ambos modos |

---

## 7. Cómo repetir la evaluación

```bash
python eval_text2sql.py --pull
```

Evalúa los modelos de `SUPPORTED_MODELS` (los descarga si faltan) en los 2 modos y
los 3 niveles, y escribe `eval/resultados.md` y `.json`. Al re-evaluar un modelo, un
modo o un nivel (`--models`, `--modes`, `--levels`), solo se reemplazan esas filas;
`--fresh` empieza de cero. Las corridas intermedias se conservan en
`eval/iter0_qwen.json`, `eval/iter1_qwen_basico.json` y `eval/final_3modelos.json`.

---

## 8. Fallos reales observados por modelo

Tomados de `eval/resultados.json` (prompt final). Los niveles básico y anclada se
listan en ambos modos; negocio solo en solo LLM, porque en el sistema completo es
10/10 para todos.

### qwen2.5:1.5b
- **B7 (stock por tienda):** une `stocks` con `products` en lugar de `stores` y usa
  `store_name`, que no existe en `stocks`. Falla también en el reintento, pese a la nota
  del esquema y al few-shot 3 que hace justo ese JOIN.
- **Anclada A1 (ticket solo en Electric Bikes):** conserva la SQL de referencia sobre
  `v_orders` y le añade `category_name`, que solo existe en `v_order_lines`. No sabe
  cambiar de vista para aplicar un filtro de línea. A2, A3 y A4 sí se resuelven.
- **Solo LLM, nivel negocio (1/10):** usa métricas equivocadas (`discount_amount` como
  "pérdida" en N10, `st.quantity < 0` como inventario inactivo en N6), agrupa por
  `product_name` en vez de por marca en N7 y hace uniones innecesarias
  `v_order_lines`×`v_orders` que producen `ambiguous column name`.

### llama3.2:1b
- **Básico (6/10):**
  - B2: `SELECT * FROM v_orders` sin agregar ni filtrar estatus.
  - B7: inventa `quantity_in_stock`.
  - B9: agrupa por año, une vistas y produce `ambiguous column`.
  - B10: calcula `AVG(list_price*quantity)` sobre ventas de 2016 en vez del precio de
    lista del catálogo.
- **Ancladas (1/4):** ignora la referencia o la rompe. En A2 genera `SELECT AS …`, que
  es un error de sintaxis; en A4 aplica `strftime('%Y', customer_city) = 'TX'`.
- **Negocio solo LLM:** 0/10.

### deepseek-r1:1.5b
- **Presupuesto de tokens agotado:** el `<think>` ocupa los 400 tokens de
  `num_predict`. En muchos ítems la respuesta llega sin SQL ("La respuesta del modelo
  no contiene ninguna consulta SQL") o truncada (`SELECT s`, `… AS LIMIT`). Es el riesgo
  que se había anticipado en la Fase 2.
- **Cuando sí escribe SQL, alucina columnas:** `year`, `p.quantity`, `brand_name` en
  `products`; o consulta `orders` con columnas de `v_orders`.
- **Posible ajuste no aplicado:** subir `num_predict` solo para este modelo. Aun así su
  latencia (p50 de unos 31 s en la respuesta completa) lo descarta para la demo.

### Limitaciones del sistema que siguen vigentes
- Un filtro que exige cambiar de vista (categoría o marca sobre una métrica por orden)
  es lo más difícil en la ruta anclada; ver qwen A1.
- `extract_filters` trabaja con reglas: "el año pasado", "este trimestre" o nombres de
  ciudad que también son palabras comunes (lista de exclusión) no se detectan como filtro.
- Todas las ventas completadas terminan el 2018-03-31; las preguntas de "último mes"
  relativas a `reference_date` (2018-12-28) devuelven 0 filas.

---

## 9. Archivos de la fase

```
requirements.txt
db.py                        (Fase 2B: acceso de solo lectura compartido)
ollama_manager.py
sql_engine.py                (Fase 2B: extract_filters, plan_route, ruta anclada)
business_queries.py          (Fase 2B: parámetros, supported_filters, run_business_query, render_sql)
eval_text2sql.py
eval/golden.json             (24 ítems: básico, negocio, anclada)
eval/resultados.md / .json   (evaluación real, 3 modelos)
eval/resultados_oraculo.md / .json
eval/iter0_qwen.json, eval/iter1_qwen_basico.json, eval/final_3modelos.json
tests/test_sql_engine.py, tests/test_ollama_manager.py, tests/test_eval.py
tests/fixtures/bq_baseline/N1–N10.csv   (regresión de cifras)
database_builder.py          (ajuste: last_completed_date)
fase2.md
```

---

## 10. Fase 2B: cierre con modelos reales

### 10.1 Instalación de Ollama

`winget install --id Ollama.Ollama -e` instaló **Ollama 0.34.4** en
`%LOCALAPPDATA%\Programs\Ollama`. `ollama_manager.is_server_up()` devolvió True sin
necesidad de `try_start_server()`, porque el instalador deja el servicio corriendo.
Se descargaron los 3 modelos: qwen2.5:1.5b en 154 s, llama3.2:1b en 242 s y
deepseek-r1:1.5b en 201 s. El equipo no tiene GPU NVIDIA (12 hilos de CPU), así que
toda la inferencia corre en CPU.

### 10.2 Consultas verificadas con parámetros

- Cada SQL de `business_queries.py` acepta `:store_name`, `:date_from` y `:date_to` con
  el patrón `(:p IS NULL OR col = :p)` sobre las vistas; las fechas son inclusivas
  sobre `order_date`. `BusinessQuery.supported_filters` lista los tres para las 10
  necesidades.
- **N2 y N6:** la tienda filtra el **stock** y las fechas filtran las **ventas**. En N2
  las fechas definen la popularidad; en N6 reemplazan la ventana de 6 meses. Está
  documentado en `definicion`.
- `run_business_query(bq, store_name, date_from, date_to, limit)` ejecuta con
  parámetros enlazados por SQLite en una conexión de solo lectura.
  `render_sql(bq, ...)` produce la versión legible y ejecutable sin parámetros: quita
  los filtros vacíos e incrusta los activos. Es la SQL que ve el usuario y la que
  recibe el LLM como ancla. Una prueba verifica que `render_sql` y
  `run_business_query` den resultados idénticos en las 10 consultas.
- **Regresión:** antes de parametrizar se guardó el resultado de las 10 consultas en
  `tests/fixtures/bq_baseline/`. Con todos los parámetros en NULL, las 10 quedan
  **idénticas** (`test_null_parameters_reproduce_phase2_baseline`). N4 ganó la columna
  `pct_ingreso_desc_minimo` para el dashboard, y la comparación usa las columnas originales.

### 10.3 Extracción de filtros y tres rutas

`extract_filters(question)` detecta:
- **Soportados:** la tienda ("Baldwin", "Santa Cruz", "Rowlett" o el nombre completo);
  el año ("en 2017" da 2017-01-01 → 2017-12-31); año-mes ("marzo de 2017" da
  2017-03-01 → 2017-03-31); y rangos ("entre 2016 y 2017", "entre marzo de 2017 y
  junio de 2017").
- **No soportados:** categoría (con sinónimos como "eléctricas" o "de montaña"),
  marca, estado (NY/CA/TX o su nombre), ciudad (195 ciudades de clientes, con una
  lista de exclusión para las que son palabras comunes: Vista, Corona, Victoria,
  Encino…), cliente y vendedor por nombre, varias tiendas, comparación de periodos
  ("2016 vs 2017"), trimestre/semestre y un top-N distinto del propio de la consulta
  (N1 y N4 = 10, N2 = 20). "Los últimos 6 meses" no se confunde con un top-6.
- `BusinessQuery.fixed_filters` evita falsos positivos: N3 ya es Electric Bikes, así
  que mencionar "eléctricas" no la saca de la ruta verificada.

`plan_route` decide la ruta:

| Situación | Ruta | `source` |
|---|---|---|
| Coincide con una necesidad y todos los filtros están soportados | SQL verificada con parámetros; `QueryResult.filters` lleva los filtros aplicados | `verificada` |
| Coincide, pero hay un filtro no soportado | LLM con la SQL verificada (renderizada con los filtros soportados) añadida al system prompt: "Consulta de referencia para esta necesidad (…) adáptala a la pregunta" | `llm_anclada` |
| No coincide | LLM normal | `llm` |

Pruebas: 10 casos con filtro soportado, 6 con filtro no soportado (categoría, estado,
marca, top-N, ciudad, varias tiendas), las 30 formulaciones de antes siguen verificadas
sin filtros, los fuera de tema van al LLM y hay un caso mixto (vendedor más tienda más
rango de meses).

### 10.4 N6: "Nunca vendido" frente a "Sin ventas recientes"

N6 tiene ahora la columna `estado_inventario`: "Nunca vendido" si el producto no tiene
ninguna venta completada en todo el histórico, y "Sin ventas recientes" si se vendió
antes pero no en la ventana.

**Cifras con la ventana por defecto** (2017-10-02 → 2018-03-31): **29 productos, los
29 "Nunca vendido"**, con 1,234 unidades y $1,891,217.66, y **0 "Sin ventas
recientes"**. Se verificó de forma independiente con pandas: de los 285 productos con
stock, todo el que alguna vez se vendió tuvo al menos una venta en la ventana. El más
"dormido" vendió por última vez el 2017-10-17. Con una ventana más corta
(ene–mar 2018) aparecen 22 "Sin ventas recientes". **Conclusión de negocio:** el
inventario inmovilizado no es mercancía que dejó de moverse; son modelos 2018 que
nunca se vendieron.

### 10.5 Iteraciones del prompt (qwen2.5:1.5b, nivel básico, solo LLM)

| Iteración | Cambio | Resultado | Fallos |
|---|---|---|---|
| 0 | Prompt de la Fase 2 | **7/10** (no cumple) | B2: omite `order_status = 4` aunque dice "ventas" · B7: usa `store_name` en `stocks` · B9: ignora "en 2017" y separa año y mes en dos columnas |
| 1 | Regla 3: "Toda pregunta de ventas, ingresos, ticket o unidades vendidas DEBE filtrar order_status = 4". Regla 4: "Si la pregunta menciona un año, filtra strftime('%Y', …) = 'AAAA'; para 'por mes' agrupa por strftime('%Y-%m', …) en una sola columna". Nota en el esquema: `stocks.store_id` no tiene store_name (JOIN stores). Few-shot 6: unidades de Electra por mes en 2016 (otra marca, otro año y otra métrica que B9) | **9/10** (cumple) | B7: sigue uniendo `stocks` con `products` en lugar de `stores`, también en el reintento |

Se detuvo en la iteración 1 porque el criterio (≥ 8/10) ya se cumplía. El prompt
final completo está en §3.6.
