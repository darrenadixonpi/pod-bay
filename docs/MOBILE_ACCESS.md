# Installing Pod Bay on a phone

Pod Bay's web UI is a PWA (Progressive Web App): once loaded over a secure
origin it can be added to a phone's home screen, runs full-screen like a native
app, and keeps the interface — plus any diagrams you've already opened — working
offline (see `app/frontend/sw.js`). The chat itself still needs the backend
reachable, since answers come from the Claude API.

The one requirement the browser enforces: **the service worker only registers
over HTTPS** (or `localhost`). Plain `http://192.168.x.x:8000/` will load the
page but silently refuse to install it. So to get Pod Bay onto a phone you need
the backend served over HTTPS at your machine's LAN address. There are two ways
to do that.

## Option A — self-signed certificate on your LAN (no extra accounts)

This is the fastest path and works entirely on your own network. The catch is a
one-time "this connection isn't private" warning you have to clear on each
device, because the certificate isn't signed by a public authority.

1. Install the one extra dependency (kept out of `requirements.txt` because only
   LAN serving needs it):

   ```
   pip install cryptography
   ```

2. From `app/backend/`, with the venv active, start the HTTPS launcher:

   ```
   python run_lan.py
   ```

   It detects your machine's LAN IP, generates a self-signed certificate for
   that IP (cached under `app/backend/.certs/`, regenerated only if the IP
   changes), and starts uvicorn bound to `0.0.0.0` over TLS. It prints the two
   URLs to use:

   ```
   On this machine:  https://localhost:8000/
   On your phone:    https://192.168.1.50:8000/   (same wifi)
   ```

   Override the port with `--port 8443`, or force a specific address with
   `--host-ip 192.168.1.50`. Add `--reload` for development.

3. On the phone (connected to the **same wifi**), open the `https://<lan-ip>:…`
   URL. You'll get a certificate warning:

   - **Android / Chrome:** tap *Advanced → Proceed to … (unsafe)*.
   - **iPhone / Safari:** tap *Show Details → visit this website*. iOS is
     stricter about service workers behind an untrusted cert — if installation
     doesn't stick, see "Trusting the cert on iOS" below.

4. Add it to the home screen:

   - **Android / Chrome:** a banner or *⋮ → Add to Home screen / Install app*.
   - **iPhone / Safari:** *Share → Add to Home Screen*.

   The icon and name come from `app/frontend/manifest.json`.

### Trusting the cert on iOS (only if install fails)

iOS won't run a service worker behind an untrusted certificate, so you may need
to install and trust it explicitly:

1. Email/AirDrop yourself `app/backend/.certs/podbay.crt`, open it on the phone,
   and install the resulting profile (*Settings → General → VPN & Device
   Management → install*).
2. Enable full trust: *Settings → General → About → Certificate Trust Settings*,
   and switch on the Pod Bay certificate.
3. Reload the page in Safari, then *Add to Home Screen*.

### Windows firewall

The first time you serve on `0.0.0.0`, Windows may prompt to allow Python
through the firewall — allow it on **private networks** so phones on your wifi
can connect. If there's no prompt and the phone can't reach the URL, add an
inbound rule for the port (8000 by default).

## Option B — Tailscale (real certificate, no warnings)

If you'd rather avoid the certificate warning entirely — and be able to reach
Pod Bay from anywhere, not just your home wifi — put the machine on a
[Tailscale](https://tailscale.com) network. Tailscale can issue a genuine,
publicly-trusted certificate for your device's `*.ts.net` name, so no device has
to trust anything manually.

1. Install Tailscale on the host machine and the phone; sign both into the same
   tailnet.
2. Enable HTTPS certificates for your tailnet (Tailscale admin console → DNS →
   *Enable HTTPS*).
3. Run the plain (HTTP) backend as usual:

   ```
   uvicorn server:app --port 8000
   ```

4. Put Tailscale's TLS proxy in front of it:

   ```
   tailscale serve https / http://127.0.0.1:8000
   ```

   Tailscale terminates TLS with a real cert and forwards to the local backend.
   Open `https://<machine-name>.<tailnet>.ts.net/` on the phone — no warning —
   and add it to the home screen. Because it's over Tailscale, this works on
   cellular too, not only on the same wifi.

## Which to choose

- **Just want it on your phone in the garage, same wifi:** Option A. One `pip
  install`, one command, clear a warning once.
- **Want no warnings, access off your home network, or multiple devices without
  per-device trust steps:** Option B (Tailscale).

## Notes

- The service worker caches the app shell and any diagrams you've viewed, so the
  UI and previously-seen schematics open offline. New answers and unseen
  diagrams still require the backend to be reachable.
- After changing front-end files, bump `CACHE_NAME` in `app/frontend/sw.js`
  (e.g. `podbay-v1` → `podbay-v2`) so phones pick up the new shell; the in-app
  "Update available — Reload" toast handles the rest.
- `.certs/` is gitignored — certificates are machine-local and never committed.
