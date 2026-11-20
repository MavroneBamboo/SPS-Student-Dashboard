FROM --platform=$BUILDPLATFORM golang:1.26.11-alpine AS gosu-build

ARG TARGETOS
ARG TARGETARCH
ARG GOSU_COMMIT=29b939aa5bd4dc588af765b8248f6e39150d2565

RUN apk add --no-cache git
WORKDIR /src/gosu
RUN git init . \
    && git remote add origin https://github.com/tianon/gosu.git \
    && git fetch --depth 1 origin "$GOSU_COMMIT" \
    && git checkout --detach FETCH_HEAD
RUN CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" \
    go build -trimpath -buildvcs=false -ldflags="-s -w" -o /out/gosu .

FROM percona/percona-distribution-postgresql:17.11.1-4-ubi10
COPY --from=gosu-build --chmod=0755 /out/gosu /usr/sbin/gosu
