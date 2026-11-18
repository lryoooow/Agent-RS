ARG OPERATOR_IMAGE=rs-tools-mcp:0.1.0
FROM ${OPERATOR_IMAGE}
USER root
# Reuse the operator image's installed compute dependencies.
RUN python -m venv --system-site-packages /opt/operator-mcp && \
    /opt/operator-mcp/bin/pip install --no-cache-dir \
      "fastmcp==4.2.1; python_version >= '3.11'" "fastmcp==2.14.7; python_version < '3.11'"
COPY server.py /app/operator_server.py
USER 1000:1000
WORKDIR /app
ENTRYPOINT ["/opt/operator-mcp/bin/python","-u","/app/operator_server.py"]
