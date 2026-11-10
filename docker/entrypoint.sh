#!/usr/bin/env bash
# Punto de entrada del contenedor. Decide como ejecutar el primer argumento:
#   algo.py            -> python algo.py ...
#   algo.R             -> Rscript algo.R ...
#   prediccion [FECHA] -> predecir_diario.R con las rutas de data/ (docker/predecir.R)
#   rutina [FECHA]     -> descarga lluvia NASA + prediccion diaria
#   login-nasa         -> login interactivo de NASA Earthdata (guarda .netrc)
#   test-gee           -> verifica la cuenta de servicio de Earth Engine
#   cualquier otro     -> se ejecuta tal cual (bash, python, Rscript...)
set -e
cd /app

# config/config.py esta en .gitignore: avisar si falta.
if [ ! -f config/config.py ]; then
    echo "AVISO: falta config/config.py (credenciales de Earth Engine)."
fi

case "${1:-}" in
    *.py)       exec python "$@" ;;
    *.R)        exec Rscript "$@" ;;
    prediccion) shift; exec Rscript docker/predecir.R "$@" ;;
    rutina)     shift; exec bash docker/rutina_diaria.sh "$@" ;;
    login-nasa) exec python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True); print('Login NASA Earthdata guardado.')" ;;
    test-gee)   exec python - <<'PY'
import sys
sys.path.insert(0, "/app")
from config.config import GEE_PROJECT_ID, GEE_SERVICE_ACCOUNT_EMAIL, GEE_SERVICE_ACCOUNT_KEY_PATH
import ee
print("Proyecto :", GEE_PROJECT_ID)
print("Cuenta   :", GEE_SERVICE_ACCOUNT_EMAIL)
print("Llave    :", GEE_SERVICE_ACCOUNT_KEY_PATH)
ee.Initialize(ee.ServiceAccountCredentials(GEE_SERVICE_ACCOUNT_EMAIL, GEE_SERVICE_ACCOUNT_KEY_PATH), project=GEE_PROJECT_ID)
n = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").filterDate("2025-01-01", "2025-01-02").size().getInfo()
print(f"OK: Earth Engine responde ({n} imagenes IMERG el 2025-01-01)")
PY
    ;;
    "")         exec bash ;;
    *)          exec "$@" ;;
esac
