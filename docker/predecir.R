## Lanza scripts/04_prediccion_operativa/predecir_diario.R SIN modificarlo:
## lee el script, reemplaza solo las 4 lineas de rutas ("ruta/a/...") por las
## de las variables de entorno (o los valores por defecto de abajo) y lo ejecuta.
## Uso: Rscript docker/predecir.R [YYYY-MM-DD]
rutas <- c(
  DIR_BUFFER_LLUVIA = Sys.getenv("DIR_BUFFER_LLUVIA", "data/buffer_lluvia_imerg"),
  RUTA_TERRENO      = Sys.getenv("RUTA_TERRENO", "data/terreno_por_ladera.csv"),
  RUTA_MODELO       = Sys.getenv("RUTA_MODELO", "data/modelo/modelo_espaciotemporal.rds"),
  DIR_SALIDA        = Sys.getenv("DIR_SALIDA_PREDICCIONES", "data/predicciones")
)
## --- Buffer recortado (solo velocidad, no cambia el resultado) ---------------
## predecir_diario.R arma un indice por ladera recorriendo TODAS las laderas del
## buffer y filtrando TODAS sus filas en cada vuelta (~40 min con 36M filas).
## Aqui se le entrega un buffer temporal que ya trae solo lo que va a usar:
## la ventana de 30 dias de FECHA, las laderas de RUTA_TERRENO y sin filas
## repetidas (ladera, hora). Los valores son los mismos -> misma prediccion.
args_fecha <- commandArgs(trailingOnly = TRUE)
fecha_pred <- if (length(args_fecha) >= 1) as.Date(args_fecha[1]) else Sys.Date()
fin_vent <- as.POSIXct(paste(fecha_pred, "23:30:00"), tz = "UTC")
ini_vent <- fin_vent - 1439 * 1800
archivos <- list.files(rutas[["DIR_BUFFER_LLUVIA"]], pattern = "[.](parquet|csv)$", full.names = TRUE)
if (length(archivos) > 0) {
  cat("Preparando buffer recortado para", format(fecha_pred), "...\n")
  leer <- function(f) {
    d <- if (grepl("[.]parquet$", f)) nanoparquet::read_parquet(f) else read.csv(f, stringsAsFactors = FALSE)
    d <- as.data.frame(d)[, c("ID_slope", "time", "precip_mm")]
    d$time <- as.POSIXct(d$time, tz = "UTC")
    d[d$time >= ini_vent & d$time <= fin_vent, ]
  }
  b <- do.call(rbind, lapply(archivos, leer))
  b$ID_slope <- as.integer(b$ID_slope)
  if (file.exists(rutas[["RUTA_TERRENO"]])) {
    ids <- unique(read.csv(rutas[["RUTA_TERRENO"]])$ID_slope)
    b <- b[b$ID_slope %in% ids, ]
  }
  b <- b[!duplicated(b[, c("ID_slope", "time")]), ]
  dir_tmp <- file.path(tempdir(), "buffer_recortado")
  dir.create(dir_tmp, showWarnings = FALSE)
  nanoparquet::write_parquet(b, file.path(dir_tmp, "buffer.parquet"))
  cat("  ", nrow(b), "filas,", length(unique(b$ID_slope)), "laderas (de",
      length(archivos), "archivos del buffer)\n\n")
  rutas[["DIR_BUFFER_LLUVIA"]] <- dir_tmp
  rm(b); invisible(gc())
}

script <- "scripts/04_prediccion_operativa/predecir_diario.R"
src <- readLines(script, encoding = "UTF-8", warn = FALSE)
for (v in names(rutas)) {
  i <- grep(paste0("^", v, " *<-"), src)
  if (length(i) != 1) stop("No encuentro la linea '", v, " <-' en ", script)
  src[i] <- sprintf('%s <- "%s"', v, rutas[[v]])
  cat(sprintf("  %-17s = %s\n", v, rutas[[v]]))
}
cat("\n")
eval(parse(text = src, encoding = "UTF-8"), envir = globalenv())
