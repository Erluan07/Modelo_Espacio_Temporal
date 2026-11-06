"""
Calcula la LLUVIA TÍPICA por ladera: la lluvia media por paso de 30 min de
cada ladera durante un año de referencia (por defecto 2024, el mismo año con
el que se calibraron los cortes de la amenaza).

Se usa en predecir_diario.R para construir P_base (la probabilidad del modelo
con una lluvia "típica" de esa ladera) y con ella el aporte de la lluvia
Δ = logit(P_ST) - logit(P_base). Ver README, sección "Clasificación de la
amenaza".

Ya hay un resultado listo en data_referencia/lluvia_tipica_2024_por_ladera.csv
(calculado con el buffer IMERG de 2024 de las 2.341 laderas). Este script solo
hace falta si cambian las laderas o quieren otro año de referencia.

Entrada: carpeta con parquet/csv de lluvia (columnas ID_slope, time, precip_mm,
un registro cada 30 min) -- la misma salida de 01_descarga_lluvia/.
Importante: debe cubrir TODO el año de referencia (365/366 días x 48 pasos).

Uso:
  python calcular_lluvia_tipica.py --lluvia data/buffer_lluvia_imerg --anio 2024 \
      --out data_referencia/lluvia_tipica_2024_por_ladera.csv
"""

import argparse
import glob
import os

import pandas as pd


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lluvia", required=True, help="Carpeta con los parquet/csv de lluvia")
    ap.add_argument("--anio", type=int, default=2024, help="Año de referencia (defecto 2024)")
    ap.add_argument("--out", default="lluvia_tipica_2024_por_ladera.csv")
    args = ap.parse_args()

    archivos = sorted(glob.glob(os.path.join(args.lluvia, "*.parquet")) + glob.glob(os.path.join(args.lluvia, "*.csv")))
    if not archivos:
        raise SystemExit(f"No hay parquet/csv en {args.lluvia}")

    partes = []
    for f in archivos:
        d = pd.read_parquet(f) if f.endswith(".parquet") else pd.read_csv(f)
        d["time"] = pd.to_datetime(d["time"])
        d = d[d["time"].dt.year == args.anio]
        if len(d) == 0:
            continue
        # se descartan duplicados de tiempo (los buffers de 90 d se solapan con el trimestre siguiente)
        d = d.drop_duplicates(subset=["ID_slope", "time"])
        partes.append(d[["ID_slope", "time", "precip_mm"]])
    if not partes:
        raise SystemExit(f"Ningún archivo tiene datos de {args.anio}")
    d = pd.concat(partes).drop_duplicates(subset=["ID_slope", "time"])

    pasos_esperados = (366 if pd.Timestamp(args.anio, 12, 31).dayofyear == 366 else 365) * 48
    g = d.groupby("ID_slope")["precip_mm"].agg(media_paso_mm="mean", n_pasos="count").reset_index()
    incompletas = int((g["n_pasos"] < pasos_esperados).sum())
    if incompletas:
        print(f"AVISO: {incompletas} laderas con menos de {pasos_esperados} pasos de 30 min en {args.anio} "
              f"(la media se calcula con los que hay; revise huecos en la descarga).")
    g["ID_slope"] = g["ID_slope"].astype(int)
    g[["ID_slope", "media_paso_mm"]].to_csv(args.out, index=False)
    print(f"Guardado: {args.out} ({len(g)} laderas, media global {g.media_paso_mm.mean():.4f} mm por paso de 30 min)")


if __name__ == "__main__":
    main()
