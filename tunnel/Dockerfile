FROM alpine:3.22
RUN apk add --no-cache openssh-client curl
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["sh", "/entrypoint.sh"]
