FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies first (cache-friendly)
COPY web/package.json web/package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com \
    && if [ -f package-lock.json ]; then npm ci --ignore-scripts; else npm install --ignore-scripts; fi

# Copy source and build
COPY web/ .
RUN npm run build

# --- Production image ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Copy standalone output (includes node_modules subset)
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
