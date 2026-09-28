# ============================================================
# UrbanFlow v2 — Backend Dockerfile
# WhiteboxTools binary included at build time [44]
# ============================================================
FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps: GDAL, GEOS, PROJ, build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    gcc g++ make unzip curl git \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# WhiteboxTools binary [44]
# Uses pre-placed docker/WhiteboxTools_linux_amd64.zip if present, or downloads it during build.
COPY docker/ /tmp/docker-assets/
RUN mkdir -p /opt/whitebox && \
    if [ -f /tmp/docker-assets/WhiteboxTools_linux_amd64.zip ]; then \
      unzip -q /tmp/docker-assets/WhiteboxTools_linux_amd64.zip -d /opt/whitebox && \
      if [ -d /opt/whitebox/WhiteboxTools_linux_amd64/WBT ]; then mv /opt/whitebox/WhiteboxTools_linux_amd64/WBT /opt/whitebox/WBT; fi && \
      chmod +x /opt/whitebox/WBT/whitebox_tools && \
      echo "WhiteboxTools installed from local archive"; \
    elif curl -fsSL https://www.whiteboxgeo.com/WBT_Linux/WhiteboxTools_linux_amd64.zip -o /tmp/wbt.zip && [ -s /tmp/wbt.zip ]; then \
      unzip -q /tmp/wbt.zip -d /opt/whitebox && \
      if [ -d /opt/whitebox/WhiteboxTools_linux_amd64/WBT ]; then mv /opt/whitebox/WhiteboxTools_linux_amd64/WBT /opt/whitebox/WBT; fi && \
      chmod +x /opt/whitebox/WBT/whitebox_tools && \
      rm -f /tmp/wbt.zip && \
      echo "WhiteboxTools downloaded and installed"; \
    else \
      mkdir -p /opt/whitebox/WBT && \
      echo "WhiteboxTools zip not found and download skipped — WBT operations will use NumPy fallback"; \
    fi && \
    rm -rf /tmp/docker-assets

ENV WBT_PATH=/opt/whitebox/WBT

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel "numpy<2.0.0" && \
    pip install --no-cache-dir --no-build-isolation GDAL==$(gdal-config --version) && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Pre-create data directories so bootstrap can write without permission errors
RUN mkdir -p /data/dem /data/landcover /data/osm /data/swmm /data/snapshots

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
