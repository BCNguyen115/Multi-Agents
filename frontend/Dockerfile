# syntax=docker/dockerfile:1.7
# Next.js 15 (React 19) frontend — standalone output, non-root runtime.
#   docker build -t agent-frontend ./frontend
#   docker build --build-arg API_URL=http://api.internal:8000 -t agent-frontend ./frontend
ARG NODE_VERSION=20

# ---- deps: reproducible install from the lockfile ----
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# ---- builder ----
FROM node:${NODE_VERSION}-alpine AS builder
WORKDIR /app
# next.config.mjs rewrites /api/* to API_URL and Next bakes rewrites at build time
ARG API_URL=http://backend:8000
ENV API_URL=${API_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public && npm run build

# ---- runner: only the traced standalone server + static assets ----
FROM node:${NODE_VERSION}-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -qO- http://127.0.0.1:3000/ > /dev/null || exit 1

CMD ["node", "server.js"]
