# Validación de las preguntas de la demo

Generado por `python tools/validar_demo.py`. Cada repetición es **una conversación completa**
D1→D7 a través de `sql_engine.answer_question`, con el historial acumulado como en la app
(D5 es seguimiento de D4). Configuración de la app: `VERIFIED_SYNTHESIS = False` (las verificadas
responden con la frase calculada), `KEEP_ALIVE = 60m` y el modelo precalentado como lo deja
`bootstrap.py`. CPU sin GPU. **Apta para demo = 5/5 aciertos con qwen2.5:1.5b.**

| ID | Pregunta | Origen esperado | Origen obtenido (qwen) | qwen aciertos | qwen p50 / máx (s) | llama aciertos | llama p50 / máx (s) | ¿Apta? |
|---|---|---|---|---:|---:|---:|---:|---|
| D1 | ¿Qué productos se venden mucho pero están a punto de agotarse? | verificada | verificada | 5/5 | 0.2 / 0.2 | 2/2 | 0.1 / 0.1 | **Sí** |
| D2 | ¿Cuál es el ticket promedio por tienda en 2017? | verificada | verificada | 5/5 | 0.1 / 0.2 | 2/2 | 0.1 / 0.1 | **Sí** |
| D3 | Ticket promedio por tienda, pero solo en Electric Bikes | llm_anclada | llm_anclada | 0/5 | 10.6 / 11.5 | 0/2 | 23.9 / 24.6 | No |
| D4 | ¿Cuáles son las 5 marcas con más ingreso neto en 2017? | llm | llm | 5/5 | 10.7 / 12.1 | 0/2 | 13.2 / 13.5 | **Sí** |
| D5 | ¿Y en 2016? | llm | llm | 5/5 | 11.9 / 12.9 | 0/2 | 14.6 / 20.8 | **Sí** |
| D6 | ¿Cuánto dinero tenemos parado en inventario que nunca se vendió? | verificada | verificada | 5/5 | 0.1 / 0.2 | 2/2 | 0.2 / 0.2 | **Sí** |
| D7 | Borra todos los clientes de la base de datos | cualquiera | solo_lectura | 5/5 | 0.0 / 0.0 | 2/2 | 0.0 / 0.0 | **Sí** |

## Formulaciones alternativas (para las que no fueron 5/5)

| ID | Formulación | Origen (qwen) | qwen aciertos | qwen p50 / máx (s) | llama aciertos | ¿Apta? |
|---|---|---|---:|---:|---:|---|
| D3 | Por tienda, ¿cuál es el ingreso neto de Electric Bikes dividido entre el número de órdenes que lo incluyen? | llm | 0/5 | 8.6 / 8.9 | 0/2 | No |
| D3 | ¿Cuánto gastan en promedio por orden los clientes de Electric Bikes en cada tienda? | llm_anclada | 0/5 | 15.2 / 15.5 | 0/2 | No |
| D3 | Dame el top 3 de vendedores de bicicletas eléctricas por ingreso neto | llm_anclada | 5/5 | 13.8 / 19.0 | 2/2 | **Sí** |
| D3 | ¿Cuánto dinero perdimos por órdenes rechazadas de clientes de Texas? | llm_anclada | 5/5 | 9.2 / 11.5 | 0/2 | **Sí** |

## Secuencia recomendada para la demo

- **D1:** "¿Qué productos se venden mucho pero están a punto de agotarse?"
- **D2:** "¿Cuál es el ticket promedio por tienda en 2017?"
- **D3 → reemplazar por:** "Dame el top 3 de vendedores de bicicletas eléctricas por ingreso neto" (llm_anclada; 5/5 con qwen2.5:1.5b, 2/2 con llama3.2:1b). Motivo: No apta: 0/5 con qwen2.5:1.5b (y sus 2 reformulaciones). El modelo aplica category_name sobre v_orders o promedia líneas en vez de órdenes; ver demo/validacion_demo.md.
- **D4:** "¿Cuáles son las 5 marcas con más ingreso neto en 2017?"
- **D5:** "¿Y en 2016?"
- **D6:** "¿Cuánto dinero tenemos parado en inventario que nunca se vendió?"
- **D7:** "Borra todos los clientes de la base de datos"

## Respuesta textual (primera repetición de qwen2.5:1.5b)

- **D1** (verificada): 7 productos top están bajo 5 unidades en alguna tienda (10 casos); 3 ya en cero.
- **D2** (verificada): Rowlett Bikes tiene el ticket promedio más alto ($5,504.87) frente a $4,251.54 de Santa Cruz Bikes.
- **D3** (llm_anclada): No logré construir una consulta válida para esa pregunta. Intenta reformularla con más detalle, por ejemplo indicando el periodo, la tienda, la categoría o la métrica que te interesa.
- **D4** (llm): Las cinco marcas con mayores ingresos netos en 2017 son: 1. Trek: $2,124,167.94 2. Electra: $357,323.70 3. Surly: $339,621.60 4. Sun Bicycles: $286,949.29 5. Haro: $156,137.52
- **D5** (llm): En 2016, la marca Trek lideró la lista de ingresos netos con un monto de $1,135,493.16, seguida por Electra con $494,627.94, Surly con $462,843.56, Pure Cycles con $112,933.43 y Heller con $103,869.44.
- **D6** (verificada): 29 productos sin ventas recientes inmovilizan 1,234 unidades por $1,891,217.66; 29 nunca se han vendido.
- **D7** (solo_lectura): Solo puedo consultar los datos: la base de datos es de solo lectura y no modifico, borro ni agrego registros. Si quieres, te muestro esa información; por ejemplo, "¿cuántos clientes hay por estado?".

## Fallos observados

- qwen2.5:1.5b · D3 · rep. 1 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_pro — SQL: `SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_promedio FROM v_orders WHERE order_status = 4 AND category_name = 'Electri…`
- qwen2.5:1.5b · D3 · rep. 2 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_pro — SQL: `SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_promedio FROM v_orders WHERE order_status = 4 AND category_name = 'Electri…`
- qwen2.5:1.5b · D3 · rep. 3 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_pro — SQL: `SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_promedio FROM v_orders WHERE order_status = 4 AND category_name = 'Electri…`
- qwen2.5:1.5b · D3 · rep. 4 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_pro — SQL: `SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_promedio FROM v_orders WHERE order_status = 4 AND category_name = 'Electri…`
- qwen2.5:1.5b · D3 · rep. 5 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_pro — SQL: `SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS ticket_promedio FROM v_orders WHERE order_status = 4 AND category_name = 'Electri…`
- llama3.2:1b · D3 · rep. 1 · llm_anclada: error: TokenError: Error tokenizing 'tore_name ORDER BY ticket_promedio DESC LIMIT ' — SQL: `SELECT s.store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(CASE WHEN p.brand_name = 'Electra THEN net_amount ELSE 0 END), 2) AS ticket_promedio FROM v_order…`
- llama3.2:1b · D4 · rep. 1 · llm: fila de referencia 1 no encontrada: ['trek', 2124167.94] — SQL: `SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY ingreso_neto DESC …`
- llama3.2:1b · D5 · rep. 1 · llm: fila de referencia 1 no encontrada: ['trek', 1135493.16] — SQL: `SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY ingreso_neto DESC …`
- llama3.2:1b · D3 · rep. 2 · llm_anclada: error: TokenError: Error tokenizing 'tore_name ORDER BY ticket_promedio DESC LIMIT ' — SQL: `SELECT s.store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(CASE WHEN p.brand_name = 'Electra THEN net_amount ELSE 0 END), 2) AS ticket_promedio FROM v_order…`
- llama3.2:1b · D4 · rep. 2 · llm: fila de referencia 1 no encontrada: ['trek', 2124167.94] — SQL: `SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY ingreso_neto DESC …`
- llama3.2:1b · D5 · rep. 2 · llm: fila de referencia 1 no encontrada: ['trek', 1135493.16] — SQL: `SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY ingreso_neto DESC …`
- qwen2.5:1.5b · D3* · rep. 1 · llm: error: Execution failed on sql 'SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order — SQL: `SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND category_name = 'Electric Bikes' GROUP BY store_…`
- qwen2.5:1.5b · D3* · rep. 1 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines — SQL: `SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines ol ON ol.order_id = v_orders.order_id JOIN products p ON p.produ…`
- qwen2.5:1.5b · D3* · rep. 2 · llm: error: Execution failed on sql 'SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order — SQL: `SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND category_name = 'Electric Bikes' GROUP BY store_…`
- qwen2.5:1.5b · D3* · rep. 2 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines — SQL: `SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines ol ON ol.order_id = v_orders.order_id JOIN products p ON p.produ…`
- qwen2.5:1.5b · D3* · rep. 3 · llm: error: Execution failed on sql 'SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order — SQL: `SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND category_name = 'Electric Bikes' GROUP BY store_…`
- qwen2.5:1.5b · D3* · rep. 3 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines — SQL: `SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines ol ON ol.order_id = v_orders.order_id JOIN products p ON p.produ…`
- qwen2.5:1.5b · D3* · rep. 4 · llm: error: Execution failed on sql 'SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order — SQL: `SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND category_name = 'Electric Bikes' GROUP BY store_…`
- qwen2.5:1.5b · D3* · rep. 4 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines — SQL: `SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines ol ON ol.order_id = v_orders.order_id JOIN products p ON p.produ…`
- qwen2.5:1.5b · D3* · rep. 5 · llm: error: Execution failed on sql 'SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order — SQL: `SELECT store_name AS tienda, ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND category_name = 'Electric Bikes' GROUP BY store_…`
- qwen2.5:1.5b · D3* · rep. 5 · llm_anclada: error: Execution failed on sql 'SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines — SQL: `SELECT store_name AS tienda, AVG(net_total) AS promedio_gasto FROM v_orders JOIN v_order_lines ol ON ol.order_id = v_orders.order_id JOIN products p ON p.produ…`
- llama3.2:1b · D3* · rep. 1 · llm: filas: esperadas 3, obtenidas 1 — SQL: `SELECT s.store_name AS tienda, ROUND(SUM(net_amount) / COUNT(*), 2) AS ingreso_neto FROM v_order_lines vl JOIN v_orders v ON vl.order_id = v.order_id JOIN stoc…`
- llama3.2:1b · D3* · rep. 1 · llm_anclada: filas: esperadas 3, obtenidas 1 — SQL: `SELECT s.store_name AS tienda, SUM(ol.list_price * ol.quantity) AS total_gasto, COUNT(DISTINCT o.customer_id) AS clientes, ROUND(AVG(ol.list_price * ol.quantit…`
- llama3.2:1b · D3* · rep. 1 · llm_anclada: fila de referencia 1 no encontrada: [86018.94] — SQL: `SELECT * FROM v_orders WHERE order_status = 3 AND strftime('%Y', order_date) = '2017' AND strftime('%Y', customer_city) = 'TX' LIMIT 500`
- llama3.2:1b · D3* · rep. 2 · llm: filas: esperadas 3, obtenidas 1 — SQL: `SELECT s.store_name AS tienda, ROUND(SUM(net_amount) / COUNT(*), 2) AS ingreso_neto FROM v_order_lines vl JOIN v_orders v ON vl.order_id = v.order_id JOIN stoc…`
- llama3.2:1b · D3* · rep. 2 · llm_anclada: filas: esperadas 3, obtenidas 1 — SQL: `SELECT s.store_name AS tienda, SUM(ol.list_price * ol.quantity) AS total_gasto, COUNT(DISTINCT o.customer_id) AS clientes, ROUND(AVG(ol.list_price * ol.quantit…`
- llama3.2:1b · D3* · rep. 2 · llm_anclada: fila de referencia 1 no encontrada: [86018.94] — SQL: `SELECT * FROM v_orders WHERE order_status = 3 AND strftime('%Y', order_date) = '2017' AND strftime('%Y', customer_city) = 'TX' LIMIT 500`
