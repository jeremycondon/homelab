# Pi Zero 2 W — Pi-hole + AirPrint

Runs Pi-hole (DNS ad-blocking) and CUPS/Avahi (AirPrint bridge) natively on the Pi.
These are intentionally **not** on the main server — Pi-hole must stay up when you're tinkering with it,
and both services fight Docker networking (host mode, mDNS, port 53).

## Setup

### 1. Flash Raspberry Pi OS Lite (64-bit)
Use Raspberry Pi Imager. Enable SSH and set your username/password in the imager settings.

### 2. Static DHCP lease
Before booting, reserve a static IP for the Pi's MAC address in your router's DHCP settings.
Pi-hole will be your DNS server — if its IP changes, DNS breaks for your whole network.

### 3. (Optional) Unattended Pi-hole install
```bash
cp pihole/setupVars.conf.example pihole/setupVars.conf
# Edit setupVars.conf — at minimum set WEBPASSWORD
```
If you skip this, the script runs the interactive Pi-hole installer instead.

### 4. Run bootstrap
```bash
scp -r pi/ pi@<pi-ip>:~/
ssh pi@<pi-ip>
sudo bash ~/pi/bootstrap-pi.sh
```

### 5. Point your router's DNS at the Pi
Set your router's primary DNS server to the Pi's static IP.
All devices on the network get ad-blocking automatically.

## AirPrint

After a printer is added in CUPS, Avahi advertises it over mDNS as an AirPrint printer.
Any iOS/macOS device on the same network can print to it without any configuration.

**USB printer on Pi Zero 2:** The Pi Zero 2 has one micro-USB OTG port.
You'll need a micro-USB OTG hub/adapter to connect a USB printer.
If your printer is already on WiFi, CUPS can add it via its IP — no USB needed.

## Access

| Service | URL |
|---------|-----|
| Pi-hole admin | http://pihole.pinet.local/admin |
| CUPS admin | http://cups.pinet.local |

Raw IP fallbacks (no nginx required):

| Service | URL |
|---------|-----|
| Pi-hole admin | http://\<pi-ip\>/admin |
| CUPS admin | http://\<pi-ip\>:631 |

## Troubleshooting

### Canon UFR2 driver hangs on `dpkg --configure -a`

The Canon UFR2 driver postinstall script calls `cnsetuputil2`, a GUI setup wizard that hangs
on a headless Pi. Patch it out before re-running dpkg:

```bash
sudo sed -i 's/^cnsetuputil2/#cnsetuputil2/' /var/lib/dpkg/info/cnrdrvcups-ufr2-uk.postinst
sudo kill $(pgrep -f "cnsetuputil2")   # if it's already hanging
sudo dpkg --configure -a
```

## nginx reverse proxy (optional)

Routes `cups.pinet.local` → port 631 and `pihole.pinet.local` → port 80
so you don't have to remember port numbers.

### 1. Run the setup script

```bash
sudo bash ~/pi/nginx/setup-nginx.sh
```

### 2. Add local DNS records in Pi-hole

Pi-hole admin → Settings → Local DNS → DNS Records:

| Domain | IP |
|--------|----|
| `cups.pinet.local` | Pi's static IP |
| `pihole.pinet.local` | Pi's static IP |
