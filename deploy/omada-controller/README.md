# Omada Controller hosted by SafeNet

TP-Link's Omada Software Controller runs next to SafeNet so tenants' Omada access
points (EAP225 and others) need nothing else at their site. SafeNet shows the
login page and lets paying guests online through the controller's External
Portal API, logged in as the hotspot operator `safenet-portal`.

On the server: `~/sandbox/applications/omada-controller` (this folder's files).

- Start / update: `docker compose pull && docker compose up -d`
  (host network: Docker has no free bridge networks on this server).
- Access points adopt to `radius.safezonetz.com` (UDP 29810, TCP 29811-29817).
- Admin page: `https://radius.safezonetz.com:8043`.
- Logins are in `ADMIN_CREDENTIALS` (mode 600, not in git): controller admin,
  the device login the controller sets on adopted access points, and the
  hotspot operator.
- SafeNet reads `OMADA_HOSTED_URL=https://127.0.0.1:8043`, `OMADA_HOSTED_USER`
  and `OMADA_HOSTED_PASSWORD` from its `.env`.

## Adding a customer site
1. In the controller, create a site for the customer and adopt their access points.
2. Run `python3 sync_operator.py` here, so the SafeNet operator can use the new site.
3. In SafeNet (Sites → Omada → Use SafeNet's controller) copy the portal URL, then in
   the controller: Authentication → Portal → External Portal Server with that URL,
   and allow `radius.safezonetz.com` in Pre-Authentication Access.
