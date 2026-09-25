# Resultados de la evaluación Text-to-SQL

- Fecha: 2026-09-24 11:40
- Equipo: Windows-11-10.0.26200-SP0 · Python 3.14.0
- Ollama: http://localhost:11434
- Exactitud por ejecución (ver `eval_text2sql.py`). *Latencia SQL* = enrutar + generar + validar + ejecutar. *Respuesta completa* = lo que espera el usuario (incluye la síntesis); solo se mide en el modo sistema completo.

## Resumen

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 1/4 | 5.3 | — | — | 5 |
| qwen2.5:1.5b | sistema completo | 9/10 | 10/10 | 3/4 | 4.0 | 11.4 | 21.4 | 2 |
| llama3.2:1b | solo LLM | 6/10 | 0/10 | 0/4 | 28.0 | — | — | 11 |
| llama3.2:1b | sistema completo | 6/10 | 10/10 | 1/4 | 10.8 | 15.1 | 38.8 | 4 |
| deepseek-r1:1.5b | solo LLM | 0/10 | 0/10 | 0/4 | 43.8 | — | — | 22 |
| deepseek-r1:1.5b | sistema completo | 1/10 | 10/10 | 0/4 | 24.6 | 31.4 | 55.6 | 12 |

## Criterios de aceptación (qwen2.5:1.5b)

- Básico, solo LLM >= 8/10: **9/10** CUMPLE
- Negocio, sistema completo = 10/10: **10/10** CUMPLE

## Detalle

| Modelo | Modo | Ítem | Resultado | Fuente | Intentos | Latencia SQL (s) | Total (s) | Motivo |
|---|---|---|---|---|---:|---:|---:|---|
| qwen2.5:1.5b | solo LLM | B1 | ✅ | llm | 1 | 19.4 |  |  |
| qwen2.5:1.5b | solo LLM | B2 | ✅ | llm | 1 | 2.5 |  |  |
| qwen2.5:1.5b | solo LLM | B3 | ✅ | llm | 1 | 2.5 |  |  |
| qwen2.5:1.5b | solo LLM | B4 | ✅ | llm | 1 | 1.7 |  |  |
| qwen2.5:1.5b | solo LLM | B5 | ✅ | llm | 1 | 4.5 |  |  |
| qwen2.5:1.5b | solo LLM | B6 | ✅ | llm | 1 | 3.4 |  |  |
| qwen2.5:1.5b | solo LLM | B7 | ❌ | llm | 2 | 7.1 |  | Execution failed on sql 'SELECT store_name AS tienda, product_name AS producto, SUM(quanti |
| qwen2.5:1.5b | solo LLM | B8 | ✅ | llm | 1 | 2.3 |  |  |
| qwen2.5:1.5b | solo LLM | B9 | ✅ | llm | 1 | 3.4 |  |  |
| qwen2.5:1.5b | solo LLM | B10 | ✅ | llm | 1 | 2.2 |  |  |
| qwen2.5:1.5b | solo LLM | N1 | ✅ | llm | 1 | 2.8 |  |  |
| qwen2.5:1.5b | solo LLM | N2 | ❌ | llm | 2 | 10.2 |  | Execution failed on sql 'SELECT p.product_name AS producto, st.quantity AS stock, st.quant |
| qwen2.5:1.5b | solo LLM | N3 | ❌ | llm | 1 | 4.2 |  | filas: esperadas 6, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | N4 | ❌ | llm | 1 | 2.9 |  | fila de referencia 1 no encontrada: ['floral park', 30858.72] |
| qwen2.5:1.5b | solo LLM | N5 | ❌ | llm | 1 | 4.7 |  | fila de referencia 1 no encontrada: ['baldwin bikes', 1430618.99] |
| qwen2.5:1.5b | solo LLM | N6 | ❌ | llm | 2 | 16.5 |  | Execution failed on sql 'SELECT      p.product_name AS producto,     s.quantity AS stock,  |
| qwen2.5:1.5b | solo LLM | N7 | ❌ | llm | 2 | 7.8 |  | Execution failed on sql 'SELECT customer_name AS cliente, COUNT(DISTINCT product_name) AS  |
| qwen2.5:1.5b | solo LLM | N8 | ❌ | llm | 1 | 3.6 |  | filas: esperadas 3, obtenidas 1 |
| qwen2.5:1.5b | solo LLM | N9 | ❌ | llm | 1 | 3.5 |  | fila de referencia 1 no encontrada: ['electric bikes', 9.69] |
| qwen2.5:1.5b | solo LLM | N10 | ❌ | llm | 1 | 2.1 |  | fila de referencia 1 no encontrada: [208579.45] |
| qwen2.5:1.5b | solo LLM | A1 | ❌ | llm | 1 | 3.2 |  | filas: esperadas 3, obtenidas 1 |
| qwen2.5:1.5b | solo LLM | A2 | ❌ | llm | 2 | 10.7 |  | Execution failed on sql 'SELECT brand_name AS marca, product_name AS producto, list_price  |
| qwen2.5:1.5b | solo LLM | A3 | ❌ | llm | 1 | 3.6 |  | filas: esperadas 3, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | A4 | ✅ | llm | 1 | 2.0 |  |  |
| qwen2.5:1.5b | sistema completo | B1 | ✅ | llm | 1 | 1.8 | 1.8 |  |
| qwen2.5:1.5b | sistema completo | B2 | ✅ | llm | 1 | 2.7 | 2.7 |  |
| qwen2.5:1.5b | sistema completo | B3 | ✅ | llm | 1 | 3.2 | 13.2 |  |
| qwen2.5:1.5b | sistema completo | B4 | ✅ | llm | 1 | 1.8 | 12.6 |  |
| qwen2.5:1.5b | sistema completo | B5 | ✅ | llm | 1 | 17.2 | 21.4 |  |
| qwen2.5:1.5b | sistema completo | B6 | ✅ | llm | 1 | 3.2 | 12.1 |  |
| qwen2.5:1.5b | sistema completo | B7 | ❌ | llm | 2 | 16.7 | 16.7 | Execution failed on sql 'SELECT store_name AS tienda, product_name AS producto, SUM(quanti |
| qwen2.5:1.5b | sistema completo | B8 | ✅ | llm | 1 | 2.1 | 2.1 |  |
| qwen2.5:1.5b | sistema completo | B9 | ✅ | llm | 1 | 3.5 | 17.8 |  |
| qwen2.5:1.5b | sistema completo | B10 | ✅ | llm | 1 | 2.8 | 2.8 |  |
| qwen2.5:1.5b | sistema completo | N1 | ✅ | verificada | 0 | 0.2 | 17.5 |  |
| qwen2.5:1.5b | sistema completo | N2 | ✅ | verificada | 0 | 0.2 | 10.7 |  |
| qwen2.5:1.5b | sistema completo | N3 | ✅ | verificada | 0 | 0.2 | 8.2 |  |
| qwen2.5:1.5b | sistema completo | N4 | ✅ | verificada | 0 | 0.2 | 10.4 |  |
| qwen2.5:1.5b | sistema completo | N5 | ✅ | verificada | 0 | 0.3 | 20.5 |  |
| qwen2.5:1.5b | sistema completo | N6 | ✅ | verificada | 0 | 0.2 | 14.1 |  |
| qwen2.5:1.5b | sistema completo | N7 | ✅ | verificada | 0 | 0.2 | 9.1 |  |
| qwen2.5:1.5b | sistema completo | N8 | ✅ | verificada | 0 | 0.2 | 18.2 |  |
| qwen2.5:1.5b | sistema completo | N9 | ✅ | verificada | 0 | 0.2 | 11.3 |  |
| qwen2.5:1.5b | sistema completo | N10 | ✅ | verificada | 0 | 0.2 | 10.5 |  |
| qwen2.5:1.5b | sistema completo | A1 | ❌ | llm_anclada | 2 | 10.5 | 10.5 | Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes,        ROUND(AV |
| qwen2.5:1.5b | sistema completo | A2 | ✅ | llm_anclada | 1 | 13.1 | 33.2 |  |
| qwen2.5:1.5b | sistema completo | A3 | ✅ | llm_anclada | 1 | 6.9 | 18.3 |  |
| qwen2.5:1.5b | sistema completo | A4 | ✅ | llm_anclada | 1 | 7.3 | 11.4 |  |
| llama3.2:1b | solo LLM | B1 | ✅ | llm | 1 | 27.7 |  |  |
| llama3.2:1b | solo LLM | B2 | ❌ | llm | 1 | 32.9 |  | filas: esperadas 1, obtenidas 500 |
| llama3.2:1b | solo LLM | B3 | ✅ | llm | 1 | 7.2 |  |  |
| llama3.2:1b | solo LLM | B4 | ✅ | llm | 1 | 7.9 |  |  |
| llama3.2:1b | solo LLM | B5 | ✅ | llm | 2 | 25.8 |  |  |
| llama3.2:1b | solo LLM | B6 | ✅ | llm | 1 | 7.3 |  |  |
| llama3.2:1b | solo LLM | B7 | ❌ | llm | 2 | 30.1 |  | Execution failed on sql 'SELECT s.store_name, s.store_id, st.quantity, COALESCE(st.quantit |
| llama3.2:1b | solo LLM | B8 | ✅ | llm | 1 | 6.1 |  |  |
| llama3.2:1b | solo LLM | B9 | ❌ | llm | 2 | 38.9 |  | Execution failed on sql 'SELECT    strftime('%Y', order_date) AS mes,   ROUND(SUM(net_amou |
| llama3.2:1b | solo LLM | B10 | ❌ | llm | 1 | 26.7 |  | fila de referencia 1 no encontrada: [2500.06] |
| llama3.2:1b | solo LLM | N1 | ❌ | llm | 2 | 37.2 |  | SQL con errores de sintaxis: Invalid expression / Unexpected token. Line 8, Col: 12. |
| llama3.2:1b | solo LLM | N2 | ❌ | llm | 2 | 39.5 |  | La tabla o vista 'v_stocks' no existe. |
| llama3.2:1b | solo LLM | N3 | ❌ | llm | 2 | 46.0 |  | Execution failed on sql 'SELECT    p.product_name AS producto,    s.store_name AS tienda,  |
| llama3.2:1b | solo LLM | N4 | ❌ | llm | 2 | 44.5 |  | Execution failed on sql 'SELECT    c.city,    SUM(o.net_amount) AS total_ventas,    SUM(o. |
| llama3.2:1b | solo LLM | N5 | ❌ | llm | 1 | 30.7 |  | fila de referencia 1 no encontrada: ['baldwin bikes', 1430618.99] |
| llama3.2:1b | solo LLM | N6 | ❌ | llm | 2 | 32.8 |  | SQL con errores de sintaxis: Invalid expression / Unexpected token. Line 13, Col: 31. |
| llama3.2:1b | solo LLM | N7 | ❌ | llm | 1 | 31.0 |  | fila de referencia 1 no encontrada: ['alesia horne', 5.0] |
| llama3.2:1b | solo LLM | N8 | ❌ | llm | 2 | 44.2 |  | La tabla o vista 'pedidos' no existe. |
| llama3.2:1b | solo LLM | N9 | ❌ | llm | 2 | 46.4 |  | La tabla o vista 'categorias' no existe. |
| llama3.2:1b | solo LLM | N10 | ❌ | llm | 1 | 30.2 |  | fila de referencia 1 no encontrada: [208579.45] |
| llama3.2:1b | solo LLM | A1 | ❌ | llm | 1 | 8.9 |  | filas: esperadas 3, obtenidas 1 |
| llama3.2:1b | solo LLM | A2 | ❌ | llm | 2 | 26.0 |  | fila de referencia 1 no encontrada: ['trek slash 8 27.5 - 2016'] |
| llama3.2:1b | solo LLM | A3 | ❌ | llm | 1 | 13.5 |  | fila de referencia 1 no encontrada: ['marcelene boyer'] |
| llama3.2:1b | solo LLM | A4 | ❌ | llm | 1 | 30.4 |  | fila de referencia 1 no encontrada: [86018.94] |
| llama3.2:1b | sistema completo | B1 | ✅ | llm | 1 | 2.3 | 2.3 |  |
| llama3.2:1b | sistema completo | B2 | ❌ | llm | 1 | 28.5 | 55.4 | filas: esperadas 1, obtenidas 500 |
| llama3.2:1b | sistema completo | B3 | ✅ | llm | 1 | 6.6 | 16.7 |  |
| llama3.2:1b | sistema completo | B4 | ✅ | llm | 1 | 6.9 | 9.2 |  |
| llama3.2:1b | sistema completo | B5 | ✅ | llm | 2 | 24.4 | 28.6 |  |
| llama3.2:1b | sistema completo | B6 | ✅ | llm | 1 | 6.7 | 16.3 |  |
| llama3.2:1b | sistema completo | B7 | ❌ | llm | 2 | 28.6 | 28.6 | Execution failed on sql 'SELECT s.store_name, s.store_id, st.quantity, COALESCE(st.quantit |
| llama3.2:1b | sistema completo | B8 | ✅ | llm | 1 | 6.5 | 6.5 |  |
| llama3.2:1b | sistema completo | B9 | ❌ | llm | 2 | 38.8 | 38.8 | Execution failed on sql 'SELECT    strftime('%Y', order_date) AS mes,   ROUND(SUM(net_amou |
| llama3.2:1b | sistema completo | B10 | ❌ | llm | 1 | 22.6 | 22.6 | fila de referencia 1 no encontrada: [2500.06] |
| llama3.2:1b | sistema completo | N1 | ✅ | verificada | 0 | 0.1 | 31.0 |  |
| llama3.2:1b | sistema completo | N2 | ✅ | verificada | 0 | 0.2 | 22.3 |  |
| llama3.2:1b | sistema completo | N3 | ✅ | verificada | 0 | 0.2 | 7.2 |  |
| llama3.2:1b | sistema completo | N4 | ✅ | verificada | 0 | 0.3 | 15.1 |  |
| llama3.2:1b | sistema completo | N5 | ✅ | verificada | 0 | 0.2 | 9.3 |  |
| llama3.2:1b | sistema completo | N6 | ✅ | verificada | 0 | 0.2 | 29.3 |  |
| llama3.2:1b | sistema completo | N7 | ✅ | verificada | 0 | 0.2 | 11.7 |  |
| llama3.2:1b | sistema completo | N8 | ✅ | verificada | 0 | 0.1 | 2.7 |  |
| llama3.2:1b | sistema completo | N9 | ✅ | verificada | 0 | 0.2 | 11.0 |  |
| llama3.2:1b | sistema completo | N10 | ✅ | verificada | 0 | 0.2 | 7.0 |  |
| llama3.2:1b | sistema completo | A1 | ❌ | llm_anclada | 1 | 9.5 | 13.6 | filas: esperadas 3, obtenidas 11 |
| llama3.2:1b | sistema completo | A2 | ❌ | llm_anclada | 2 | 33.5 | 33.5 | Execution failed on sql 'SELECT AS ingreso_bruto_descuento FROM (     SELECT product_name, |
| llama3.2:1b | sistema completo | A3 | ✅ | llm_anclada | 1 | 9.3 | 14.2 |  |
| llama3.2:1b | sistema completo | A4 | ❌ | llm_anclada | 1 | 31.9 | 31.9 | fila de referencia 1 no encontrada: [86018.94] |
| deepseek-r1:1.5b | solo LLM | B1 | ❌ | llm | 1 | 43.9 |  | fila de referencia 1 no encontrada: [1019.0] |
| deepseek-r1:1.5b | solo LLM | B2 | ❌ | llm | 2 | 42.6 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | B3 | ❌ | llm | 2 | 42.5 |  | Execution failed on sql 'SELECT p.product_name AS producto, SUM(p.quantity) AS unidades FR |
| deepseek-r1:1.5b | solo LLM | B4 | ❌ | llm | 2 | 43.7 |  | fila de referencia 1 no encontrada: [62.0] |
| deepseek-r1:1.5b | solo LLM | B5 | ❌ | llm | 2 | 44.1 |  | Execution failed on sql 'SELECT s LIMIT 500': no such column: s |
| deepseek-r1:1.5b | solo LLM | B6 | ❌ | llm | 2 | 42.3 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | B7 | ❌ | llm | 2 | 44.6 |  | Execution failed on sql 'SELECT s.store_name, SUM(p.quantity) AS unidades FROM v_orders o  |
| deepseek-r1:1.5b | solo LLM | B8 | ❌ | llm | 2 | 45.1 |  | Execution failed on sql 'SELECT COUNT(*) AS ordenes_completados FROM v_orders WHERE order_ |
| deepseek-r1:1.5b | solo LLM | B9 | ❌ | llm | 1 | 28.9 |  | filas: esperadas 12, obtenidas 1 |
| deepseek-r1:1.5b | solo LLM | B10 | ❌ | llm | 2 | 49.6 |  | Execution failed on sql 'SELECT SUM(list_price) / COUNT(1) AS avg_list_price FROM products |
| deepseek-r1:1.5b | solo LLM | N1 | ❌ | llm | 2 | 43.8 |  | SQL con errores de sintaxis: Invalid expression / Unexpected token. Line 5, Col: 5. |
| deepseek-r1:1.5b | solo LLM | N2 | ❌ | llm | 2 | 42.3 |  | SQL con errores de sintaxis: Expecting ). Line 2, Col: 79. |
| deepseek-r1:1.5b | solo LLM | N3 | ❌ | llm | 2 | 43.3 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | N4 | ❌ | llm | 2 | 43.3 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | N5 | ❌ | llm | 2 | 46.4 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | N6 | ❌ | llm | 2 | 47.5 |  | Execution failed on sql 'SELECT      brand_name AS brand,      ROUND(SUM(net_amount), 2) A |
| deepseek-r1:1.5b | solo LLM | N7 | ❌ | llm | 2 | 45.6 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | N8 | ❌ | llm | 2 | 42.4 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | N9 | ❌ | llm | 2 | 46.3 |  | Execution failed on sql 'SELECT      c.category_name LIMIT 500': no such column: c.categor |
| deepseek-r1:1.5b | solo LLM | N10 | ❌ | llm | 2 | 45.9 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | A1 | ❌ | llm | 2 | 41.7 |  | SQL con errores de sintaxis: Required keyword: 'expression' missing for <class 'sqlglot.ex |
| deepseek-r1:1.5b | solo LLM | A2 | ❌ | llm | 2 | 46.6 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | solo LLM | A3 | ❌ | llm | 2 | 47.7 |  | Execution failed on sql 'SELECT store_name, ROUND(SUM(net_total), 2) AS ingreso_neto, net_ |
| deepseek-r1:1.5b | solo LLM | A4 | ❌ | llm | 2 | 41.7 |  | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | sistema completo | B1 | ✅ | llm | 1 | 22.2 | 22.2 |  |
| deepseek-r1:1.5b | sistema completo | B2 | ❌ | llm | 2 | 42.1 | 42.1 | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | sistema completo | B3 | ❌ | llm | 2 | 45.6 | 45.6 | Execution failed on sql 'SELECT p.product_name AS producto, SUM(p.quantity) AS unidades FR |
| deepseek-r1:1.5b | sistema completo | B4 | ❌ | llm | 2 | 43.2 | 55.6 | fila de referencia 1 no encontrada: [62.0] |
| deepseek-r1:1.5b | sistema completo | B5 | ❌ | llm | 2 | 40.9 | 40.9 | Execution failed on sql 'SELECT s LIMIT 500': no such column: s |
| deepseek-r1:1.5b | sistema completo | B6 | ❌ | llm | 2 | 45.0 | 45.0 | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | sistema completo | B7 | ❌ | llm | 2 | 45.9 | 45.9 | Execution failed on sql 'SELECT s.store_name, SUM(p.quantity) AS unidades FROM v_orders o  |
| deepseek-r1:1.5b | sistema completo | B8 | ❌ | llm | 2 | 39.9 | 39.9 | Execution failed on sql 'SELECT COUNT(*) AS ordenes_completados FROM v_orders WHERE order_ |
| deepseek-r1:1.5b | sistema completo | B9 | ❌ | llm | 1 | 19.4 | 31.4 | filas: esperadas 12, obtenidas 1 |
| deepseek-r1:1.5b | sistema completo | B10 | ❌ | llm | 2 | 44.0 | 44.0 | Execution failed on sql 'SELECT SUM(list_price) / COUNT(1) AS avg_list_price FROM products |
| deepseek-r1:1.5b | sistema completo | N1 | ✅ | verificada | 0 | 0.1 | 24.4 |  |
| deepseek-r1:1.5b | sistema completo | N2 | ✅ | verificada | 0 | 0.2 | 16.2 |  |
| deepseek-r1:1.5b | sistema completo | N3 | ✅ | verificada | 0 | 0.2 | 15.4 |  |
| deepseek-r1:1.5b | sistema completo | N4 | ✅ | verificada | 0 | 0.2 | 17.6 |  |
| deepseek-r1:1.5b | sistema completo | N5 | ✅ | verificada | 0 | 0.2 | 13.2 |  |
| deepseek-r1:1.5b | sistema completo | N6 | ✅ | verificada | 0 | 0.1 | 23.2 |  |
| deepseek-r1:1.5b | sistema completo | N7 | ✅ | verificada | 0 | 0.1 | 13.8 |  |
| deepseek-r1:1.5b | sistema completo | N8 | ✅ | verificada | 0 | 0.2 | 11.8 |  |
| deepseek-r1:1.5b | sistema completo | N9 | ✅ | verificada | 0 | 0.1 | 16.9 |  |
| deepseek-r1:1.5b | sistema completo | N10 | ✅ | verificada | 0 | 0.2 | 16.2 |  |
| deepseek-r1:1.5b | sistema completo | A1 | ❌ | llm_anclada | 2 | 44.1 | 44.1 | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | sistema completo | A2 | ❌ | llm_anclada | 2 | 57.1 | 57.1 | Execution failed on sql 'SELECT p.product_name AS producto, st.quantity AS stock, st.quant |
| deepseek-r1:1.5b | sistema completo | A3 | ❌ | llm_anclada | 2 | 50.6 | 50.6 | La respuesta del modelo no contiene ninguna consulta SQL. |
| deepseek-r1:1.5b | sistema completo | A4 | ❌ | llm_anclada | 2 | 48.3 | 48.3 | SQL con errores de sintaxis: Invalid expression / Unexpected token. Line 10, Col: 22. |
