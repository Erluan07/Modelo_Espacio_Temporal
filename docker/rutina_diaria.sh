#!/usr/bin/env bash
# Rutina diaria: prediccion de amenaza por movimientos en masa, por ladera.
#   1) completa la lluvia IMERG (NASA, Early) de los ultimos 31 dias
#      (solo baja los dias que falten y borra los de mas de 31 dias)
#   2) predice la probabilidad por ladera para FECHA
# FECHA = argumento YYYY-MM-DD, o AYER en UTC (la ventana de 30 dias del
# modelo termina a las 23:30 UTC de FECHA, el dia tiene que estar completo).
set -euo pipefail
cd /app

FECHA="${1:-$(date -u -d yesterday +%F)}"
INICIO="$(date -u -d "$FECHA -30 days" +%F)"
SLOPES="data/Unidades_ladera/Unidades_ladera_comp_1500k.shp"
TERRENO="data/terreno_por_ladera.csv"
MODELO="data/modelo/modelo_espaciotemporal.rds"

echo "=== Prediccion para $FECHA ==="

echo; echo "--- 1/2 Lluvia $INICIO a $FECHA (NASA) ---"
python scripts/01_descarga_lluvia/descargar_imerg_nasa_directo.py \
    --slopes "$SLOPES" --start "$INICIO" --end "$FECHA" \
    --out data/buffer_lluvia_imerg --retener-dias 31

echo; echo "--- 2/2 Prediccion ---"
falta=0
[ -f "$MODELO" ]  || { echo "FALTA $MODELO"; falta=1; }
[ -f "$TERRENO" ] || { echo "FALTA $TERRENO"; falta=1; }
if [ "$falta" = 1 ]; then
    echo "La lluvia quedo descargada, pero sin esos archivos no se puede predecir."
    exit 2
fi
Rscript docker/predecir.R "$FECHA"
echo; echo "Resultado: data/predicciones/prediccion_${FECHA//-/}.csv"
