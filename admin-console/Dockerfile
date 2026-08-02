# ArenaRank Admin Console — production image.
#
# Multi-stage: build the SPA with node, then serve the static bundle with caddy,
# which ALSO reverse-proxies /api to the backend.
#
# Why caddy proxies /api instead of the browser calling the API directly:
# the console's "local" preset uses an EMPTY base, so requests go to a relative
# `/api` path (see src/lib/backend.ts). In dev that rides the Vite proxy. A
# static build has no dev server, so without this proxy the operator would be
# forced onto the "custom" preset with an absolute URL — which is cross-origin
# and would need the backend's CORS_ORIGINS widened to include the console.
# Serving both from ONE origin keeps the admin surface CORS-free and means a
# single tunnelled port reaches the whole console.
#
# The console is an operator UI (noindex). It carries no secrets — the admin key
# is typed in the UI and kept in the browser's localStorage per backend — but it
# should still not be exposed publicly; the compose files bind it to 127.0.0.1.

# ---- build ---------------------------------------------------------------
FROM node:20-slim AS build
WORKDIR /app

# Copy manifests first so `npm ci` is cached independently of source edits.
COPY package.json package-lock.json* ./
# npm ci needs a lockfile; fall back to install so the image builds either way.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
# VITE_* are baked in at BUILD time (Vite inlines them), not read at runtime.
ARG VITE_PROD_API_URL=""
ENV VITE_PROD_API_URL=$VITE_PROD_API_URL
RUN npm run build

# ---- serve ---------------------------------------------------------------
FROM caddy:2-alpine AS serve
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080
