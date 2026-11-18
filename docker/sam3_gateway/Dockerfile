FROM python:3.11-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir "fastmcp==4.2.1" "httpx2>=2.16.2,<3"
COPY gateway.py /app/gateway.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
USER 65532:65532
ENTRYPOINT ["python", "-u", "/app/gateway.py"]
