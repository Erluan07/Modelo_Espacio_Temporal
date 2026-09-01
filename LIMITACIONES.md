# Limitaciones conocidas — leer antes de usar en producción

Este documento reúne, con honestidad, lo que sabemos que el modelo NO hace
bien todavía. No se ocultó nada de esto durante el desarrollo — está aquí
para que quien lo opere tome decisiones informadas.

## 1. Desempeño modesto bajo validación honesta

| Partición | AUC |
|---|---|
| Aleatoria (optimista, split 70/30) | ~0,75 |
| Espacial (honesta, bloques geográficos) | ~0,72 |
| Temporal (la más exigente y realista: entrena con 2024, prueba con 2025) | ~0,58-0,71 según la zona |

El AUC temporal es el que más importa para uso operativo (simula
"predecir el futuro con lo que se sabía en el pasado"), y es
sustancialmente más bajo que el aleatorio. Algunas zonas caen a niveles
cercanos al azar bajo partición temporal. **No es un modelo fuerte
todavía** — es razonable como apoyo a criterio experto, no como sistema de
alerta autónomo.

## 2. Comportamiento contraintuitivo del término de lluvia (confirmado)

Se encontró, y se confirmó con pruebas controladas (ver
`scripts/05_diagnostico/diagnostico_forma_af.R`), que el modelo es
sensible a la **forma** de la curva de lluvia dentro de la ventana de 30
días, no solo al total acumulado:

- Con el mismo total de lluvia, una tormenta concentrada en el último día
  predice **menos** probabilidad que la misma agua repartida uniforme en
  30 días — y la diferencia crece mientras más llueve.
- Con la misma tormenta exacta, moverla de "hace 30 días" a "ayer" cambia
  la probabilidad predicha de ~0,70 a ~0,03 — más de 20 veces, **en la
  dirección contraria a la intuición física** (lluvia reciente debería
  aumentar el riesgo, no reducirlo).

**Causa más probable**: sobreajuste del término funcional `af()` — con
solo ~547 presencias para ajustar una curva de 1.440 puntos de
flexibilidad, el modelo puede estar aprendiendo patrones específicos de
las tormentas de entrenamiento en vez de una relación causal genuina.

**Qué hacer**: antes de confiar en las predicciones día a día, se
recomienda reducir la complejidad del término `af()` (bajar el parámetro
`k`, actualmente `c(8,5)`) o volver a un diseño de dos términos
corto/largo plazo (en vez de un solo término de 1.440 puntos), y
revalidar. Esto no se hizo todavía.

## 3. Nunca se probó con datos IMERG Early o Late (los únicos disponibles en tiempo real)

El modelo se entrenó con la corrida **Final** de IMERG (calibrada con
pluviómetros), que solo está disponible ~3,5 meses después del hecho — no
sirve para operación diaria. En producción habría que usar Early (~4h de
rezago) o Late (~14h), que **no están calibradas igual** que Final. Nunca
se cuantificó cuánto se desvían las predicciones al usar Early/Late en vez
de Final.

**Recomendación**: correr un piloto de varias semanas con Early/Late en
paralelo a Final (cuando esté disponible, con el rezago correspondiente) y
comparar antes de operar solo con Early/Late.

## 4. Muestra pequeña y desbalanceada geográficamente

547 presencias en total, con ~45% concentradas en una sola zona (0_1). Las
zonas con pocos casos (ej. zona 5, con muy pocos positivos en cualquier
partición de prueba) tienen estimaciones de desempeño poco confiables —
"AUC bajo" ahí puede ser tanto una señal real como ruido estadístico por
tamaño de muestra.

## 5. Origen del inventario de entrenamiento

Solo se usaron eventos con Fuente Planetscope/Planet Scope (fecha real).
Se descartó Google Earth Pro porque su fecha es la de la foto histórica
más cercana, no la fecha real del evento — mezclar ambas fuentes hacía que
el modelo "memorizara" fechas de captura en vez de aprender una relación
real (se verificó explícitamente: las fechas "tormenta" sospechosas
resultaron ser 100% Google Earth Pro). Esto significa que el modelo actual
depende de que el inventario siga incorporando eventos con fecha real
(Planet u otra fuente de revisita frecuente) para poder reentrenarse en el
futuro — si esa fuente deja de actualizarse, no hay forma de ampliar la
muestra de entrenamiento con la misma calidad de fecha.
