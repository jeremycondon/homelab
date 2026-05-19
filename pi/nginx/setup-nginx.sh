#!/bin/bash
set -euo pipefail

# Sets up nginx as a reverse proxy for Pi-hole and CUPS.
# Assumes Pi-hole DNS has already been configured with local DNS records:
#   cups.pinet.local   → this Pi's IP
#   pihole.pinet.local → this Pi's IP
# Run with: sudo bash setup-nginx.sh

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo bash setup-nginx.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing nginx"
apt-get install -y nginx

echo "==> Removing default site"
rm -f /etc/nginx/sites-enabled/default

echo "==> Installing site configs"
cp "$SCRIPT_DIR/cups.pinet.local"   /etc/nginx/sites-available/cups.pinet.local
cp "$SCRIPT_DIR/pihole.pinet.local" /etc/nginx/sites-available/pihole.pinet.local

ln -sf /etc/nginx/sites-available/cups.pinet.local   /etc/nginx/sites-enabled/cups.pinet.local
ln -sf /etc/nginx/sites-available/pihole.pinet.local /etc/nginx/sites-enabled/pihole.pinet.local

echo "==> Testing nginx config"
nginx -t

echo "==> Enabling and starting nginx"
systemctl enable nginx
systemctl restart nginx

echo ""
echo "=================================================="
echo "nginx reverse proxy configured."
echo ""
echo "Add these records in Pi-hole (Settings > Local DNS > DNS Records):"
PI_IP=$(hostname -I | awk '{print $1}')
echo "  cups.pinet.local   → ${PI_IP}"
echo "  pihole.pinet.local → ${PI_IP}"
echo ""
echo "Then access:"
echo "  http://cups.pinet.local"
echo "  http://pihole.pinet.local/admin"
echo "=================================================="
