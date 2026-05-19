# homelab

Home server configuration. Checked into git. Secrets encrypted with SOPS+age.

**Server** (Ubuntu): Portainer, Jellyfin, Grafana+Prometheus, Samba (files + Time Machine)
**Pi Zero 2 W**: Pi-hole, AirPrint — see `pi/`

## Services

All HTTP services are routed through Traefik (ports 80/443). HTTP redirects to HTTPS automatically.
TLS certs are issued by Let's Encrypt via Route53 DNS challenge — no port forwarding needed.

Add Route53 A records pointing each subdomain to the server's **internal** IP (they don't need to be
publicly reachable — only the DNS records need to exist):

| Service | URL | Notes |
|---------|-----|-------|
| Traefik | https://traefik.yourdomain.com | Dashboard |
| Portainer | https://portainer.yourdomain.com | Docker UI |
| Grafana | https://grafana.yourdomain.com | Metrics dashboards |
| Prometheus | https://prometheus.yourdomain.com | Metrics scraper |
| Jellyfin | http://jellyfin.yourdomain.com | Media (host network — DLNA) |
| Samba `files` | smb://server/files | Finder file share |
| Samba `timemachine` | smb://server/timemachine | Time Machine target |

## First-time setup (server)

### 1. Install Ubuntu, clone repo, bootstrap

```bash
git clone https://github.com/jeremycondon/homelab
cd homelab
sudo bash bootstrap.sh
```

Bootstrap will print your **age public key**. Add it to `.sops.yaml`:

```yaml
creation_rules:
  - path_regex: secrets/.*
    age: age1your-public-key-here
```

**Back up the private key** at `~/.config/sops/age/keys.txt` to 1Password. This is the only key
that decrypts your secrets. Without it you cannot restore.

### 2. Create secrets

```bash
cp secrets/grafana.env.example secrets/grafana.env
cp secrets/samba-config.yml.example secrets/samba-config.yml
# Edit both — change all passwords
nano secrets/grafana.env
nano secrets/samba-config.yml
make encrypt-secrets
# Commit the .enc files
```

> **TLS (Let's Encrypt via Route53):** not yet configured — using self-signed certs for now.
> Full instructions are in `services/traefik/traefik.yml`.

### 3. Start

```bash
make up
```

## Nuke and restore

1. Fresh Ubuntu install, clone repo
2. `sudo bash bootstrap.sh`
3. Restore private key from 1Password to `~/.config/sops/age/keys.txt`
4. `make decrypt-secrets && make up`

`decrypt-secrets` will restore `grafana.env` and `samba-config.yml` from their `.enc` files (and `traefik.env` once Let's Encrypt is configured).

Data lives in `/data/` — back this up separately (Jellyfin config, Grafana state, Samba files).
Media in `/data/media` is not backed up by default.

## Time Machine setup (Mac)

Samba's `fruit` VFS module handles Time Machine over SMB natively.

1. macOS **System Settings → General → Time Machine**
2. **Add Backup Disk → Network Volume**
3. Enter `smb://server-ip/timemachine`
4. Authenticate with the credentials from `samba-config.yml`

Limit is set to 500G in the Samba config — adjust `time machine max size` to ~1.5× your Mac's internal drive.

## Grafana dashboards

Prometheus and node_exporter are pre-wired. Import community dashboard **[1860](https://grafana.com/grafana/dashboards/1860)**
(Node Exporter Full) for system metrics out of the box.

## Useful commands

```bash
make ps                        # container status
make logs s=jellyfin           # follow service logs
make pull && make restart      # update all images
make edit-secrets f=secrets/grafana.env.enc   # edit encrypted file in-place
```

## Pi Zero 2 W

See [pi/README.md](pi/README.md).
