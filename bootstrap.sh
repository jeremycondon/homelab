#!/bin/bash
set -euo pipefail

# Run with: sudo bash bootstrap.sh
# Ubuntu 22.04+

SOPS_VERSION="3.8.1"
AGE_VERSION="1.1.1"

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo bash bootstrap.sh"
  exit 1
fi

echo "==> Installing Docker"
apt-get update -q
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -q
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$SUDO_USER"
echo "Docker installed."

echo "==> Installing age v${AGE_VERSION}"
curl -fsSL "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz" \
  | tar -xz -C /usr/local/bin --strip-components=1 age/age age/age-keygen

echo "==> Installing SOPS v${SOPS_VERSION}"
curl -fsSL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
  -o /usr/local/bin/sops
chmod +x /usr/local/bin/sops

echo "==> Creating data directories under /data"
mkdir -p /data/{jellyfin/{config,cache},media,grafana,samba/{timemachine,files},prometheus}
chown -R "$SUDO_USER:$SUDO_USER" /data
echo "Data dirs created. Media goes in /data/media."

echo "==> Generating age keypair for $SUDO_USER"
AGE_KEY_DIR="/home/$SUDO_USER/.config/sops/age"
AGE_KEY_FILE="$AGE_KEY_DIR/keys.txt"
if [ ! -f "$AGE_KEY_FILE" ]; then
  mkdir -p "$AGE_KEY_DIR"
  age-keygen -o "$AGE_KEY_FILE"
  chown -R "$SUDO_USER:$SUDO_USER" "/home/$SUDO_USER/.config"
  echo ""
  echo "=================================================="
  echo "Your age PUBLIC KEY (paste into .sops.yaml):"
  echo ""
  age-keygen -y "$AGE_KEY_FILE"
  echo ""
  echo "BACK UP the private key to 1Password NOW:"
  echo "  $AGE_KEY_FILE"
  echo "=================================================="
else
  echo "age key already exists at $AGE_KEY_FILE — skipping."
  echo "Public key:"
  age-keygen -y "$AGE_KEY_FILE"
fi

echo ""
echo "==> Done."
echo ""
echo "Next steps:"
echo "  1. Add your age public key to .sops.yaml"
echo "  2. cp secrets/grafana.env.example secrets/grafana.env"
echo "  3. cp secrets/samba-config.yml.example secrets/samba-config.yml"
echo "  4. Edit both secret files with real values"
echo "  5. make encrypt-secrets"
echo "  6. make up"
