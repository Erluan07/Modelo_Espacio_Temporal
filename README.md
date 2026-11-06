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
de la foto histórica más cercana, no la fecha real del evento.

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
  04_prediccion_operativa/   Predicción DIARIA (el que va en el cron): probabilidad,
                              aporte de la lluvia y clase de amenaza; amenaza
                              confirmada (moda de 5 días)
  05_diagnostico/            Prueba de sensibilidad del término de lluvia
                              a la forma de la curva
data_referencia/             lluvia_tipica_2024_por_ladera.csv (insumo de la
                              clasificación de la amenaza; ya calculado)
config/
  config.example.py          Plantilla de credenciales -- copiar a config.py
                              (NUNCA subir config.py con datos reales)
REQUERIMIENTOS_TECNICOS.md   Qué se necesita para desplegar esto en producción
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
(`modelo_espaciotemporal.rds`, ~478 MB) se distribuye como archivo aparte: no
está en el árbol de git (GitHub bloquea archivos de más de 100 MB en un push
normal). Si en la sección **Releases** de este repo hay un adjunto,
descárguenlo de ahí; si no, pídanselo al equipo del modelo. Colóquenlo en la
ruta que apunte `RUTA_MODELO` en
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
   Late — **leer la nota sobre esto en el propio script**; el script incluye
   `--retener-dias` para podar el buffer automáticamente).
5. Correr `04_prediccion_operativa/predecir_diario.R` todos los días. Además de
   la probabilidad, deja el aporte de la lluvia (`delta`) y la clase de amenaza
   del día.
6. Correr `04_prediccion_operativa/amenaza_confirmada.R` justo después: calcula
   la amenaza confirmada (moda de los últimos 5 días). Ver la sección siguiente.

## Clasificación de la amenaza (cómo se pasa de la probabilidad a una categoría)

`predecir_diario.R` entrega por ladera y día la `probabilidad` (P_ST, entre 0
y 1). Es una probabilidad **relativa**: el modelo se entrenó con 1 presencia
por cada 7 ausencias, así que sirve para ordenar laderas y días, no como
probabilidad real de ocurrencia. Depende del terreno, de la época del año y
de la lluvia acumulada de 30 días.

La categoría de amenaza **no se saca de la P_ST directamente**, sino del
**aporte de la lluvia (Δ)**: cuánto sube la probabilidad por la lluvia
reciente frente a una lluvia típica de esa misma ladera.

```
Δ = logit(P_ST) − logit(P_base)        logit(p) = ln( p / (1 − p) )
```

- **P_ST**: la salida del modelo con la lluvia observada de los últimos 30 días.
- **P_base**: la misma ladera, el mismo modelo y el mismo día del año, pero
  con una curva de lluvia "típica": una rampa acumulada igual a la lluvia
  media por paso de 30 min de esa ladera en 2024 por k, con k = 1…1440. Esa
  lluvia media está en `data_referencia/lluvia_tipica_2024_por_ladera.csv`
  (ya calculada para las 2.341 laderas; si cambian las laderas o el año de
  referencia se regenera con `calcular_lluvia_tipica.py`).
- Antes del logit, las probabilidades se recortan a [1e-6, 1 − 1e-6].

**Clase de amenaza del día** (cortes fijos sobre Δ, en `CORTES_DELTA`):

| Clase | Δ | Equivale a multiplicar los odds de la ladera por |
|---|---|---|
| baja | menor a 1,5 | menos de 4,5 |
| media | de 1,5 a 2,5 | 4,5 a 12 |
| alta | de 2,5 a 3,2 | 12 a 25 |
| muy alta | 3,2 o más | más de 25 |

**Amenaza confirmada**: es la moda de la clase de amenaza del día y de los 4
días anteriores (5 en total); si hay empate gana la clase más alta. Es la que
debe entrar a la regla de la consola — no la clase de un solo día. La calcula
`amenaza_confirmada.R`, que lee los `prediccion_AAAAMMDD.csv` de
`DIR_SALIDA` y escribe `amenaza_confirmada_AAAAMMDD.csv` (`clase_confirmada`,
`clase_confirmada_num` 0-3 y `n_dias`, los días con dato dentro de la ventana).

Cómo correrlo:

```
Rscript scripts/04_prediccion_operativa/predecir_diario.R 2026-11-05
Rscript scripts/04_prediccion_operativa/amenaza_confirmada.R 2026-11-05
```

Hay que fijar las rutas de `DIR_SALIDA` (y las demás) dentro de cada script;
`config.py` no las lee. Ejecutar `amenaza_confirmada.R` solo después de que
exista la predicción del día pedido.

Salida de `predecir_diario.R` (`prediccion_AAAAMMDD.csv`): `fecha, ID_slope,
x_m, y_m, probabilidad, p_base, delta, clase_num, clase_amenaza`.

**Advertencias**
- Los cortes 1,5 / 2,5 / 3,2 se calibraron con IMERG y con una versión del
  modelo entrenada solo con 2024; el modelo actual (2024-2025) puede
  desplazar un poco la distribución de Δ. Revisen qué porcentaje de
  ladera-días cae en cada clase antes de usarlos en producción (en la prueba,
  alta + muy alta fue cerca del 1,7 % de los torre-días). Además son cortes
  ilustrativos: no están calibrados contra la tasa real de movimientos.
- Usar lluvia **observada**. Con lluvia pronosticada (ECMWF), Δ concuerda poco
  con el calculado con lluvia observada (correlación ≈ 0,3).
- Una ladera sin lluvia típica en el CSV (ID_slope nuevo) queda con `p_base`,
  `delta` y clase en NA.
- La probabilidad `probabilidad` también puede leerse en 4 rangos
  (0,10 / 0,25 / 0,50) como segunda lectura, pero refleja sobre todo el
  terreno y la época, no la lluvia reciente; no reemplaza a Δ.

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

