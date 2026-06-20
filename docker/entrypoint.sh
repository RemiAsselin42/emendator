#!/bin/sh
# Copy the baked server into the mounted /data volume (which shadows the image's
# /data at runtime), then boot from there so logs, crash-reports and .mixin.out
# land where the runner reads them. Mods are already mounted at /data/mods.
set -e
cp -rn /opt/server/. /data/ 2>/dev/null || true
echo "eula=true" > /data/eula.txt
cd /data
exec java \
  -Dmixin.debug.export=true \
  -Dmixin.debug.verbose=true \
  -Dmixin.checks=true \
  -jar server.jar nogui
