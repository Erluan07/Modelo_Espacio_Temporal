"""
Descarga de precipitacion GPM IMERG (media hora) directamente desde NASA
GES DISC, muestreada en los centroides de las laderas del área de estudio
(MISMA convención de salida que descargar_imerg_gee_historico.py: columnas
ID_slope, time, precip_mm -- así el resto del pipeline, en particular
scripts/04_prediccion_operativa/predecir_diario.R, puede leer el buffer sin
importar cuál de los dos scripts de descarga lo generó).

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

Uso (corrida diaria típica, con retención de 31 días de buffer):
  python descargar_imerg_nasa_directo.py --slopes ruta/al/laderas.shp \
      --start 2026-01-01 --end 2026-01-01 --out data/buffer_lluvia_imerg \
      --retener-dias 31
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import earthaccess
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

SHORT_NAME = "GPM_3IMERGHHE"  # ver nota arriba -- Early por defecto para uso operativo
VERSION = "07"
PRECIP_VAR_CANDIDATES = ["precipitation", "precipitationCal", "precipitationUncal"]
BBOX_PADDING_DEG = 0.15  # asegura cubrir al menos un pixel IMERG (0.1 grados) alrededor del AOI
MAX_REINTENTOS_GRANULO = 3
ESPERA_REINTENTO_S = 5
MAX_REINTENTOS_DIA = 2

_log_file = None  # se abre en main(); ver log()


def log(msg: str) -> None:
    """print() a consola Y a un archivo de log en disco -- REQUERIMIENTOS_TECNICOS.md
    §7 asume que esta descarga deja registro persistente para poder monitorearla."""
    print(msg)
    if _log_file is not None:
        _log_file.write(msg + "\n")
        _log_file.flush()


def leer_centroides_laderas(slopes_path: str) -> gpd.GeoDataFrame:
    """Shapefile de laderas (columna ID_slope, entero) -> centroides en
    lat/lon (EPSG:4326), para muestrear IMERG en el mismo punto que usa
    descargar_imerg_gee_historico.py."""
    slopes = gpd.read_file(slopes_path, encoding="latin1")
    slopes["ID_slope"] = slopes["ID_slope"].astype(int)
    # centroide en un CRS proyectado (evita el aviso/These de centroid en grados),
    # igual patrón que el script de Earth Engine
    cent = slopes.to_crs(3116).geometry.centroid.to_crs(4326)
    return gpd.GeoDataFrame({"ID_slope": slopes["ID_slope"]},
                             geometry=cent, crs="EPSG:4326")


def calcular_bbox(centroides: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = centroides.total_bounds
    return (minx - BBOX_PADDING_DEG, miny - BBOX_PADDING_DEG,
            maxx + BBOX_PADDING_DEG, maxy + BBOX_PADDING_DEG)


def abrir_granulo(archivo) -> xr.Dataset:
    return xr.open_dataset(archivo, engine="h5netcdf", group="Grid")


def extraer_variable_precip(ds: xr.Dataset) -> str:
    for nombre in PRECIP_VAR_CANDIDATES:
        if nombre in ds.data_vars:
            return nombre
    raise KeyError(f"Ninguna variable de precipitacion conocida en el granulo: {list(ds.data_vars)}")


def granulo_a_dataframe(ds: xr.Dataset, centroides: gpd.GeoDataFrame) -> pd.DataFrame:
    """Muestrea la media hora de este gránulo en cada centroide de ladera
    (vecino más cercano -- la resolución nativa de IMERG, ~0.1°/~11km, es
    mucho más gruesa que la separación típica entre laderas, así que varias
    laderas comparten el mismo pixel de origen; esto es intencional y es el
    mismo criterio que usa descargar_imerg_gee_historico.py vía Earth
    Engine)."""
    var = extraer_variable_precip(ds)
    tiempo = pd.to_datetime(ds["time"].values[0].isoformat()) if hasattr(ds["time"].values[0], "isoformat") \
        else pd.to_datetime(str(ds["time"].values[0]))

    lon_da = xr.DataArray(centroides.geometry.x.to_numpy(), dims="ladera")
    lat_da = xr.DataArray(centroides.geometry.y.to_numpy(), dims="ladera")
    muestreado = ds[var].sel(lon=lon_da, lat=lat_da, method="nearest")
    valores = np.asarray(muestreado.values).reshape(-1)

    df = pd.DataFrame({
        "ID_slope": centroides["ID_slope"].to_numpy(),
        "time": tiempo,
        "precip_mm_hr": valores,
    })
    df = df[df["precip_mm_hr"] >= 0]  # descarta fill values (-9999.9)
    df["precip_mm"] = df["precip_mm_hr"] * 0.5  # tasa mm/h -> lamina acumulada en 30 min
    return df[["ID_slope", "time", "precip_mm"]]


def procesar_dia(dia: datetime, bbox: tuple[float, float, float, float],
                  centroides: gpd.GeoDataFrame, out_dir: Path) -> None:
    out_file = out_dir / f"{dia:%Y%m%d}.parquet"
    if out_file.exists():
        log(f"  [skip] {dia:%Y-%m-%d} ya existe")
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
        log(f"  [warn] sin granulos para {dia:%Y-%m-%d} (¿aún no publicados? reintentar más tarde)")
        return

    archivos = earthaccess.open(resultados)
    partes = []
    for i, archivo in enumerate(archivos):
        for intento in range(1, MAX_REINTENTOS_GRANULO + 1):
            try:
                ds = abrir_granulo(archivo)
                partes.append(granulo_a_dataframe(ds, centroides))
                ds.close()
                break
            except Exception as e:
                if intento == MAX_REINTENTOS_GRANULO:
                    log(f"  [warn] {dia:%Y-%m-%d} granulo {i+1}/{len(resultados)} "
                        f"fallo tras {MAX_REINTENTOS_GRANULO} intentos ({type(e).__name__}: {e}) -- se omite")
                else:
                    log(f"  [retry] {dia:%Y-%m-%d} granulo {i+1}/{len(resultados)} "
                        f"intento {intento} fallo, reintentando en {ESPERA_REINTENTO_S}s...")
                    time.sleep(ESPERA_REINTENTO_S)

    if not partes:
        log(f"  [warn] {dia:%Y-%m-%d} ningun granulo se pudo leer")
        return

    df_dia = pd.concat(partes, ignore_index=True)
    if df_dia.empty:
        log(f"  [warn] {dia:%Y-%m-%d} sin datos validos dentro del area")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    df_dia.to_parquet(out_file, index=False)
    log(f"  [ok] {dia:%Y-%m-%d} -> {out_file.name} ({len(df_dia)} filas, "
        f"{df_dia['ID_slope'].nunique()} laderas)")


def podar_buffer(out_dir: Path, dias_retener: int, dia_referencia: datetime) -> None:
    """Borra del buffer los parquet diarios más viejos que `dias_retener`
    días respecto a `dia_referencia` -- sin esto el buffer crece sin límite
    (ver REQUERIMIENTOS_TECNICOS.md §4, que asume un buffer acotado a ~30
    días)."""
    limite = dia_referencia - timedelta(days=dias_retener)
    borrados = 0
    for f in out_dir.glob("[0-9]" * 8 + ".parquet"):
        try:
            fecha_archivo = datetime.strptime(f.stem, "%Y%m%d")
        except ValueError:
            continue
        if fecha_archivo < limite:
            f.unlink()
            borrados += 1
    if borrados:
        log(f"\nPoda de buffer: {borrados} archivo(s) anteriores a {limite:%Y-%m-%d} eliminados "
            f"(retención configurada: {dias_retener} días).")


def main() -> None:
    global _log_file
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slopes", required=True,
                     help="Shapefile de laderas (columna ID_slope) -- se descarga en sus centroides")
    ap.add_argument("--start", required=True, help="Fecha inicial YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="Fecha final YYYY-MM-DD (incluida)")
    ap.add_argument("--out", required=True, help="Carpeta de salida (buffer de lluvia, un parquet por día)")
    ap.add_argument("--retener-dias", type=int, default=None,
                     help="Si se indica, borra del buffer los días más viejos que N respecto a --end "
                          "(recomendado en producción, ej. 31, para no acumular el buffer indefinidamente)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _log_file = open(out_dir / f"log_descarga_{datetime.now():%Y%m%d_%H%M%S}.txt", "w", encoding="utf-8")

    try:
        log("Cargando centroides de laderas...")
        centroides = leer_centroides_laderas(args.slopes)
        bbox = calcular_bbox(centroides)
        log(f"  {len(centroides)} laderas | BBOX (lon_min, lat_min, lon_max, lat_max): {bbox}")
        log(f"Corrida IMERG: {SHORT_NAME}")

        earthaccess.login()

        inicio = datetime.strptime(args.start, "%Y-%m-%d")
        fin = datetime.strptime(args.end, "%Y-%m-%d")

        dias_fallidos = []
        dia = inicio
        while dia <= fin:
            for intento in range(1, MAX_REINTENTOS_DIA + 1):
                try:
                    procesar_dia(dia, bbox, centroides, out_dir)
                    break
                except Exception as e:
                    if intento == MAX_REINTENTOS_DIA:
                        log(f"  [ERROR] {dia:%Y-%m-%d} fallo por completo tras {MAX_REINTENTOS_DIA} intentos "
                            f"({type(e).__name__}: {e}) -- se continua con el siguiente dia.")
                        dias_fallidos.append(dia.strftime("%Y-%m-%d"))
                    else:
                        log(f"  [retry] {dia:%Y-%m-%d} fallo el dia completo (intento {intento}), reintentando...")
                        time.sleep(ESPERA_REINTENTO_S)
            dia += timedelta(days=1)

        if dias_fallidos:
            log(f"\n{len(dias_fallidos)} dias quedaron sin descargar (fallo persistente): "
                f"{', '.join(dias_fallidos)}")
            log("Volver a correr el mismo comando para reintentarlos (los dias ya completos se saltan).")
        else:
            log("\nTodos los dias del rango se procesaron sin fallos persistentes.")

        if args.retener_dias is not None:
            podar_buffer(out_dir, args.retener_dias, fin)
    finally:
        _log_file.close()


if __name__ == "__main__":
    main()
