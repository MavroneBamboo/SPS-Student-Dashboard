FROM postgres:17.11-alpine3.23

RUN apk upgrade --no-cache \
    && apk add --no-cache age bash \
    && rm -f /usr/local/bin/gosu

COPY deploy/database-maintenance.sh /usr/local/bin/database-maintenance
RUN chmod 0755 /usr/local/bin/database-maintenance

ENTRYPOINT ["/usr/local/bin/database-maintenance"]
