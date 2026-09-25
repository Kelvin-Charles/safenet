# Omada Controller hosted by SafeNet

TP-Link's Omada Software Controller runs next to SafeNet so tenants' Omada access
points (EAP225 and others) need nothing else at their site. SafeNet shows the
login page and lets paying guests online through the controller's External
Portal API, logged in as the hotspot operator `safenet-portal`.

On the server: `~/sandbox/applications/omada-controller` (this folder's files).

- Start / update: `docker compose pull && docker compose up -d`
  (host network: Docker has no free bridge networks on this server).
- Access points adopt to `radius.safezonetz.com` (UDP 29810, TCP 29811-29817).
- Admin page: `https://omada.safezonetz.com` (Nginx Proxy Manager host with its own Let's Encrypt
  certificate, forwarding to port 8043). `https://radius.safezonetz.com:8043` also works.
- Logins are in `ADMIN_CREDENTIALS` (mode 600, not in git): controller admin,
  the device login the controller sets on adopted access points, and the
  hotspot operator.
- SafeNet reads `OMADA_HOSTED_URL=https://127.0.0.1:8043`, `OMADA_HOSTED_USER`
  and `OMADA_HOSTED_PASSWORD` from its `.env`.
- Controller hostname (Settings → Controller → Access Config) is set to
  `radius.safezonetz.com`, so its inform URL is
  `omada://radius.safezonetz.com:8043?dPort=29810&mPort=29814&omadacId=…`.
  Without it the controller hands out an internal server address.
- `sync_operator.py` runs every 5 minutes from cron (log: `sync_operator.log`),
  so new controller sites reach the SafeNet operator automatically.
- The admin page uses the same Let's Encrypt certificate as radius.safezonetz.com:
  `update_cert.sh` copies it from Nginx Proxy Manager (`npm-230`) into `cert/` and
  recreates the controller when it changed. Cron: Mondays 04:00 (log: `update_cert.log`).

## Adding a customer site
1. In the controller, create a site for the customer and adopt their access points.
2. Wait up to 5 minutes (cron runs `sync_operator.py`) or run it yourself.
3. In SafeNet (Sites → Omada → Use SafeNet's controller) copy the portal URL, then in
   the controller: Authentication → Portal → External Portal Server with that URL,
   and allow `radius.safezonetz.com` in Pre-Authentication Access.
