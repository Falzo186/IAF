# Consistencia del modelo (N corridas independientes por pregunta)

- Fecha: 2026-10-12 09:05 · N = 5 · modo LLM libre (sin enrutador), 1 intento por corrida, sin feedback entre corridas; temperatura de producción (0).
- Tiempo total: 8.3 min.
- *Correctas* = corridas que pasan el comparador determinista. *Consistencia* = % de corridas con el resultado más frecuente (huella de valores normalizados, o el error). *Correctas idénticas* (N ≥ 3) = si todas las corridas correctas devolvieron exactamente los mismos valores y columnas.
- **En negrita**: consistencia < 100 % (el modelo no es confiable en esa pregunta, aunque a veces acierte).

| ID | Nivel | Pregunta | qwen2.5:1.5b: correctas / consistencia |
|---|---|---|---|
| B1 | basico | ¿Cuántos clientes hay en el estado de NY? | 5/5 · 100 % |
| B2 | basico | ¿Cuál fue el ingreso neto total de las ventas en 2017? | 5/5 · 100 % |
| B3 | basico | ¿Cuáles son los 5 productos con más unidades vendidas? | 5/5 · 100 % |
| B4 | basico | ¿Cuántas órdenes hay en cada estatus (Pendiente, En proceso, Rechazada, Completada)? | 5/5 · 100 % |
| B5 | basico | ¿Qué tienda tuvo el mayor ingreso neto por ventas en 2017? | 5/5 · 100 % |
| B6 | basico | Muestra el ingreso neto de las ventas por categoría, de mayor a menor. | 5/5 · 100 % |
| B7 | basico | ¿Cuántas unidades hay en inventario en cada tienda? | 0/5 · 100 % |
| B8 | basico | ¿Cuántas órdenes completadas hubo en 2016? | 5/5 · 100 % |
| B9 | basico | ¿Cuál fue el ingreso neto de las ventas por mes en 2017? | **5/5 · 80 % (correctas con valores distintos)** |
| B10 | basico | ¿Cuál es el precio de lista promedio de los productos de la marca Trek? | 5/5 · 100 % |
| N1 | negocio | ¿Cuánto dinero estamos dejando sobre la mesa con los descuentos en cada producto? | **5/5 · 80 % (correctas con valores distintos)** |
| N2 | negocio | ¿Qué productos se venden mucho pero están a punto de agotarse en alguna tienda? | 0/5 · 100 % |
| N3 | negocio | ¿Quiénes son nuestros mejores vendedores de bicicletas eléctricas? | 0/5 · 100 % |
| N4 | negocio | ¿En qué ciudades se concentran las compras hechas con el menor descuento? | 0/5 · 100 % |
| N5 | negocio | ¿Cuánto nos están costando los envíos que llegan tarde y en qué tiendas pasa más? | **0/5 · 80 %** |
| N6 | negocio | ¿Qué mercancía lleva meses en bodega sin moverse y cuánto capital tenemos ahí parado? | 0/5 · 100 % |
| N7 | negocio | ¿Qué clientes suelen combinar varias marcas en un mismo pedido? | **0/5 · 80 %** |
| N8 | negocio | ¿Cuánto gasta en promedio un cliente por pedido en cada una de nuestras tiendas? | 0/5 · 100 % |
| N9 | negocio | ¿Qué categorías y marcas tienen la salida más lenta del catálogo? | 0/5 · 100 % |
| N10 | negocio | ¿Cuánto dinero perdimos por pedidos que al final no se concretaron? | 0/5 · 100 % |

**Preguntas con consistencia < 100 %:** 4 de 20.
