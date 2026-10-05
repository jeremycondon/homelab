# homelab

Home server configuration. Checked into git. Secrets encrypted with SOPS+age.

**Server** (Ubuntu): Portainer, Plex, PhotoPrism, Home Assistant, Grafana+Prometheus, Samba (tank + files + Time Machine), nightly NVMe→ZFS backup
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
| Plex | https://plex.yourdomain.com (or http://server:32400/web) | Media (host network — GDM/DLNA); `/tank/media` read-only |
| PhotoPrism | https://photos.yourdomain.com | Photos in `/tank/photos` |
| Home Assistant | https://home.yourdomain.com (or http://server:8123) | Host network (discovery, HomeKit Bridge); config in `services/homeassistant/`, state in `/data/homeassistant` |
| Samba `tank` | smb://server/tank | Whole ZFS pool (`/tank`) |
| Samba `files` | smb://server/files | `/tank/documents` |
| Samba `documents` | smb://server/documents | `~/Documents` on the NVMe — **not** in the nightly backup |
| Samba `timemachine` | smb://server/timemachine | Time Machine target (`/tank/backups/timemachine`, 2T ZFS quota) |

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
cp secrets/photoprism.env.example secrets/photoprism.env
# Edit all three — change all passwords (photoprism: DATABASE_PASSWORD must equal MARIADB_PASSWORD)
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

`decrypt-secrets` will restore `grafana.env`, `samba-config.yml` and `photoprism.env` from their `.enc` files (and `traefik.env` once Let's Encrypt is configured).

App data lives on the NVMe in `/data/` (Plex config, PhotoPrism storage, Grafana state) plus Docker volumes,
and is backed up nightly to ZFS (see **Backups**). To restore it after a reinstall, before `make up`:

5. `sudo zpool import tank`, then copy back from the latest backup snapshot, e.g.
   `sudo rsync -aHX --numeric-ids /tank/backups/hosts/jeremy-n100/.zfs/snapshot/<nvme-…>/files/data/ /data/`
   (same for `files/var/lib/docker/volumes/`), and load PhotoPrism's DB from `db-dumps/photoprism_db.sql.gz`.
6. `make install-backup` to re-enable the nightly job.

Media, photos and documents live on the ZFS pool (`/tank/...`), not on the NVMe.

## Backups

`host/nvme-backup/` — nightly (03:30) systemd job that backs up the NVMe app data to the ZFS dataset
`tank/backups/hosts/jeremy-n100`:

- dumps running database containers (`photoprism_db`) to `db-dumps/`
- mirrors `/data`, Docker volumes, this repo and `/etc` into `files/` (rebuildable caches excluded)
- snapshots the dataset (`@nvme-YYYY-MM-DD_HHMM`) and prunes **only its own** snapshots
  (keeps the newest 30 + first of each month for 12 months)
- writes `nvme_backup.prom` for a node_exporter textfile-collector alert

Install / re-install (runs once, tests a restore, then enables the timer): `make install-backup`.
Run now: `sudo systemctl start nvme-backup`. Status: `systemctl list-timers nvme-backup.timer`, `journalctl -u nvme-backup`.

## Time Machine setup (Mac)

Samba's `fruit` VFS module handles Time Machine over SMB natively.

1. macOS **System Settings → General → Time Machine**
2. **Add Backup Disk → Network Volume**
3. Enter `smb://server-ip/timemachine`
4. Authenticate with the credentials from `samba-config.yml`

Size is capped by the ZFS quota on `tank/backups/timemachine` (2T); macOS sees the quota as the disk size. Change it live with `sudo zfs set quota=<size> tank/backups/timemachine` — no Samba restart needed. (crazymax/samba ignores per-share `fruit:` options, so `time machine max size` can't be set in `samba-config.yml`.)

## Grafana dashboards

Prometheus and node_exporter are pre-wired. Import community dashboard **[1860](https://grafana.com/grafana/dashboards/1860)**
(Node Exporter Full) for system metrics out of the box.

## Useful commands

```bash
make ps                        # container status
make logs s=plex               # follow service logs
make pull && make restart      # update all images
make edit-secrets f=secrets/grafana.env.enc   # edit encrypted file in-place
```

## Pi Zero 2 W

See [pi/README.md](pi/README.md).
