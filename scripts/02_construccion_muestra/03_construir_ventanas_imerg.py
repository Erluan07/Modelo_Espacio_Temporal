"""
Arma la ventana funcional de 30 días a resolución media-horaria (1.440
pasos) para cada fila (píxel, fecha) de la muestra base, a partir de las
series IMERG descargadas (ver scripts/01_descarga_lluvia/).

Convención importante: la ventana se guarda ACUMULADA (cumsum), no como
tasa/lámina instantánea -- así es como el modelo espera el insumo del
término funcional af(). Cada fila usa la serie de SU PROPIA ladera
(columna ID_slope), no la de un punto fijo.

Una fila se descarta si falta CUALQUIER media hora dentro de la ventana de
30 días (criterio estricto, documentado -- ver LIMITACIONES.md sobre la
tasa de retención esperable).

Uso:
  python 03_construir_ventanas_imerg.py
"""
import glob
import os

import numpy as np
import pandas as pd

VENTANA_DIAS = 30
PASOS_30MIN = VENTANA_DIAS * 48  # 1440

# --- CONFIGURAR: rutas reales -------------------------------------------------
IMERG_DIR = "ruta/a/data/buffer_lluvia_imerg"  # carpeta con los parquet de 01_descarga_lluvia/
BASE_CSV = "muestra_base.csv"                    # salida de 02_construir_muestra_base.py
OUT_CSV = "muestra_imerg_30d.csv"
FECHA_MIN_USABLE = pd.Timestamp("2024-01-01")   # ajustar al primer dia con 30d de historia completos


def cargar_imerg_por_ladera() -> dict:
    print("Cargando parquets de IMERG...")
    archivos = sorted(glob.glob(os.path.join(IMERG_DIR, "*.parquet")))
    partes = [pd.read_parquet(f) for f in archivos]
    todo = pd.concat(partes, ignore_index=True)
    todo["time"] = pd.to_datetime(todo["time"])
    todo["ID_slope"] = todo["ID_slope"].astype(int)
    todo = todo.drop_duplicates(subset=["ID_slope", "time"])
    print(f"  {len(todo):,} filas, {todo['ID_slope'].nunique()} laderas, "
          f"{todo['time'].min()} a {todo['time'].max()}")
    por_ladera = {}
    for idv, g in todo.groupby("ID_slope"):
        por_ladera[idv] = g.set_index("time")["precip_mm"].sort_index()
    return por_ladera


def main():
    df = pd.read_csv(BASE_CSV)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df[df.fecha >= FECHA_MIN_USABLE].reset_index(drop=True)
    print(f"Filas base (fecha usable): {len(df)} ({(df.presencia == 1).sum()} presencias)")

    imerg = cargar_imerg_por_ladera()

    n = len(df)
    matriz = np.full((n, PASOS_30MIN), np.nan)
    saltadas = 0
    for i, r in df.iterrows():
        idv = int(r["ID_slope"])
        fin = r["fecha"] + pd.Timedelta(hours=23, minutes=30)
        ini = fin - pd.Timedelta(minutes=30 * (PASOS_30MIN - 1))
        pasos = pd.date_range(ini, fin, freq="30min")

        serie = imerg.get(idv)
        if serie is None:
            saltadas += 1
            continue
        vals = serie.reindex(pasos)
        if vals.isna().any():
            saltadas += 1
            continue
        matriz[i, :] = vals.to_numpy()

        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{n} filas procesadas ({saltadas} saltadas por huecos)...")

    ok = ~np.isnan(matriz).any(axis=1)
    print(f"\nFilas con ventana completa: {ok.sum()} / {n} ({saltadas} saltadas)")

    df_ok = df.loc[ok].reset_index(drop=True)
    matriz_ok = matriz[ok]

    acumulado = np.cumsum(matriz_ok, axis=1)
    cols = [f"h{-(PASOS_30MIN - 1 - j)}" for j in range(PASOS_30MIN)]  # h-1439 .. h0
    salida_cols = {c: acumulado[:, j] for j, c in enumerate(cols)}
    out = pd.concat([df_ok, pd.DataFrame(salida_cols, index=df_ok.index)], axis=1)

    out.to_csv(OUT_CSV, index=False)
    print(f"\nGuardado: {OUT_CSV} ({len(out)} filas, {(out.presencia == 1).sum()} presencias, "
          f"{PASOS_30MIN} columnas de ventana horaria)")


if __name__ == "__main__":
    main()
