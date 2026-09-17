# Modelo espacio-temporal de amenaza por movimientos en masa

Modelo estadístico (FGAM — *Functional Generalized Additive Model*, vía
`refund::pfr` en R) que predice la probabilidad de movimiento en masa por
ladera/píxel a partir de:

- **Lluvia**: la curva acumulada de los últimos **30 días** de precipitación
  IMERG a resolución **media-horaria** (1.440 puntos), como término
  funcional `af()` — no un escalar tipo "mm acumulados", el modelo pondera
  distintos tramos de la curva de forma flexible.
- **Terreno** (fijo, no cambia día a día): pendiente, aspecto (tratamiento
  circular), geología, cobertura.
- **Estacionalidad**: día del año (spline cíclico).

Las presencias de entrenamiento se restringieron a eventos del inventario
con **Fuente = Planetscope/Planet Scope** (fecha real, revisita casi
diaria) — se excluyó explícitamente Google Earth Pro porque su fecha es la
de la foto histórica más cercana, no la fecha real del evento (ver
`LIMITACIONES.md`).

## Estructura del repo

```
scripts/
  01_descarga_lluvia/        Descarga de IMERG (histórica vía Earth Engine,
                              y en tiempo real vía NASA GES DISC directo) --
                              AMBOS scripts producen la misma salida
                              (ID_slope, time, precip_mm), intercambiable.
  02_construccion_muestra/   Presencia/ausencia por píxel + ventanas de 30d
                              + terreno por ladera (ver orden abajo)
  03_ajuste_modelo/          Ajuste del FGAM (R, refund::pfr)
  04_prediccion_operativa/   Script de predicción DIARIA (el que va en el cron)
  05_diagnostico/            Prueba de sensibilidad del término de lluvia
                              a la forma de la curva (ver LIMITACIONES.md)
config/
  config.example.py          Plantilla de credenciales -- copiar a config.py
                              (NUNCA subir config.py con datos reales)
REQUERIMIENTOS_TECNICOS.md   Qué se necesita para desplegar esto en producción
LIMITACIONES.md              Lo que hay que saber antes de confiar en el modelo
```

## Prerrequisito externo (leer antes de empezar)

`02_construir_muestra_base.py` necesita una tabla de presencia/ausencia por
píxel **ya construida** (`BASE_PARQUET` en ese script) con columnas
`row_px, col_px, x_m, y_m, ID_slope, Zona, fecha, presencia, slope, aspect,
geologia, cobertura, doy`. Esa tabla es un pipeline aparte (rasterización de
presencias del inventario + generación de ausencias aleatorias con control
de sesgo espacial) que **no forma parte de este repo** — si su equipo no la
tiene todavía, hay que construirla primero. Sin ella, `02_construir_muestra_base.py`
falla al arrancar.

## Modelo ya entrenado (opcional, para no reentrenar)

Si no necesitan reentrenar con inventario propio, el modelo ya ajustado
(`modelo_espaciotemporal.rds`, ~478 MB) está disponible como adjunto en la
sección **Releases** de este repo (no está en el árbol de git -- GitHub
bloquea archivos de más de 100 MB en un push normal). Descárguenlo desde
ahí y colóquenlo en la ruta que apunte `RUTA_MODELO` en
`04_prediccion_operativa/predecir_diario.R` (por defecto
`ruta/a/modelo_espaciotemporal.rds`).

Es el modelo FGAM final: ventana de lluvia de 30 días, entrenado solo con
presencias Fuente=Planetscope de 2024-2025, las 6 zonas actuales. Con esto
alcanza para correr directamente `04_prediccion_operativa/predecir_diario.R`
sin pasar por el paso 3 (ajuste) del flujo de abajo -- solo necesitan
`terreno_por_ladera.csv` (paso 2.4) y el buffer de lluvia actualizado (paso 4).

## Flujo de trabajo (de cero a predicción)

**Entrenamiento / construcción del modelo** (una vez, y cada vez que se
reentrene con inventario nuevo):

1. Descargar lluvia histórica: `01_descarga_lluvia/descargar_imerg_gee_historico.py`
   — cubre el período de entrenamiento.
2. Construir la muestra, en `02_construccion_muestra/`:
   - `01_asignar_fuente_inventario.py` es **opcional** — una herramienta de
     conteo/verificación por zona, no genera un archivo que otro script lea.
   - `02_construir_muestra_base.py` — presencias Planet + terreno (requiere
     el prerrequisito externo de arriba).
   - `03_construir_ventanas_imerg.py` — arma las ventanas acumuladas de 30
     días a partir de la lluvia descargada en el paso 1.
   - `04_extraer_terreno_por_ladera.py` — deriva `terreno_por_ladera.csv`
     (un valor de terreno por `ID_slope`) a partir de la muestra del paso
     anterior; es el insumo de terreno que usa la predicción diaria en
     producción.
3. Ajustar el modelo: `03_ajuste_modelo/ajustar_modelo.R` — guarda
   `modelo_espaciotemporal.rds` y las métricas de validación (AUC por
   partición aleatoria/espacial/temporal).

**Producción diaria** (automatizado, ver `REQUERIMIENTOS_TECNICOS.md`):

4. Mantener el buffer de lluvia actualizado con
   `01_descarga_lluvia/descargar_imerg_nasa_directo.py` (corrida Early o
   Late — **leer la nota sobre esto en el propio script y en
   `LIMITACIONES.md`**; el script incluye `--retener-dias` para podar el
   buffer automáticamente).
5. Correr `04_prediccion_operativa/predecir_diario.R` todos los días.

## Diccionario de datos de entrada

- **Shapefile de laderas** (`SLOPES` en varios scripts): debe tener una
  columna `ID_slope` (entero, identificador único de cada ladera) y `Zona`
  (texto, agrupación geográfica usada para la validación espacial).
- **Shapefile(s) de inventario** (`INV_1`/`INV_2`): columnas `Proceso`
  (texto, se filtra por contener "movimiento en masa"), `Reporte` (fecha del
  evento, formato `dd/mm/yyyy`), `Fuente` (texto, se filtra a
  Planetscope/Planet Scope), y opcionalmente `Sin_dia` (si no está vacío,
  la fecha se considera incierta y se descarta esa fila).
- **Rásters de terreno** (`RASTERS`/`RASTER_GEOLOGIA`): un valor numérico
  por celda. `aspect == -1` es la convención estándar para "terreno plano /
  sin orientación definida" (no es un rumbo real) — todos los scripts que
  usan aspecto lo separan en un indicador binario `aspect_flat_f` antes de
  aplicar el spline circular, para no tratarlo como si apuntara al norte.

## Antes de usar esto operativamente

Este modelo tiene limitaciones conocidas y documentadas honestamente en
`LIMITACIONES.md`. Leerlo antes de tomar decisiones operativas con las
predicciones de este modelo.
