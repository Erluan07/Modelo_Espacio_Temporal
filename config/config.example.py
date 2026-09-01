"""
Plantilla de configuración — credenciales y rutas del proyecto.

Copiar este archivo a `config/config.py` (ese nombre está en .gitignore,
nunca se sube al repo) y rellenar con los valores reales de la cuenta de
servicio de Google Earth Engine que la empresa cree para este proyecto.

NUNCA subir config.py con credenciales reales al repositorio.
"""

import os

# --- Google Earth Engine (necesario para scripts/01_descarga_lluvia) --------
# Cuenta de servicio dedicada para este proyecto (crear una nueva, no
# reutilizar una personal): https://console.cloud.google.com/iam-admin/serviceaccounts
# Habilitar la Earth Engine API en el proyecto de Google Cloud correspondiente.
GEE_SERVICE_ACCOUNT_EMAIL = os.environ.get("GEE_SERVICE_ACCOUNT_EMAIL", "")
# Ruta al archivo .json de la clave privada de esa cuenta de servicio
# (descargado desde Google Cloud Console). Guardarlo FUERA del repo.
GEE_SERVICE_ACCOUNT_KEY_PATH = os.environ.get("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
# ID del proyecto de Google Cloud con Earth Engine habilitado
GEE_PROJECT_ID = os.environ.get("GEE_PROJECT_ID", "")

# --- NASA Earthdata (necesario solo si se usa descarga directa Early/Late) --
# Crear cuenta gratuita en https://urs.earthdata.nasa.gov/
# Las credenciales se configuran vía `earthaccess.login(persist=True)`
# (guarda un token en ~/.netrc) -- NUNCA poner usuario/contraseña en texto
# plano en el código. Ejecutar ese login una sola vez, de forma interactiva,
# en la máquina donde corre el pipeline.

# --- Rutas de datos internos de la empresa (ajustar a la infraestructura real) ---
# Estas NO son credenciales, son rutas a las capas estáticas ya calculadas
# (terreno, geología, cobertura, inventario) que el equipo de ISA mantiene.
RUTA_SLOPES_SHP = os.environ.get("RUTA_SLOPES_SHP", "data/00_area_estudio/Slopes_Final.shp")
RUTA_AOI_SHP = os.environ.get("RUTA_AOI_SHP", "data/00_area_estudio/Area_influencia.shp")

# --- Directorios de trabajo (buffer de lluvia, salidas) ---------------------
DIR_BUFFER_LLUVIA = os.environ.get("DIR_BUFFER_LLUVIA", "data/buffer_lluvia_imerg")
DIR_SALIDA_PREDICCIONES = os.environ.get("DIR_SALIDA_PREDICCIONES", "data/predicciones")
