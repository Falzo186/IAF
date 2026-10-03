# Experimento de contexto de esquema (qwen2.5:1.5b)

- Fecha: 2026-10-03 17:04
- Equipo: Windows-11-10.0.26200-SP0 · Python 3.12.5
- Golden set básico + negocio (20 ítems), solo LLM, sin enrutador, mismas reglas y ejemplos en los tres niveles; solo cambia el bloque de esquema. Exactitud por ejecución (`eval_text2sql.py`).

## Acierto y tamaño del contexto

| Nivel de contexto | Básico | Negocio | Total | % acierto | Tokens del esquema (aprox.) | Tokens del prompt (aprox.) | Con reintento |
|---|---|---|---|---:|---:|---:|---:|
| A · sin_contexto | 9/10 | 3/10 | 12/20 | 60 % | 46 | 787 | 10 |
| B · actual (producción) | 9/10 | 1/10 | 10/20 | 50 % | 827 | 1,568 | 4 |
| C · describe_completo | 9/10 | 1/10 | 10/20 | 50 % | 891 | 1,632 | 9 |

## Distribución de categorías de falla

Cuenta de ítems incorrectos por categoría (ver `eval_text2sql.classify_failure`). La pregunta de fondo: ¿un contexto más completo cambia QUÉ error comete el modelo, y no solo cuántos?

| Categoría | A · sin_contexto | B · actual (producción) | C · describe_completo |
|---|---:|---:|---:|
| `error_ejecucion` | 0 | 0 | 2 |
| `tabla_columna_inexistente` | 6 | 4 | 5 |
| `agregacion_incorrecta` | 2 | 6 | 3 |
| `filtro_incorrecto` | 0 | 0 | 0 |
| `otro` | 0 | 0 | 0 |
| **Total de fallas** | **8** | **10** | **10** |

## Detalle por ítem

| Ítem | A · sin_contexto | B · actual (producción) | C · describe_completo |
|---|---|---|---|
| B1 | ❌ `tabla_columna_inexistente` | ✅ | ✅ |
| B2 | ✅ | ✅ | ✅ |
| B3 | ✅ | ✅ | ✅ |
| B4 | ✅ | ✅ | ✅ |
| B5 | ✅ | ✅ | ✅ |
| B6 | ✅ | ✅ | ✅ |
| B7 | ✅ | ❌ `tabla_columna_inexistente` | ❌ `error_ejecucion` |
| B8 | ✅ | ✅ | ✅ |
| B9 | ✅ | ✅ | ✅ |
| B10 | ✅ | ✅ | ✅ |
| N1 | ✅ | ❌ `agregacion_incorrecta` | ❌ `tabla_columna_inexistente` |
| N2 | ❌ `agregacion_incorrecta` | ❌ `agregacion_incorrecta` | ❌ `tabla_columna_inexistente` |
| N3 | ❌ `tabla_columna_inexistente` | ❌ `agregacion_incorrecta` | ❌ `tabla_columna_inexistente` |
| N4 | ❌ `tabla_columna_inexistente` | ❌ `tabla_columna_inexistente` | ❌ `agregacion_incorrecta` |
| N5 | ❌ `agregacion_incorrecta` | ❌ `tabla_columna_inexistente` | ❌ `tabla_columna_inexistente` |
| N6 | ❌ `tabla_columna_inexistente` | ❌ `tabla_columna_inexistente` | ❌ `tabla_columna_inexistente` |
| N7 | ❌ `tabla_columna_inexistente` | ❌ `agregacion_incorrecta` | ❌ `agregacion_incorrecta` |
| N8 | ✅ | ❌ `agregacion_incorrecta` | ❌ `agregacion_incorrecta` |
| N9 | ❌ `tabla_columna_inexistente` | ❌ `agregacion_incorrecta` | ❌ `error_ejecucion` |
| N10 | ✅ | ✅ | ✅ |
