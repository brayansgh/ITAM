#!/bin/bash
set -euo pipefail
umask 077

DEST=/srv/backups/itam
mkdir -p -- "$DEST"
if [[ -L "$DEST" || ! -O "$DEST" || $(stat -c '%a' -- "$DEST") != 700 ]]; then
    echo "El directorio de respaldos debe pertenecer al usuario actual y tener permisos 0700." >&2
    exit 1
fi
FILE="$DEST/itam-$(date +%F_%H%M%S).dump"
TEMP=$(mktemp -- "$DEST/.itam-XXXXXXXX.tmp")
trap 'unlink -- "$TEMP"' EXIT

docker exec itam-db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$TEMP"
docker exec -i itam-db pg_restore --list < "$TEMP" > /dev/null
# Publicar de forma atómica sin sustituir otro respaldo con la misma marca de tiempo.
ln -T -- "$TEMP" "$FILE"

# Borra respaldos de más de 14 días
find "$DEST" -name "itam-*.dump" -mtime +14 -delete

echo "Backup OK: $FILE ($(du -h "$FILE" | cut -f1))"
