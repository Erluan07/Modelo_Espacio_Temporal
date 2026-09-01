"""
Combina los eventos de movimiento en masa con Fuente Planet(scope) de los
inventarios disponibles (típicamente hay varias fases/versiones del
inventario en distintas rutas) en un único listado (ID_slope, fecha).

Por qué filtrar por Fuente=Planet: el campo `Fuente` del inventario indica
el origen de la imagen satelital usada para digitalizar el evento. La
mayoría de los registros suelen venir de Google Earth Pro, cuya fecha es la
de la foto histórica más cercana (NO la fecha real del evento) -- eso
concentra muchos eventos reales distintos en un puñado de fechas y hace que
un modelo funcional de alta resolución "memorice" la curva de lluvia de esa
fecha en vez de aprender una relación real (ver LIMITACIONES.md). Los
registros con Fuente Planetscope/Planet Scope sí tienen fecha real
(revisita casi diaria), por eso se usan exclusivamente para este modelo.

CONFIGURAR antes de correr: las rutas INV_1/INV_2 abajo apuntan a los
inventarios reales de la empresa (pueden ser más de dos si hay varias
fases) -- ajustar a las rutas vigentes. SLOPES es el shapefile de laderas
usado como grilla de referencia en todo el pipeline.

IMPORTANTE -- este script es una herramienta de VERIFICACIÓN/CONTEO
independiente (para ver cuántas presencias Planet hay por zona antes de
construir la muestra completa), **no es un paso obligatorio de la tubería**:
02_construir_muestra_base.py filtra el inventario por su cuenta y no lee el
CSV que este script genera. Es normal (y esperado) correr solo 02 y 03
directamente sin pasar por este script primero; úsenlo cuando quieran
inspeccionar la cobertura del inventario antes de comprometerse a construir
toda la muestra.

Salida: inventario_fuente_por_slope_fecha.csv (ID_slope, fecha, Zona)

Uso:
  python 01_asignar_fuente_inventario.py
"""

import geopandas as gpd
import pandas as pd

# --- CONFIGURAR: rutas reales de los inventarios y del shapefile de laderas ---
INV_1 = "ruta/al/inventario_fase_actual.shp"
INV_2 = "ruta/al/inventario_fotointerpretacion_mas_reciente.shp"
SLOPES = "ruta/al/shapefile_de_laderas.shp"
OUT_CSV = "inventario_fuente_por_slope_fecha.csv"

FECHA_MIN = pd.Timestamp("2000-06-01")
FECHA_MAX = pd.Timestamp("2025-12-31")
FUENTES_PLANET = {"Planetscope", "Planet Scope"}


def es_movimiento_masa(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.lower().str.contains("movimiento en masa", na=False)


def preparar_presencias_planet(ruta_shp: str, slopes_crs) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(ruta_shp)
    g = gdf[es_movimiento_masa(gdf["Proceso"])].copy()
    g["fecha"] = pd.to_datetime(g["Reporte"], format="%d/%m/%Y", errors="coerce")
    if "Sin_dia" in g.columns:
        # Sin_dia no vacío = fecha incierta (ej. "solo se sabe el mes") -- descartar
        fecha_confirmada = g["Sin_dia"].isna() | (g["Sin_dia"].astype(str).str.strip() == "")
    else:
        fecha_confirmada = pd.Series(True, index=g.index)
    p = g[fecha_confirmada & g["fecha"].notna() & g["fecha"].between(FECHA_MIN, FECHA_MAX)].copy()
    p = p[p["Fuente"].isin(FUENTES_PLANET)]
    return p.to_crs(slopes_crs)


def asignar_a_slopes(p: gpd.GeoDataFrame, slopes: gpd.GeoDataFrame) -> pd.DataFrame:
    """Asigna cada evento a la ladera que lo contiene; si cae justo fuera de
    todas (precisión de digitalización), se asigna a la más cercana dentro
    de 100 m."""
    u = gpd.sjoin(p[["fecha", "geometry"]], slopes[["ID_slope", "geometry"]],
                  how="inner", predicate="within")
    matched_idx = u.index.unique()
    falt = p[~p.index.isin(matched_idx)]
    rec = gpd.sjoin_nearest(falt[["fecha", "geometry"]], slopes[["ID_slope", "geometry"]],
                             max_distance=100)
    return pd.concat([u[["ID_slope", "fecha"]], rec[["ID_slope", "fecha"]]], ignore_index=True)


def main():
    slopes = gpd.read_file(SLOPES, encoding="latin1")
    slopes["ID_slope"] = slopes["ID_slope"].astype(int)

    p1 = preparar_presencias_planet(INV_1, slopes.crs)
    p2 = preparar_presencias_planet(INV_2, slopes.crs)
    print(f"Inventario 1 presencias Planet candidatas: {len(p1)}")
    print(f"Inventario 2 presencias Planet candidatas: {len(p2)}")

    m1 = asignar_a_slopes(p1, slopes)
    m2 = asignar_a_slopes(p2, slopes)
    print(f"Inventario 1 dentro del area de estudio: {len(m1.drop_duplicates())}")
    print(f"Inventario 2 dentro del area de estudio: {len(m2.drop_duplicates())}")

    combinado = pd.concat([m1, m2], ignore_index=True).drop_duplicates(subset=["ID_slope", "fecha"])
    combinado = combinado.merge(slopes[["ID_slope", "Zona"]].drop_duplicates(), on="ID_slope", how="left")
    print(f"\nUnion sin duplicados: {len(combinado)}")
    print("Por zona:")
    print(combinado["Zona"].value_counts())
    print("Fechas distintas:", combinado["fecha"].nunique())

    combinado.to_csv(OUT_CSV, index=False)
    print(f"\nGuardado: {OUT_CSV}")


if __name__ == "__main__":
    main()
