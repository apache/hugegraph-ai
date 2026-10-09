# ontogeny -- single image: API + built UI on one port.
#
# Build:  docker build -f deploy/Dockerfile -t ontogeny .
# Run:    docker run -p 8000:8000 -v ontogeny-data:/data ontogeny
#
# The UI stage compiles web/ and the app stage serves web/dist from the same
# origin as the API (no CORS, no second service).

# ---------- stage 1: build the SPA ----------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- stage 2: python service ----------
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ONTOGENY_DATA_DIR=/data \
    ONTOGENY_DB_DSN=sqlite+aiosqlite:////data/ontogeny.db \
    ONTOGENY_UI_DIR=/app/web/dist \
    ONTOGENY_PACKAGE_ROOT=/data/pkg \
    ONTOGENY_EXTENSIONS_DIR=/app/extensions

WORKDIR /app

COPY pyproject.toml ./
COPY server/ ./server/
# the MCP tool surface (/mcp) is part of the shipped agent surface
RUN pip install --no-cache-dir '.[mcp]'

COPY extensions/ ./extensions/
COPY domains/ ./domains/
COPY --from=ui /ui/dist ./web/dist

# demo bootstrap needs the example package next to the service
RUN mkdir -p /data

# non-root by default; /data is the only writable path (volume it)
RUN useradd --create-home --uid 10001 ontogeny && chown -R ontogeny:ontogeny /app /data
USER ontogeny

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/meta/ontology', timeout=4).status==200 else 1)"

# --demo seeds sources, copies the package into /data/pkg and serves the UI
CMD ["ontogeny", "serve", "--demo", "--data-dir", "/data", "--host", "0.0.0.0", "--port", "8000", "--no-build-ui"]
