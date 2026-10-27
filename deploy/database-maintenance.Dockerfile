FROM postgres:17.2-alpine

RUN apk add --no-cache age bash

COPY deploy/database-maintenance.sh /usr/local/bin/database-maintenance
RUN chmod 0755 /usr/local/bin/database-maintenance

ENTRYPOINT ["/usr/local/bin/database-maintenance"]
