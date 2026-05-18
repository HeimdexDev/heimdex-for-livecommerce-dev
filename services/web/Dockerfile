# ---- Stage 1: Install dependencies ----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts

# ---- Stage 2: Build ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_AUTH0_ENABLED
ARG NEXT_PUBLIC_AUTH0_DOMAIN
ARG NEXT_PUBLIC_AUTH0_CLIENT_ID
ARG NEXT_PUBLIC_AUTH0_AUDIENCE
ARG NEXT_PUBLIC_GA_MEASUREMENT_ID
# Shorts editor V2 panel rollout flag — defaults false at the compose level,
# flipped to "true" via .env on staging/prod EC2 hosts after the V2 panel
# (PR #92) and preset migration (PR #93) merge. NEXT_PUBLIC_* bakes at build
# time, so flipping the flag requires `docker compose build web` + restart.
ARG NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED

# Promote build ARGs to ENV so Next.js inlines them into the client bundle
# at build time. Without this, NEXT_PUBLIC_* vars stay undefined in
# `npm run build` and every feature gate that reads them falls back to its
# default.
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_AUTH0_ENABLED=$NEXT_PUBLIC_AUTH0_ENABLED \
    NEXT_PUBLIC_AUTH0_DOMAIN=$NEXT_PUBLIC_AUTH0_DOMAIN \
    NEXT_PUBLIC_AUTH0_CLIENT_ID=$NEXT_PUBLIC_AUTH0_CLIENT_ID \
    NEXT_PUBLIC_AUTH0_AUDIENCE=$NEXT_PUBLIC_AUTH0_AUDIENCE \
    NEXT_PUBLIC_GA_MEASUREMENT_ID=$NEXT_PUBLIC_GA_MEASUREMENT_ID \
    NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED=$NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Stage 3: Production runner ----
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# Next.js standalone output does not include the public/ folder by default;
# copy it explicitly so login logo, fonts, and figma assets resolve at runtime.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
