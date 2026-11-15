# UniFi controller hosted by SafeNet

Ubiquiti's UniFi Network Application runs next to SafeNet so businesses' UniFi access points need nothing
else at their site. SafeNet makes a controller site for each SafeNet site (Sites → UniFi → Use SafeNet's
controller), creates the open guest Wi-Fi and sets the guest portal to SafeNet; it lets paying guests online
with the controller's `authorize-guest` command.

On the server: `~/sandbox/applications/unifi-controller` (this folder's files).

## First start
1. Copy this folder to the server and start it: `docker compose up -d`. First start takes a few minutes.
2. Open the port access points use, in the server's firewall: **TCP 8089** (inform). Optional: **UDP 3480**
   (STUN, for "locate" and live device commands).
3. Set the STUN port: after the first start, add `unifi.stun.port=3480` to
   `/unifi/data/system.properties` in the volume (`docker exec -it unifi-controller sh`), then
   `docker compose restart`. UniFi's default 3478 is already taken on this server.
4. Open the setup page through an SSH tunnel (`ssh -L 8445:127.0.0.1:8445 …`, then https://127.0.0.1:8445),
   choose **advanced setup → local account**, and create the admin. Skip the UI.com sign-in.
5. Settings → System → Advanced: **Inform host override** = `radius.safezonetz.com` (otherwise access points
   are told an internal address).
6. Make a second local admin for SafeNet (full access, local only), and put it in SafeNet's `.env`:
   ```
   UNIFI_HOSTED_URL=https://127.0.0.1:8445
   UNIFI_HOSTED_USER=safenet
   UNIFI_HOSTED_PASSWORD=…
   ```
   then redeploy SafeNet (or `docker compose up -d web`).
7. Keep the logins in `ADMIN_CREDENTIALS` here (mode 600, not in git), like the Omada controller.

## Guests' login page address
The controller sends guests to `http://radius.safezonetz.com/guest/s/<site>/…` (Nginx Proxy Manager forwards
it to SafeNet like every radius.safezonetz.com request). Some UniFi versions only accept an IP for the external
portal server: then guests arrive at `http://209.74.72.96/guest/s/…`, which Nginx Proxy Manager answers itself
(403). If that happens, add a proxy host (or the default site) for the bare IP that forwards `/guest/s/` to
SafeNet on port 5001.

## Memory
The controller is limited to 1.6 GB (`mem_limit`, Java heap 1 GB). Check `docker stats unifi-controller`.
