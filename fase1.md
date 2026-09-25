# Fase 1: construcción de la base SQLite (Bike Stores)

**Objetivo:** convertir los 9 CSV de Bike Stores en una base SQLite validada y
reproducible, con un esquema explícito y vistas semánticas. Esas vistas son la
fuente única de verdad para el dashboard y para el motor Text-to-SQL de las
fases siguientes.

**Alcance:** `config.py`, `database_builder.py` y `tests/test_database.py`.
Esta fase no incluye `app.py`, `sql_engine.py` ni scripts de arranque.

---

## 1. Preparación del entorno

| Paso | Detalle |
|---|---|
| Ubicación de los datos | Los CSV venían en `Data/Bike store/`. La especificación pide `data/bike_stores/`, así que se copiaron ahí. En Windows las rutas no distinguen mayúsculas, por lo que `Data` y `data` son la misma carpeta. No se pudo renombrar la carpeta original porque estaba en uso; la copia antigua `Data/Bike store/` puede borrarse. |
| Python | 3.14.0 |
| pandas | 3.0.1 (ya instalado) |
| pytest | 9.1.1 (se instaló con `python -m pip install pytest`) |

---

## 2. Inspección de los CSV (antes de escribir código)

| Archivo | Filas | Columnas | Observaciones |
|---|---:|---|---|
| categories.csv | 7 | category_id, category_name | Fin de línea CRLF |
| brands.csv | 9 | brand_id, brand_name | Fin de línea CRLF |
| products.csv | 321 | product_id, product_name, brand_id, category_id, model_year, list_price | Ningún nombre contiene comas |
| customers.csv | 1445 | customer_id, first_name, last_name, phone, email, street, city, state, zip_code | `phone` = "NULL" en 1267 filas; `street` trae un espacio al final (p. ej. `'9273 Thorne Ave. '`) |
| stores.csv | 3 | store_id, store_name, phone, email, street, city, state, zip_code | Sin nulos |
| staffs.csv | 10 | staff_id, first_name, last_name, email, phone, active, store_id, manager_id | `manager_id` = "NULL" en 1 fila (staff 1, la gerente general) |
| orders.csv | 1615 | order_id, customer_id, order_status, order_date, required_date, shipped_date, store_id, staff_id | `shipped_date` = "NULL" en 170 filas (todas con estado 1, 2 o 3) |
| order_items.csv | 4722 | order_id, item_id, product_id, quantity, list_price, discount | `discount` entre 0.05 y 0.20 (ya es decimal) |
| stocks.csv | 939 | store_id, product_id, quantity | Sin nulos |

**Conclusiones:**
- **BOM:** ningún archivo lo trae (empiezan directamente con el encabezado). Igual se lee con `utf-8-sig` para tolerarlo si aparece.
- **Nulos:** vienen como la cadena literal `NULL`. No hay celdas vacías ni `NaN`.
- **Fechas:** todas en ISO `YYYY-MM-DD`. `order_date` va de 2016-01-01 a 2018-12-28 y `shipped_date` llega hasta 2018-04-02.
- **Estados de orden:** 4 = 1445, 2 = 63, 1 = 62, 3 = 45.
- **Codificación:** ASCII puro. Algunos archivos terminan en CRLF y pandas lo maneja sin problema.

---

## 3. `config.py`

Reúne en un solo lugar las constantes del proyecto. Las rutas usan `pathlib` y se
resuelven respecto al propio archivo, así el proyecto funciona desde cualquier
directorio de trabajo.

- `BASE_DIR`, `DATA_DIR = BASE_DIR/"data"/"bike_stores"`, `DB_PATH = BASE_DIR/"bikestores.db"`
- `OLLAMA_HOST` (se puede sobrescribir con una variable de entorno), `DEFAULT_MODEL`, `SUPPORTED_MODELS`
- `ORDER_STATUS = {1: "Pendiente", 2: "En proceso", 3: "Rechazada", 4: "Completada"}`

---

## 4. `database_builder.py`

Solo usa la biblioteca estándar y pandas. Los logs están en español y se emiten con `logging`.

### 4.1 CLI

```bash
python database_builder.py            # construye solo si falta la BD o algún CSV es más nuevo
python database_builder.py --force    # reconstruye siempre
python database_builder.py --check    # valida la BD existente e imprime el reporte
```

Hay dos opciones adicionales, `--data-dir` y `--db`, que las pruebas usan para
trabajar en directorios temporales. El programa sale con 0 si todo va bien y con
1 ante cualquier error, ya sea de construcción, de validación o inesperado.

**Cuándo reconstruye:** compara la fecha de modificación de cada CSV con la de
`bikestores.db`. Si no hay BD, o si algún CSV es más nuevo, reconstruye.

### 4.2 Lectura y limpieza (`load_table`)

1. Si falta alguno de los 9 CSV obligatorios, lanza `BuildError` con la lista de
   los que faltan. Esto se comprueba antes de tocar nada.
2. Lee todo como texto (`dtype=str`, `keep_default_na=False`, `encoding="utf-8-sig"`)
   para que pandas no adivine tipos.
3. Normaliza los encabezados con `strip()` y minúsculas. Valida que estén todas
   las columnas esperadas; las columnas sobrantes se ignoran con un warning.
4. Quita espacios en los extremos de cada valor. Los tokens `""`, `NULL` y `NaN`
   (y sus variantes en minúscula) se convierten en `None`, que SQLite guarda como NULL.
5. **Tipos:** las columnas de ids y enteros se convierten a `int` de Python y
   `list_price` y `discount` a `float`. Si un valor no es numérico, o no es entero
   en una columna entera, la carga falla indicando la línea del CSV.
6. **Fechas:** para cada columna se detecta el primer formato de una lista que
   interpreta todos los valores (`%Y-%m-%d`, `%Y/%m/%d`, `%d/%m/%Y`, `%m/%d/%Y`,
   con hora, etc.) y se normaliza a `YYYY-MM-DD`. Si ningún formato sirve, falla
   mostrando ejemplos de valores no interpretables y el formato mayoritario.
7. **discount:** si hay valores mayores que 1, se interpretan como porcentaje, se
   dividen entre 100 y se registra un warning. Con los datos actuales no ocurre.

Los valores se pasan a tipos nativos de Python y no a `numpy.int64`, porque
`sqlite3` no sabe enlazar estos últimos.

### 4.3 Esquema

El esquema se define con DDL explícito en `SCHEMA_SQL`; no se usa `pandas.to_sql`.
Las tablas se crean en orden de dependencias: categories, brands, products,
customers, stores, staffs, orders, order_items, stocks, order_status_lookup y
db_metadata.

- Cada conexión activa `PRAGMA foreign_keys = ON` mediante la función `connect()`.
  Ese PRAGMA vale solo para la conexión que lo ejecuta, así que cualquier consumidor
  futuro debería abrir la BD con `connect()`.
- `orders.order_status` tiene `CHECK (order_status IN (1,2,3,4))`.
- `staffs.manager_id` es una FK a `staffs` que admite NULL.
- `order_items` usa la PK `(order_id, item_id)` y `stocks` la PK `(store_id, product_id)`.
- `order_status_lookup` se llena con `config.ORDER_STATUS`.
- `db_metadata` guarda `built_at` (UTC), `reference_date` (MAX de order_date), `last_completed_date` (MAX de order_date con order_status = 4, añadido en la Fase 2),
  `min_order_date` y el conteo de filas de cada tabla bajo claves `rows.<tabla>`.

**Índices:** hay uno en cada llave foránea, más los pedidos en la especificación:
`orders(order_date)`, `orders(order_status)`, `orders(store_id, order_date)`,
`customers(city)`, `order_items(product_id)` y `stocks(quantity)`. Algunos se
solapan con índices de PK, como `order_items(order_id)`; se crearon igual para
cumplir la especificación al pie de la letra y su costo es despreciable.

### 4.4 Vistas semánticas

Cada vista lleva un comentario SQL que la documenta y queda guardado en `sqlite_master`.

**`v_order_lines`**: una fila por línea de pedido. Incluye order_id, item_id,
order_date, order_status, status_label, store_id, store_name, staff_id,
staff_name, customer_id, customer_city, customer_state, product_id,
product_name, brand_name, category_name, quantity, list_price y discount, además de:
- `gross_amount = list_price * quantity`
- `discount_amount = list_price * quantity * discount`
- `net_amount = list_price * quantity * (1 - discount)`

Las dimensiones se unen con `LEFT JOIN` para que ninguna línea desaparezca si
falta un dato de catálogo.

**`v_orders`**: una fila por orden. Agrega `v_order_lines`, de modo que la fórmula
de montos vive en un solo lugar. Incluye fechas, estado, tienda, vendedor, ciudad
y estado del cliente, y además:
- `n_items` (número de líneas) y `n_brands` (`COUNT(DISTINCT brand_name)`)
- `gross_total` y `net_total`
- `is_shipped = shipped_date IS NOT NULL`
- `is_late = 1` solo si la orden se envió y `shipped_date > required_date`
- `days_late`: 0 si se envió a tiempo, días de retraso si se envió tarde y NULL si no se ha enviado

Columnas extra que no pedía la especificación: `total_quantity` (unidades) y
`discount_total`. Se añadieron porque el dashboard las necesitará.

### 4.5 Construcción atómica

1. Si existe un `bikestores.db.tmp` de una ejecución anterior, se borra.
2. Se crea el esquema en el `.tmp` con `executescript`.
3. Todo se inserta dentro de **una sola transacción** (`BEGIN … COMMIT`) usando `executemany`.
   Se activa `PRAGMA defer_foreign_keys = ON`, de modo que las FK se verifican al
   final y la autorreferencia de `staffs.manager_id` no depende del orden de las filas.
4. Antes del `COMMIT` se ejecuta `PRAGMA foreign_key_check`. Si hay violaciones,
   se hace `ROLLBACK` y el error las lista.
5. Se valida la BD (sección 4.6). Si todo sale bien, se cierra la conexión y se
   reemplaza la BD con `os.replace(tmp, bikestores.db)`.
6. Si algo falla en cualquier punto, se cierra la conexión, se borran el `.tmp`
   y su `-journal` y se relanza el error. La BD anterior queda intacta, y esto
   está cubierto por una prueba.

### 4.6 Validación (se ejecuta al construir y con `--check`)

- Las filas de cada tabla coinciden con las del CSV. `order_status_lookup` se
  compara con `ORDER_STATUS`.
- `PRAGMA integrity_check` devuelve `ok`.
- `PRAGMA foreign_key_check` no devuelve filas; si las hubiera, se listan.
- `SUM(net_amount)` de `v_order_lines` es igual a `SUM(net_total)` de `v_orders`, con tolerancia de 0.01.
- `0 <= discount <= 1`.
- Ninguna fecha está fuera de formato ISO. Se verifica con `GLOB` y además con
  `date(col) = col`, que también rechaza fechas imposibles como 2018-02-30.

Al final se imprime una tabla-resumen y los indicadores `reference_date`,
ingreso neto total y número de órdenes con retraso.

---

## 5. Pruebas (`tests/test_database.py`)

`pytest.ini` agrega la raíz al `pythonpath`. Hay 12 pruebas:

| Prueba | Qué verifica |
|---|---|
| `test_build_from_scratch` | Construcción en un directorio temporal: conteos iguales al CSV, vistas creadas, metadatos correctos, no queda `.tmp` y el reporte sale OK |
| `test_nulls_are_real_nulls` | La cadena "NULL" se convirtió en NULL real (phone, shipped_date, manager_id) |
| `test_idempotent_without_force` | Sin `--force` la BD no se reconstruye (su mtime no cambia); con `--force` sí |
| `test_rebuilds_when_csv_is_newer` | Un CSV más nuevo que la BD provoca la reconstrucción |
| `test_foreign_keys_enforced` | Insertar un `order_items` huérfano lanza `IntegrityError` |
| `test_order_status_check_constraint` | `order_status = 9` viola el CHECK |
| `test_net_amount_matches_pandas` | `net_amount` coincide con el cálculo en pandas sobre los CSV, en total y por orden |
| `test_late_orders_match_pandas` | `is_late` coincide con pandas; las órdenes no enviadas nunca cuentan como tarde |
| `test_dates_normalized_and_discount_percent` | Fechas `dd/mm/YYYY` se normalizan a ISO y un descuento de 20 se convierte en 0.20 |
| `test_missing_csv_fails` | Si falta un CSV, se lanza un error explicativo |
| `test_failed_build_keeps_previous_db` | Una fecha inválida aborta el proceso, la BD previa queda idéntica byte a byte y no queda `.tmp` |
| `test_cli_exit_codes` | Códigos de salida 0 y 1 en `--check`, en la construcción y cuando falta un CSV |

---

## 6. Resultados de la entrega

```
python database_builder.py --force   -> exit 0
python database_builder.py           -> "La BD bikestores.db está al día; no se reconstruye" (exit 0)
python database_builder.py --check   -> exit 0
pytest -q                            -> 12 passed
```

Reporte final:

```
REPORTE DE VALIDACION
==========================================================
tabla                   filas CSV   filas BD  estado
----------------------------------------------------------
categories                      7          7  OK
brands                          9          9  OK
products                      321        321  OK
customers                    1445       1445  OK
stores                          3          3  OK
staffs                         10         10  OK
orders                       1615       1615  OK
order_items                  4722       4722  OK
stocks                        939        939  OK
order_status_lookup             4          4  OK
----------------------------------------------------------
[OK   ] integrity_check: ok
[OK   ] foreign_key_check: sin violaciones
[OK   ] net_amount == net_total: líneas=7,689,116.56 órdenes=7,689,116.56 dif=0.0000
[OK   ] 0 <= discount <= 1: 0 fila(s) fuera de rango
[OK   ] fechas ISO YYYY-MM-DD: 0 fecha(s) inválidas
----------------------------------------------------------
reference_date        : 2018-12-28
ingreso neto total    : 7,689,116.56
órdenes con retraso   : 458
resultado             : OK
==========================================================
```

`.gitignore` excluye `bikestores.db`, `*.tmp`, los journals de SQLite y las cachés de Python.

---

## 7. Decisiones y notas para las fases siguientes

- **Fecha de referencia:** usar `db_metadata.reference_date` (2018-12-28) como "hoy"
  en el análisis, porque los datos son históricos. Por ejemplo, "último mes" debe
  calcularse respecto a esa fecha y no a la fecha real.
- **Ingresos:** el dashboard y el LLM deben consultar `v_order_lines` y `v_orders`,
  no recalcular montos a partir de las tablas base.
- **Ingreso neto total:** 7,689,116.56 incluye todas las órdenes, también las
  rechazadas y las pendientes. Si el negocio necesita solo ventas completadas,
  se filtra con `order_status = 4`.
- **Conexiones:** abrirlas con `database_builder.connect()` para que las llaves
  foráneas queden activas.
- **Limpieza:** se quitaron los espacios finales de `customers.street`.

## 8. Archivos de la fase

```
config.py
database_builder.py
pytest.ini
.gitignore
tests/test_database.py
data/bike_stores/*.csv   (copiados desde Data/Bike store/)
bikestores.db            (generado; ignorado por git)
fase1.md
```
