# UniFi controller hosted by SafeNet

Ubiquiti's UniFi Network Application runs next to SafeNet so businesses' UniFi access points need nothing
else at their site. SafeNet makes a controller site for each SafeNet site (Sites → UniFi → Use SafeNet's
controller), creates the open guest Wi-Fi and sets the guest portal to SafeNet; it lets paying guests online
with the controller's `authorize-guest` command.

On the server: `~/sandbox/applications/unifi-controller` (this folder's files).

## Set up (done 2026-11-15)
1. `docker compose up -d` (image jacobalberty/unifi:v9.5.21, host network).
2. `/unifi/data/system.properties` has `unifi.stun.port=3480` (3478 and 3479 belong to other services here).
3. Admin `safenet` (super admin, local) — login in `ADMIN_CREDENTIALS` (mode 600, not in git). The setup wizard's
   API said ok but saved no admin, so it was added straight into the controller's database (`admin` and
   `privilege` collections, password as SHA-512 crypt) — the usual UniFi recovery method. `setup_first_run.py`
   here does the first-run calls and checks the login.
4. Inform host override: `radius.safezonetz.com` (`super_identity.hostname`, `super_mgmt.override_inform_host`).
5. SafeNet's `.env` has `UNIFI_HOSTED_URL`, `UNIFI_HOSTED_USER`, `UNIFI_HOSTED_PASSWORD` (copied from
   `ADMIN_CREDENTIALS`; backup of the old file in `.env.bak-unifi`).

Ports in use: TCP 8089 (inform, open to the internet), 8445 (admin page and API), 8844/8881 (built-in portal,
unused), 6789 (speed test); UDP 3480 (STUN), 10001 (discovery), 5514 (syslog); MongoDB on 127.0.0.1:27117.
Admin page: https://radius.safezonetz.com:8445 (self-signed certificate).

## Guests' login page address
The controller only accepts an **IP address** as the external portal server (9.5 rejects names), so guests are
sent to `http://209.74.72.96/guest/s/<site>/…`. SafeNet sends them on to `https://radius.safezonetz.com/…`, but
the request has to reach SafeNet first: in Nginx Proxy Manager add a **Redirection Host** for `209.74.72.96`
→ `https://radius.safezonetz.com`, **Preserve Path on**, HTTP code 302 (no SSL certificate for the IP).

## Memory
The controller is limited to 1.6 GB (`mem_limit`, Java heap 1 GB). Check `docker stats unifi-controller`.
