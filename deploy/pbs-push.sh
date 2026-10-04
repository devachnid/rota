#!/bin/sh
# Push the nightly database copy to the Proxmox Backup Server, run by
# rota-pbs.service as the rota user straight after rota-backup.service. It
# sends the finished copies in $state/backups, never the live WAL database.
# The repository, token and fingerprint arrive as PBS_* variables from
# /etc/pbs-backup/rota.env, which systemd reads as root; the encryption key
# arrives as a credential. So neither is ever readable by the rota user or
# by the web process. The copy is encrypted here: the server holds no
# plaintext.
set -eu
state="${STATE_DIRECTORY:-/var/lib/rota}"
exec proxmox-backup-client backup "data.pxar:$state/backups" \
    --ns rota --backup-id rota \
    --keyfile "${CREDENTIALS_DIRECTORY:?run this under rota-pbs.service}/pbs.key"
