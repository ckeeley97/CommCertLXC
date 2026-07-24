#!/usr/bin/env bash
# ============================================================================
# ONE-SHOT deploy. Run this on the Proxmox VE HOST and it does EVERYTHING:
#   1. downloads the Debian 12 template (if missing)
#   2. creates + starts an unprivileged LXC
#   3. installs git inside the container and clones your GitHub repo
#   4. provisions the app (Python venv, WeasyPrint, systemd service, nginx)
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
# or override any config inline:
#   CTID=211 GIT_REPO=https://github.com/you/ascom-commissioning-form.git ./deploy.sh
# ============================================================================
set -euo pipefail

# ============================= CONFIG =======================================
CTID="${CTID:-210}"                       # container ID (must be free)
HOSTNAME="${HOSTNAME:-ascom-form}"

# --- your GitHub repo (the one holding this project) ---
GIT_REPO="${GIT_REPO:-https://github.com/YOUR_USER/ascom-commissioning-form.git}"
GIT_BRANCH="${GIT_BRANCH:-main}"
# For a PRIVATE repo, use a tokenised URL, e.g.:
#   GIT_REPO=https://<TOKEN>@github.com/you/ascom-commissioning-form.git

# --- Proxmox placement / sizing ---
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
ROOTFS_STORAGE="${ROOTFS_STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
CORES="${CORES:-1}"
MEMORY="${MEMORY:-1024}"                   # MB
DISK="${DISK:-4}"                          # GB
IPCONFIG="${IPCONFIG:-ip=dhcp}"            # or ip=192.168.1.50/24,gw=192.168.1.1
ROOT_PASSWORD="${ROOT_PASSWORD:-changeme123}"
# Leave TEMPLATE empty to auto-pick the latest debian-12-standard image,
# or pin one, e.g. TEMPLATE=debian-12-standard_12.12-1_amd64.tar.zst
TEMPLATE="${TEMPLATE:-}"
# ============================================================================

SRC_DIR=/opt/ascom-form/src

if [[ "$GIT_REPO" == *YOUR_USER* ]]; then
  echo "!! Set GIT_REPO to your repository URL first (edit the CONFIG block)." >&2
  exit 1
fi

echo ">> [1/4] Ensuring a Debian 12 template is present…"
pveam update >/dev/null 2>&1 || true
if [[ -z "$TEMPLATE" ]]; then
  # Auto-pick the newest debian-12-standard image from the catalog.
  TEMPLATE=$(pveam available --section system \
             | awk '/debian-12-standard/ {print $2}' | sort -V | tail -n1)
fi
if [[ -z "$TEMPLATE" ]]; then
  echo "!! Could not find a debian-12-standard template. Run:" >&2
  echo "   pveam available --section system | grep debian-12-standard" >&2
  exit 1
fi
echo "   using template: $TEMPLATE"
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

echo ">> [2/4] Creating LXC $CTID ($HOSTNAME)…"
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" --memory "$MEMORY" --swap 256 \
  --rootfs "$ROOTFS_STORAGE:$DISK" \
  --net0 "name=eth0,bridge=$BRIDGE,$IPCONFIG,firewall=1" \
  --unprivileged 1 --features nesting=1 \
  --password "$ROOT_PASSWORD" --onboot 1

pct start "$CTID"
echo ">> waiting for network…"
sleep 6

echo ">> [3/4] Cloning repo inside the container…"
pct exec "$CTID" -- bash -e  <<EOF
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends git ca-certificates
rm -rf "$SRC_DIR"
mkdir -p "\$(dirname "$SRC_DIR")"
git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$SRC_DIR"
EOF

echo ">> [4/4] Provisioning app…"
pct exec "$CTID" -- bash "$SRC_DIR/proxmox/provision.sh" "$SRC_DIR/app"

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
echo
echo "============================================================"
echo " Ascom Commissioning form is live:  http://${IP}/"
echo " Container:   $CTID ($HOSTNAME)"
echo " Update later: pct exec $CTID -- bash -c 'cd $SRC_DIR && git pull && systemctl restart ascom-form'"
echo " Enter shell: pct enter $CTID"
echo "============================================================"
