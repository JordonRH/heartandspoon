FROM postgres:16-alpine
RUN apk add --no-cache openssl tar
COPY backup.sh /usr/local/bin/hearth-backup
RUN chmod 755 /usr/local/bin/hearth-backup
ENTRYPOINT ["/usr/local/bin/hearth-backup"]
