# Reuse the shared host's verified tool dependencies; update application code only.
FROM rs-tools-mcp:0.2.0
USER root
COPY docker/rs_tools/*.py /app/
RUN python -c "import mcp_server"
USER appuser
