# U-Net (LandCover.ai) land-cover semantic segmentation MCP server.
# Base ships torch 2.0.1 + torchvision + CUDA 11.7 (matches the checkpoint's
# training stack); CPU inference also works when no GPU is present.
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

WORKDIR /app

# rasterio needs no system GDAL here (manylinux wheel bundles it); opencv is not
# used (we read via rasterio), so no system libGL/libglib is required.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Fetch the trained checkpoint (full pickled smp U-Net, ~25MB) at build time so
# runtime stays offline. smp==0.3.3 is already installed above, so torch.load
# unpickles the model against matching class definitions.
RUN python -c "import urllib.request; \
    urllib.request.urlretrieve( \
        'https://github.com/souvikmajumder26/Land-Cover-Semantic-Segmentation-PyTorch/raw/main/models/trained_landcover_unet_efficientnet-b0_epochs18_patch512_batch16.pth', \
        '/app/landcover_unet.pth')"

# Pre-cache the imagenet encoder weights smp pulls for get_preprocessing_fn so
# the offline runtime does not attempt a download.
RUN python -c "import segmentation_models_pytorch as smp; smp.encoders.get_preprocessing_fn('efficientnet-b0', 'imagenet')"

COPY compute_segment.py /app/compute_segment.py
COPY mcp_server.py /app/mcp_server.py

ENV RS_SEGMENT_MODEL_PATH=/app/landcover_unet.pth

ENTRYPOINT ["python", "-u", "mcp_server.py"]
