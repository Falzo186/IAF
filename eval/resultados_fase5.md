# Resultados de la evaluación Text-to-SQL

- Fecha: 2026-09-25 12:10
- Equipo: Windows-11-10.0.26200-SP0 · Python 3.14.0
- Ollama: http://127.0.0.1:11434
- Exactitud por ejecución (ver `eval_text2sql.py`). *Latencia SQL* = enrutar + generar + validar + ejecutar. *Respuesta completa* = lo que espera el usuario (incluye la síntesis); solo se mide en el modo sistema completo.

## Resumen

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 1/4 | 7.2 | — | — | 4 |
| qwen2.5:1.5b | sistema completo | 9/10 | 10/10 | 3/4 | 4.5 | 3.0 | 39.7 | 2 |

## Criterios de aceptación (qwen2.5:1.5b)

- Básico, solo LLM >= 8/10: **9/10** CUMPLE
- Negocio, sistema completo = 10/10: **10/10** CUMPLE

## Detalle

| Modelo | Modo | Ítem | Resultado | Fuente | Intentos | Latencia SQL (s) | Total (s) | Motivo |
|---|---|---|---|---|---:|---:|---:|---|
| qwen2.5:1.5b | solo LLM | B1 | ✅ | llm | 1 | 25.1 |  |  |
| qwen2.5:1.5b | solo LLM | B2 | ✅ | llm | 1 | 4.1 |  |  |
| qwen2.5:1.5b | solo LLM | B3 | ✅ | llm | 1 | 3.9 |  |  |
| qwen2.5:1.5b | solo LLM | B4 | ✅ | llm | 1 | 2.8 |  |  |
| qwen2.5:1.5b | solo LLM | B5 | ✅ | llm | 1 | 6.2 |  |  |
| qwen2.5:1.5b | solo LLM | B6 | ✅ | llm | 1 | 4.9 |  |  |
| qwen2.5:1.5b | solo LLM | B7 | ❌ | llm | 2 | 11.2 |  | Execution failed on sql 'SELECT store_name AS tienda, product_name AS producto, SUM(quanti |
| qwen2.5:1.5b | solo LLM | B8 | ✅ | llm | 1 | 3.2 |  |  |
| qwen2.5:1.5b | solo LLM | B9 | ✅ | llm | 1 | 6.1 |  |  |
| qwen2.5:1.5b | solo LLM | B10 | ✅ | llm | 1 | 3.3 |  |  |
| qwen2.5:1.5b | solo LLM | N1 | ✅ | llm | 1 | 5.7 |  |  |
| qwen2.5:1.5b | solo LLM | N2 | ❌ | llm | 2 | 17.7 |  | Execution failed on sql 'SELECT p.product_name AS producto, st.quantity AS stock, st.quant |
| qwen2.5:1.5b | solo LLM | N3 | ❌ | llm | 1 | 9.6 |  | filas: esperadas 6, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | N4 | ❌ | llm | 1 | 4.5 |  | fila de referencia 1 no encontrada: ['floral park', 30858.72] |
| qwen2.5:1.5b | solo LLM | N5 | ❌ | llm | 1 | 6.9 |  | fila de referencia 1 no encontrada: ['baldwin bikes', 1430618.99] |
| qwen2.5:1.5b | solo LLM | N6 | ❌ | llm | 1 | 7.4 |  | filas: esperadas 29, obtenidas 10 |
| qwen2.5:1.5b | solo LLM | N7 | ❌ | llm | 2 | 9.6 |  | Execution failed on sql 'SELECT customer_name, COUNT(DISTINCT product_name) AS marcas_comb |
| qwen2.5:1.5b | solo LLM | N8 | ❌ | llm | 1 | 4.2 |  | filas: esperadas 3, obtenidas 1 |
| qwen2.5:1.5b | solo LLM | N9 | ❌ | llm | 1 | 4.5 |  | fila de referencia 1 no encontrada: ['electric bikes', 9.69] |
| qwen2.5:1.5b | solo LLM | N10 | ❌ | llm | 1 | 3.1 |  | fila de referencia 1 no encontrada: [208579.45] |
| qwen2.5:1.5b | solo LLM | A1 | ❌ | llm | 1 | 4.9 |  | filas: esperadas 3, obtenidas 1 |
| qwen2.5:1.5b | solo LLM | A2 | ❌ | llm | 2 | 15.6 |  | Execution failed on sql 'SELECT product_name AS producto, list_price AS precio_bruto, list |
| qwen2.5:1.5b | solo LLM | A3 | ❌ | llm | 1 | 5.2 |  | filas: esperadas 3, obtenidas 0 |
| qwen2.5:1.5b | solo LLM | A4 | ✅ | llm | 1 | 2.8 |  |  |
| qwen2.5:1.5b | sistema completo | B1 | ✅ | llm | 1 | 2.1 | 2.1 |  |
| qwen2.5:1.5b | sistema completo | B2 | ✅ | llm | 1 | 3.9 | 3.9 |  |
| qwen2.5:1.5b | sistema completo | B3 | ✅ | llm | 1 | 4.1 | 15.5 |  |
| qwen2.5:1.5b | sistema completo | B4 | ✅ | llm | 1 | 2.4 | 9.4 |  |
| qwen2.5:1.5b | sistema completo | B5 | ✅ | llm | 1 | 5.8 | 10.1 |  |
| qwen2.5:1.5b | sistema completo | B6 | ✅ | llm | 1 | 6.1 | 4487.9 |  |
| qwen2.5:1.5b | sistema completo | B7 | ❌ | llm | 2 | 16.0 | 16.0 | Execution failed on sql 'SELECT store_name AS tienda, product_name AS producto, SUM(quanti |
| qwen2.5:1.5b | sistema completo | B8 | ✅ | llm | 1 | 5.2 | 5.2 |  |
| qwen2.5:1.5b | sistema completo | B9 | ✅ | llm | 1 | 9.8 | 27.3 |  |
| qwen2.5:1.5b | sistema completo | B10 | ✅ | llm | 1 | 3.0 | 3.0 |  |
| qwen2.5:1.5b | sistema completo | N1 | ✅ | verificada | 0 | 0.2 | 0.2 |  |
| qwen2.5:1.5b | sistema completo | N2 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N3 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N4 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N5 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N6 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N7 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N8 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N9 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| qwen2.5:1.5b | sistema completo | N10 | ✅ | verificada | 0 | 0.2 | 0.2 |  |
| qwen2.5:1.5b | sistema completo | A1 | ❌ | llm_anclada | 2 | 13.4 | 13.4 | Execution failed on sql 'SELECT store_name AS tienda, COUNT(*) AS ordenes,        ROUND(AV |
| qwen2.5:1.5b | sistema completo | A2 | ✅ | llm_anclada | 1 | 16.2 | 39.7 |  |
| qwen2.5:1.5b | sistema completo | A3 | ✅ | llm_anclada | 1 | 9.3 | 19.0 |  |
| qwen2.5:1.5b | sistema completo | A4 | ✅ | llm_anclada | 1 | 8.6 | 13.2 |  |
