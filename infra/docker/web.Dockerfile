FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies first (cache-friendly)
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts

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
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
