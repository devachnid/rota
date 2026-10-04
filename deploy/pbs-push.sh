#!/bin/sh
# Push the nightly database copy to the Proxmox Backup Server, run by
# rota-pbs.service as the rota user straight after rota-backup.service. It
# sends the finished copies in $state/backups, never the live WAL database.
# The repository address and certificate fingerprint (not secrets) arrive as PBS_*
# variables from /etc/pbs-backup/rota.env. The API token and the encryption
# key are systemd credentials, passed by file: a token in the environment
# would be readable from /proc by any other process running as rota, such as
# the web service. The copy is encrypted here: the server holds no plaintext.
set -eu
state="${STATE_DIRECTORY:-/var/lib/rota}"
creds="${CREDENTIALS_DIRECTORY:?run this under rota-pbs.service}"
export PBS_PASSWORD_FILE="$creds/pbs.token"
exec proxmox-backup-client backup "data.pxar:$state/backups" \
    --ns rota --backup-id rota \
    --keyfile "$creds/pbs.key"
