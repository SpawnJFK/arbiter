# Arbiter web (Next.js 16). Build context: apps/web
#   docker build -f deploy/web.Dockerfile apps/web
# Kept in deploy/ so the infra lives in one place. Prefers Next "standalone" output
# (set output: "standalone" in apps/web/next.config.ts); falls back to `next start`
# with full node_modules if standalone output is not enabled yet.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Baked into the client bundle at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build \
 && mkdir -p /out \
 && if [ -d .next/standalone ]; then \
      cp -r .next/standalone/. /out/ \
      && mkdir -p /out/.next && cp -r .next/static /out/.next/static \
      && if [ -d public ]; then cp -r public /out/public; fi \
      && echo "standalone" > /out/.arbiter-mode; \
    else \
      npm prune --omit=dev \
      && cp -r package.json node_modules .next /out/ \
      && if [ -d public ]; then cp -r public /out/public; fi \
      && echo "next-start" > /out/.arbiter-mode; \
    fi

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /out ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["sh", "-c", "if [ \"$(cat .arbiter-mode)\" = standalone ]; then exec node server.js; else exec node node_modules/next/dist/bin/next start -p $PORT -H $HOSTNAME; fi"]
