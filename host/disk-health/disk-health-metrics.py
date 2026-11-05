#!/usr/bin/env python3
"""Disk (SMART) + ZFS pool health -> node_exporter textfile metrics.

Run every 5 min by disk-health.timer, as root (smartctl and `zpool status` need it).
Writes /var/lib/node_exporter/textfile_collector/disk_health.prom; Grafana alerts on it
(services/grafana/provisioning/alerting/rules.yml).

Long-term SMART history is smartd's attribute log, not this script:
/var/lib/smartmontools/attrlog.<model>-<serial>.ata.csv (every attribute, every 30 min).
"""
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime

OUT = "/var/lib/node_exporter/textfile_collector/disk_health.prom"
STATE_DIR = "/var/lib/disk-health"  # last finished scrub per pool (`zpool status` only shows the latest scan)
# ATA attributes whose raw value is a plain counter (3 and 194 are packed, so temperature comes from smartctl's own field)
ATA_ATTRS = {1, 5, 7, 10, 22, 187, 188, 196, 197, 198, 199}

samples = defaultdict(list)  # metric name -> ["name{labels} value", ...]; grouped so each family is contiguous
HELP = {}


def add(metric, value, help_, **labels):
    if value is None:
        return
    HELP.setdefault(metric, help_)
    lbl = ",".join('%s="%s"' % (k, str(v).replace("\\", "\\\\").replace('"', '\\"')) for k, v in labels.items())
    samples[metric].append("%s{%s} %s" % (metric, lbl, float(value)) if lbl else "%s %s" % (metric, float(value)))


def run(cmd, timeout=60):
    """stdout, or None if the command can't run or hangs. Non-zero exit is fine (smartctl's is a bitmask)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def disks():
    j = json.loads(run(["lsblk", "-dJo", "NAME,TYPE,TRAN"]) or '{"blockdevices": []}')
    for d in j["blockdevices"]:
        if d["type"] == "disk" and d.get("tran") in ("usb", "sata", "nvme"):
            yield "/dev/" + d["name"], d["tran"]


def smart(dev, tran):
    # USB enclosures need -d sat for ATA passthrough; everything else autodetects
    out = run(["smartctl", "-j", "-a"] + (["-d", "sat"] if tran == "usb" else []) + [dev])
    try:
        j = json.loads(out)
    except (TypeError, ValueError):
        j = {}
    serial = j.get("serial_number")
    if not serial or "smart_status" not in j:
        add("smart_read_failed", 1, "smartctl could not read SMART data from this device.", device=dev)
        print(f"{dev}: SMART read failed")
        return
    kind = "nvme" if j.get("device", {}).get("type") == "nvme" else "hdd"
    s = dict(serial=serial, kind=kind)
    add("smart_device_info", 1, "Disk identity.", device=dev, model=j.get("model_name", ""), **s)
    add("smart_device_up", 1, "SMART data was read this run.", **s)
    add("smart_health_passed", int(j["smart_status"].get("passed", False)), "Drive's overall SMART self-assessment (1 = PASSED).", **s)
    temp = j.get("temperature", {}).get("current")
    add("smart_temperature_celsius", temp, "Current drive temperature.", **s)
    add("smart_power_on_hours", j.get("power_on_time", {}).get("hours"), "Power-on hours.", **s)
    summary = [f"temp={temp}"]
    for a in j.get("ata_smart_attributes", {}).get("table", []):
        if a["id"] in ATA_ATTRS:
            add("smart_attribute_raw", a["raw"]["value"], "Raw value of counter-type ATA SMART attributes.",
                id=a["id"], name=a["name"], **s)
            if a["id"] in (5, 197, 198, 199):
                summary.append(f"{a['name']}={a['raw']['value']}")
    log = j.get("nvme_smart_health_information_log")
    if log:
        add("smart_nvme_critical_warning", log.get("critical_warning"), "NVMe critical warning bitfield (0 = fine).", **s)
        add("smart_nvme_percentage_used", log.get("percentage_used"), "NVMe endurance used, percent.", **s)
        add("smart_nvme_available_spare", log.get("available_spare"), "NVMe available spare, percent.", **s)
        add("smart_nvme_media_errors", log.get("media_errors"), "NVMe media and data integrity errors.", **s)
        summary += [f"used={log.get('percentage_used')}%", f"media_errors={log.get('media_errors')}"]
    print(f"{dev} {serial}: passed={j['smart_status'].get('passed')} " + " ".join(summary))


def serial_map():
    """partition/disk name or PARTUUID -> parent disk serial, to label pool members with the physical disk."""
    m = {}
    j = json.loads(run(["lsblk", "-Jo", "NAME,SERIAL,PARTUUID"]) or '{"blockdevices": []}')
    for d in j["blockdevices"]:
        for node in [d] + d.get("children", []):
            for key in (node.get("name"), node.get("partuuid")):
                if key and d.get("serial"):
                    m[key] = d["serial"]
    return m


def scrub_state(pool, scan):
    """Remember the end time of the last finished scrub; a later resilver replaces it in `zpool status`."""
    path = os.path.join(STATE_DIR, pool + ".last_scrub")
    m = re.match(r"scrub repaired \S+ in .* with (\d+) errors on (.+)$", scan)
    if m:
        end = datetime.strptime(" ".join(m[2].split()), "%a %b %d %H:%M:%S %Y").timestamp()
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(f"{int(end)} {m[1]}\n")
    try:
        end, errors = open(path).read().split()
    except (OSError, ValueError):
        return
    add("zpool_last_scrub_end_timestamp_seconds", end, "When the last finished scrub ended.", pool=pool)
    add("zpool_last_scrub_errors", errors, "Errors found by the last finished scrub.", pool=pool)


def zpool(pool, serials):
    st = run(["zpool", "status", "-p", pool])
    if st is None:
        return
    scan, rows, in_config = "", [], False
    for line in st.splitlines():
        s = line.strip()
        if s.startswith("scan:"):
            scan = s[5:].strip()
        elif s.startswith("config:"):
            in_config = True
        elif s.startswith("errors:"):
            in_config = False
            n = 0 if "No known data errors" in s else (re.search(r"(\d+) data errors", s) or [None, None])[1]
            add("zpool_data_errors", n, "Files/objects with permanent errors (zpool status -v lists them).", pool=pool)
        elif in_config and s and not s.startswith("NAME"):
            rows.append((len(line.expandtabs(8)) - len(line.expandtabs(8).lstrip()), s.split()))
    # leaf vdevs (the disks) are rows not followed by a more-indented row
    for i, (indent, parts) in enumerate(rows):
        is_leaf = i + 1 == len(rows) or rows[i + 1][0] <= indent
        if not is_leaf or len(parts) < 5 or not all(p.isdigit() for p in parts[2:5]):
            continue
        v = dict(pool=pool, vdev=parts[0], serial=serials.get(parts[0], "unknown"))
        add("zpool_vdev_online", int(parts[1] == "ONLINE"), "Pool member disk state is ONLINE.", **v)
        for kind, n in zip(("read", "write", "checksum"), parts[2:5]):
            add("zpool_vdev_errors", n, "Pool member error counters since last zpool clear/import.", type=kind, **v)
    add("zpool_scrub_in_progress", int("scrub in progress" in scan), "A scrub is running.", pool=pool)
    scrub_state(pool, scan)


def main():
    for dev, tran in disks():
        smart(dev, tran)
    serials = serial_map()
    for pool in (run(["zpool", "list", "-H", "-o", "name"]) or "").split():
        zpool(pool, serials)
    add("disk_health_last_run_timestamp_seconds", time.time(), "When disk-health-metrics last ran.")

    text = "".join(f"# HELP {n} {HELP[n]}\n# TYPE {n} gauge\n" + "\n".join(lines) + "\n" for n, lines in samples.items())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w") as f:
        f.write(text)
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main()
