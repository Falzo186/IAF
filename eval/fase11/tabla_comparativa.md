# Fase 11: Base | Few shot | RAG | Harness 

- Fecha: 2026-10-25 17:57 · Windows-11-10.0.26300-SP0 · Python 3.12.5 · commit `c011903`
- Modo de red: **offline** · conexiones externas intentadas: **0**
- Catálogo `8b2e39e4039e9fee` (138 ejemplos; train 93, heldout 45) · golden `1e5be7623198`
- Intentos máx.: 2 · reparación: produccion · repeticiones: 1 · temperatura 0 · RAG_MIN_SCORE 0.3 · FEWSHOT_MAX_CHARS 2400
- Corrección por `compare_results` (determinista). Política oficial de ejemplos: **sin_gemelas** (ver docstring de `eval_fase11.py`).

## Tabla comparativa (política oficial: sin_gemelas)

| Modelo | Conjunto | Base | Few shot | RAG | Harness |
|---|---|---|---|---|---|
| qwen2.5:1.5b | Golden (24) | 11/24 (46 %) | 10/24 (42 %) | 10/24 (42 %) | 12/24 (50 %) |
| qwen2.5:1.5b | Heldout | 6/45 (13 %) | 16/45 (36 %) | 12/45 (27 %) | 14/45 (31 %) |

### Variantes

| Modelo | Conjunto | Few shot (estático) | Harness + router |
|---|---|---|---|
| qwen2.5:1.5b | Golden (24) | 11/24 (46 %) | 20/24 (83 %) |
| qwen2.5:1.5b | Heldout | 7/45 (16 %) | 28/45 (62 %) |

## Política permisiva (cota superior: un hermano con la misma SQL puede aparecer)

| Modelo | Conjunto | Base | Few shot | RAG | Harness |
|---|---|---|---|---|---|
| qwen2.5:1.5b | Golden (24) | 11/24 (46 %) | 13/24 (54 %) | 12/24 (50 %) | 13/24 (54 %) |
| qwen2.5:1.5b | Heldout | 6/45 (13 %) | 16/45 (36 %) | 17/45 (38 %) | 14/45 (31 %) |

## Política estricta (sin ningún ejemplo de la misma necesidad)

| Modelo | Conjunto | Base | Few shot | RAG | Harness |
|---|---|---|---|---|---|
| qwen2.5:1.5b | Golden (24) | 11/24 (46 %) | 10/24 (42 %) | 10/24 (42 %) | 10/24 (42 %) |
| qwen2.5:1.5b | Heldout | 6/45 (13 %) | 4/45 (9 %) | 4/45 (9 %) | 2/45 (4 %) |

## Calidad de la SQL y costo (política oficial)

| Modelo | Modo | Conjunto | Aciertos | SQL ejecutable | Columnas inventadas | Intentos prom. | p50 (s) | p95 (s) | RAM Ollama (MB) |
|---|---|---|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | Base | golden | 11/24 (46 %) | 79 % | 17 % | 1.21 | 0.5 | 2.6 | 91.6 |
| qwen2.5:1.5b | Base | negativas_heldout | 6/45 (13 %) | 73 % | 22 % | 1.36 | 0.8 | 1.7 | 91.6 |
| qwen2.5:1.5b | Few shot | golden | 10/24 (42 %) | 75 % | 25 % | 1.29 | 0.9 | 2.8 | 91.6 |
| qwen2.5:1.5b | Few shot | negativas_heldout | 16/45 (36 %) | 87 % | 11 % | 1.16 | 1.4 | 3.2 | 91.6 |
| qwen2.5:1.5b | Few shot (estático) | golden | 11/24 (46 %) | 83 % | 17 % | 1.29 | 1.0 | 2.2 | 91.6 |
| qwen2.5:1.5b | Few shot (estático) | negativas_heldout | 7/45 (16 %) | 76 % | 20 % | 1.33 | 1.2 | 2.2 | 91.6 |
| qwen2.5:1.5b | Harness | golden | 12/24 (50 %) | 79 % | 21 % | 1.29 | 0.9 | 2.9 | 91.6 |
| qwen2.5:1.5b | Harness | negativas_heldout | 14/45 (31 %) | 73 % | 22 % | 1.29 | 1.3 | 3.0 | 91.6 |
| qwen2.5:1.5b | Harness + router | golden | 20/24 (83 %) | 88 % | 12 % | 0.75 | 0.5 | 1.1 | 91.6 |
| qwen2.5:1.5b | Harness + router | negativas_heldout | 28/45 (62 %) | 82 % | 13 % | 0.64 | 0.1 | 2.9 | 91.6 |
| qwen2.5:1.5b | RAG | golden | 10/24 (42 %) | 67 % | 33 % | 1.38 | 1.0 | 2.2 | 91.6 |
| qwen2.5:1.5b | RAG | negativas_heldout | 12/45 (27 %) | 78 % | 16 % | 1.24 | 1.3 | 3.2 | 91.6 |

## Vistas vs no vistas

*Vistas*: preguntas de una necesidad cuyos hermanos están en el catálogo (golden N1-N10 y todo el heldout). *No vistas*: golden básico y anclada (el catálogo no tiene su tipo) y cualquier ítem bajo la política estricta. Se muestran las tres políticas de ejemplos: con `permisivo` puede aparecer un hermano con la misma SQL.

| Modelo | Modo | Política | Golden negocio (vistas) | Golden básico+anclada (no vistas) | Heldout (vistas) |
|---|---|---|---|---|---|
| qwen2.5:1.5b | Base | n/a | 1/10 (10 %) | 10/14 (71 %) | 6/45 (13 %) |
| qwen2.5:1.5b | Few shot | sin_gemelas | 1/10 (10 %) | 9/14 (64 %) | 16/45 (36 %) |
| qwen2.5:1.5b | Few shot | permisivo | 4/10 (40 %) | 9/14 (64 %) | 16/45 (36 %) |
| qwen2.5:1.5b | Few shot | estricto | 1/10 (10 %) | 9/14 (64 %) | 4/45 (9 %) |
| qwen2.5:1.5b | RAG | sin_gemelas | 1/10 (10 %) | 9/14 (64 %) | 12/45 (27 %) |
| qwen2.5:1.5b | RAG | permisivo | 3/10 (30 %) | 9/14 (64 %) | 17/45 (38 %) |
| qwen2.5:1.5b | RAG | estricto | 1/10 (10 %) | 9/14 (64 %) | 4/45 (9 %) |
| qwen2.5:1.5b | Harness | sin_gemelas | 2/10 (20 %) | 10/14 (71 %) | 14/45 (31 %) |
| qwen2.5:1.5b | Harness | permisivo | 3/10 (30 %) | 10/14 (71 %) | 14/45 (31 %) |
| qwen2.5:1.5b | Harness | estricto | 0/10 (0 %) | 10/14 (71 %) | 2/45 (4 %) |

## Comparación pareada frente a Base (política oficial)

Con pocos ítems (24 y 45) una diferencia de uno o dos aciertos es ruido: la prueba de los signos mira solo los ítems que cambiaron de resultado. p < 0.05 sugiere que el cambio no es azar.

| Modelo | Conjunto | Modo | Mejoran | Empeoran | Igual | p (prueba de los signos) |
|---|---|---|---:|---:|---:|---:|
| qwen2.5:1.5b | golden | Few shot | 2 | 3 | 19 | 1.000 |
| qwen2.5:1.5b | golden | RAG | 3 | 4 | 17 | 1.000 |
| qwen2.5:1.5b | golden | Harness | 3 | 2 | 19 | 1.000 |
| qwen2.5:1.5b | golden | Harness + router | 11 | 2 | 11 | 0.022 |
| qwen2.5:1.5b | negativas_heldout | Few shot | 12 | 2 | 31 | 0.013 |
| qwen2.5:1.5b | negativas_heldout | RAG | 9 | 3 | 33 | 0.146 |
| qwen2.5:1.5b | negativas_heldout | Harness | 11 | 3 | 31 | 0.057 |
| qwen2.5:1.5b | negativas_heldout | Harness + router | 25 | 3 | 17 | 0.000 |


## Heldout por tipo de variante (política oficial)

| Modelo | Modo | parafrasis | filtro_distinto | agregado_distinto | casi_igual_trampa | ruido | ambigua |
|---|---|---|---|---|---|---|---|
| qwen2.5:1.5b | Base | 1/8 (12 %) | 2/12 (17 %) | 2/5 (40 %) | 0/6 (0 %) | 1/9 (11 %) | 0/5 (0 %) |
| qwen2.5:1.5b | Few shot | 2/8 (25 %) | 8/12 (67 %) | 2/5 (40 %) | 2/6 (33 %) | 2/9 (22 %) | 0/5 (0 %) |
| qwen2.5:1.5b | Few shot (estático) | 1/8 (12 %) | 4/12 (33 %) | 2/5 (40 %) | 0/6 (0 %) | 0/9 (0 %) | 0/5 (0 %) |
| qwen2.5:1.5b | Harness | 3/8 (38 %) | 7/12 (58 %) | 1/5 (20 %) | 2/6 (33 %) | 1/9 (11 %) | 0/5 (0 %) |
| qwen2.5:1.5b | Harness + router | 7/8 (88 %) | 11/12 (92 %) | 2/5 (40 %) | 3/6 (50 %) | 3/9 (33 %) | 2/5 (40 %) |
| qwen2.5:1.5b | RAG | 1/8 (12 %) | 8/12 (67 %) | 2/5 (40 %) | 1/6 (17 %) | 0/9 (0 %) | 0/5 (0 %) |

## Categorías de falla (política oficial, golden + heldout)

| Modelo | Modo | error_ejecucion | tabla_columna_inexistente | agregacion_incorrecta | filtro_incorrecto | otro |
|---|---|---:|---:|---:|---:|---:|
| qwen2.5:1.5b | Base | 4 | 13 | 30 | 4 | 1 |
| qwen2.5:1.5b | Few shot | 1 | 11 | 23 | 6 | 2 |
| qwen2.5:1.5b | Few shot (estático) | 2 | 13 | 29 | 2 | 5 |
| qwen2.5:1.5b | RAG | 3 | 15 | 20 | 6 | 3 |
| qwen2.5:1.5b | Harness | 2 | 15 | 17 | 5 | 4 |
| qwen2.5:1.5b | Harness + router | 2 | 9 | 4 | 4 | 2 |

## Cambios frente a Base (puntos porcentuales, política oficial)

| Modelo | Conjunto | Few shot | RAG | Harness |
|---|---|---|---|---|
| qwen2.5:1.5b | golden | -4 | -4 | +4 |
| qwen2.5:1.5b | negativas_heldout | +22 | +13 | +18 |

## Detalle de fallas (primeras de cada celda)

- `qwen2.5:1.5b` · Base · golden · B7 · tabla_columna_inexistente: no such column: store_name — `SELECT store_name AS tienda, product_id, SUM(quantity) AS unidades_en_inventario FROM stocks JOIN products ON stocks.product_id = products.product_id GROUP BY t`
- `qwen2.5:1.5b` · Base · negativas_heldout · N1-neg-001 · agregacion_incorrecta: agregación (('Count(DISTINCT)', 'Sum'), 1) contra referencia (('Sum', 'Sum', 'Sum'), 0) — `SELECT product_name AS producto, SUM(discount) AS descuento_total, COUNT(DISTINCT order_id) AS n_productos_vendidos FROM v_order_lines WHERE order_status = 4 GR`
- `qwen2.5:1.5b` · Few shot · golden · B2 · tabla_columna_inexistente: no such column: net_amount — `SELECT ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND strftime('%Y', order_date) = '2017'`
- `qwen2.5:1.5b` · Few shot · negativas_heldout · N1-neg-006 · agregacion_incorrecta: agregación (('Sum', 'Sum', 'Sum', 'Sum'), 1) contra referencia (('Sum', 'Sum'), 1) — `SELECT category_name AS categoria,         ROUND(SUM(discount * quantity), 2) AS valor_descuento_bruto,        SUM(list_price * quantity) AS valor_bruto_total, `
- `qwen2.5:1.5b` · Few shot (estático) · golden · B3 · otro: fila de referencia 3 no encontrada: ['electra townie original 21d - 2016'] — `SELECT product_name AS producto, SUM(quantity) AS unidades_vendidas FROM v_order_lines WHERE order_status = 4 GROUP BY product_id ORDER BY unidades_vendidas DES`
- `qwen2.5:1.5b` · Few shot (estático) · negativas_heldout · N1-neg-001 · agregacion_incorrecta: agregación (('Count', 'Sum'), 1) contra referencia (('Sum', 'Sum', 'Sum'), 0) — `SELECT      product_name AS nombre_producto,     COUNT(*) AS unidades_vendidas,     SUM(discount) AS ingreso_descuento_cedido FROM      v_order_lines WHERE     `
- `qwen2.5:1.5b` · RAG · golden · B1 · tabla_columna_inexistente: no such column: state — `SELECT COUNT(DISTINCT customer_id) AS num_clientes FROM v_orders WHERE state = 'NY' AND order_status = 4`
- `qwen2.5:1.5b` · RAG · negativas_heldout · N1-neg-006 · otro: fila de referencia 1 no encontrada: ['cyclocross bicycles', 11.14] — `SELECT category_name, ROUND(SUM(discount_amount) / SUM(list_price), 2) * 100 AS porcentaje_descuentos_cedidos FROM v_order_lines WHERE order_status = 4 AND disc`
- `qwen2.5:1.5b` · Harness · golden · B5 · tabla_columna_inexistente: La columna 'net_amount' no existe en 'v_orders'. Columnas de v_orders: order_id, order_date, required_date, sh — `SELECT store_name AS tienda, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND strftime('%Y', order_date) = '2017' GROUP BY sto`
- `qwen2.5:1.5b` · Harness · negativas_heldout · N1-neg-005 · otro: fila de referencia 1 no encontrada: ['trek', 450171.75] — `SELECT brand_name, ROUND(SUM(discount), 2) AS descuento_total FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY descuento_total DESC LIMIT `
- `qwen2.5:1.5b` · Harness + router · golden · B5 · tabla_columna_inexistente: La columna 'net_amount' no existe en 'v_orders'. Columnas de v_orders: order_id, order_date, required_date, sh — `SELECT store_name AS tienda, ROUND(SUM(net_amount), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4 AND strftime('%Y', order_date) = '2017' GROUP BY sto`
- `qwen2.5:1.5b` · Harness + router · negativas_heldout · N1-neg-005 · otro: fila de referencia 1 no encontrada: ['trek', 450171.75] — `SELECT brand_name, ROUND(SUM(discount), 2) AS descuento_total FROM v_order_lines WHERE order_status = 4 GROUP BY brand_name ORDER BY descuento_total DESC LIMIT `
