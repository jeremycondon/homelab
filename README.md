# homelab

Home server configuration. Checked into git. Secrets encrypted with SOPS+age.

**Server** (Ubuntu): Portainer, Plex, PhotoPrism, Home Assistant, Grafana+Prometheus+cAdvisor, Samba (tank + files + Time Machine), nightly NVMe→ZFS backup
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
| Pi-hole | https://pihole.yourdomain.com/admin/ | Proxied to nginx on the Pi (`services/traefik/dynamic/pi.yml`) |
| CUPS | https://cups.yourdomain.com | Proxied to nginx on the Pi (same file) |
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

## Disk health & alerts

`host/disk-health/` — systemd timer (every 5 min) that reads SMART from every disk (`smartctl -d sat` for the
USB enclosure) and parses `zpool status`, writing `disk_health.prom` for node_exporter's textfile collector:
temperature, reallocated/pending/CRC counters, NVMe wear, pool member state and error counters, permanent
data errors, last finished scrub, pool size/allocation and per-dataset (and snapshot) usage. Install / re-install:
`make install-disk-health`.
Each run also logs a one-line summary per disk: `journalctl -u disk-health`.

Long-term SMART history comes from `smartd` (package `smartmontools`), which logs every attribute every 30 min to
`/var/lib/smartmontools/attrlog.<model>-<serial>.ata.csv`. smartd only scans for disks at startup, so restart it
(`sudo systemctl restart smartmontools`) if the enclosure reconnects.

Alerts are Grafana-managed and provisioned from `services/grafana/provisioning/alerting/`: `rules.yml` (pool not
ONLINE, disk missing, data/I/O errors, SMART failures and rising counters, temperature, NVMe wear, scrub overdue,
stale metrics, NVMe backup failed), `contact-points.yml` and `policies.yml`. They push to [ntfy](https://ntfy.sh):
install the ntfy app and subscribe to the topic in `NTFY_URL` (`secrets/grafana.env`). Critical alerts are urgent
priority and repeat every 4 h; warnings repeat every 12 h. Edit the files and `make restart s=grafana`; rules
provisioned this way are read-only in the Grafana UI.

To check the phone side, send a test push with `scripts/test-alert.sh <critical|warning> [message]`.

These alerts run on this box, so they can't report the box itself being down.

## Time Machine setup (Mac)

Samba's `fruit` VFS module handles Time Machine over SMB natively.

1. macOS **System Settings → General → Time Machine**
2. **Add Backup Disk → Network Volume**
3. Enter `smb://server-ip/timemachine`
4. Authenticate with the credentials from `samba-config.yml`

Size is capped by the ZFS quota on `tank/backups/timemachine` (2T); macOS sees the quota as the disk size. Change it live with `sudo zfs set quota=<size> tank/backups/timemachine` — no Samba restart needed. (crazymax/samba ignores per-share `fruit:` options, so `time machine max size` can't be set in `samba-config.yml`.)

## Grafana dashboards

Provisioned from `services/grafana/dashboards/` into the **Homelab** folder (read-only in the UI):

| Dashboard | What | Data |
|---|---|---|
| Storage & backups | Pool/disk/SMART status tiles, scrubs, NVMe backup, capacity per dataset and snapshot, disk temps and I/O, ARC | disk-health + nvme-backup textfile metrics, node_exporter |
| Containers | Memory/CPU/network/disk per container, memory vs `mem_limit`, PSI memory pressure, OOM kills, uptime | cAdvisor |
| Traefik | Requests, 4xx/5xx, p95 latency, bandwidth per service; cert expiry | Traefik's metrics entrypoint (`:8082`, not published) |
| Pi-hole | Queries, blocked %, cache hits, upstream latency, top clients/domains, blocklist size | `pihole-exporter` (runs here, polls the Pi's FTL API on `:8080`) |
| PiAware | Aircraft count, max range, messages/s, signal/noise/gain, strong-signal %, dropped samples, dump1090 CPU | `piaware-exporter` (json-exporter, runs here, reads SkyAware's JSON from `piaware.local`) |
| Node Exporter Full | Everything about the host | [grafana.com #1860](https://grafana.com/grafana/dashboards/1860), downloaded as-is |
| Hot tub | Spa controller | ESP32 bridge |

Storage, Containers, Traefik, Pi-hole and PiAware are generated by `services/grafana/dashboards/gen.py`: edit it, run `python3 gen.py`, then
`make restart s=grafana`. Tile thresholds match `alerting/rules.yml`. Traefik's per-service counters only appear
after a service gets its first request. Plex and Home Assistant use host networking, so cAdvisor can't split
out their network traffic, and Traefik only sees them when they're reached by their https names.

## Useful commands

```bash
make ps                        # container status
make logs s=plex               # follow service logs
make update                    # after merging a Renovate PR: git pull, pull images, recreate
make edit-secrets f=secrets/grafana.env.enc   # edit encrypted file in-place
```

## Image updates & supply chain

Images in `docker-compose.yml` are pinned by digest (`image:tag@sha256:…`), so the server runs exactly
what CI scanned. `docker compose pull` will not move to newer builds on its own.

- **Renovate** (`renovate.json`) opens PRs every Monday: one grouped PR for digest bumps of rolling tags,
  separate PRs for version bumps. Majors for mariadb and uptime-kuma only appear on the Dependency Dashboard issue until you tick them (they need a migration plan).
- **Image Security Scan** runs Trivy on every PR touching the compose file, on pushes to main, and weekly.
  Fixable CRITICAL vulns fail the run; full CRITICAL/HIGH results go to the Security tab. Accept a CVE by
  adding it to `.trivyignore.yaml` with a `statement` (why) and an `expired_at` date. Entries stop
  suppressing once that date passes, so the CVE fails the scan again and gets re-reviewed — review it
  rather than pushing the date out by reflex. The same workflow verifies cosign signatures for the images
  whose publishers sign them (currently only Home Assistant).
- **Dependabot** (`.github/dependabot.yml`) bumps the SHA-pinned GitHub Actions weekly. It cannot bump
  Trivy itself: `trivy-action` defaults to whatever Trivy its own release shipped with, which lags, so the
  Trivy version is pinned in `image-scan.yml`. Bump it when a scan log prints a newer version is available.

After merging an image PR, run `make update` on the server.

## Pi Zero 2 W

See [pi/README.md](pi/README.md).

## PiAware (ADS-B feeder, second Pi Zero 2 W)

Not set up by this repo: flash FlightAware's PiAware image (or install the `piaware` package) and claim the
site on flightaware.com. For monitoring:

1. Give the Pi a DHCP reservation and a Pi-hole local DNS record for `piaware.local` (same as `hottub.local`).
   If you pick another name, change the three targets in the `piaware` job in `services/prometheus/prometheus.yml`.
2. Set the site location on your FlightAware stats page so `receiver.json` has lat/lon; the range panels need it.
3. Check `http://piaware.local/skyaware/data/stats.json` opens, then `make up` and `make restart s=prometheus`.

Metrics are read from `/skyaware/data/{stats,aircraft,receiver}.json`; the field mapping is in
`services/piaware-exporter/config.yml`. Aircraft metrics are one series per aircraft (`hex` label), which is
what lets the dashboard count them and compute range. That's a few hundred short-lived series a day, so it's fine.
