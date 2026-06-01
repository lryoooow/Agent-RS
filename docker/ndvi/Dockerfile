FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip gdal-bin libgdal-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir rasterio numpy matplotlib Pillow

COPY compute_ndvi.py /app/compute_ndvi.py

WORKDIR /app
ENTRYPOINT ["python3", "compute_ndvi.py"]
