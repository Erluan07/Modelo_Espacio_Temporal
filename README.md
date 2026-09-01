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
                              y en tiempo real vía NASA GES DISC directo)
  02_construccion_muestra/   Presencia/ausencia por píxel + ventanas de 30d
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

## Flujo de trabajo (de cero a predicción)

1. **Descargar lluvia histórica** (`01_descarga_lluvia/descargar_imerg_gee_historico.py`)
   — cubre el período de entrenamiento.
2. **Construir la muestra** (`02_construccion_muestra/`, en orden 01→02→03)
   — presencias Planet + terreno + ventanas de 30 días acumuladas.
3. **Ajustar el modelo** (`03_ajuste_modelo/ajustar_modelo.R`) — guarda
   `modelo_espaciotemporal.rds` y las métricas de validación (AUC por
   partición aleatoria/espacial/temporal).
4. **Producción diaria**: mantener el buffer de lluvia actualizado
   (`01_descarga_lluvia/descargar_imerg_nasa_directo.py`, corrida Early o
   Late — **leer la nota sobre esto en el propio script y en
   LIMITACIONES.md**) y correr `04_prediccion_operativa/predecir_diario.R`
   todos los días (ver `REQUERIMIENTOS_TECNICOS.md` para la automatización).

## Antes de usar esto operativamente

Este modelo tiene limitaciones conocidas y documentadas honestamente en
`LIMITACIONES.md` — en particular, un comportamiento contraintuitivo
confirmado (la probabilidad puede bajar después de una tormenta real,
dependiendo de la forma/momento de la lluvia dentro de la ventana de 30
días) y el hecho de que nunca se probó con datos IMERG Early/Late (los
únicos disponibles en tiempo real). **Leer ese documento antes de tomar
decisiones operativas con las predicciones de este modelo.**
