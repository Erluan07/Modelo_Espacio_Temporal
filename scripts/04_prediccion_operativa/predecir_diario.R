## ===========================================================================
## Predicción OPERATIVA diaria del modelo espacio-temporal: para cada
## ladera/punto de la zona, construye la ventana acumulada de 30 días (a
## partir del buffer de lluvia IMERG ya actualizado, ver
## scripts/01_descarga_lluvia/) y predice la probabilidad con el modelo ya
## ajustado (ver scripts/03_ajuste_modelo/).
##
## Este es el script que debe correr la tarea programada (cron) diaria --
## ver REQUERIMIENTOS_TECNICOS.md para el resto de la infraestructura.
##
## Requiere: library(refund) cargada ANTES de predict() (el modelo es un
## objeto "pfr", no un "gam" normal -- sin refund cargado, predict() cae en
## el metodo generico de "lm" y falla con un error críptico, ya nos pasó).
##
## Uso: Rscript predecir_diario.R [YYYY-MM-DD]
##      (sin argumento, usa la fecha de hoy)
## ===========================================================================

suppressPackageStartupMessages(library(refund))

# --- CONFIGURAR: rutas reales ------------------------------------------------
DIR_BUFFER_LLUVIA <- "ruta/a/data/buffer_lluvia_imerg"      # parquets/csv de 01_descarga_lluvia
RUTA_TERRENO <- "ruta/a/terreno_por_ladera.csv"              # x_m, y_m, ID_slope, slope, aspect, geologia, cobertura
RUTA_MODELO <- "ruta/a/modelo_espaciotemporal.rds"
DIR_SALIDA <- "ruta/a/data/predicciones"

PASOS <- 1440  # 30 dias x 48 medias horas

args <- commandArgs(trailingOnly = TRUE)
FECHA <- if (length(args) >= 1) as.Date(args[1]) else Sys.Date()

dir.create(DIR_SALIDA, showWarnings = FALSE, recursive = TRUE)
log_con <- file(file.path(DIR_SALIDA, paste0("log_prediccion_", format(FECHA, "%Y%m%d"), ".txt")), open = "wt")
sink(log_con, split = TRUE)
cat("=== Predicción diaria --", format(FECHA), "===\n")
cat("Inicio:", format(Sys.time()), "\n\n")

## --- 1. Cargar el buffer de lluvia (parquet/csv con columnas ID_slope, time, precip_mm) ---
cat("Cargando buffer de lluvia...\n")
archivos <- list.files(DIR_BUFFER_LLUVIA, pattern = "\\.(parquet|csv)$", full.names = TRUE)
if (length(archivos) == 0) stop("No hay archivos de lluvia en ", DIR_BUFFER_LLUVIA)
leer_uno <- function(f) {
  if (grepl("\\.parquet$", f)) nanoparquet::read_parquet(f) else read.csv(f, stringsAsFactors = FALSE)
}
series <- do.call(rbind, lapply(archivos, leer_uno))
series$time <- as.POSIXct(series$time, tz = "UTC")
series$ID_slope <- as.integer(series$ID_slope)
cat("  ", nrow(series), "filas,", length(unique(series$ID_slope)), "laderas,",
    format(min(series$time)), "a", format(max(series$time)), "\n\n")

## índice rápido por ladera
series_por_ladera <- new.env()
for (idv in unique(series$ID_slope)) {
  s <- series[series$ID_slope == idv, ]
  s <- s[order(s$time), ]
  assign(as.character(idv), setNames(s$precip_mm, as.character(s$time)), envir = series_por_ladera)
}

## --- 2. Terreno (fijo, no cambia día a día) ---
cat("Cargando terreno...\n")
zt <- read.csv(RUTA_TERRENO, stringsAsFactors = FALSE)
zt <- zt[!duplicated(zt[, c("x_m", "y_m")]), ]
cat("  ", nrow(zt), "puntos (", length(unique(zt$ID_slope)), "laderas )\n\n")

zt$aspect_flat <- as.integer(zt$aspect == -1)
zt$non_flat <- 1L - zt$aspect_flat
zt$aspect_adj <- ifelse(zt$aspect == -1, 0, zt$aspect)
rad <- zt$aspect_adj * pi / 180
zt$aspect_sin_adj <- zt$non_flat * sin(rad)
zt$aspect_cos_adj <- zt$non_flat * cos(rad)
zt$aspect_flat_f <- factor(zt$aspect_flat, levels = c(0, 1))

## --- 3. Modelo ---
modelo <- readRDS(RUTA_MODELO)
zt$geologia_f <- factor(zt$geologia, levels = levels(modelo$model$geologia_f))
zt$cobertura_f <- factor(zt$cobertura, levels = levels(modelo$model$cobertura_f))

construir_ventana <- function(vec_ladera, fecha) {
  ## OJO: deja NA donde falte una media hora en el buffer -- NO se rellena
  ## con 0. Rellenar con 0 disfrazaría un hueco de datos como "no llovió",
  ## y el modelo es MUY sensible a la forma de la curva cerca de "hoy" (ver
  ## LIMITACIONES.md #2) -- justo la zona donde Early/Late tienen más
  ## probabilidad de tener huecos por latencia. cumsum() propaga el NA
  ## hacia adelante, así que basta un hueco para invalidar toda la fila
  ## (mismo criterio ESTRICTO que 02_construccion_muestra/03_construir_ventanas_imerg.py
  ## usa en el entrenamiento -- entrenamiento y producción deben tratar los
  ## huecos igual, si no las predicciones no son comparables con el AUC
  ## reportado).
  fin <- as.POSIXct(paste(fecha, "23:30:00"), tz = "UTC")
  pasos <- seq(fin - 30 * 24 * 3600 + 1800, fin, by = "30 min")
  as.numeric(vec_ladera[as.character(pasos)])
}

## --- 4. Construir la ventana acumulada de 30d, UNA vez por ladera, y predecir ---
cat("Construyendo ventanas de 30 días y prediciendo...\n")
ladera_ids <- unique(zt$ID_slope)
curvas <- vector("list", length(ladera_ids))
names(curvas) <- as.character(ladera_ids)
laderas_sin_serie <- character(0)
laderas_con_hueco <- character(0)

for (idv in ladera_ids) {
  idc <- as.character(idv)
  vec_ladera <- if (exists(idc, envir = series_por_ladera)) get(idc, envir = series_por_ladera) else NULL
  if (is.null(vec_ladera)) {
    laderas_sin_serie <- c(laderas_sin_serie, idc)
    curvas[[idc]] <- rep(NA_real_, PASOS)
    next
  }
  media_hora <- construir_ventana(vec_ladera, FECHA)
  if (anyNA(media_hora)) laderas_con_hueco <- c(laderas_con_hueco, idc)
  curvas[[idc]] <- cumsum(media_hora)
}
if (length(laderas_sin_serie) > 0) {
  cat("  AVISO:", length(laderas_sin_serie), "laderas sin ninguna serie de lluvia en el buffer, "
      , "se omiten de la prediccion de hoy.\n")
}
if (length(laderas_con_hueco) > 0) {
  cat("  AVISO:", length(laderas_con_hueco), "laderas con al menos una media hora faltante ",
      "en la ventana de 30 dias (buffer incompleto), se omiten de la prediccion de hoy ",
      "(mismo criterio estricto que en entrenamiento -- no se rellena con 0).\n", sep = "")
}

mat_precip <- do.call(rbind, curvas[as.character(zt$ID_slope)])
ok <- stats::complete.cases(mat_precip)

nd <- zt[ok, ]
nd$precip_imerg <- I(mat_precip[ok, , drop = FALSE])
nd$doy <- as.numeric(format(FECHA, "%j"))

pred <- as.numeric(predict(modelo, newdata = nd, type = "response"))

salida <- data.frame(fecha = FECHA, ID_slope = nd$ID_slope, x_m = nd$x_m, y_m = nd$y_m, probabilidad = pred)
out_file <- file.path(DIR_SALIDA, paste0("prediccion_", format(FECHA, "%Y%m%d"), ".csv"))
write.csv(salida, out_file, row.names = FALSE)

cat("\nPredichas", nrow(salida), "de", nrow(zt), "laderas -- probabilidad media:",
    round(mean(pred), 4), ", máxima:", round(max(pred), 4), "\n")
cat("Guardado:", out_file, "\n")
cat("\nFin:", format(Sys.time()), "\n")
sink(); close(log_con)
