FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime@sha256:c8268a92a69bd500f8be0e665b2630ee006dadaf7bfbc24249141b15ff622755
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt && python -m pip install --no-cache-dir --no-deps ultralytics==8.3.40 ultralytics-thop==2.0.12
COPY yolo11s-obb.pt LICENSE provenance.json /app/detection-model/
RUN echo '43fa63102922e0701501241b307420d24fc55e080816888b18bf8c6f96b1a45a  /app/detection-model/yolo11s-obb.pt' | sha256sum -c -
COPY compute_detect.py tiled_obb.py mcp_server.py /app/
ENV RS_DETECT_REQUIRE_GPU=1 RS_DETECT_MODEL_PATH=/app/detection-model/yolo11s-obb.pt YOLO_CONFIG_DIR=/tmp/ultralytics YOLO_AUTOINSTALL=False YOLO_OFFLINE=True OMP_NUM_THREADS=8 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-u", "mcp_server.py"]
