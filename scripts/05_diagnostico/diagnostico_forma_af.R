## Diagnostico del comportamiento contraintuitivo encontrado en la animacion
## (prob baja despues de una tormenta real de 109mm en vez de subir).
## Hipotesis: el termino af() es sensible a la FORMA de la curva de lluvia
## (donde exactamente caen los milimetros dentro de la ventana de 30 dias),
## no solo al TOTAL acumulado. Prueba directa: construir curvas sinteticas
## con el MISMO total pero forma distinta (gradual vs. concentrada en un
## pico al final, como una tormenta real) y comparar la prediccion.
##
## Uso: Rscript diagnostico_forma_af.R

suppressPackageStartupMessages(library(refund))  # refund carga mgcv internamente
dir_out <- "."
PASOS <- 1440

log_con <- file(file.path(dir_out, "log_diagnostico_forma_af.txt"), open = "wt", encoding = "UTF-8")
sink(log_con, split = TRUE)
cat("=== Diagnostico: sensibilidad del af() a la FORMA de la curva de lluvia ===\n\n")

modelo <- readRDS(file.path(dir_out, "modelo_espaciotemporal.rds"))
niveles_geo <- levels(modelo$model$geologia_f)
niveles_cob <- levels(modelo$model$cobertura_f)

## --- terreno fijo: valores representativos (mediana/moda de la muestra de entrenamiento) ---
muestra <- read.csv(file.path(dir_out, "muestra_imerg_30d.csv"), stringsAsFactors = FALSE)
moda <- function(v) as.numeric(names(sort(table(v), decreasing = TRUE))[1])
slope_rep <- median(muestra$slope)
geo_rep <- moda(muestra$geologia)
cob_rep <- moda(muestra$cobertura)
cat(sprintf("Terreno representativo: slope=%.1f, geologia=%d, cobertura=%d\n\n", slope_rep, geo_rep, cob_rep))

construir_fila <- function(precip_cumsum, doy = 51) {
  data.frame(
    precip_imerg = I(matrix(precip_cumsum, nrow = 1)),
    slope = slope_rep, aspect_flat_f = factor(0, levels = c(0, 1)),
    aspect_sin_adj = sin(180 * pi / 180), aspect_cos_adj = cos(180 * pi / 180),
    geologia_f = factor(geo_rep, levels = niveles_geo),
    cobertura_f = factor(cob_rep, levels = niveles_cob),
    doy = doy
  )
}

## --- curvas sinteticas: mismo TOTAL, forma distinta ---
## "gradual": el total repartido uniforme en los 1440 pasos
## "concentrada": 90% del total cae en el ULTIMO dia (48 pasos), como una tormenta real
generar_curvas <- function(total_mm) {
  gradual <- rep(total_mm / PASOS, PASOS)
  concentrada <- rep(total_mm * 0.10 / (PASOS - 48), PASOS - 48)
  pico_final <- rep(total_mm * 0.90 / 48, 48)
  concentrada <- c(concentrada, pico_final)
  list(gradual = cumsum(gradual), concentrada = cumsum(concentrada))
}

cat("Comparando 'gradual' (lluvia repartida uniforme en 30 dias) vs.\n")
cat("'concentrada' (90% del total cae en el ultimo dia, como una tormenta real),\n")
cat("MISMO total acumulado en ambos casos:\n\n")
cat(sprintf("%-12s %-15s %-15s %-15s\n", "Total (mm)", "AUC gradual", "AUC concentrada", "Diferencia"))

resultados <- list()
for (total_mm in c(100, 200, 300, 400, 500, 600)) {
  curvas <- generar_curvas(total_mm)
  nd_grad <- construir_fila(curvas$gradual)
  nd_conc <- construir_fila(curvas$concentrada)
  p_grad <- as.numeric(predict(modelo, newdata = nd_grad, type = "response"))
  p_conc <- as.numeric(predict(modelo, newdata = nd_conc, type = "response"))
  cat(sprintf("%-12d %-15.4f %-15.4f %-15.4f\n", total_mm, p_grad, p_conc, p_conc - p_grad))
  resultados[[as.character(total_mm)]] <- data.frame(total_mm = total_mm, prob_gradual = p_grad,
                                                        prob_concentrada = p_conc, diferencia = p_conc - p_grad)
}
tabla <- do.call(rbind, resultados)
write.csv(tabla, file.path(dir_out, "diagnostico_forma_af_resultado.csv"), row.names = FALSE)

## --- variante 2: dentro de un MISMO total (300mm), mover el pico de posicion
## (al principio de la ventana / a la mitad / al final) para ver si importa CUANDO cae ---
cat("\n\nMismo total (300mm), pero moviendo la posicion del pico dentro de la ventana de 30 dias:\n")
cat(sprintf("%-20s %-15s\n", "Posicion del pico", "Prob predicha"))
total_mm <- 300
for (pos in c("inicio_ventana_hace_30d", "mitad_ventana_hace_15d", "final_ventana_ayer")) {
  base <- rep(total_mm * 0.10 / (PASOS - 48), PASOS - 48)
  pico <- rep(total_mm * 0.90 / 48, 48)
  if (pos == "inicio_ventana_hace_30d") {
    serie <- c(pico, base)
  } else if (pos == "mitad_ventana_hace_15d") {
    mitad <- PASOS %/% 2
    serie <- c(base[1:mitad], pico, base[(mitad + 1):length(base)])
  } else {
    serie <- c(base, pico)
  }
  nd <- construir_fila(cumsum(serie))
  p <- as.numeric(predict(modelo, newdata = nd, type = "response"))
  cat(sprintf("%-20s %-15.4f\n", pos, p))
}

cat("\nFin diagnostico.\n")
sink(type = "message"); sink(); close(log_con)
