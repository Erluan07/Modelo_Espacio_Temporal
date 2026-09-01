# Requerimientos técnicos para desplegar en producción

## 1. Servidor
- VM pequeña/mediana en la nube (2-4 vCPU, 8 GB RAM es de sobra — el
  pipeline no es intensivo en cómputo: predecir toda la zona toma segundos
  a un par de minutos).
- Linux recomendado (facilita cron + instalación de dependencias R/Python).
- Conexión a internet estable — el pipeline depende de llamadas a Google
  Earth Engine y/o NASA GES DISC en cada corrida.

## 2. Software
- **R** con los paquetes `refund` (el modelo es un objeto `pfr`, no un
  `gam` normal — **hay que cargar `library(refund)` antes de `predict()`**,
  si no R cae en el método genérico de `lm` y falla con un error críptico)
  y `pROC` (solo para el ajuste/validación, no para producción).
- **Python 3.10+** con `geopandas`, `rasterio`, `pandas`, `numpy`, `pyproj`,
  `earthengine-api`, `earthaccess` (ver `requirements.txt`).
- Un framework web ligero si van a exponer resultados en una página
  (Flask/FastAPI), o simplemente servir los CSV/GeoJSON de salida desde un
  bucket/CDN si no necesitan lógica de servidor.

## 3. Automatización
Tarea programada (cron en Linux, Task Scheduler en Windows) que corra, en
este orden, **todos los días**:

1. Descargar la lluvia del día y podar el buffer en un solo paso:
   `01_descarga_lluvia/descargar_imerg_nasa_directo.py ... --retener-dias 31`
   (el flag `--retener-dias` borra automáticamente los parquet diarios más
   viejos que 31 días respecto a la fecha corrida -- sin esto el buffer
   crece indefinidamente).
2. Correr `04_prediccion_operativa/predecir_diario.R`.
3. Publicar el resultado (subir el CSV/mapa a donde lo consuma la página).

**¿A qué hora?** Depende de la corrida de IMERG que usen:
- **Early** (~4h de latencia): se puede correr temprano, ej. 4-6am, para
  tener el día anterior completo.
- **Late** (~14h de latencia): hay que esperar más, ej. medio día.

Si quieren más de una actualización diaria, se puede correr 2 veces
(mañana/tarde) usando Early ambas veces.

## 4. Almacenamiento
| Componente | Tamaño estimado |
|---|---|
| Buffer de lluvia (30 días, toda la zona) | ~27 MB (datos crudos, sin comprimir) |
| Predicción diaria (tabla por ladera) | Unos KB por día |
| Historial de predicciones (1 año) | ~1-2 MB |

Nota sobre mapas: si van a mostrar un mapa web, usar **puntos/laderas
coloreados** (liviano, unos KB o directamente datos para un mapa
interactivo tipo Leaflet), no un ráster continuo de alta resolución — ese
tipo de ráster puede pesar cientos de MB y no tiene sentido regenerarlo a
diario para un modelo que predice por ladera, no por píxel de imagen.

## 5. Conectividad y credenciales
- **Cuenta de servicio de Google Earth Engine** (si usan la corrida Final
  para históricos/reentrenamiento) — crear una cuenta de servicio dedicada
  al proyecto, habilitar la Earth Engine API en Google Cloud, descargar la
  clave `.json`. Ver `config/config.example.py`.
- **Cuenta de NASA Earthdata** (gratuita, para Early/Late en producción) —
  registrarse en https://urs.earthdata.nasa.gov/ y aprobar la aplicación
  "NASA GESDISC DATA ARCHIVE". Autenticación vía `earthaccess.login(persist=True)`
  corrido una vez, de forma interactiva, en la máquina de producción (guarda
  un token local, no hay que repetirlo).
- **Nunca** poner usuario/contraseña/tokens en el código o en el repo —
  usar variables de entorno o un gestor de secretos (ej. AWS Secrets
  Manager, Google Secret Manager, o simplemente variables de entorno del
  sistema si es una VM propia).

## 6. Publicación web (si va montado en una página)
- Dominio + certificado HTTPS.
- Mapa interactivo (ej. Leaflet/Mapbox) o dashboard simple mostrando la
  última predicción por ladera.
- Si exponen una API, protegerla con autenticación básica o una API key —
  no dejar el endpoint de predicciones completamente abierto sin control.

## 7. Monitoreo
- Logs de cada corrida diaria (todos los scripts de este repo generan un
  archivo de log en su carpeta de salida, incluida la descarga de lluvia:
  `descargar_imerg_nasa_directo.py` escribe `log_descarga_AAAAMMDD_HHMMSS.txt`
  en el mismo directorio del buffer).
- Alerta (email/Slack/lo que usen) si el pipeline falla — en particular si
  la descarga de lluvia no responde (Earth Engine/NASA caídos, o la cuenta
  de servicio expiró) o si faltan demasiadas laderas en el buffer del día
  (`predecir_diario.R` reporta cuántas laderas quedaron sin serie o con
  huecos en su log -- revisar ese conteo, no solo si el script terminó sin
  error).
