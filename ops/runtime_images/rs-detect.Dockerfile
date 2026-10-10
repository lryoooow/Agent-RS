# Preserve the validated Hygon GPU runtime and model checkpoint.
FROM rs-detect-mcp:0.2.0
COPY docker/rs_detect/compute_detect.py docker/rs_detect/tiled_obb.py docker/rs_detect/mcp_server.py /app/
RUN python -c "import mcp_server"
