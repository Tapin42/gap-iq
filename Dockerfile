# --- Stage 1: build the SPA ---------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# --- Stage 2: runtime ---------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /srv

# git is needed because racedata is pinned by git URL rather than published to PyPI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app/ ./app/
COPY capture/ ./capture/
COPY config/ ./config/
RUN pip install --no-cache-dir .

COPY --from=web /web/dist ./web/dist

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
