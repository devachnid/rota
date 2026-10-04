#!/bin/sh
# Nightly copy of the database, kept 30 days, run by rota-backup.service as
# the rota user. Each copy is complete — password hashes, and session keys
# that work as login cookies — so it is written readable by nobody else
# (umask 077) into the app's own state directory, which is closed too.
# systemd sets STATE_DIRECTORY from the unit's StateDirectory=.
set -eu
umask 077
state="${STATE_DIRECTORY:-/var/lib/rota}"
mkdir -p "$state/backups"
sqlite3 "$state/db.sqlite3" ".backup '$state/backups/db-$(date +%F).sqlite3'"
find "$state/backups" -name 'db-*.sqlite3' -mtime +30 -delete
