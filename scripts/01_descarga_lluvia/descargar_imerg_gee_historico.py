"""
Descarga la serie IMERG V07 media-horaria (Google Earth Engine, corrida
FINAL) para todas las laderas del área de estudio, en un rango de fechas
dado. Uso principal: construir/actualizar el histórico completo (para
reentrenar el modelo) — NO es el script para la actualización diaria en
producción (ver `actualizar_buffer_diario.py`), porque la corrida Final de
IMERG tiene ~3.5 meses de rezago y solo está disponible así en Earth Engine.

Requiere una cuenta de servicio de Google Earth Engine (ver
config/config.example.py) con la Earth Engine API habilitada en el
proyecto de Google Cloud correspondiente.

Nota de escala (ver README): con miles de laderas, un solo reduceRegions()
por trimestre completo puede exceder el límite de Earth Engine
("Computed value is too large"). Se trocea en lotes (TAM_LOTE) — probado
hasta 1200 puntos por lote sin problema, se deja margen usando 800.

Uso:
  python descargar_imerg_gee_historico.py \
      --slopes ruta/a/laderas.shp --out data/buffer_lluvia_imerg \
      --inicio 2023-11-01 --fin 2026-01-01
"""

import argparse
import re
import sys
import time
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.config import (
    GEE_SERVICE_ACCOUNT_EMAIL,
    GEE_SERVICE_ACCOUNT_KEY_PATH,
    GEE_PROJECT_ID,
)

ESCALA_M = 11132  # resolucion nativa IMERG (~0.1 grados)
TAM_LOTE = 800  # puntos por lote de reduceRegions (ver nota de escala arriba)


def inicializar_ee() -> None:
    if not (GEE_SERVICE_ACCOUNT_EMAIL and GEE_SERVICE_ACCOUNT_KEY_PATH and GEE_PROJECT_ID):
        raise RuntimeError(
            "Faltan credenciales de Earth Engine. Copiar config/config.example.py a "
            "config/config.py (o definir las variables de entorno GEE_SERVICE_ACCOUNT_EMAIL, "
            "GEE_SERVICE_ACCOUNT_KEY_PATH, GEE_PROJECT_ID) antes de correr este script."
        )
    credenciales = ee.ServiceAccountCredentials(GEE_SERVICE_ACCOUNT_EMAIL, GEE_SERVICE_ACCOUNT_KEY_PATH)
    ee.Initialize(credenciales, project=GEE_PROJECT_ID)


def cargar_puntos(ruta_slopes: str) -> tuple[gpd.GeoDataFrame, list[list[ee.Feature]]]:
    """El shapefile de laderas debe traer una columna `ID_slope` (entero,
    identificador único de cada ladera/unidad de análisis)."""
    slopes = gpd.read_file(ruta_slopes, encoding="latin1")
    slopes["ID_slope"] = slopes["ID_slope"].astype(int)
    slopes = slopes.reset_index(drop=True)

    cent = slopes.to_crs(3116).geometry.centroid.to_crs(4326)
    feats = [
        ee.Feature(ee.Geometry.Point([lon, lat]), {"ID_slope": int(idv)})
        for idv, lon, lat in zip(slopes["ID_slope"], cent.x, cent.y)
    ]
    lotes = [feats[i:i + TAM_LOTE] for i in range(0, len(feats), TAM_LOTE)]
    return slopes, lotes


def generar_trimestres(inicio: pd.Timestamp, fin: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    trimestres = []
    cur = inicio
    while cur < fin:
        nxt = cur + pd.DateOffset(months=3)
        etiqueta = f"{cur.year}-{cur.month:02d}"
        trimestres.append((cur, min(nxt, fin), etiqueta))
        cur = nxt
    return trimestres


def descargar_lote(img_apilada: ee.Image, lote: list[ee.Feature]) -> pd.DataFrame:
    fc = ee.FeatureCollection(lote)
    resultado = img_apilada.reduceRegions(collection=fc, reducer=ee.Reducer.first(), scale=ESCALA_M)
    datos = resultado.getInfo()

    filas = []
    patron_fecha = re.compile(r"^(\d{14})_precipitation$")
    for feat in datos["features"]:
        props = feat["properties"]
        id_slope = props.get("ID_slope")
        for clave, valor in props.items():
            m = patron_fecha.match(clave)
            if m and valor is not None:
                tiempo = pd.to_datetime(m.group(1), format="%Y%m%d%H%M%S")
                # la banda "precipitation" de IMERG es una TASA en mm/h ->
                # lamina acumulada en esa media hora = tasa * 0.5
                filas.append((id_slope, tiempo, valor * 0.5))

    return pd.DataFrame(filas, columns=["ID_slope", "time", "precip_mm"])


def descargar_trimestre(ini: pd.Timestamp, fin: pd.Timestamp, lotes: list[list[ee.Feature]]) -> pd.DataFrame:
    col = (
        ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
        .filterDate(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
        .select("precipitation")
    )
    img_apilada = col.toBands()
    partes = [descargar_lote(img_apilada, lote) for lote in lotes]
    return pd.concat(partes, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slopes", required=True, help="Shapefile de laderas (columna ID_slope)")
    ap.add_argument("--out", required=True, help="Carpeta de salida (un parquet por trimestre)")
    ap.add_argument("--inicio", required=True, help="Fecha inicial YYYY-MM-DD")
    ap.add_argument("--fin", required=True, help="Fecha final YYYY-MM-DD (exclusiva)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Inicializando Earth Engine...")
    inicializar_ee()

    print("Cargando centroides de laderas...")
    slopes, lotes = cargar_puntos(args.slopes)
    print(f"  {len(slopes)} laderas en {len(lotes)} lotes de hasta {TAM_LOTE}\n")

    inicio = pd.Timestamp(args.inicio)
    fin = pd.Timestamp(args.fin)
    trimestres = generar_trimestres(inicio, fin)
    print(f"Rango: {inicio.date()} a {fin.date()} -> {len(trimestres)} trimestres\n")

    t0_total = time.time()
    resumen = []
    for ini, tfin, etiqueta in trimestres:
        out_file = out_dir / f"imerg_{etiqueta}.parquet"
        if out_file.exists():
            print(f"[skip] {etiqueta} (ya existe)")
            continue

        t0 = time.time()
        try:
            df = descargar_trimestre(ini, tfin, lotes)
        except Exception as e:
            print(f"[ERROR] {etiqueta}: {type(e).__name__}: {str(e)[:200]}")
            resumen.append((etiqueta, "ERROR", 0, 0))
            continue

        df.to_parquet(out_file, index=False)
        dt = time.time() - t0
        n_medias_horas_esperadas = int((tfin - ini).total_seconds() / 1800)
        cobertura = 100 * len(df) / (len(slopes) * n_medias_horas_esperadas)
        print(f"[ok] {etiqueta}: {len(df):>9,} filas | {dt:5.1f}s | cobertura {cobertura:.1f}%")
        resumen.append((etiqueta, "ok", len(df), dt))

    print(f"\nTotal: {time.time() - t0_total:.1f}s")
    print("\nResumen:")
    for etiqueta, estado, n, dt in resumen:
        print(f"  {etiqueta}: {estado} ({n:,} filas)")


if __name__ == "__main__":
    main()
