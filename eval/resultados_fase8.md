# Resultados de la evaluación Text-to-SQL

- Fecha: 2026-10-12 09:11
- Equipo: Windows-11-10.0.26200-SP0 · Python 3.14.0
- Ollama: http://127.0.0.1:11434
- Exactitud por ejecución (ver `eval_text2sql.py`). *Latencia SQL* = enrutar + generar + validar + ejecutar. *Respuesta completa* = lo que espera el usuario (incluye la síntesis); solo se mide en el modo sistema completo.

## Resumen

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 2/4 | 10.2 | — | — | 0 |

## Criterios de aceptación (qwen2.5:1.5b)

- Básico, solo LLM >= 8/10: **9/10** CUMPLE

## Categorías de falla

Solo se clasifican los ítems incorrectos (los aciertos no se reclasifican). Orden: `error_ejecucion` (la consulta no se ejecutó), `tabla_columna_inexistente` (el error nombra una tabla o columna fuera del esquema), `agregacion_incorrecta` (se ejecuta, pero la forma del resultado o las agregaciones no coinciden con la referencia), `filtro_incorrecto` (mismo nivel de agregación, otro estado, fecha o nombre) y `otro`.

| Categoría | qwen2.5:1.5b · solo LLM | Total |
|---|---:|---:|
| `error_ejecucion` | 0 | 0 |
| `tabla_columna_inexistente` | 3 | 3 |
| `agregacion_incorrecta` | 7 | 7 |
| `filtro_incorrecto` | 0 | 0 |
| `otro` | 2 | 2 |

### Un ejemplo real por categoría

| Categoría | Modelo · modo | Ítem | Pregunta | SQL generada | Detalle |
|---|---|---|---|---|---|
| `error_ejecucion` | — | — | (sin casos) | — | — |
| `tabla_columna_inexistente` | qwen2.5:1.5b · solo LLM | B7 | ¿Cuántas unidades hay en inventario en cada tienda? | `SELECT store_name AS tienda, product_name AS producto, SUM(quantity) AS unidades FROM stocks JOIN products ON stocks.product_id = products.product_id GROUP BY tienda, producto ORDER BY tienda, producto` | no such column: store_name |
| `agregacion_incorrecta` | qwen2.5:1.5b · solo LLM | N2 | ¿Qué productos se venden mucho pero están a punto de agotarse en alguna tienda? | `SELECT p.product_name AS producto, st.quantity AS stock, st.quantity - v_order_lines.quantity AS stock_disponible FROM v_order_lines JOIN products p ON p.product_id = v_order_lines.product_id JOIN stocks st ON st.product` | agregación ((), 0) contra referencia (('Sum', 'Sum'), 0) |
| `filtro_incorrecto` | — | — | (sin casos) | — | — |
| `otro` | qwen2.5:1.5b · solo LLM | N3 | ¿Quiénes son nuestros mejores vendedores de bicicletas eléctricas? | `SELECT staff_name AS vendedor, COUNT(DISTINCT order_id) AS órdenes, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_order_lines JOIN staffs ON staffs.staff_id = v_order_lines.staff_id JOIN products ON products.product_i` | filas: esperadas 6, obtenidas 0 |

## Detalle

| Modelo | Modo | Ítem | Resultado | Fuente | Intentos | Latencia SQL (s) | Total (s) | Motivo |
|---|---|---|---|---|---:|---:|---:|---|
| qwen2.5:1.5b | solo LLM | B1 | ✅ | llm | 1 | 23.7 |  |  |
| qwen2.5:1.5b | solo LLM | B2 | ✅ | llm | 1 | 3.9 |  |  |
| qwen2.5:1.5b | solo LLM | B3 | ✅ | llm | 1 | 3.6 |  |  |
| qwen2.5:1.5b | solo LLM | B4 | ✅ | llm | 1 | 2.6 |  |  |
| qwen2.5:1.5b | solo LLM | B5 | ✅ | llm | 1 | 5.0 |  |  |
| qwen2.5:1.5b | solo LLM | B6 | ✅ | llm | 1 | 3.8 |  |  |
| qwen2.5:1.5b | solo LLM | B7 | ❌ | llm | 3 | 12.7 |  | Execution failed on sql 'SELECT store_name AS tienda, product_name AS producto, SUM(quanti |
| qwen2.5:1.5b | solo LLM | B8 | ✅ | llm | 1 | 2.7 |  |  |
| qwen2.5:1.5b | solo LLM | B9 | ✅ | llm | 1 | 4.3 |  |  |
| qwen2.5:1.5b | solo LLM | B10 | ✅ | llm | 1 | 2.4 |  |  |
| qwen2.5:1.5b | solo LLM | N1 | ✅ | llm | 1 | 3.1 |  |  |
| qwen2.5:1.5b | solo LLM | N2 | ❌ | llm | 3 | 16.4 |  | fila de referencia 1 no encontrada: ['surly ice cream truck frameset - 2016', 'santa cruz  |
| qwen2.5:1.5b | solo LLM | N3 | ❌ | llm | 3 | 18.7 |  | filas: esperadas 6, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | N4 | ❌ | llm | 3 | 11.3 |  | Execution failed on sql 'SELECT store_name, COUNT(DISTINCT order_id) AS ordenes, SUM(net_a |
| qwen2.5:1.5b | solo LLM | N5 | ❌ | llm | 3 | 20.4 |  | fila de referencia 1 no encontrada: ['baldwin bikes', 1430618.99] |
| qwen2.5:1.5b | solo LLM | N6 | ❌ | llm | 3 | 20.4 |  | Execution failed on sql 'SELECT      p.product_name AS producto,     s.quantity AS stock,  |
| qwen2.5:1.5b | solo LLM | N7 | ❌ | llm | 3 | 11.8 |  | fila de referencia 1 no encontrada: ['alesia horne', 5.0] |
| qwen2.5:1.5b | solo LLM | N8 | ❌ | llm | 3 | 13.6 |  | filas: esperadas 3, obtenidas 1 |
| qwen2.5:1.5b | solo LLM | N9 | ❌ | llm | 3 | 12.3 |  | fila de referencia 1 no encontrada: ['electric bikes', 9.69] |
| qwen2.5:1.5b | solo LLM | N10 | ❌ | llm | 3 | 11.6 |  | fila de referencia 1 no encontrada: [208579.45] |
| qwen2.5:1.5b | solo LLM | A1 | ❌ | llm | 3 | 14.7 |  | fila de referencia 1 no encontrada: ['baldwin bikes', 4845.27] |
| qwen2.5:1.5b | solo LLM | A2 | ✅ | llm | 1 | 7.9 |  |  |
| qwen2.5:1.5b | solo LLM | A3 | ❌ | llm | 3 | 14.4 |  | filas: esperadas 3, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | A4 | ✅ | llm | 1 | 2.4 |  |  |
