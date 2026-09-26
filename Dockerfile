# A single stage image. There is no build step to separate out: the project is
# pure Python and the UI is one static file with no bundler.
FROM python:3.12-slim

# Keeps the image small and the logs honest.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies are declared in pyproject.toml, so it is copied first and
# installed on its own. Docker then reuses that layer whenever only source
# changes, which is almost every rebuild.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

COPY eval/ ./eval/

# The warehouse and uploaded files live here. Mounted as a volume by compose so
# ingested data survives a rebuild.
RUN mkdir -p /app/data
ENV INSIGHTS_DATA_DIR=/app/data

# Listen on all interfaces inside the container. The default of 127.0.0.1 is
# right for a laptop and wrong here, because it would refuse the port mapping.
ENV INSIGHTS_HOST=0.0.0.0 \
    INSIGHTS_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "insights"]
