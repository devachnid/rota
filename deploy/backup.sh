#!/bin/sh
set -eu
mkdir -p /root/rota/backups
sqlite3 /root/rota/db.sqlite3 ".backup /root/rota/backups/db-$(date +%F).sqlite3"
find /root/rota/backups -name 'db-*.sqlite3' -mtime +30 -delete
