## ===========================================================================
## FGAM espacio-temporal por pixel, TODAS LAS ZONAS, con IMERG HORARIO (GEE),
## presencias restringidas a Fuente Planet(scope) 2024-2025 -- version 2 del
## experimento IMERG horario, que corrige el problema de fecha-memorizacion
## encontrado en la version zona-4/Google-Earth-Pro (ver
## log_ajustar_fgam_imerg_zona4.txt: AUC aleatoria/espacial ~0.92-0.93 pero
## temporal ~0.51, explicado por fechas de "captura" GEP compartidas por
## cientos de eventos distintos).
##
## Particion temporal aqui: train = 2024, test = 2025 (unico corte posible
## con solo 2 años de cobertura Planet).
##
## Uso: Rscript ajustar_modelo.R
## ===========================================================================

suppressPackageStartupMessages({ library(refund); library(pROC) })
set.seed(42)
dir_out <- "."
PASOS <- 1440

log_con <- file(file.path(dir_out, "log_ajustar_modelo.txt"), open = "wt", encoding = "UTF-8")
sink(log_con, split = TRUE)
sink(log_con, type = "message", append = TRUE)

t0 <- Sys.time()
cat("=== FGAM IMERG horario, TODAS LAS ZONAS, presencias Planet 2024-2025 ===\n")
cat("Inicio:", format(t0), "\n\n")

df <- read.csv(file.path(dir_out, "muestra_imerg_30d.csv"), stringsAsFactors = FALSE)
df$fecha <- as.Date(df$fecha)
df$presencia <- as.integer(df$presencia)
df$anio <- as.integer(format(df$fecha, "%Y"))
cat("Filas:", nrow(df), "| presencias:", sum(df$presencia == 1), "\n")
cat("Presencias por zona:\n")
print(table(df$Zona[df$presencia == 1]))
cat("Presencias por anio:\n")
print(table(df$anio[df$presencia == 1]))
cat("Fechas distintas entre las presencias:", length(unique(df$fecha[df$presencia == 1])), "\n\n")

df$aspect_flat <- as.integer(df$aspect == -1)
df$non_flat <- 1L - df$aspect_flat
df$aspect_adj <- ifelse(df$aspect == -1, 0, df$aspect)
rad <- df$aspect_adj * pi / 180
df$aspect_sin_adj <- df$non_flat * sin(rad)
df$aspect_cos_adj <- df$non_flat * cos(rad)
df$aspect_flat_f <- factor(df$aspect_flat, levels = c(0, 1))
niveles_geologia <- sort(unique(df$geologia))
niveles_cobertura <- sort(unique(df$cobertura))
df$geologia_f <- factor(df$geologia, levels = niveles_geologia)
df$cobertura_f <- factor(df$cobertura, levels = niveles_cobertura)

cols_h <- paste0("h", -(PASOS - 1):0)
cols_h <- gsub("h-", "h.", cols_h, fixed = TRUE)
df$precip_imerg <- I(as.matrix(df[, cols_h]))
argvals_imerg <- -(PASOS - 1):0

formula_str <- paste0(
  "presencia ~ af(precip_imerg, argvals = argvals_imerg, k = c(8, 5)) + ",
  "s(slope, k = 10) + aspect_flat_f + s(aspect_sin_adj, k = 10) + s(aspect_cos_adj, k = 10) + ",
  "geologia_f + cobertura_f + s(doy, bs = 'cc', k = 10)"
)
cat("Formula:", formula_str, "\n\n")

## --- particiones ---
n <- nrow(df)
set.seed(42)
idx_train_rand <- sample(seq_len(n), size = round(0.7 * n))
split_rand <- rep("train", n); split_rand[-idx_train_rand] <- "test"

set.seed(42)
k_clusters <- min(10, floor(n / 30))
km <- kmeans(scale(df[, c("x_m", "y_m")]), centers = k_clusters, nstart = 10, iter.max = 50)
cluster_esp <- km$cluster
tab_cl <- table(cluster_esp)
set.seed(42)
orden_cl <- sample(as.integer(names(tab_cl)))
acumcl <- cumsum(tab_cl[as.character(orden_cl)])
clusters_test <- orden_cl[acumcl <= round(0.30 * n)]
if (length(clusters_test) == 0) clusters_test <- orden_cl[1]
split_esp <- ifelse(cluster_esp %in% clusters_test, "test", "train")
cat("Particion espacial:", k_clusters, "clusters, test =", sum(split_esp == "test"),
    sprintf("(%.1f%%)\n", 100 * mean(split_esp == "test")))

## temporal: train=2024, test=2025 (unico corte posible con 2 años de datos)
split_temp <- ifelse(df$anio >= 2025, "test", "train")
cat("Particion temporal: train 2024 (n=", sum(split_temp == "train"),
    ", pres=", sum(df$presencia[split_temp == "train"]), "), test 2025 (n=",
    sum(split_temp == "test"), ", pres=", sum(df$presencia[split_temp == "test"]), ")\n\n", sep = "")

particiones <- list(aleatoria = split_rand, espacial = split_esp, temporal = split_temp)

compute_auc <- function(obs, pred) {
  if (length(unique(obs)) < 2) return(NA_real_)
  as.numeric(pROC::auc(pROC::roc(obs, pred, quiet = TRUE, direction = "<")))
}

metricas <- list()
for (pn in names(particiones)) {
  sp <- particiones[[pn]]
  train <- df[sp == "train", ]; test <- df[sp == "test", ]
  cat(sprintf("[%s] train=%d (pres=%d) test=%d (pres=%d) ... ", pn, nrow(train), sum(train$presencia),
              nrow(test), sum(test$presencia)))
  if (sum(train$presencia) < 5 || length(unique(test$presencia)) < 2) {
    cat("SALTADO (muy pocos casos)\n")
    next
  }
  t1 <- Sys.time()
  m <- tryCatch(pfr(as.formula(formula_str), data = train, family = binomial(), method = "REML"),
                error = function(e) { cat("ERROR:", conditionMessage(e), "\n"); NULL })
  if (is.null(m)) next
  pred <- as.numeric(predict(m, newdata = test, type = "response"))
  auc <- compute_auc(test$presencia, pred)
  cat(sprintf("AUC=%.4f (%.1fs)\n", auc, as.numeric(Sys.time() - t1, units = "secs")))
  metricas[[pn]] <- data.frame(particion = pn, n_train = nrow(train), n_pos_train = sum(train$presencia),
                                n_test = nrow(test), n_pos_test = sum(test$presencia), AUC = auc)
  rm(m); gc(verbose = FALSE)
}

tabla <- do.call(rbind, metricas)
cat("\n=== RESUMEN ===\n")
print(tabla)
write.csv(tabla, file.path(dir_out, "metricas_modelo.csv"), row.names = FALSE)

cat("\nAjustando modelo final (100% de los datos)...\n")
t1 <- Sys.time()
modelo_final <- tryCatch(pfr(as.formula(formula_str), data = df, family = binomial(), method = "REML"),
                          error = function(e) { cat("ERROR:", conditionMessage(e), "\n"); NULL })
cat(sprintf("Ajuste final: %.1f s\n", as.numeric(Sys.time() - t1, units = "secs")))
if (!is.null(modelo_final)) {
  dev_exp <- (modelo_final$null.deviance - deviance(modelo_final)) / modelo_final$null.deviance
  cat(sprintf("Deviance explicada (100%% datos): %.4f\n", dev_exp))
  saveRDS(modelo_final, file.path(dir_out, "modelo_espaciotemporal.rds"))
  cat("Guardado: modelo_espaciotemporal.rds\n")
}

cat("\nTiempo total:", format(Sys.time() - t0), "\n")
sink(type = "message"); sink(); close(log_con)
