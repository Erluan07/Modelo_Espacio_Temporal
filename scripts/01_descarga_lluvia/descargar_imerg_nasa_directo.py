"""
Descarga de precipitacion GPM IMERG (media hora) directamente desde NASA
GES DISC, para un area de interes y rango de fechas.

ESTE es el script relevante para OPERACIÓN EN TIEMPO REAL (a diferencia de
descargar_imerg_gee_historico.py, que usa la corrida Final vía Earth Engine
con ~3.5 meses de rezago, no sirve para producción diaria).

Cambiar SHORT_NAME según la corrida que necesiten:
  - "GPM_3IMERGHH"  -> Final   (~3.5 meses de rezago, con pluviometros, la
                                 más precisa -- ES LA QUE SE USÓ PARA
                                 ENTRENAR EL MODELO)
  - "GPM_3IMERGHHE" -> Early   (~4 horas de rezago, solo satélite)
  - "GPM_3IMERGHHL" -> Late    (~14 horas de rezago, satélite + corrección)

IMPORTANTE (ver LIMITACIONES.md): el modelo se entrenó con la corrida
Final. Alimentarlo en producción con Early o Late introduce un desajuste
entre entrenamiento y uso real que **no se ha medido**. Antes de usar esto
en producción se recomienda un piloto: correr en paralelo con Final (con
rezago) y con Early/Late, y comparar cuánto se parecen las predicciones.

Fuente: NASA GES DISC. Requiere cuenta gratuita en
https://urs.earthdata.nasa.gov/ con la aplicación "NASA GESDISC DATA
ARCHIVE" aprobada.

Autenticación (una de las dos, NUNCA credenciales en texto plano en el código):
  1) Variables de entorno EARTHDATA_USERNAME y EARTHDATA_PASSWORD
  2) Ejecutar UNA VEZ, de forma interactiva, en la máquina donde corre el
     pipeline: python -c "import earthaccess; earthaccess.login(persist=True)"
     (guarda un token en ~/.netrc para las siguientes corridas -- no hay
     que volver a hacer login después de eso)

Uso:
  python descargar_imerg_nasa_directo.py --aoi ruta/al/area_estudio.shp \
      --start 2026-01-01 --end 2026-01-01 --out data/buffer_lluvia_imerg
"""

import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

import earthaccess
import geopandas as gpd
import pandas as pd
import xarray as xr

SHORT_NAME = "GPM_3IMERGHHE"  # ver nota arriba -- Early por defecto para uso operativo
VERSION = "07"
PRECIP_VAR_CANDIDATES = ["precipitation", "precipitationCal", "precipitationUncal"]
BBOX_PADDING_DEG = 0.15  # asegura cubrir al menos un pixel IMERG (0.1 grados) alrededor del AOI
MAX_REINTENTOS_GRANULO = 3
ESPERA_REINTENTO_S = 5
MAX_REINTENTOS_DIA = 2


def leer_bbox_aoi(aoi_path: str) -> tuple[float, float, float, float]:
    gdf = gpd.read_file(aoi_path)
    if gdf.crs is None:
        raise ValueError(f"{aoi_path} no tiene CRS definido (falta .prj)")
    gdf = gdf.to_crs(epsg=4326)
    minx, miny, maxx, maxy = gdf.total_bounds
    return (
        minx - BBOX_PADDING_DEG,
        miny - BBOX_PADDING_DEG,
        maxx + BBOX_PADDING_DEG,
        maxy + BBOX_PADDING_DEG,
    )


def abrir_granulo(archivo) -> xr.Dataset:
    return xr.open_dataset(archivo, engine="h5netcdf", group="Grid")


def extraer_variable_precip(ds: xr.Dataset) -> str:
    for nombre in PRECIP_VAR_CANDIDATES:
        if nombre in ds.data_vars:
            return nombre
    raise KeyError(f"Ninguna variable de precipitacion conocida en el granulo: {list(ds.data_vars)}")


def granulo_a_dataframe(ds: xr.Dataset, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    minx, miny, maxx, maxy = bbox
    var = extraer_variable_precip(ds)

    sub = ds[[var]].sel(lon=slice(minx, maxx), lat=slice(miny, maxy))
    if sub[var].size == 0:
        return pd.DataFrame(columns=["time", "lat", "lon", "precip_mm"])

    df = sub.to_dataframe().reset_index()
    df = df.rename(columns={var: "precip_mm_hr"})
    df = df[df["precip_mm_hr"] >= 0]  # descarta fill values (-9999.9)
    df["precip_mm"] = df["precip_mm_hr"] * 0.5  # tasa mm/h -> lamina acumulada en 30 min
    df["time"] = pd.to_datetime(df["time"].apply(lambda t: t.isoformat()))
    return df[["time", "lat", "lon", "precip_mm"]]


def procesar_dia(dia: datetime, bbox: tuple[float, float, float, float], out_dir: Path) -> None:
    out_file = out_dir / f"{dia:%Y%m%d}.parquet"
    if out_file.exists():
        print(f"  [skip] {dia:%Y-%m-%d} ya existe")
        return

    inicio = dia.strftime("%Y-%m-%d 00:00:00")
    fin = (dia + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

    resultados = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=(inicio, fin),
        bounding_box=bbox,
    )
    if not resultados:
        print(f"  [warn] sin granulos para {dia:%Y-%m-%d} (¿aún no publicados? reintentar más tarde)")
        return

    archivos = earthaccess.open(resultados)
    partes = []
    for i, archivo in enumerate(archivos):
        for intento in range(1, MAX_REINTENTOS_GRANULO + 1):
            try:
                ds = abrir_granulo(archivo)
                partes.append(granulo_a_dataframe(ds, bbox))
                ds.close()
                break
            except Exception as e:
                if intento == MAX_REINTENTOS_GRANULO:
                    print(f"  [warn] {dia:%Y-%m-%d} granulo {i+1}/{len(resultados)} "
                          f"fallo tras {MAX_REINTENTOS_GRANULO} intentos ({type(e).__name__}: {e}) -- se omite")
                else:
                    print(f"  [retry] {dia:%Y-%m-%d} granulo {i+1}/{len(resultados)} "
                          f"intento {intento} fallo, reintentando en {ESPERA_REINTENTO_S}s...")
                    time.sleep(ESPERA_REINTENTO_S)

    if not partes:
        print(f"  [warn] {dia:%Y-%m-%d} ningun granulo se pudo leer")
        return

    df_dia = pd.concat(partes, ignore_index=True)
    if df_dia.empty:
        print(f"  [warn] {dia:%Y-%m-%d} sin datos validos dentro del bbox")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    df_dia.to_parquet(out_file, index=False)
    print(f"  [ok] {dia:%Y-%m-%d} -> {out_file.name} ({len(df_dia)} filas)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True, help="Shapefile del area de interes (cualquier CRS)")
    ap.add_argument("--start", required=True, help="Fecha inicial YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="Fecha final YYYY-MM-DD (incluida)")
    ap.add_argument("--out", required=True, help="Carpeta de salida para los parquet diarios")
    args = ap.parse_args()

    bbox = leer_bbox_aoi(args.aoi)
    print(f"BBOX (lon_min, lat_min, lon_max, lat_max): {bbox}")
    print(f"Corrida IMERG: {SHORT_NAME}")

    earthaccess.login()

    out_dir = Path(args.out)
    inicio = datetime.strptime(args.start, "%Y-%m-%d")
    fin = datetime.strptime(args.end, "%Y-%m-%d")

    dias_fallidos = []
    dia = inicio
    while dia <= fin:
        for intento in range(1, MAX_REINTENTOS_DIA + 1):
            try:
                procesar_dia(dia, bbox, out_dir)
                break
            except Exception as e:
                if intento == MAX_REINTENTOS_DIA:
                    print(f"  [ERROR] {dia:%Y-%m-%d} fallo por completo tras {MAX_REINTENTOS_DIA} intentos "
                          f"({type(e).__name__}: {e}) -- se continua con el siguiente dia.")
                    dias_fallidos.append(dia.strftime("%Y-%m-%d"))
                else:
                    print(f"  [retry] {dia:%Y-%m-%d} fallo el dia completo (intento {intento}), reintentando...")
                    time.sleep(ESPERA_REINTENTO_S)
        dia += timedelta(days=1)

    if dias_fallidos:
        print(f"\n{len(dias_fallidos)} dias quedaron sin descargar (fallo persistente): "
              f"{', '.join(dias_fallidos)}")
        print("Volver a correr el mismo comando para reintentarlos (los dias ya completos se saltan).")
    else:
        print("\nTodos los dias del rango se procesaron sin fallos persistentes.")


if __name__ == "__main__":
    main()
