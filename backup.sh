#!/bin/bash
set -euo pipefail

DEST=/srv/backups/itam
FILE="$DEST/itam-$(date +%F_%H%M).dump"

# Dump a un archivo temporal; solo se renombra si terminó bien
docker exec itam-db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"

# Verifica que el dump sea legible
docker exec -i itam-db pg_restore --list < "$FILE" > /dev/null

# Borra respaldos de más de 14 días
find "$DEST" -name "itam-*.dump" -mtime +14 -delete

echo "Backup OK: $FILE ($(du -h "$FILE" | cut -f1))"
