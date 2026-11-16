# ResearchTrace lite image: static web build + FastAPI API/worker (CPU only).
# Base images are build arguments so a registry mirror can be used where
# Docker Hub is rate-limited, e.g. --build-arg REGISTRY=mirror.gcr.io/library/
ARG REGISTRY=
FROM ${REGISTRY}node:22-bookworm-slim AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM ${REGISTRY}python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-droid-fallback \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --no-compile -r requirements.lock
COPY services ./services
COPY --from=web /build/dist ./apps/web/dist
RUN useradd --uid 10001 --create-home researchtrace \
 && mkdir -p /app/data && chown researchtrace:researchtrace /app/data
USER researchtrace
ENV RT_HOST=0.0.0.0 RT_PORT=18970 RT_DATA_DIR=/app/data MPLCONFIGDIR=/app/data/matplotlib PYTHONUNBUFFERED=1
EXPOSE 18970
CMD ["python", "-m", "services.api.serve"]
