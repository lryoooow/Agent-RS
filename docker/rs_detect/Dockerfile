# PP-YOLOE-R rotated-box detection MCP server (DOTA 15-class, RGB).
# Base ships paddlepaddle-gpu 2.6.2 + Python 3.10 + CUDA 12.0; CPU kernels
# are included too, so the same image falls back to CPU when no GPU is present.
FROM paddlepaddle/paddle:2.6.2-gpu-cuda12.0-cudnn8.9-trt8.6

WORKDIR /app

# NOTE: no apt-get here. The build network cannot reach the Ubuntu mirror
# (archive.ubuntu.com returns 502). opencv-python-headless needs no system
# libGL/libglib, and PaddleDetection is fetched as a tarball via Python's
# urllib instead of git, so no system packages are required.

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Fetch PaddleDetection (release/2.6) as a tarball — provides the rotated-box
# deploy pipeline — without needing git.
RUN python -c "import urllib.request, tarfile, io; \
    data = urllib.request.urlopen('https://github.com/PaddlePaddle/PaddleDetection/archive/refs/heads/release/2.6.tar.gz', timeout=300).read(); \
    tarfile.open(fileobj=io.BytesIO(data), mode='r:gz').extractall('/app'); \
    import os; os.rename('/app/PaddleDetection-release-2.6', '/app/PaddleDetection')" \
    && pip install --no-cache-dir -r /app/PaddleDetection/requirements.txt

# Normalize the dependency stack to a single consistent set. PaddleDetection's
# requirements pull opencv-python 4.5.5.64 (whose binary lacks cv2.dnn.DictValue) on
# top of the 4.10 typing stubs, which crashes `import cv2`; they also pin numpy 1.23.5
# (below rasterio's >=1.24 floor) and ship the empty `sklearn==0.0` stub instead of
# the real importable module (ppdet's tracker import chain does `import sklearn`).
# Force one headless OpenCV, a numpy satisfying rasterio + paddle 2.6.2 (<2.0), and
# the actual scikit-learn package.
RUN (pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless || true) \
    && pip install --no-cache-dir \
        "opencv-python-headless==4.10.0.84" \
        "numpy==1.26.4" \
        "scikit-learn==1.3.2" \
        "Pillow==9.5.0"

# Download PP-YOLOE-R-l DOTA weights and export an inference model at build time
# (network is available during build; runtime stays offline).
RUN mkdir -p /app/weights \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://paddledet.bj.bcebos.com/models/ppyoloe_r_crn_l_3x_dota.pdparams', '/app/weights/ppyoloe_r_crn_l_3x_dota.pdparams')" \
    && cd /app/PaddleDetection \
    && python tools/export_model.py \
        -c configs/rotate/ppyoloe_r/ppyoloe_r_crn_l_3x_dota.yml \
        -o weights=/app/weights/ppyoloe_r_crn_l_3x_dota.pdparams \
        --output_dir /app/inference_model

COPY compute_detect.py /app/compute_detect.py
COPY mcp_server.py /app/mcp_server.py

ENV RS_DETECT_MODEL_DIR=/app/inference_model/ppyoloe_r_crn_l_3x_dota
ENV PADDLEDET_DIR=/app/PaddleDetection

ENTRYPOINT ["python", "-u", "mcp_server.py"]
