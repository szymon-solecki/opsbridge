FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM build AS browser-tests
RUN apk add --no-cache chromium
ENV CHROMIUM_PATH=/usr/bin/chromium-browser
CMD ["npm","test"]

FROM nginx:stable-alpine AS dashboard
ENV API_UPSTREAM=api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 30-monitoring-config.sh /docker-entrypoint.d/30-monitoring-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
