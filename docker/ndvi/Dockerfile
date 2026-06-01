FROM python:3.11-slim

RUN pip install --no-cache-dir rasterio numpy matplotlib Pillow

COPY compute_ndvi.py /app/compute_ndvi.py

WORKDIR /app
ENTRYPOINT ["python", "compute_ndvi.py"]
