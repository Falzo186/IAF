# Cifras clave para la presentación

Generado con `python tools/cifras_clave.py` a partir de `eval/resultados.json` y de la
base de datos (misma SQL verificada que el dashboard). CPU sin GPU, Ollama 0.34.4.

## 1. Acierto por modelo × modo × nivel

| Modelo | Modo | Básico (10) | Negocio (10) | Anclada (4) |
|---|---|---:|---:|---:|
| qwen2.5:1.5b | solo LLM | 9/10 | 1/10 | 1/4 |
| qwen2.5:1.5b | sistema completo | 9/10 | 10/10 | 3/4 |
| llama3.2:1b | solo LLM | 6/10 | 0/10 | 0/4 |
| llama3.2:1b | sistema completo | 6/10 | 10/10 | 1/4 |
| deepseek-r1:1.5b | solo LLM | 0/10 | 0/10 | 0/4 |
| deepseek-r1:1.5b | sistema completo | 1/10 | 10/10 | 0/4 |

*Solo LLM*: el modelo genera toda la SQL. *Sistema completo*: enrutador de consultas
verificadas + LLM. Negocio = 10/10 en el sistema completo porque las 10 necesidades se
responden con SQL verificada; el dato honesto del modelo solo es la fila *solo LLM*.

## 2. Latencia p50 por ruta (respuesta completa, sistema completo)

| Modelo | Verificada (con redacción IA) | Verificada (por defecto) | Generada por IA | IA anclada |
|---|---:|---:|---:|---:|
| qwen2.5:1.5b | 11.0 s | 0.1 s | 12.4 s | 14.8 s |
| llama3.2:1b | 11.4 s | 0.1 s | 19.6 s | 23.1 s |
| deepseek-r1:1.5b | 16.2 s | 0.1 s | 43.0 s | 49.4 s |

"Por defecto" = `VERIFIED_SYNTHESIS = False`: la ruta verificada responde con una frase
calculada, sin LLM (medido: 12.0 s → 0.13 s de p50; ver fase4.md).

## 3. Las 6 cifras de negocio más fuertes

| # | Cifra | Valor | Definición |
|---:|---|---|---|
| 1 | Capital inmovilizado en productos que nunca se vendieron (N6) | **$1,891,217.66** en 29 productos (1,234 unidades) | Stock > 0 sin ninguna venta completada en todo el histórico, valuado a precio de lista. |
| 2 | Valor de órdenes entregadas tarde (N5) | **$2,042,907.07** en 458 órdenes (31.7 % de las completadas) | Órdenes enviadas después de la fecha requerida; valor neto de esas órdenes (no es un costo). |
| 3 | Productos top en riesgo de quiebre (N2) | **7 de los 20 más vendidos** con < 5 unidades en alguna tienda; 3 ya agotados | Top 20 por unidades vendidas; stock por tienda sumando los product_id duplicados. |
| 4 | Ingreso perdido por órdenes rechazadas (N10) | **$208,579.45** en 45 órdenes | Estado Rechazada (no existe "cancelada"); valor neto de esas órdenes, todo el histórico. |
| 5 | Descuento cedido en ventas (N1) | **$289,142.15** solo en los 10 productos de más ingreso; 10.4 % del bruto en total | Precio de lista × cantidad × descuento, en órdenes completadas. |
| 6 | Concentración en Electric Bikes (N3) | **Marcelene Boyer** vende $271,184.17, el 37 % de la categoría | Ingreso neto de ventas completadas en la categoría Electric Bikes por vendedor. |

Contexto: ingreso neto de ventas completadas $6,662,615.24 (ene 2016 – mar 2018), 1,445 órdenes completadas.
