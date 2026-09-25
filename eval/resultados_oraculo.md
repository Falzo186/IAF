# Verificación del arnés de evaluación (oráculo, sin LLM)

- Fecha: 2026-09-24 10:20
- Equipo: Windows-11-10.0.26200-SP0 · Python 3.14.0
- Ollama: http://localhost:11434
- Exactitud por ejecución (ver `eval_text2sql.py`). *Latencia SQL* = enrutar + generar + validar + ejecutar. *Respuesta completa* = lo que espera el usuario (incluye la síntesis); solo se mide en el modo sistema completo.

## Resumen

| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) | Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |
|---|---|---|---|---|---:|---:|---:|---:|
| oraculo | solo LLM | 10/10 | 10/10 | 4/4 | 0.0 | — | — | 0 |
| oraculo | sistema completo | 10/10 | 10/10 | 4/4 | 0.1 | 0.1 | 0.2 | 0 |

## Detalle

| Modelo | Modo | Ítem | Resultado | Fuente | Intentos | Latencia SQL (s) | Total (s) | Motivo |
|---|---|---|---|---|---:|---:|---:|---|
| oraculo | solo LLM | B1 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B2 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B3 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B4 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B5 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B6 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B7 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B8 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B9 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | B10 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N1 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N2 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N3 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N4 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N5 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N6 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N7 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N8 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N9 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | N10 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | A1 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | A2 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | A3 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | solo LLM | A4 | ✅ | llm | 1 | 0.0 |  |  |
| oraculo | sistema completo | B1 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B2 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B3 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B4 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B5 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B6 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B7 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B8 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B9 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | B10 | ✅ | llm | 1 | 0.0 | 0.0 |  |
| oraculo | sistema completo | N1 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N2 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N3 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N4 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N5 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N6 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N7 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | N8 | ✅ | verificada | 0 | 0.2 | 0.2 |  |
| oraculo | sistema completo | N9 | ✅ | verificada | 0 | 0.2 | 0.2 |  |
| oraculo | sistema completo | N10 | ✅ | verificada | 0 | 0.1 | 0.1 |  |
| oraculo | sistema completo | A1 | ✅ | llm_anclada | 1 | 0.1 | 0.1 |  |
| oraculo | sistema completo | A2 | ✅ | llm_anclada | 1 | 0.1 | 0.1 |  |
| oraculo | sistema completo | A3 | ✅ | llm_anclada | 1 | 0.1 | 0.1 |  |
| oraculo | sistema completo | A4 | ✅ | llm_anclada | 1 | 0.1 | 0.1 |  |
