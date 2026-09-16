# Build rs-segment-mcp for the host accelerator first; retain its vendor torch pair.
ARG BASE_IMAGE=rs-segment-mcp:0.1.0
FROM ${BASE_IMAGE}
WORKDIR /app
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple 'numpy==1.24.3' 'opencv-python-headless==4.10.0.84' 'matplotlib==3.8.4' 'pandas==2.2.3' 'seaborn==0.13.2' 'psutil==6.1.0' 'py-cpuinfo==9.0.0' 'shapely==2.0.6' && pip install --no-cache-dir --no-deps --index-url https://mirrors.aliyun.com/pypi/simple 'ultralytics==8.3.40' 'ultralytics-thop==2.0.12'
COPY yolo11s-obb.pt LICENSE provenance.json /app/detection-model/
RUN echo '43fa63102922e0701501241b307420d24fc55e080816888b18bf8c6f96b1a45a  /app/detection-model/yolo11s-obb.pt' | sha256sum -c -
COPY compute_detect.py tiled_obb.py mcp_server.py /app/
ENV RS_DETECT_MODEL_PATH=/app/detection-model/yolo11s-obb.pt YOLO_CONFIG_DIR=/tmp/ultralytics YOLO_AUTOINSTALL=False YOLO_OFFLINE=True OMP_NUM_THREADS=8 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-u", "mcp_server.py"]
