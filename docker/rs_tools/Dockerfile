FROM python:3.11.9-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY compute_raster_inspect.py /app/compute_raster_inspect.py
COPY compute_ndvi.py /app/compute_ndvi.py
COPY compute_spectral_index.py /app/compute_spectral_index.py
COPY compute_band_composite.py /app/compute_band_composite.py
COPY mcp_server.py /app/mcp_server.py

RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python -c "import numpy, rasterio, PIL"

ENTRYPOINT ["python", "-u", "mcp_server.py"]
