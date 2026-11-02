FROM node:22-alpine AS build

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./

ARG VITE_API_BASE_URL=http://localhost:5706
ARG VITE_OIDC_AUTHORITY=http://localhost:5707/realms/sahyog
ARG VITE_OIDC_CLIENT_ID=sahyog-web
ARG VITE_OIDC_REDIRECT_URI=http://localhost:5705/auth/callback
ARG VITE_OIDC_POST_LOGOUT_REDIRECT_URI=http://localhost:5705/
ARG VITE_APP_ENV=dev
ARG VITE_DEFAULT_LOCALE=en-IN
ARG VITE_SUPPORTED_LOCALES=en-IN,hi-IN,mr-IN

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_OIDC_AUTHORITY=$VITE_OIDC_AUTHORITY \
    VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID \
    VITE_OIDC_REDIRECT_URI=$VITE_OIDC_REDIRECT_URI \
    VITE_OIDC_POST_LOGOUT_REDIRECT_URI=$VITE_OIDC_POST_LOGOUT_REDIRECT_URI \
    VITE_APP_ENV=$VITE_APP_ENV \
    VITE_DEFAULT_LOCALE=$VITE_DEFAULT_LOCALE \
    VITE_SUPPORTED_LOCALES=$VITE_SUPPORTED_LOCALES

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

ARG AUTH_ORIGIN=http://localhost:5707

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/security-headers.conf /etc/nginx/security-headers.conf
RUN sed -i "s|__AUTH_ORIGIN__|${AUTH_ORIGIN}|g" \
    /etc/nginx/conf.d/default.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER 101
EXPOSE 8080
