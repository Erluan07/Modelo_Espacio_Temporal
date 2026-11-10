# Entorno completo (R + Python) del modelo espacio-temporal.
# La imagen solo trae las dependencias: el codigo, config/ y data/ se montan
# desde la carpeta del proyecto (ver run_docker.bat), asi no hay que
# reconstruir la imagen al cambiar un script.
#
# rocker/r-ver usa Ubuntu 24.04 y el CRAN binario de Posit (instala refund rapido).
FROM rocker/r-ver:4.5.1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    SHAPE_RESTORE_SHX=YES

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

# --- Python ---
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt pyyaml h5py cftime

# --- R (mismos paquetes que install_r_packages.R) ---
RUN install2.r --error --skipinstalled --ncpus -1 refund mgcv pROC nanoparquet \
    && rm -rf /tmp/downloaded_packages

COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint && chmod +x /usr/local/bin/entrypoint

WORKDIR /app
ENTRYPOINT ["entrypoint"]
CMD ["bash"]
