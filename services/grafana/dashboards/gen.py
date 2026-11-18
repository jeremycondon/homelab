#!/usr/bin/env python3
"""Generates storage.json, containers.json, traefik.json, pihole.json and piaware.json in this folder.

Edit here, run `python3 services/grafana/dashboards/gen.py`, then `make restart s=grafana`.
(Provisioned dashboards are read-only in the UI: allowUiUpdates is false.)
hottub.json and node-exporter-full.json (grafana.com #1860) are not generated.
Thresholds mirror provisioning/alerting/rules.yml so a red tile means an alert is firing or about to.
"""
import json
import os

DS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}
HERE = os.path.dirname(os.path.abspath(__file__))
GREEN, YELLOW, RED, BLUE = "green", "#EAB839", "red", "blue"


def steps(*pairs):
    """steps(GREEN, (30, YELLOW), (40, RED)) -> threshold steps."""
    out = [{"color": pairs[0], "value": None}]
    out += [{"color": c, "value": v} for v, c in pairs[1:]]
    return {"mode": "absolute", "steps": out}


def target(expr, legend="", ref="A", instant=False, fmt=None):
    t = {"refId": ref, "datasource": DS, "expr": expr, "legendFormat": legend or "__auto"}
    if instant:
        t.update(instant=True, range=False)
    if fmt:
        t["format"] = fmt
    return t


class Board:
    def __init__(self, uid, title, tags, refresh="1m", time_from="now-24h", description=""):
        self.d = {
            "uid": uid, "title": title, "tags": ["homelab"] + tags, "description": description,
            "editable": False, "schemaVersion": 39, "refresh": refresh, "timezone": "browser",
            "time": {"from": time_from, "to": "now"}, "graphTooltip": 1,
            "annotations": {"list": []}, "templating": {"list": []}, "panels": [],
            "links": [{"title": "Homelab", "type": "dashboards", "tags": ["homelab"], "asDropdown": True}],
        }
        self.x = self.y = self.row_h = 0
        self.next_id = 1

    def row(self, title):
        self.newline()
        self._add({"type": "row", "title": title, "collapsed": False, "panels": []}, 24, 1)
        self.newline()

    def newline(self):
        if self.x:
            self.y += self.row_h
        self.x = self.row_h = 0

    def _add(self, p, w, h):
        if self.x + w > 24:
            self.newline()
        p["id"] = self.next_id
        self.next_id += 1
        p["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        if self.x >= 24:
            self.newline()
        self.d["panels"].append(p)
        return p

    def panel(self, kind, title, targets, w, h, desc="", unit=None, th=None, mappings=None,
              decimals=None, min_=None, max_=None, options=None, custom=None, overrides=None,
              transformations=None, color=None, links=None):
        defaults = {}
        if unit:
            defaults["unit"] = unit
        if th:
            defaults["thresholds"] = th
        if mappings:
            defaults["mappings"] = mappings
        if decimals is not None:
            defaults["decimals"] = decimals
        if min_ is not None:
            defaults["min"] = min_
        if max_ is not None:
            defaults["max"] = max_
        if custom:
            defaults["custom"] = custom
        defaults["color"] = color or ({"mode": "thresholds"} if th else {"mode": "palette-classic"})
        p = {"type": kind, "title": title, "description": desc, "datasource": DS,
             "targets": targets if isinstance(targets, list) else [targets],
             "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
             "options": options or {}}
        if transformations:
            p["transformations"] = transformations
        if links:
            p["links"] = links
        return self._add(p, w, h)

    def stat(self, title, expr, w=4, h=4, legend="", text_mode="value", graph=False, **kw):
        opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "colorMode": "background", "graphMode": "area" if graph else "none",
                "textMode": text_mode, "justifyMode": "center", "orientation": "auto", "wideLayout": True}
        return self.panel("stat", title, target(expr, legend, instant=not graph), w, h, options=opts, **kw)

    def ts(self, title, targets, w=12, h=8, stack=False, fill=10, unit=None, legend_calcs=("mean", "max"),
           draw="line", **kw):
        custom = {"drawStyle": draw, "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
                  "spanNulls": False, "axisSoftMin": 0,
                  "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
        custom.update(kw.pop("custom", {}))
        opts = {"legend": {"displayMode": "table", "placement": "right" if w >= 12 else "bottom",
                           "calcs": list(legend_calcs), "sortBy": legend_calcs[-1].capitalize() if legend_calcs else None,
                           "sortDesc": True},
                "tooltip": {"mode": "multi", "sort": "desc"}}
        return self.panel("timeseries", title, targets, w, h, unit=unit, custom=custom, options=opts, **kw)

    def bars(self, title, expr, w=8, h=8, legend="", unit=None, **kw):
        opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                "valueMode": "color", "namePlacement": "left", "sizing": "auto"}
        return self.panel("bargauge", title, target(expr, legend, instant=True), w, h, unit=unit,
                          options=opts, **kw)

    def gauge(self, title, expr, w=4, h=6, **kw):
        opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "showThresholdLabels": False, "showThresholdMarkers": True}
        return self.panel("gauge", title, target(expr, instant=True), w, h, options=opts, **kw)

    def table(self, title, queries, columns, w=24, h=7, overrides=None, key="serial", sort=None, **kw):
        """queries: [(ref, expr)] instant table queries all keyed by `key`; columns: {field: display name}."""
        targets = [target(e, ref=r, instant=True, fmt="table") for r, e in queries]
        drop = {f"Time {i}": True for i in range(1, len(queries) + 1)}
        drop["Time"] = True
        tr = [{"id": "joinByField", "options": {"byField": key, "mode": "outer"}},
              {"id": "organize", "options": {"excludeByName": drop,
                                             "indexByName": {k: i for i, k in enumerate(columns)},
                                             "renameByName": columns}}]
        # keep only the listed columns (drops stray label columns such as job/instance)
        tr.append({"id": "filterFieldsByName", "options": {"include": {"names": list(columns.values())}}})
        opts = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
        if sort:
            opts["sortBy"] = [{"displayName": sort, "desc": False}]
        return self.panel("table", title, targets, w, h, transformations=tr, options=opts,
                          overrides=overrides, custom={"align": "auto", "cellOptions": {"type": "auto"}}, **kw)

    def text(self, content, w=24, h=3):
        p = {"type": "text", "title": "", "options": {"mode": "markdown", "content": content},
             "transparent": True}
        return self._add(p, w, h)

    def save(self, name):
        with open(os.path.join(HERE, name), "w") as f:
            json.dump(self.d, f, indent=2)
            f.write("\n")
        return self.d


def ok_bad(ok_text="OK", bad_text="FAIL", ok_val=1):
    """Value mapping for 0/1 metrics."""
    bad_val = 1 - ok_val
    return [{"type": "value", "options": {str(ok_val): {"text": ok_text, "color": GREEN, "index": 0},
                                          str(bad_val): {"text": bad_text, "color": RED, "index": 1}}}]


def override(name, props, by="byName"):
    return {"matcher": {"id": by, "options": name}, "properties": [{"id": k, "value": v} for k, v in props.items()]}


def cell_color(name, th, mode="color-background", unit=None, mappings=None):
    props = {"thresholds": th, "custom.cellOptions": {"type": mode}}
    if unit:
        props["unit"] = unit
    if mappings:
        props["mappings"] = mappings
    return override(name, props)


# ─────────────────────────────────────────────────────────────── Storage & backups
def storage():
    b = Board("storage", "Storage & backups", ["zfs", "smart", "backup"], refresh="5m", time_from="now-7d",
              description="tank pool, SMART, scrubs and the NVMe backup. Data: host/disk-health and host/nvme-backup "
                          "(textfile collector, every 5 min) + node_exporter's zfs collector.")
    b.row("Health")
    b.stat("Pool tank", 'node_zfs_zpool_state{zpool="tank",state="online"}', w=3,
           th=steps(RED, (1, GREEN)), mappings=ok_bad("ONLINE", "NOT ONLINE"),
           desc="From the kernel. Alert: ZFS pool not ONLINE.")
    b.stat("Disks online", 'sum(zpool_vdev_online{pool="tank"})', w=3, th=steps(RED, (3, GREEN)),
           desc="Pool members ONLINE (of 3). Alert: ZFS pool disk not ONLINE / Pool disks missing.")
    b.stat("Disk I/O errors", 'sum(zpool_vdev_errors{pool="tank"})', w=3, th=steps(GREEN, (1, RED)),
           desc="Read+write+checksum errors across pool members since last zpool clear.")
    b.stat("Data errors", 'zpool_data_errors{pool="tank"}', w=3, th=steps(GREEN, (1, RED)),
           desc="Files with permanent errors. `zpool status -v tank` lists them.")
    b.stat("SMART", 'min(smart_health_passed)', w=3, th=steps(RED, (1, GREEN)),
           mappings=ok_bad("ALL PASSED", "FAILED"), desc="Every drive's overall self-assessment.")
    b.stat("Days since scrub",
           '(time() - zpool_last_scrub_end_timestamp_seconds{pool="tank"}) / 86400', w=3, unit="d", decimals=1,
           th=steps(GREEN, (30, YELLOW), (40, RED)), desc="Alert at 40 days (not while a scrub is running).")
    b.stat("Scrub", 'zpool_scrub_in_progress{pool="tank"}', w=3, th=steps("text", (1, BLUE)),
           mappings=[{"type": "value", "options": {"0": {"text": "idle", "index": 0},
                                                   "1": {"text": "RUNNING", "index": 1}}}])
    b.stat("Last scrub errors", 'zpool_last_scrub_errors{pool="tank"}', w=3, th=steps(GREEN, (1, RED)))

    b.stat("NVMe backup", 'nvme_backup_last_success', w=4, th=steps(RED, (1, GREEN)),
           mappings=ok_bad("OK", "FAILED"), desc="Result of the last nightly run (host/nvme-backup).")
    b.stat("Last good backup", '(time() - nvme_backup_last_success_timestamp_seconds) / 3600', w=4, unit="h",
           decimals=1, th=steps(GREEN, (26, YELLOW), (30, RED)), desc="Alert at 30 h.")
    b.stat("Health job ran", 'time() - disk_health_last_run_timestamp_seconds', w=4, unit="s",
           th=steps(GREEN, (900, YELLOW), (1800, RED)),
           desc="disk-health.timer runs every 5 min. Alert at 30 min (metrics stale).")
    b.stat("Hottest HDD", 'max(smart_temperature_celsius{kind="hdd"})', w=4, unit="celsius",
           th=steps(GREEN, (45, YELLOW), (50, RED)), desc="Alert above 50 °C.")
    b.stat("NVMe temp", 'max(smart_temperature_celsius{kind="nvme"})', w=4, unit="celsius",
           th=steps(GREEN, (60, YELLOW), (70, RED)), desc="Alert above 70 °C.")
    b.stat("NVMe wear", 'max(smart_nvme_percentage_used)', w=4, unit="percent",
           th=steps(GREEN, (50, YELLOW), (80, RED)), desc="Endurance used. Alert above 80%.")

    b.row("Capacity")
    b.gauge("Pool used", '100 * zpool_allocated_bytes{pool="tank"} / zpool_size_bytes{pool="tank"}', w=5, h=7,
            unit="percent", min_=0, max_=100, th=steps(GREEN, (80, YELLOW), (90, RED)),
            desc="Raw allocation incl. parity (zpool list CAP). ZFS slows down past ~80%.")
    b.stat("Usable free", 'zfs_dataset_available_bytes{dataset="tank"}', w=4, h=7, unit="bytes",
           th=steps("text"), desc="What you can still write, after parity (zfs list AVAIL).")
    b.bars("Used by dataset", 'sort_desc(zfs_dataset_used_by_dataset_bytes{dataset="tank"} or '
                              'zfs_dataset_used_bytes{dataset!="tank"})', w=8, h=7, legend="{{dataset}}",
           unit="bytes", th=steps(BLUE), color={"mode": "continuous-BlPu"},
           desc="Top-level datasets incl. their children and snapshots. 'tank' = files stored directly in the "
                "root dataset.")
    b.bars("Held only by snapshots", 'sort_desc(zfs_dataset_used_by_snapshots_bytes > 0)', w=7, h=7,
           legend="{{dataset}}", unit="bytes", th=steps(YELLOW), color={"mode": "fixed", "fixedColor": YELLOW},
           desc="Freed if that dataset's snapshots are destroyed (`zfs list -t snapshot -o name,used -s used`).")
    b.ts("Pool allocation", [target('zpool_allocated_bytes{pool="tank"}', "allocated"),
                             target('zpool_size_bytes{pool="tank"}', "size")],
         w=12, h=7, unit="bytes", fill=0, legend_calcs=("lastNotNull",),
         overrides=[override("size", {"custom.lineStyle": {"fill": "dash", "dash": [10, 10]},
                                      "color": {"mode": "fixed", "fixedColor": RED}})])
    b.ts("Dataset growth", target('zfs_dataset_used_bytes{dataset!="tank"}', "{{dataset}}"), w=12, h=7,
         unit="bytes", fill=0, legend_calcs=("lastNotNull",))

    b.row("Disks")
    hdd = '{kind="hdd"}'
    attr = lambda i: f'max by (serial) (smart_attribute_raw{{id="{i}"}})'
    b.table("Drives", [
        ("A", "max by (serial, model, device) (smart_device_info)"),
        ("B", "max by (serial) (smart_health_passed)"),
        ("C", "max by (serial) (smart_temperature_celsius)"),
        ("D", "max by (serial) (smart_power_on_hours)"),
        ("E", attr(5)), ("F", attr(197)), ("G", attr(198)), ("H", attr(199)),
        ("I", "max by (serial) (sum by (serial, type) (zpool_vdev_errors))"),
    ], {"device": "Device", "model": "Model", "serial": "Serial", "Value #B": "SMART",
        "Value #C": "Temp", "Value #D": "Power-on", "Value #E": "Reallocated",
        "Value #F": "Pending", "Value #G": "Uncorrectable", "Value #H": "CRC errors", "Value #I": "ZFS errors"},
        h=6, sort="Device", overrides=[
            cell_color("SMART", steps(RED, (1, GREEN)), mappings=ok_bad("PASSED", "FAILED")),
            cell_color("Temp", steps(GREEN, (45, YELLOW), (50, RED)), mode="color-text", unit="celsius"),
            override("Power-on", {"unit": "h", "decimals": 0}),
            cell_color("Reallocated", steps(GREEN, (1, YELLOW), (1000, RED))),
            cell_color("Pending", steps(GREEN, (1, RED))),
            cell_color("Uncorrectable", steps(GREEN, (1, RED))),
            cell_color("CRC errors", steps(GREEN, (1, YELLOW))),
            cell_color("ZFS errors", steps(GREEN, (1, RED))),
        ], desc="Reallocated sectors already remapped (yellow = watch it, alert fires if it grows). Pending/"
                "uncorrectable = sectors that can't be read now. CRC = cable/enclosure, not the disk. "
                "ZFS errors = worst of read/write/checksum for that member.")
    b.ts("Drive temperature", target("smart_temperature_celsius", "{{serial}} ({{kind}})"), w=12, h=8,
         unit="celsius", fill=0, legend_calcs=("lastNotNull", "max"),
         custom={"axisSoftMin": 25, "thresholdsStyle": {"mode": "dashed"}},
         th=steps("transparent", (50, RED)))
    b.ts("Reallocated sectors", target(attr(5), "{{serial}}"),
         w=12, h=8, fill=0, legend_calcs=("min", "lastNotNull"),
         desc="Flat is fine. A rising line means the disk is actively failing sectors.")
    io = lambda m: f'sum by (device) (rate(node_disk_{m}_bytes_total{{device=~"sd[a-z]+"}}[$__rate_interval]))'
    b.ts("Pool disk throughput", [target(io("read"), "{{device}} read"),
                                  target(f"-{io('written')}", "{{device}} write")],
         w=12, h=8, unit="Bps", fill=5, legend_calcs=("mean", "max"),
         desc="Reads up, writes down. sd* = the three pool disks.")
    b.ts("Pool disk busy", target('rate(node_disk_io_time_seconds_total{device=~"sd[a-z]+"}[$__rate_interval])',
                                  "{{device}}"), w=12, h=8, unit="percentunit", fill=0, max_=1,
         desc="Fraction of time the disk had I/O in flight. Pegged at 100% = the disk is the bottleneck "
              "(scrubs, Plex scans, PhotoPrism indexing).")

    b.row("ZFS ARC (read cache in RAM)")
    b.ts("ARC size", [target("node_zfs_arc_size", "ARC"), target("node_zfs_arc_c_max", "max"),
                      target("node_memory_MemAvailable_bytes", "host RAM available")],
         w=12, h=8, unit="bytes", fill=0, legend_calcs=("lastNotNull", "max"),
         desc="ARC gives memory back under pressure, but on a 3.3 GB box it competes with the containers.")
    b.ts("ARC hit rate",
         target("rate(node_zfs_arc_hits[$__rate_interval]) / "
                "(rate(node_zfs_arc_hits[$__rate_interval]) + rate(node_zfs_arc_misses[$__rate_interval]))",
                "hit rate"), w=12, h=8, unit="percentunit", fill=10, min_=0, max_=1,
         legend_calcs=("mean", "min"))
    return b.save("storage.json")


# ─────────────────────────────────────────────────────────────── Containers
def containers():
    b = Board("containers", "Containers", ["docker", "cadvisor"], refresh="30s", time_from="now-6h",
              description="Per-container resources from cAdvisor. Plex and Home Assistant use host networking, "
                          "so their network traffic is only in the host totals.")
    sel = '{name!=""}'
    cpu = f'sum by (name) (rate(container_cpu_usage_seconds_total{sel}[$__rate_interval]))'
    mem = f'max by (name) (container_memory_working_set_bytes{sel})'
    b.row("Host")
    b.stat("Containers", f"count(container_start_time_seconds{sel})", w=4, th=steps("text"))
    b.stat("RAM available", "node_memory_MemAvailable_bytes", w=5, unit="bytes", graph=True,
           th=steps(RED, (300 * 2**20, YELLOW), (600 * 2**20, GREEN)),
           desc="What the kernel can hand out without swapping (includes reclaimable cache, not ARC).")
    b.stat("Swap used", "node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", w=5, unit="bytes", graph=True,
           th=steps(GREEN, (512 * 2**20, YELLOW), (1536 * 2**20, RED)))
    b.stat("Memory pressure", "rate(node_pressure_memory_waiting_seconds_total[$__rate_interval])", w=5,
           unit="percentunit", graph=True, th=steps(GREEN, (0.05, YELLOW), (0.2, RED)),
           desc="Share of time some task was stalled waiting for memory (PSI). Sustained > 5% = the box is "
                "short on RAM.")
    b.stat("OOM kills (range)", f"sum(increase(container_oom_events_total{sel}[$__range])) or vector(0)", w=5,
           th=steps(GREEN, (1, RED)), desc="Out-of-memory kills inside containers over the selected time range.")

    b.row("Memory")
    b.ts("Memory by container", target(mem, "{{name}}"), w=16, h=10, stack=True, fill=40, unit="bytes",
         legend_calcs=("lastNotNull", "max"),
         desc="Working set: what the kernel counts toward the limit and the OOM killer. Stacked.")
    b.bars("Memory vs limit", f'sort_desc({mem} / on (name) (max by (name) '
                              f'(container_spec_memory_limit_bytes{sel}) > 0))',
           w=8, h=10, legend="{{name}}", unit="percentunit", min_=0, max_=1,
           th=steps(GREEN, (0.8, YELLOW), (0.95, RED)),
           desc="Only containers with a mem_limit in docker-compose.yml.")
    b.row("CPU")
    b.ts("CPU by container", target(cpu, "{{name}}"), w=16, h=9, stack=True, fill=40, unit="percentunit",
         legend_calcs=("mean", "max"), desc="1.0 = one full core; the N100 has 4.")
    b.bars("CPU now", f"sort_desc({cpu})", w=8, h=9, legend="{{name}}", unit="percentunit",
           th=steps(GREEN, (1, YELLOW), (3, RED)), min_=0, max_=4)
    b.row("I/O")
    net = lambda d: f'sum by (name) (rate(container_network_{d}_bytes_total{sel}[$__rate_interval]))'
    b.ts("Network (bridge containers)", [target(net("receive"), "{{name}} in"),
                                         target(f"-{net('transmit')}", "{{name}} out")],
         w=12, h=9, unit="Bps", fill=5, legend_calcs=("mean", "max"))
    disk = lambda d: (f'sum by (name) (rate(container_blkio_device_usage_total{{name!="",operation="{d}"}}'
                      f'[$__rate_interval]))')
    b.ts("Disk I/O", [target(disk("Read"), "{{name}} read"), target(f"-{disk('Write')}", "{{name}} write")],
         w=12, h=9, unit="Bps", fill=5, legend_calcs=("mean", "max"))
    b.row("Uptime")
    b.table("Container uptime", [
        ("A", f"max by (name) (time() - container_start_time_seconds{sel})"),
        ("B", mem),
        ("C", cpu.replace("$__rate_interval", "5m")),
    ], {"name": "Container", "Value #A": "Up for", "Value #B": "Memory", "Value #C": "CPU (5m)"},
        key="name", h=10, sort="Up for", overrides=[
            cell_color("Up for", steps(YELLOW, (3600, "text")), mode="color-text", unit="s"),
            override("Memory", {"unit": "bytes"}),
            override("CPU (5m)", {"unit": "percentunit", "decimals": 2}),
        ], desc="Short uptime on a container you didn't restart = it crashed (yellow under 1 h).")
    return b.save("containers.json")


# ─────────────────────────────────────────────────────────────── Traefik
def traefik():
    b = Board("traefik", "Traefik", ["traefik", "http"], refresh="30s", time_from="now-6h",
              description="Requests through the reverse proxy, per service. Plex and Home Assistant only show "
                          "up here when reached via their https://*.domain names, not direct IP:port.")
    req = "traefik_service_requests_total"
    rate = lambda f="": f"sum by (service) (rate({req}{f}[$__rate_interval]))"
    b.row("Overview")
    b.stat("Requests/s", f"sum(rate({req}[$__rate_interval]))", w=4, unit="reqps", graph=True, th=steps("text"))
    b.stat("5xx rate", f'sum(rate({req}{{code=~"5.."}}[$__rate_interval])) / sum(rate({req}[$__rate_interval]))',
           w=4, unit="percentunit", graph=True, th=steps(GREEN, (0.01, YELLOW), (0.05, RED)),
           desc="Share of responses that were server errors. Includes 502/504 from a backend that is down.")
    b.stat("p95 latency", "histogram_quantile(0.95, sum by (le) "
                          "(rate(traefik_service_request_duration_seconds_bucket[$__rate_interval])))",
           w=4, unit="s", graph=True, th=steps(GREEN, (1, YELLOW), (3, RED)))
    b.stat("Open connections", "sum(traefik_open_connections)", w=4, graph=True, th=steps("text"))
    b.stat("Cert expires in", "min((traefik_tls_certs_not_after - time()) / 86400)", w=4, unit="d", decimals=0,
           th=steps(RED, (14, YELLOW), (30, GREEN)),
           desc="Soonest-expiring certificate Traefik serves. It renews at 30 days left, so yellow = renewal "
                "is failing (check Route53 creds / `docker logs traefik`).")
    b.stat("Config reloads", "sum(increase(traefik_config_reloads_total[$__range]))", w=4, th=steps("text"),
           desc="Over the selected range. Each container start/stop triggers one.")
    b.row("Per service")
    b.ts("Requests/s by service", target(rate(), "{{service}}"), w=12, h=9, unit="reqps", stack=True, fill=30)
    b.ts("Errors by service (4xx + 5xx)", [target(rate('{code=~"5.."}'), "{{service}} 5xx"),
                                           target(rate('{code=~"4.."}'), "{{service}} 4xx")],
         w=12, h=9, unit="reqps", fill=10,
         overrides=[{"matcher": {"id": "byRegexp", "options": ".*5xx"},
                     "properties": [{"id": "custom.lineWidth", "value": 2}]}],
         desc="4xx are often harmless (scanners, expired sessions, Plex's 401 polling). 5xx mean the backend "
              "failed or was down.")
    b.ts("p95 latency by service", target("histogram_quantile(0.95, sum by (le, service) "
                                          "(rate(traefik_service_request_duration_seconds_bucket[$__rate_interval])))",
                                          "{{service}}"), w=12, h=9, unit="s", fill=0)
    b.ts("Responses by status code", target(f"sum by (code) (rate({req}[$__rate_interval]))", "{{code}}"),
         w=12, h=9, unit="reqps", stack=True, fill=40,
         overrides=[{"matcher": {"id": "byRegexp", "options": "5.."},
                     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": RED}}]},
                    {"matcher": {"id": "byRegexp", "options": "4.."},
                     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": YELLOW}}]}])
    b.ts("Bandwidth by service", target("sum by (service) (rate(traefik_service_responses_bytes_total"
                                        "[$__rate_interval]))", "{{service}}"), w=12, h=9, unit="Bps", fill=10)
    b.ts("Open connections by entrypoint", target("sum by (entrypoint) (traefik_open_connections)",
                                                  "{{entrypoint}}"), w=12, h=9, fill=10,
         legend_calcs=("lastNotNull", "max"))
    return b.save("traefik.json")


# ─────────────────────────────────────────────────────────────── Pi-hole
def pihole():
    b = Board("pihole", "Pi-hole", ["pihole", "dns"], refresh="1m", time_from="now-24h",
              description="Pi-hole on the Pi Zero (192.168.68.82) via pihole-exporter. '…today' counters are "
                          "Pi-hole's rolling 24 h window, not since midnight.")
    j = '{job="pihole"}'
    # queries in each interval, from Pi-hole's rolling 24 h counters (clamped: the window drops old queries too)
    per = lambda m: f"clamp_min(delta({m}{j}[$__interval]), 0)"
    b.row("Overview")
    b.stat("Blocking", f"pihole_status{j}", w=4, th=steps(RED, (1, GREEN)),
           mappings=ok_bad("ENABLED", "DISABLED"), desc="Whether ad blocking is switched on.")
    b.stat("Exporter", 'up{job="pihole"}', w=4, th=steps(RED, (1, GREEN)), mappings=ok_bad("UP", "DOWN"),
           desc="DOWN = Prometheus can't reach pihole-exporter. If this is UP but everything else is empty, the "
                "exporter can't reach the Pi's API (`docker logs pihole-exporter`).")
    b.stat("Queries (24 h)", f"pihole_dns_queries_today{j}", w=4, graph=True, th=steps("text"))
    b.stat("Blocked (24 h)", f"pihole_ads_blocked_today{j}", w=4, graph=True, th=steps("text"))
    b.stat("Blocked %", f"pihole_ads_percentage_today{j}", w=4, unit="percent", decimals=1, graph=True,
           th=steps("text"))
    b.stat("Domains on blocklists", f"pihole_domains_being_blocked{j}", w=4, th=steps("text"), decimals=0,
           desc="Gravity size. A sudden drop to ~0 means a blocklist update failed.")
    b.stat("Clients (24 h)", f"pihole_unique_clients{j}", w=4, th=steps("text"),
           desc="Devices that asked Pi-hole something. If this stays at 1 (the Pi itself), DHCP isn't "
                "handing Pi-hole out as the DNS server yet.")
    b.stat("Cache hit %", f"100 * pihole_queries_cached{j} / clamp_min(pihole_dns_queries_today{j}, 1)", w=4,
           unit="percent", decimals=0, th=steps("text"))
    b.stat("Upstream response",
           f'max(pihole_forward_destinations_responsetime{{job="pihole",destination!~"cache|blocklist|other"}})',
           w=4, unit="ms", decimals=1, th=steps(GREEN, (50, YELLOW), (200, RED)),
           desc="Slowest upstream DNS server's average response time, as Pi-hole reports it.")
    b.stat("Unique domains (24 h)", f"pihole_unique_domains{j}", w=4, th=steps("text"))
    b.stat("Forwarded (24 h)", f"pihole_queries_forwarded{j}", w=4, th=steps("text"))
    b.stat("Clients ever seen", f"pihole_clients_ever_seen{j}", w=4, th=steps("text"))

    b.row("Traffic")
    qp = b.ts("Queries per interval", [target(per("pihole_dns_queries_today"), "all"),
                                  target(per("pihole_ads_blocked_today"), "blocked")],
         w=16, h=8, fill=20, draw="bars", legend_calcs=("sum",),
         overrides=[override("blocked", {"color": {"mode": "fixed", "fixedColor": RED}})],
         desc="Approximate: change in Pi-hole's rolling 24 h counters, so queries ageing out of the window "
              "are netted off (and negatives clamped to 0).")
    qp["interval"] = "5m"  # at least ~10 samples per bar at the 30 s scrape interval
    b.ts("Blocked % (24 h window)", target(f"pihole_ads_percentage_today{j}", "blocked %"), w=8, h=8,
         unit="percent", fill=10, legend_calcs=("lastNotNull",))
    b.ts("Answered by", target(f'pihole_forward_destinations{j}', "{{destination_name}}"), w=12, h=8,
         stack=True, fill=40, legend_calcs=("lastNotNull",),
         desc="Where answers came from over the last 24 h: cache, blocklist or each upstream server.")
    b.ts("Upstream response time", target(f'pihole_forward_destinations_responsetime{{job="pihole",'
                                          f'destination!~"cache|blocklist|other"}}', "{{destination_name}}"),
         w=12, h=8, unit="ms", fill=0, legend_calcs=("mean", "max"))

    b.row("Breakdown (last 24 h)")
    b.bars("Top clients", f"topk(10, pihole_top_sources{j})", w=8, h=9,
           legend="{{source_name}} ({{source}})", th=steps(BLUE), color={"mode": "continuous-BlPu"})
    b.bars("Top domains", f"topk(10, pihole_top_queries{j})", w=8, h=9, legend="{{domain}}",
           th=steps(BLUE), color={"mode": "continuous-BlPu"})
    b.bars("Top blocked domains", f"topk(10, pihole_top_ads{j})", w=8, h=9, legend="{{domain}}",
           th=steps(RED), color={"mode": "fixed", "fixedColor": RED},
           desc="Empty until Pi-hole has blocked something.")
    b.bars("Query types", f"sort_desc(pihole_querytypes{j} > 0)", w=12, h=8, legend="{{type}}",
           th=steps(BLUE), color={"mode": "continuous-BlPu"})
    b.bars("Reply types", f"sort_desc(pihole_reply{j} > 0)", w=12, h=8, legend="{{type}}",
           th=steps(BLUE), color={"mode": "continuous-BlPu"},
           desc="nx_domain = name doesn't exist; refused/other spikes can mean an upstream problem.")
    return b.save("pihole.json")


# ─────────────────────────────────────────────────────────────── PiAware (ADS-B)
def piaware():
    b = Board("piaware", "PiAware", ["piaware", "adsb"], refresh="1m", time_from="now-24h",
              description="PiAware (dump1090-fa) on the Pi Zero 2 W via json-exporter "
                          "(services/piaware-exporter/config.yml).")
    j = '{job="piaware"}'
    # great-circle distance (km) from the receiver to each aircraft with a position in the last minute
    rlat, rlon = "piaware_receiver_lat", "piaware_receiver_lon"
    lat, lon = "piaware_aircraft_position_lat", "piaware_aircraft_position_lon"
    dist = (f"(6371 * 2 * asin(sqrt(sin(rad({lat} - scalar({rlat})) / 2) ^ 2 + scalar(cos(rad({rlat}))) "
            f"* cos(rad({lat})) * sin(rad({lon} - scalar({rlon})) / 2) ^ 2)) "
            f"and piaware_aircraft_position_seen_seconds < 60)")
    aircraft = "count(piaware_aircraft_seen_seconds < 60) or vector(0)"
    positioned = "count(piaware_aircraft_position_seen_seconds < 60) or vector(0)"
    strong_pct = "100 * rate(piaware_strong_signals_total[5m]) / clamp_min(rate(piaware_messages_total[5m]), 1)"
    no_range = "Empty if the site has no location: set it on your FlightAware stats page (receiver.json)."

    b.row("Overview")
    b.stat("Feeder", f"min(up{j})", w=4, th=steps(RED, (1, GREEN)), mappings=ok_bad("UP", "DOWN"),
           desc="DOWN = at least one of stats/aircraft/receiver.json can't be read. Check Explore with "
                f"up{j} (label `file`), then `docker logs piaware-exporter` and http://piaware.local/skyaware/.")
    b.stat("Aircraft now", aircraft, w=4, graph=True, th=steps("text"),
           desc="Heard in the last 60 s.")
    b.stat("With position", positioned, w=4, graph=True, th=steps("text"),
           desc="Position in the last 60 s (ADS-B equipped and decoded).")
    b.stat("Max range now", f"max({dist})", w=4, unit="lengthkm", decimals=0, th=steps("text"), desc=no_range)
    b.stat("Max range (24 h)", f"max_over_time(max({dist})[24h:1m])", w=4, unit="lengthkm", decimals=0,
           th=steps("text"), desc=no_range)
    b.stat("Messages/s", "sum(rate(piaware_messages_total[5m]))", w=4, unit="short", decimals=0, graph=True,
           th=steps("text"))
    b.stat("Strong signals", strong_pct, w=4, unit="percent", decimals=1,
           th=steps(GREEN, (5, YELLOW), (10, RED)),
           desc="Share of messages above -3 dBFS. A few % is fine; much more means the gain is too high "
                "and close aircraft are drowning out distant ones.")
    b.stat("Gain", "piaware_gain_db", w=4, unit="dB", decimals=1, th=steps("text"))
    b.stat("Noise floor", "piaware_noise_dbfs", w=4, unit="dB", decimals=1, th=steps("text"),
           desc="dBFS. Should sit well below the mean signal; a rising floor means local interference.")
    b.stat("Samples dropped (24 h)", "sum(increase(piaware_samples_dropped_total[24h])) or vector(0)", w=4,
           decimals=0, th=steps(GREEN, (1, RED)),
           desc="Above 0 = the Pi didn't read the SDR fast enough: CPU, USB or undervoltage.")
    b.stat("dump1090 CPU", "(" + " + ".join(f"rate(piaware_cpu_{c}_milliseconds_total[5m])" for c in ("demod", "reader", "background"))
           + ") / 10",
           w=4, unit="percent", decimals=0, th=steps(GREEN, (60, YELLOW), (85, RED)),
           desc="% of one core. The Zero 2 W has four, but the demodulator only uses one.")
    b.stat("Positions/s", "rate(piaware_cpr_global_ok_total[5m])", w=4, decimals=1, graph=True,
           th=steps("text"))

    b.row("Traffic")
    b.ts("Aircraft", [target(aircraft, "all"), target(positioned, "with position")], w=12, h=8,
         legend_calcs=("mean", "max"))
    b.ts("Max range", target(f"max({dist})", "max range"), w=12, h=8, unit="lengthkm", fill=10,
         legend_calcs=("mean", "max"), desc=no_range)
    b.ts("Messages/s", [target("rate(piaware_messages_total[5m])", "messages"),
                        target("rate(piaware_cpr_global_ok_total[5m])", "positions")], w=12, h=8,
         legend_calcs=("mean", "max"))
    b.ts("New tracks/min", [target("60 * rate(piaware_tracks_total[5m])", "all"),
                            target("60 * rate(piaware_tracks_single_message_total[5m])", "single message")],
         w=12, h=8, legend_calcs=("mean", "max"),
         desc="Single-message tracks are mostly noise or aircraft right at the edge of range.")

    b.row("Receiver")
    b.ts("Signal (dBFS)", [target("piaware_signal_dbfs", "mean signal"),
                           target("piaware_peak_signal_dbfs", "peak"),
                           target("piaware_noise_dbfs", "noise floor")],
         w=12, h=8, unit="dB", fill=0, legend_calcs=("mean", "min", "max"), custom={"axisSoftMin": None},
         desc="From each minute of stats.json. Peak near 0 dBFS = clipping; drop the gain.")
    b.ts("Strong signals %", target(strong_pct, "strong"), w=12, h=8, unit="percent", fill=10,
         legend_calcs=("mean", "max"))
    b.ts("dump1090 CPU (% of one core)",
         [target(f"rate(piaware_cpu_{c}_milliseconds_total[5m]) / 10", c) for c in ("demod", "reader", "background")],
         w=12, h=8, unit="percent", stack=True, fill=40, legend_calcs=("mean", "max"))
    b.ts("Gain", target("piaware_gain_db", "gain"), w=12, h=8, unit="dB", fill=0, legend_calcs=("min", "max"),
         custom={"axisSoftMin": None}, desc="Flat unless adaptive gain is on.")
    return b.save("piaware.json")


if __name__ == "__main__":
    for fn in (storage, containers, traefik, pihole, piaware):
        d = fn()
        print(f"{d['uid']}.json: {sum(p['type'] != 'row' for p in d['panels'])} panels")
