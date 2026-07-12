#!/bin/sh
# Nightly pg_dump. This holds every payment, every ledger entry, and every ISP's payout
# account — if it is lost, we cannot tell an ISP what they earned, and no apology fixes
# that.
#
# A BACKUP YOU HAVE NEVER RESTORED IS NOT A BACKUP. Do the restore drill in
# docs/DEPLOYMENT.md before you take real money, and again whenever the schema changes
# shape. Backups fail silently far more often than they fail loudly.
set -eu

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
DIR=/backups

while true; do
	STAMP=$(date -u +%Y%m%d-%H%M%S)
	FILE="$DIR/wifios-$STAMP.sql.gz"

	echo "[backup] dumping to $FILE"
	if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
		-h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
		--no-owner --no-privileges | gzip >"$FILE.tmp"; then
		# Only rename once the dump SUCCEEDED. A half-written file with the right
		# name is worse than no file: it looks like a backup right up until the
		# moment you need it.
		mv "$FILE.tmp" "$FILE"
		echo "[backup] ok — $(du -h "$FILE" | cut -f1)"
	else
		echo "[backup] FAILED — dump did not complete" >&2
		rm -f "$FILE.tmp"
	fi

	# Prune. Local copies are for a fast restore, not for retention — the OFFSITE copy
	# is what survives the box being destroyed, so make sure something is syncing this
	# directory somewhere else (see docs/DEPLOYMENT.md).
	find "$DIR" -name 'wifios-*.sql.gz' -mtime "+$KEEP_DAYS" -delete

	sleep 86400
done
