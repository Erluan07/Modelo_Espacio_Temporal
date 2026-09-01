"""
Extrae la tabla de terreno POR LADERA (un valor de slope/aspecto/geología/
cobertura representativo por cada ID_slope) a partir de la muestra ya
construida -- esta es la tabla que consume
scripts/04_prediccion_operativa/predecir_diario.R (RUTA_TERRENO), porque en
producción no se necesita volver a muestrear los rásters de terreno cada
día: el terreno no cambia, solo la lluvia.

Toma el PRIMER registro de cada ladera en la muestra (todas las filas de
una misma ladera comparten terreno por construcción -- ver
02_construir_muestra_base.py, snap_a_pixel). Si su zona de estudio necesita
un punto por PÍXEL en vez de por ladera (varios píxeles por ladera con
terreno distinto), usar en su lugar la tabla de predictores estáticos
completa, deduplicada por (x_m, y_m) en vez de por ID_slope.

Uso:
  python 04_extraer_terreno_por_ladera.py --muestra muestra_imerg_30d.csv --out terreno_por_ladera.csv
"""

import argparse

import pandas as pd


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--muestra", required=True,
                     help="CSV de la muestra (salida de 02_construir_muestra_base.py o "
                          "03_construir_ventanas_imerg.py -- cualquiera sirve, solo se usan "
                          "las columnas de terreno)")
    ap.add_argument("--out", default="terreno_por_ladera.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.muestra, usecols=["x_m", "y_m", "ID_slope", "slope", "aspect", "geologia", "cobertura"])
    terreno = df.drop_duplicates(subset="ID_slope", keep="first").reset_index(drop=True)

    n_variantes = df.groupby("ID_slope")[["slope", "aspect", "geologia", "cobertura"]].nunique().max().max()
    if n_variantes > 1:
        print(f"AVISO: al menos una ladera tiene más de un valor distinto de terreno entre sus filas "
              f"(máximo {n_variantes} valores distintos para una misma variable) -- se usó el primero "
              f"encontrado. Si su caso de uso necesita resolución de píxel (no de ladera), no use este "
              f"script: use la tabla de predictores estáticos completa, deduplicada por (x_m, y_m).")

    terreno.to_csv(args.out, index=False)
    print(f"Guardado: {args.out} ({len(terreno)} laderas)")


if __name__ == "__main__":
    main()
