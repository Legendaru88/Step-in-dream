#!/bin/sh
set -eu
umask 077
mkdir -p /run/ssh
# Copy from the Windows bind mount; OpenSSH must see Linux mode 600.
cp /keys/recipient_ed25519 /run/ssh/id_ed25519
chmod 600 /run/ssh/id_ed25519
exec ssh -F /dev/null -N -D 0.0.0.0:1080 -i /run/ssh/id_ed25519 \
  -o UserKnownHostsFile=/config/known_hosts -o StrictHostKeyChecking=yes \
  -o HostKeyAlgorithms=ssh-ed25519 -o BatchMode=yes -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  tggoals-recipient@140.235.130.63
