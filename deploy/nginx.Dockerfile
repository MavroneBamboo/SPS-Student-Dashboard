FROM nginx:1.30.7-alpine3.24

RUN apk upgrade --no-cache && apk add --no-cache gettext-envsubst

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx-production.conf.template /etc/nginx/production.conf.template
COPY --chmod=755 deploy/40-production-tls.sh /docker-entrypoint.d/40-production-tls.sh
COPY prototype/ /usr/share/nginx/html/prototype/

EXPOSE 80 443
