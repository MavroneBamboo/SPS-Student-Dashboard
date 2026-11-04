FROM nginx:1.30.6-alpine3.24

RUN apk upgrade --no-cache

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY prototype/ /usr/share/nginx/html/prototype/

EXPOSE 80
