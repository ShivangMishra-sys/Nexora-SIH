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

# WhiteboxTools binary — pre-placed at docker/WhiteboxTools_linux_amd64.zip [44]
# If the zip is not in the repo, the RUN block falls back to a no-op.
COPY docker/WhiteboxTools_linux_amd64.zip /tmp/wbt.zip
RUN if [ -f /tmp/wbt.zip ]; then \
      unzip /tmp/wbt.zip -d /opt/whitebox && \
      chmod +x /opt/whitebox/WBT/whitebox_tools && \
      echo "WhiteboxTools installed"; \
    else \
      mkdir -p /opt/whitebox/WBT && \
      echo "WhiteboxTools zip not found — WBT operations will use NumPy fallback"; \
    fi

ENV WBT_PATH=/opt/whitebox/WBT

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir GDAL==$(gdal-config --version | awk -F'[.]' '{print $1"."$2}') && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Pre-create data directories so bootstrap can write without permission errors
RUN mkdir -p /data/dem /data/landcover /data/osm /data/swmm /data/snapshots

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
