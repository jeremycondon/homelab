#!/bin/bash
set -euo pipefail

# Pi Zero 2 W — Raspberry Pi OS Lite (64-bit)
# Run with: sudo bash bootstrap-pi.sh
# Sets up Pi-hole and AirPrint (CUPS + avahi)

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo bash bootstrap-pi.sh"
  exit 1
fi

PI_USER="${SUDO_USER:-pi}"

echo "==> Updating system"
apt-get update -q && apt-get upgrade -y

# ── Fix port 53 conflict ───────────────────────────────────────────────────
# systemd-resolved's stub listener conflicts with Pi-hole on port 53

echo "==> Disabling systemd-resolved stub listener (conflicts with Pi-hole)"
mkdir -p /etc/systemd/resolved.conf.d
cat > /etc/systemd/resolved.conf.d/pihole.conf << 'EOF'
[Resolve]
DNSStubListener=no
DNS=8.8.8.8 8.8.4.4
EOF
systemctl restart systemd-resolved
# Point resolv.conf at the real resolver (not the stub)
ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
echo "Done."

# ── Pi-hole ────────────────────────────────────────────────────────────────

echo "==> Installing Pi-hole"

# Unattended install config — edit pihole/setupVars.conf before running
# or let the installer prompt you interactively.
PIHOLE_SETUP="$(dirname "$0")/pihole/setupVars.conf"

if [ -f "$PIHOLE_SETUP" ]; then
  echo "Found setupVars.conf — installing unattended"
  mkdir -p /etc/pihole
  cp "$PIHOLE_SETUP" /etc/pihole/setupVars.conf
  curl -sSL https://install.pi-hole.net | bash /dev/stdin --unattended
else
  echo "No setupVars.conf found — running interactive installer"
  echo "(See pi/pihole/setupVars.conf.example to automate this next time)"
  curl -sSL https://install.pi-hole.net | bash
fi

# ── CUPS + Avahi (AirPrint) ────────────────────────────────────────────────

echo "==> Installing CUPS and Avahi for AirPrint"
apt-get install -y cups avahi-daemon

echo "==> Configuring CUPS to allow LAN access"
# Allow the admin UI and printer management from the local network
cp /etc/cups/cupsd.conf /etc/cups/cupsd.conf.bak

# Listen on all interfaces (not just localhost)
sed -i 's/^Listen localhost:631/Listen 631/' /etc/cups/cupsd.conf

# Allow LAN access to the UI and admin
if ! grep -q "Allow @LOCAL" /etc/cups/cupsd.conf; then
  sed -i '/<Location \/>/{n;s/Order allow,deny/Order allow,deny\n  Allow @LOCAL/}' /etc/cups/cupsd.conf
  sed -i '/<Location \/admin>/{n;s/Order allow,deny/Order allow,deny\n  Allow @LOCAL/}' /etc/cups/cupsd.conf
fi

usermod -aG lpadmin "$PI_USER"

echo "==> Enabling printer sharing and AirPrint broadcasting"
cupsctl --share-printers BrowseLocalProtocols=dnssd

echo "==> Enabling CUPS and Avahi"
systemctl enable cups avahi-daemon
systemctl restart cups avahi-daemon

# ── Done ───────────────────────────────────────────────────────────────────

PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=================================================="
echo "Setup complete."
echo ""
echo "Pi-hole admin:  http://${PI_IP}/admin"
echo "CUPS admin:     http://${PI_IP}:631"
echo ""
echo "IMPORTANT — set a static DHCP lease for this Pi on your router."
echo "Pi-hole is your DNS server. If its IP changes, DNS breaks."
echo ""
echo "Router DNS setting: point to ${PI_IP}"
echo ""
echo "To add a printer (use CLI — the web UI rewrites cupsd.conf and breaks remote access):"
echo ""
echo "  1. Connect the printer via USB, then find its name:"
echo "       lpstat -p"
echo ""
echo "  2. If not listed, discover available USB/network devices:"
echo "       lpinfo -v"
echo ""
echo "  3. Add the printer (replace PRINTER_URI and NAME):"
echo "       sudo lpadmin -p NAME -E -v PRINTER_URI -m everywhere"
echo "     e.g. for USB:  sudo lpadmin -p MyPrinter -E -v usb://... -m everywhere"
echo ""
echo "  4. Enable sharing on the printer:"
echo "       sudo lpadmin -p NAME -o printer-is-shared=true"
echo "       sudo systemctl restart cups"
echo ""
echo "  5. Verify it's shared and broadcasting:"
echo "       lpstat -p NAME -l | grep -i shared"
echo "       dns-sd -B _ipp._tcp local   # should appear within a few seconds"
echo ""
echo "  Avahi will broadcast it as AirPrint automatically once shared."
echo "=================================================="
