# ui-console/Dockerfile
#
# Build from the repo root:
#   docker build -f ui-console/Dockerfile \
#     --build-arg VITE_API_BASE_URL=https://api.example.com \
#     -t security-assistant-web ./ui-console
#
# VITE_API_BASE_URL is baked into the static JS at BUILD time (that's how
# Vite env vars work -- there's no "runtime config" for a static bundle),
# so it has to be supplied as a --build-arg, not a container env var. Get
# it wrong and you need to rebuild the image, not just restart it.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
