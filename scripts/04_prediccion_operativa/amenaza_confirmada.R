## ===========================================================================
## Amenaza CONFIRMADA por ladera: la moda de la clase de amenaza de los últimos
## 5 días (el día pedido y los 4 anteriores). En empate, gana la clase más alta.
## Es la amenaza que entra a la matriz de la consola (no se usa la clase de un
## solo día).
##
## Lee los prediccion_AAAAMMDD.csv que deja predecir_diario.R (columna
## clase_num: 0 = baja, 1 = media, 2 = alta, 3 = muy alta). Si faltan días
## (por ejemplo, el proceso diario no corrió), usa los que haya y lo informa
## en la columna n_dias.
##
## Uso: Rscript amenaza_confirmada.R [YYYY-MM-DD]
##      (sin argumento, usa la fecha de hoy)
## ===========================================================================

# --- CONFIGURAR: la misma carpeta DIR_SALIDA de predecir_diario.R -------------
DIR_SALIDA <- "ruta/a/data/predicciones"

VENTANA_DIAS <- 5
NOMBRES_CLASE <- c("baja", "media", "alta", "muy alta")

args <- commandArgs(trailingOnly = TRUE)
FECHA <- if (length(args) >= 1) as.Date(args[1]) else Sys.Date()

dias <- seq(FECHA - (VENTANA_DIAS - 1), FECHA, by = "day")
archivos <- file.path(DIR_SALIDA, paste0("prediccion_", format(dias, "%Y%m%d"), ".csv"))
existen <- file.exists(archivos)
if (!existen[length(dias)]) stop("No existe la predicción del día pedido: ", archivos[length(dias)])
if (any(!existen)) {
  cat("AVISO: faltan", sum(!existen), "de", VENTANA_DIAS, "días (", paste(format(dias[!existen]), collapse = ", "),
      "). Se usa la moda de los", sum(existen), "disponibles.\n")
}

pred <- do.call(rbind, lapply(archivos[existen], function(f) {
  d <- read.csv(f, stringsAsFactors = FALSE)
  if (!"clase_num" %in% names(d)) stop(f, " no tiene la columna clase_num: corra predecir_diario.R actualizado.")
  d[, c("ID_slope", "x_m", "y_m", "clase_num")]
}))

## moda de las clases; en empate, la más alta
moda_alta <- function(x) {
  x <- x[!is.na(x)]
  if (length(x) == 0) return(NA_integer_)
  tb <- table(x)
  max(as.integer(names(tb)[tb == max(tb)]))
}

clave <- paste(pred$ID_slope, pred$x_m, pred$y_m)
res <- data.frame(
  ID_slope = tapply(pred$ID_slope, clave, `[`, 1),
  x_m = tapply(pred$x_m, clave, `[`, 1),
  y_m = tapply(pred$y_m, clave, `[`, 1),
  clase_confirmada_num = tapply(pred$clase_num, clave, moda_alta),
  n_dias = tapply(!is.na(pred$clase_num), clave, sum)
)
res$clase_confirmada <- NOMBRES_CLASE[res$clase_confirmada_num + 1L]
res <- cbind(fecha = FECHA, res[order(res$ID_slope), ], row.names = NULL)

out_file <- file.path(DIR_SALIDA, paste0("amenaza_confirmada_", format(FECHA, "%Y%m%d"), ".csv"))
write.csv(res, out_file, row.names = FALSE)
cat("Amenaza confirmada", format(FECHA), ":", nrow(res), "laderas ->",
    paste(NOMBRES_CLASE, table(factor(res$clase_confirmada_num, levels = 0:3)), sep = " = ", collapse = ", "), "\n")
cat("Guardado:", out_file, "\n")
