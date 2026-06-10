# RapidOCR (PP-OCRv4, ONNXRuntime) OCR MCP server. Chinese+English text
# recognition over raster imagery. Pure pip — the build network's Debian/Ubuntu
# apt mirrors return 502, so no apt-get here. The det/rec/cls ONNX models ship
# inside the rapidocr_onnxruntime wheel, so runtime stays fully offline.
FROM python:3.11.9-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --timeout 300 --retries 10 -r requirements.txt

# rapidocr_onnxruntime pulls in the full opencv-python, whose binary needs
# system GUI libs (libGL/libxcb) that we cannot apt-install on this build
# network. Replace it with the headless build: uninstall every opencv variant
# (they share the cv2/ dir), then force-reinstall headless so cv2 lands cleanly.
RUN (pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless || true) \
    && pip install --no-cache-dir --timeout 300 --retries 10 --force-reinstall "opencv-python-headless>=4.8.0,<5.0.0" \
    && python -c "import cv2; print('cv2', cv2.__version__)"

COPY compute_ocr.py /app/compute_ocr.py
COPY mcp_server.py /app/mcp_server.py

# Warm the model cache / fail fast at build time if the bundled ONNX models or
# their import chain are broken (build still has network; runtime will not).
# `import mcp_server` also guards the `from compute_ocr import ...` chain so a
# missing COPY fails the build instead of crashing at container runtime.
RUN python -c "import mcp_server" \
    && python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"

RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import numpy, rasterio, cv2, rapidocr_onnxruntime"

ENTRYPOINT ["python", "-u", "mcp_server.py"]
