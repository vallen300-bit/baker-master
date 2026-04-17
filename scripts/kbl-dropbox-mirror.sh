#!/bin/bash
# kbl-dropbox-mirror.sh — daily 23:50 Europe/Vienna log mirror.
# rsyncs /var/log/kbl/ into ~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/<date>/.
# Gives the Director an always-present copy even if Mac Mini is offline.

set -euo pipefail

SRC="/var/log/kbl/"
DEST="${HOME}/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/$(date +%Y-%m-%d)/"
mkdir -p "${DEST}"
rsync -a --include='*.log' --include='*.log.*' --exclude='*' "${SRC}" "${DEST}"
