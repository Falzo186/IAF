"""Las 10 necesidades de negocio con SQL verificada y parametrizable.

Esta SQL es la fuente única que usan el chat (vía el enrutador de sql_engine) y
el dashboard (Fase 3). Todas las consultas trabajan sobre las vistas
v_order_lines / v_orders y consideran "ventas" = order_status = 4 (Completada).

Parámetros nombrados opcionales (NULL = sin filtro), con el patrón
``(:p IS NULL OR col = :p)``:
    :store_name   nombre exacto de la tienda
    :date_from    fecha ISO inicial (inclusive) sobre order_date
    :date_to      fecha ISO final (inclusive) sobre order_date

`keywords` es una tupla de grupos de raíces normalizadas (minúsculas, sin
acentos). Una pregunta suma un punto por cada grupo en el que aparece alguna
raíz como prefijo de palabra; el enrutador exige al menos `min_score` puntos.
Si aparece alguna raíz de `exclude`, la consulta se descarta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

import config
import db

ALL_FILTERS = ("store_name", "date_from", "date_to")


def _filters(alias: str = "", store: bool = True, dates: bool = True) -> str:
    """Fragmento AND con los filtros opcionales sobre una vista (alias opcional)."""
    p = f"{alias}." if alias else ""
    parts = []
    if store:
        parts.append(f"(:store_name IS NULL OR {p}store_name = :store_name)")
    if dates:
        parts.append(f"(:date_from IS NULL OR {p}order_date >= :date_from)")
        parts.append(f"(:date_to IS NULL OR {p}order_date <= :date_to)")
    return " AND ".join(parts)


F = _filters()


@dataclass(frozen=True)
class BusinessQuery:
    id: str
    titulo: str
    definicion: str
    sql: str
    keywords: tuple[tuple[str, ...], ...]
    min_score: int = 2
    exclude: tuple[str, ...] = ()   # raíces que descartan la consulta aunque haya puntaje
    supported_filters: tuple[str, ...] = ALL_FILTERS
    # Filtros que la necesidad ya trae incorporados (p. ej. N3 = Electric Bikes): si la
    # pregunta los menciona no cuentan como filtro no soportado.
    fixed_filters: dict = field(default_factory=dict)
    # Top-N que la consulta ya aplica; otro top-N en la pregunta no está soportado.
    default_top: int | None = None


BUSINESS_QUERIES: list[BusinessQuery] = [
    BusinessQuery(
        id="N1",
        titulo="Rentabilidad por descuentos",
        definicion=(
            "Por producto, solo líneas de ventas completadas con discount > 0: ingreso neto, "
            "descuento cedido (SUM(discount_amount)) y % cedido = cedido / bruto. Se muestran el "
            "top 10 por ingreso neto y el top 10 por % cedido. Como no hay costos en el dataset, "
            "la 'pérdida marginal' se mide como el ingreso cedido por descuentos. Producto = "
            "product_name (29 nombres están dados de alta en varias categorías con otro product_id). "
            "Filtros: tienda de la venta y fecha de la orden."
        ),
        sql=f"""
WITH p AS (
    SELECT product_name, brand_name,
           SUM(net_amount)      AS ingreso_neto,
           SUM(discount_amount) AS descuento_cedido,
           SUM(gross_amount)    AS ingreso_bruto
    FROM v_order_lines
    WHERE order_status = 4 AND discount > 0 AND {F}
    GROUP BY product_name
)
SELECT * FROM (
    SELECT 'Top ingreso neto' AS ranking, product_name AS producto, brand_name AS marca,
           ROUND(ingreso_neto, 2) AS ingreso_neto, ROUND(descuento_cedido, 2) AS descuento_cedido,
           ROUND(100.0 * descuento_cedido / ingreso_bruto, 2) AS pct_cedido
    FROM p ORDER BY ingreso_neto DESC LIMIT 10
)
UNION ALL
SELECT * FROM (
    SELECT 'Top % cedido' AS ranking, product_name, brand_name,
           ROUND(ingreso_neto, 2), ROUND(descuento_cedido, 2),
           ROUND(100.0 * descuento_cedido / ingreso_bruto, 2) AS pct_cedido
    FROM p ORDER BY pct_cedido DESC, ingreso_neto DESC LIMIT 10
)""",
        keywords=(
            ("descuent", "rebaja", "promocion"),
            ("rentab", "margin", "margen", "perdid", "cedid", "sacrific", "cuesta", "costo", "regal", "dej"),
            ("producto", "articulo", "bici"),
        ),
        default_top=10,
    ),
    BusinessQuery(
        id="N2",
        titulo="Riesgo de quiebre de stock",
        definicion=(
            "Productos 'populares' = top 20 por product_name en unidades vendidas (ventas "
            "completadas de todas las tiendas). Se listan las tiendas donde su stock (suma de "
            "stocks.quantity de los product_id con ese nombre) es menor que 5. Filtros: la tienda "
            "aplica al STOCK (qué tienda revisar) y las fechas a las VENTAS que definen la popularidad."
        ),
        sql=f"""
WITH populares AS (
    SELECT product_name, SUM(quantity) AS unidades_vendidas
    FROM v_order_lines
    WHERE order_status = 4 AND {_filters(store=False)}
    GROUP BY product_name
    ORDER BY unidades_vendidas DESC
    LIMIT 20
),
stock_tienda AS (
    SELECT p.product_name, st.store_id, SUM(st.quantity) AS stock
    FROM stocks st JOIN products p ON p.product_id = st.product_id
    GROUP BY p.product_name, st.store_id
)
SELECT pop.product_name AS producto, pop.unidades_vendidas, s.store_name AS tienda,
       sk.stock
FROM populares pop
JOIN stock_tienda sk ON sk.product_name = pop.product_name
JOIN stores s        ON s.store_id = sk.store_id
WHERE sk.stock < 5 AND {_filters("s", dates=False)}
ORDER BY sk.stock, pop.unidades_vendidas DESC""",
        keywords=(
            ("quiebre", "agot", "stock", "existencia", "inventario", "reabastec", "surtir", "falt", "queda"),
            ("popular", "vend", "demand", "exito", "mas vendid", "salida", "riesgo"),
        ),
        default_top=20,
    ),
    BusinessQuery(
        id="N3",
        titulo="Productividad en Electric Bikes",
        definicion=(
            "Vendedores (staff) ordenados por ingreso neto de ventas completadas en la categoría "
            "'Electric Bikes', con unidades vendidas y número de órdenes. Filtros: tienda de la "
            "venta y fecha de la orden."
        ),
        sql=f"""
SELECT staff_name AS vendedor, store_name AS tienda,
       ROUND(SUM(net_amount), 2)  AS ingreso_neto,
       SUM(quantity)              AS unidades,
       COUNT(DISTINCT order_id)   AS ordenes
FROM v_order_lines
WHERE order_status = 4 AND category_name = 'Electric Bikes' AND {F}
GROUP BY staff_id
ORDER BY ingreso_neto DESC""",
        keywords=(
            ("electric", "electrica", "e-bike", "ebike"),
            ("vendedor", "empleado", "staff", "personal", "productiv", "equipo", "quien vend", "colaborador"),
        ),
        fixed_filters={"categoria": "Electric Bikes"},
    ),
    BusinessQuery(
        id="N4",
        titulo="Perfil geográfico premium",
        definicion=(
            "No existen ventas sin descuento (el mínimo del dataset es 0.05), así que 'premium' "
            "= líneas con el descuento mínimo (MIN(discount) de todo el dataset). Top 10 ciudades "
            "por ingreso neto en esas líneas (ventas completadas), con su descuento promedio "
            "general en %. Filtros: tienda de la venta y fecha de la orden."
        ),
        sql=f"""
WITH minimo AS (SELECT MIN(discount) AS d FROM order_items),
general AS (
    SELECT customer_city, customer_state, AVG(discount) AS desc_prom,
           SUM(net_amount) AS ingreso_total
    FROM v_order_lines WHERE order_status = 4 AND {F}
    GROUP BY customer_city, customer_state
)
SELECT l.customer_city AS ciudad, l.customer_state AS estado,
       ROUND(SUM(l.net_amount), 2)  AS ingreso_neto_desc_minimo,
       ROUND(100.0 * g.desc_prom, 2) AS descuento_promedio_pct,
       ROUND(100.0 * SUM(l.net_amount) / g.ingreso_total, 2) AS pct_ingreso_desc_minimo
FROM v_order_lines l
JOIN general g ON g.customer_city = l.customer_city AND g.customer_state = l.customer_state
WHERE l.order_status = 4 AND l.discount = (SELECT d FROM minimo) AND {_filters("l")}
GROUP BY l.customer_city, l.customer_state
ORDER BY ingreso_neto_desc_minimo DESC
LIMIT 10""",
        keywords=(
            ("ciudad", "geograf", "region", "zona", "donde", "localidad"),
            ("premium", "sin descuento", "precio complet", "menor descuento", "descuento minimo",
             "poco descuento", "menos descuento", "casi sin"),
        ),
        default_top=10,
    ),
    BusinessQuery(
        id="N5",
        titulo="Ineficiencia logística",
        definicion=(
            "Órdenes con is_late = 1 (enviadas después de required_date): número de órdenes, "
            "valor neto de esas órdenes y días de retraso promedio, por tienda y total. No es un "
            "costo logístico (no hay costos en el dataset): es el valor de lo entregado tarde. "
            "Filtros: tienda y fecha de la orden."
        ),
        sql=f"""
SELECT * FROM (
    SELECT store_name AS tienda, COUNT(*) AS ordenes_tarde,
           ROUND(SUM(net_total), 2) AS monto_neto, ROUND(AVG(days_late), 2) AS dias_retraso_prom
    FROM v_orders WHERE is_late = 1 AND {F}
    GROUP BY store_id
    ORDER BY monto_neto DESC
)
UNION ALL
SELECT 'Total', COUNT(*), ROUND(SUM(net_total), 2), ROUND(AVG(days_late), 2)
FROM v_orders WHERE is_late = 1 AND {F}""",
        keywords=(
            ("retras", "tarde", "demor", "ineficien", "atras", "a tiempo", "impuntual", "fuera de plazo", "incumpl"),
            ("logistic", "envio", "entreg", "orden", "pedido", "despach", "monto", "tienda", "cuanto"),
        ),
    ),
    BusinessQuery(
        id="N6",
        titulo="Inventario inactivo",
        definicion=(
            "Productos con stock > 0 sin ventas completadas en la ventana de análisis; por defecto, "
            "los 6 meses anteriores a db_metadata.last_completed_date (del 2017-10-02 al 2018-03-31). "
            "estado_inventario = 'Nunca vendido' si el producto no tiene ninguna venta completada en "
            "todo el histórico, o 'Sin ventas recientes' si se vendió antes pero no en la ventana. "
            "Unidades inmovilizadas = suma de stock; valor = unidades × list_price. Producto = "
            "product_name (se consolidan los product_id duplicados). Filtros: la tienda aplica al "
            "STOCK y las fechas reemplazan la ventana de VENTAS."
        ),
        sql=f"""
WITH ref AS (SELECT value AS fecha FROM db_metadata WHERE key = 'last_completed_date'),
ventana AS (
    SELECT COALESCE(:date_from, date(fecha, '-6 months', '+1 day')) AS desde,
           COALESCE(:date_to, fecha) AS hasta
    FROM ref
),
vendidos_ventana AS (
    SELECT DISTINCT product_name FROM v_order_lines, ventana
    WHERE order_status = 4 AND order_date >= ventana.desde AND order_date <= ventana.hasta
),
vendidos_historico AS (
    SELECT DISTINCT product_name FROM v_order_lines WHERE order_status = 4
)
SELECT p.product_name AS producto,
       CASE WHEN p.product_name IN (SELECT product_name FROM vendidos_historico)
            THEN 'Sin ventas recientes' ELSE 'Nunca vendido' END AS estado_inventario,
       SUM(st.quantity) AS unidades_inmovilizadas,
       MAX(p.list_price) AS precio_lista,
       ROUND(SUM(st.quantity * p.list_price), 2) AS valor_inmovilizado
FROM stocks st
JOIN products p ON p.product_id = st.product_id
JOIN stores s   ON s.store_id = st.store_id
WHERE st.quantity > 0
  AND p.product_name NOT IN (SELECT product_name FROM vendidos_ventana)
  AND {_filters("s", dates=False)}
GROUP BY p.product_name
ORDER BY valor_inmovilizado DESC""",
        keywords=(
            ("inactiv", "inmoviliz", "estancad", "parad", "sin venta", "sin moverse", "no se vend",
             "no se han vendido", "no rota", "sin rotacion", "muert", "dormid", "no se mueve", "acumul"),
            ("inventario", "stock", "existencia", "almacen", "bodega", "capital", "producto", "mercancia"),
        ),
    ),
    BusinessQuery(
        id="N7",
        titulo="Diversificación de marcas por cliente",
        definicion=(
            "Clientes con órdenes completadas que incluyen 2 o más marcas (n_brands >= 2): "
            "cuántas órdenes de ese tipo tiene cada uno y su máximo de marcas en una orden. "
            "Filtros: tienda y fecha de la orden."
        ),
        sql=f"""
SELECT c.first_name || ' ' || c.last_name AS cliente, o.customer_city AS ciudad,
       COUNT(*) AS ordenes_multimarca, MAX(o.n_brands) AS max_marcas
FROM v_orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 4 AND o.n_brands >= 2 AND {_filters("o")}
GROUP BY o.customer_id
ORDER BY ordenes_multimarca DESC, max_marcas DESC, cliente""",
        keywords=(
            ("marca",),
            ("diversif", "varias", "distintas", "diferentes", "multimarca", "mas de una", "combin", "mezcl"),
            ("cliente", "comprador", "consumidor", "quien"),
        ),
    ),
    BusinessQuery(
        id="N8",
        titulo="Ticket promedio por tienda",
        definicion=(
            "AVG(net_total) por tienda sobre órdenes completadas, con el número de órdenes. "
            "Filtros: tienda y fecha de la orden."
        ),
        sql=f"""
SELECT store_name AS tienda, COUNT(*) AS ordenes,
       ROUND(AVG(net_total), 2) AS ticket_promedio
FROM v_orders
WHERE order_status = 4 AND {F}
GROUP BY store_id
ORDER BY ticket_promedio DESC""",
        keywords=(
            ("ticket", "valor medio", "promedio por orden", "promedio por pedido", "gasto promedio",
             "gasto medio", "cuanto gasta", "importe medio", "importe promedio", "compra promedio",
             "compra media", "pedido promedio", "pedido medio", "orden promedio"),
            ("tienda", "sucursal", "local", "punto de venta", "promedio", "medio"),
        ),
    ),
    BusinessQuery(
        id="N9",
        titulo="Eficiencia del catálogo (rotación)",
        definicion=(
            "Rotación = unidades vendidas (ventas completadas) / número de meses con ventas, por "
            "categoría y por marca, ordenada de menor a mayor rotación. Filtros: tienda y fecha "
            "de la orden."
        ),
        sql=f"""
SELECT * FROM (
    SELECT 'Categoría' AS dimension, category_name AS nombre, SUM(quantity) AS unidades,
           COUNT(DISTINCT strftime('%Y-%m', order_date)) AS meses_con_ventas,
           ROUND(1.0 * SUM(quantity) / COUNT(DISTINCT strftime('%Y-%m', order_date)), 2) AS rotacion_mensual
    FROM v_order_lines WHERE order_status = 4 AND {F}
    GROUP BY category_name
)
UNION ALL
SELECT * FROM (
    SELECT 'Marca', brand_name, SUM(quantity),
           COUNT(DISTINCT strftime('%Y-%m', order_date)),
           ROUND(1.0 * SUM(quantity) / COUNT(DISTINCT strftime('%Y-%m', order_date)), 2)
    FROM v_order_lines WHERE order_status = 4 AND {F}
    GROUP BY brand_name
)
ORDER BY dimension, rotacion_mensual""",
        keywords=(
            ("rotacion", "rota", "eficien", "lent", "se mueve", "mueven", "ritmo", "velocidad"),
            ("catalogo", "categoria", "marca", "linea"),
        ),
    ),
    BusinessQuery(
        id="N10",
        titulo="Cancelaciones (órdenes rechazadas)",
        definicion=(
            "El dataset no tiene estado 'cancelada'; se usa Rechazada (order_status = 3). Monto "
            "neto perdido (net_total) y número de órdenes: total, por tienda y por mes. Filtros: "
            "tienda y fecha de la orden."
        ),
        sql=f"""
SELECT * FROM (
    SELECT 'Total' AS nivel, 'Todas' AS detalle, COUNT(*) AS ordenes,
           ROUND(SUM(net_total), 2) AS monto_neto_perdido
    FROM v_orders WHERE order_status = 3 AND {F}
)
UNION ALL
SELECT * FROM (
    SELECT 'Tienda', store_name, COUNT(*), ROUND(SUM(net_total), 2)
    FROM v_orders WHERE order_status = 3 AND {F}
    GROUP BY store_id ORDER BY 4 DESC
)
UNION ALL
SELECT * FROM (
    SELECT 'Mes', strftime('%Y-%m', order_date), COUNT(*), ROUND(SUM(net_total), 2)
    FROM v_orders WHERE order_status = 3 AND {F}
    GROUP BY 2 ORDER BY 2
)""",
        keywords=(
            ("cancel", "rechaz", "anulad", "caid", "no se concret", "frustr", "se cayeron"),
            ("orden", "pedido", "venta", "monto", "dinero", "ingreso", "cuanto", "tienda", "mes"),
        ),
        # Preguntas que mezclan estatus (p. ej. conteo por cada estatus) no son "rechazadas".
        exclude=("pendient", "complet", "en proceso", "cada estatus", "por estatus"),
    ),
]

BY_ID: dict[str, BusinessQuery] = {q.id: q for q in BUSINESS_QUERIES}


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def build_params(store_name=None, date_from=None, date_to=None) -> dict:
    return {"store_name": store_name or None, "date_from": _iso(date_from), "date_to": _iso(date_to)}


def run_business_query(bq: BusinessQuery | str, store_name: str | None = None,
                       date_from=None, date_to=None, limit: int | None = None,
                       db_path: Path = config.DB_PATH, timeout: float | None = db.QUERY_TIMEOUT_S
                       ) -> pd.DataFrame:
    """Ejecuta una consulta verificada con filtros opcionales (None = sin filtro)."""
    if isinstance(bq, str):
        bq = BY_ID[bq]
    sql = bq.sql.strip()
    if limit is not None:
        sql = f"SELECT * FROM (\n{sql}\n) LIMIT {int(limit)}"
    return db.run_query(sql, build_params(store_name, date_from, date_to), db_path, timeout)


_FILTER_RE = re.compile(r"\s+AND\s+\(:(\w+) IS NULL OR ([^()]*)\)")


def _literal(value) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def render_sql(bq: BusinessQuery | str, store_name=None, date_from=None, date_to=None) -> str:
    """SQL legible y ejecutable sin parámetros: quita los filtros vacíos e incrusta los activos.

    Es la versión que se muestra al usuario y la que se usa como ancla para el LLM.
    """
    if isinstance(bq, str):
        bq = BY_ID[bq]
    params = build_params(store_name, date_from, date_to)

    def repl(m: re.Match) -> str:
        name, inner = m.group(1), m.group(2)
        if params[name] is None:
            return ""
        return " AND " + inner.replace(f":{name}", _literal(params[name]))

    sql = _FILTER_RE.sub(repl, bq.sql.strip())
    sql = re.sub(r"COALESCE\(:(\w+), (.+?)\) AS",
                 lambda m: (f"{_literal(params[m.group(1)])} AS" if params[m.group(1)] is not None
                            else f"{m.group(2)} AS"), sql)
    return re.sub(r":(store_name|date_from|date_to)", lambda m: _literal(params[m.group(1)]), sql)
