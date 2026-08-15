#!/bin/bash
# Chrony setup for multisync (DESIGN.md §5)
#
#   master: runs chrony as an NTP server for the venue LAN
#   remote: syncs its clock to the master
#
# Run once per device during provisioning (DESIGN.md §10), after the
# hostname is set via raspi-config and before verifying sync status.
#
# Usage:
#   sudo bash chrony-setup.sh --role master [--subnet 192.168.1.0/24]
#   sudo bash chrony-setup.sh --role remote --master-host master-stage.local
#
# The master/remote address here is a provisioning-time input, not part
# of the sync.json config (DESIGN.md §3) — chrony needs it before any
# state packets exist to learn it from.

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash chrony-setup.sh ..."
    exit 1
fi

ROLE=""
SUBNET=""
MASTER_HOST=""

while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="$2"; shift 2 ;;
        --subnet) SUBNET="$2"; shift 2 ;;
        --master-host) MASTER_HOST="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [ "$ROLE" != "master" ] && [ "$ROLE" != "remote" ]; then
    echo "Usage:"
    echo "  sudo bash chrony-setup.sh --role master [--subnet 192.168.1.0/24]"
    echo "  sudo bash chrony-setup.sh --role remote --master-host <hostname-or-ip>"
    exit 1
fi

if [ "$ROLE" = "remote" ] && [ -z "$MASTER_HOST" ]; then
    echo "--master-host is required for --role remote"
    exit 1
fi

echo "Installing chrony..."
apt-get update -qq
apt-get install -y chrony

CONF_DIR="/etc/chrony/conf.d"
mkdir -p "$CONF_DIR"

# Debian/Raspberry Pi OS chrony.conf includes conf.d by default; make sure
# of it so a drop-in file here actually takes effect.
if ! grep -q "^confdir $CONF_DIR" /etc/chrony/chrony.conf 2>/dev/null; then
    echo "confdir $CONF_DIR" >> /etc/chrony/chrony.conf
fi

if [ "$ROLE" = "master" ]; then
    if [ -z "$SUBNET" ]; then
        # Derive the subnet from the primary wired interface's address.
        SUBNET=$(ip -o -4 addr show scope global | grep -v ' lo' | head -n1 | awk '{print $4}')
        if [ -z "$SUBNET" ]; then
            echo "Could not auto-detect LAN subnet; pass --subnet explicitly (e.g. 192.168.1.0/24)"
            exit 1
        fi
        echo "Auto-detected subnet: $SUBNET"
    fi

    cat > "$CONF_DIR/50-multisync.conf" << EOF
# multisync: serve LAN time even with no internet access (DESIGN.md §5)
local stratum 10
allow $SUBNET
EOF

    echo "Configured chrony as LAN NTP server, allowing $SUBNET"
else
    cat > "$CONF_DIR/50-multisync.conf" << EOF
# multisync: sync to the master only (DESIGN.md §5) — fast poll for
# quick convergence on a quiet wired LAN.
server $MASTER_HOST iburst minpoll 0 maxpoll 4
EOF

    echo "Configured chrony to sync against $MASTER_HOST"
fi

systemctl restart chrony
echo "chrony restarted"

echo ""
echo "Waiting 5s for initial sync..."
sleep 5
chronyc tracking

echo ""
echo "T1 pass criteria: offset < 1ms sustained (DESIGN.md §11). Re-check with:"
echo "  watch chronyc tracking"
