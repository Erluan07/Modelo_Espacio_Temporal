# Instala las dependencias de R necesarias para este repo.
# Uso: Rscript install_r_packages.R

paquetes <- c("refund", "mgcv", "pROC", "nanoparquet")
faltantes <- paquetes[!(paquetes %in% installed.packages()[, "Package"])]
if (length(faltantes) > 0) install.packages(faltantes, repos = "https://cloud.r-project.org")
cat("Listo. Paquetes disponibles:", paste(paquetes, collapse = ", "), "\n")
