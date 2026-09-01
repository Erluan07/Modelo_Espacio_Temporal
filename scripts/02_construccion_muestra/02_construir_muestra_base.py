"""
Construye la tabla base de presencia/ausencia por píxel para el modelo
espacio-temporal, combinando los eventos Planet(scope) (ver
01_asignar_fuente_inventario.py) con las 4 covariables estáticas de terreno
(slope, aspecto, geología, cobertura).

DEPENDENCIA IMPORTANTE: este script asume que ya existe una tabla base de
presencia/ausencia por píxel (`BASE_PARQUET`) construida previamente para
el modelo de susceptibilidad/espacio-temporal por píxel de la empresa (con
columnas x_m, y_m, row_px, col_px, ID_slope, Zona, fecha, presencia, slope,
aspect, geologia, cobertura, doy). Ese es un pipeline aparte (rasterización
de presencias del inventario + generación de ausencias aleatorias con
control de sesgo espacial) que NO forma parte de este repo -- si no existe
todavía, hay que construirlo primero (contactar al equipo que mantiene el
modelo de susceptibilidad por píxel).

Lo que SÍ hace este script: toma los eventos Planet nuevos que no estén ya
en esa tabla base (pasa con inventarios que se actualizan con el tiempo) y
les muestrea las 4 covariables directamente de los rásters, en vez de
descartarlos. Las ausencias se reutilizan tal cual de la tabla base.

CONFIGURAR antes de correr: rutas de INV_1/INV_2 (mismos que en
01_asignar_fuente_inventario.py), SLOPES, BASE_PARQUET, y los rásters
estáticos (RASTERS / RASTER_GEOLOGIA). La geología suele estar en un CRS
distinto (ej. un sistema local tipo CTM12/MAGNA-SIRGAS) al resto -- ajustar
CRS_GEOLOGIA si aplica.

Salida: muestra_base.csv (x_m, y_m, ID_slope, Zona, fecha, presencia,
        slope, aspect, geologia, cobertura, doy)

Uso:
  python 02_construir_muestra_base.py
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

# --- CONFIGURAR: rutas reales ------------------------------------------------
INV_1 = "ruta/al/inventario_fase_actual.shp"
INV_2 = "ruta/al/inventario_fotointerpretacion_mas_reciente.shp"
SLOPES = "ruta/al/shapefile_de_laderas.shp"
BASE_PARQUET = "ruta/a/la/tabla_base_presencia_ausencia_pixel.parquet"

RASTERS = {
    "slope": "ruta/a/slope.tif",
    "aspect": "ruta/a/aspect.tif",
    "cobertura": "ruta/a/cobertura.tif",
}
RASTER_GEOLOGIA = "ruta/a/geologia.tif"
CRS_GEOLOGIA = "ESRI:103599"  # ajustar si el raster de geologia usa otro CRS

OUT_CSV = "muestra_base.csv"

FECHA_MIN = pd.Timestamp("2000-06-01")
FECHA_MAX = pd.Timestamp("2025-12-31")
FUENTES_PLANET = {"Planetscope", "Planet Scope"}
FECHA_INI_BASE = pd.Timestamp("2024-01-01")  # ventana de la muestra final (ajustar al rango deseado)
FECHA_FIN_BASE = pd.Timestamp("2025-12-31")


def es_movimiento_masa(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.lower().str.contains("movimiento en masa", na=False)


def preparar_presencias_planet(ruta_shp: str, slopes_crs) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(ruta_shp)
    g = gdf[es_movimiento_masa(gdf["Proceso"])].copy()
    g["fecha"] = pd.to_datetime(g["Reporte"], format="%d/%m/%Y", errors="coerce")
    if "Sin_dia" in g.columns:
        fecha_confirmada = g["Sin_dia"].isna() | (g["Sin_dia"].astype(str).str.strip() == "")
    else:
        fecha_confirmada = pd.Series(True, index=g.index)
    p = g[fecha_confirmada & g["fecha"].notna() & g["fecha"].between(FECHA_MIN, FECHA_MAX)].copy()
    p = p[p["Fuente"].isin(FUENTES_PLANET)]
    p["geometry"] = p.representative_point()
    return p[["fecha", "geometry"]].to_crs(slopes_crs)


def snap_a_pixel(xs: np.ndarray, ys: np.ndarray, transform) -> tuple:
    col = np.floor((xs - transform.c) / transform.a).astype(np.int64)
    row = np.floor((ys - transform.f) / transform.e).astype(np.int64)
    xc = transform.c + (col + 0.5) * transform.a
    yc = transform.f + (row + 0.5) * transform.e
    return xc, yc, row, col


def muestrear_puntual(path: str, xs: np.ndarray, ys: np.ndarray, es_geologia: bool,
                       transformer_to_geo) -> tuple:
    with rasterio.open(path) as src:
        if es_geologia:
            gx, gy = transformer_to_geo.transform(xs, ys)
            coords = list(zip(gx, gy))
        else:
            coords = list(zip(xs, ys))
        vals = np.array([v[0] for v in src.sample(coords)], dtype=np.float64)
        nodata = src.nodata
    es_nodata = np.isclose(vals, nodata) if nodata is not None and np.isfinite(nodata) else np.zeros(len(vals), dtype=bool)
    return vals, ~es_nodata


def main():
    slopes = gpd.read_file(SLOPES, encoding="latin1")
    slopes["ID_slope"] = slopes["ID_slope"].astype(int)

    p1 = preparar_presencias_planet(INV_1, slopes.crs)
    p2 = preparar_presencias_planet(INV_2, slopes.crs)
    todas = pd.concat([p1, p2], ignore_index=True)
    print(f"Candidatas Planet: {len(todas)}")

    with rasterio.open(RASTERS["slope"]) as src:
        transform_ref = src.transform

    xs = todas.geometry.x.to_numpy()
    ys = todas.geometry.y.to_numpy()
    xc, yc, row, col = snap_a_pixel(xs, ys, transform_ref)
    todas["x_m"] = xc
    todas["y_m"] = yc
    todas["row_px"] = row
    todas["col_px"] = col
    todas = todas.drop_duplicates(subset=["row_px", "col_px", "fecha"]).reset_index(drop=True)

    pts = gpd.GeoDataFrame(todas, geometry=gpd.points_from_xy(todas.x_m, todas.y_m), crs=slopes.crs)
    u = gpd.sjoin(pts, slopes[["ID_slope", "Zona", "geometry"]], how="left", predicate="within")
    u = u.drop(columns=["index_right"], errors="ignore")
    u = u[~u.index.duplicated(keep="first")]
    falt = u["ID_slope"].isna()
    if falt.any():
        rec = gpd.sjoin_nearest(pts[falt.values], slopes[["ID_slope", "Zona", "geometry"]],
                                 max_distance=100, how="left")
        rec = rec[~rec.index.duplicated(keep="first")]
        u.loc[falt, "ID_slope"] = rec["ID_slope"].reindex(u.index[falt]).to_numpy()
        u.loc[falt, "Zona"] = rec["Zona"].reindex(u.index[falt]).to_numpy()
    u = u.dropna(subset=["ID_slope"]).copy()
    u["ID_slope"] = u["ID_slope"].astype(int)
    print(f"Con ladera asignada (area de estudio): {len(u)}")

    base = pd.read_parquet(BASE_PARQUET,
                            columns=["row_px", "col_px", "fecha", "x_m", "y_m", "ID_slope", "Zona",
                                     "presencia", "slope", "aspect", "geologia", "cobertura", "doy"])
    base["fecha"] = pd.to_datetime(base["fecha"])
    base_pres = base[base.presencia == 1]

    u["fecha"] = pd.to_datetime(u["fecha"])
    u = u.merge(base_pres[["row_px", "col_px", "fecha"]].assign(en_base=True),
                on=["row_px", "col_px", "fecha"], how="left")
    ya_en_base = u[u["en_base"] == True].copy()
    nuevas = u[u["en_base"].isna()].copy()
    print(f"Ya existian en la tabla base: {len(ya_en_base)} | nuevas (requieren muestreo raster): {len(nuevas)}")

    filas_existentes = base_pres.merge(
        ya_en_base[["row_px", "col_px", "fecha"]].drop_duplicates(),
        on=["row_px", "col_px", "fecha"], how="inner")
    filas_existentes = filas_existentes.drop_duplicates(subset=["row_px", "col_px", "fecha"])

    transformer_to_geo = Transformer.from_crs(slopes.crs, CRS_GEOLOGIA, always_xy=True)
    xs_n = nuevas["x_m"].to_numpy()
    ys_n = nuevas["y_m"].to_numpy()
    valido = np.ones(len(nuevas), dtype=bool)
    for var, path in RASTERS.items():
        vals, ok = muestrear_puntual(path, xs_n, ys_n, False, transformer_to_geo)
        nuevas[var] = vals
        valido &= ok
    vals_geo, ok_geo = muestrear_puntual(RASTER_GEOLOGIA, xs_n, ys_n, True, transformer_to_geo)
    nuevas["geologia"] = vals_geo
    valido &= ok_geo
    nuevas = nuevas[valido].copy()

    nuevas["doy"] = nuevas["fecha"].dt.dayofyear
    nuevas["presencia"] = 1
    cols_final = ["x_m", "y_m", "ID_slope", "Zona", "fecha", "presencia", "slope", "aspect",
                  "geologia", "cobertura", "doy"]
    presencias_combinadas = pd.concat([filas_existentes[cols_final], nuevas[cols_final]], ignore_index=True)
    presencias_combinadas = presencias_combinadas[
        presencias_combinadas["fecha"].between(FECHA_INI_BASE, FECHA_FIN_BASE)].reset_index(drop=True)
    print(f"\nPresencias en ventana {FECHA_INI_BASE.date()}..{FECHA_FIN_BASE.date()}: {len(presencias_combinadas)}")

    ausencias = base[(base.presencia == 0) & base["fecha"].between(FECHA_INI_BASE, FECHA_FIN_BASE)][cols_final]
    print(f"Ausencias en la ventana: {len(ausencias)}")

    out = pd.concat([presencias_combinadas, ausencias], ignore_index=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nGuardado: {OUT_CSV} ({len(out)} filas, {(out.presencia == 1).sum()} presencias, "
          f"{(out.presencia == 0).sum()} ausencias)")


if __name__ == "__main__":
    main()
