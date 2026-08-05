---
layout: default
---

# Hermes Remote

Hermes Mobile can connect to a full [Hermes Agent](https://github.com/NousResearch/hermes-agent) backend running `hermes serve`. This gives your phone access to a more powerful agent with additional tools, models, and session persistence.

## How it works

The mobile client uses the **same JSON-RPC WebSocket protocol** as Hermes Desktop:

1. `GET /api/status` — discover the backend version and authentication providers
2. Basic login (or session token) — authenticate without embedding credentials in URLs
3. One-time WebSocket ticket → `/api/ws` — open a streaming connection
4. JSON-RPC — create sessions, list history, resume conversations, submit prompts, interrupt execution

## Setup

1. Make sure `hermes serve` is running on a machine your phone can reach (see [Connection methods](#connection-methods) above)
2. Open Hermes Mobile → **More (⋯) → Messaging** (or Connections)
3. Switch to **Remote** mode
4. Enter your Hermes backend URL:
   - Tailscale: `https://vps.tailnet.ts.net:9119`
   - Direct: `https://your-vps.com:9119`
   - Local: `http://192.168.1.42:9119`
5. Enter your Hermes username and password
6. The mobile client connects and pulls the model catalog from the backend

## Security

- **Credentials** are stored in the app-private encrypted store, never in settings JSON
- **HTTPS is required** for public hosts
- **Plain HTTP** is accepted only for loopback, private LAN (192.168.x.x, 10.x.x.x, 172.16-31.x.x), and Tailscale (.ts.net) addresses
- **Insecure mode** requires explicit opt-in — never the default

## Remote vs Local

| Feature | Local Mode | Remote Mode |
|---|---|---|
| Models | 7 providers, configured on-device | Backend's full provider list |
| Tools | 41 mobile handlers | Backend's tool set (50+) |
| Memory | SQLite on-device | Backend's memory provider |
| Sessions | Local only | Resumable across devices |
| Petdex | Local hint only | Full pet gallery from backend |
| Skills | Local skills directory | Backend's skill manager |

## Troubleshooting

**"Connection refused"** — check that `hermes serve` is running and the port is reachable. Try `curl http://<host>:9119/api/status` from your phone's browser.

**"HTTPS required"** — the backend URL must use `https://` for non-local hosts. If you're on Tailscale and the backend doesn't have a TLS certificate, use a Tailscale Serve or Funnel.

**Auth failure** — check your Hermes username/password. These are the credentials you set during `hermes setup`, not your API keys.
## Connection methods

You can connect to `hermes serve` any way your phone can reach the host:

**Tailscale (recommended for private VPS)**
```
https://vps.tailnet.ts.net:9119
```
Zero config — your phone joins the tailnet and gets a private IP. HTTPS
via Tailscale's built-in TLS certificates.

**Direct URL (public VPS with HTTPS)**
```
https://plfy.online:9119
```
Works like any website. Make sure your firewall allows the port and you
have a valid TLS certificate (Let's Encrypt, Caddy, or nginx reverse proxy).

**Local network (development or LAN)**
```
http://192.168.1.42:9119
```
Plain HTTP is accepted automatically for private addresses. Useful when
testing against a laptop on the same Wi-Fi.

**Tunnel (ngrok / Cloudflare Tunnel)**
```
https://hermes.ngrok.app
```
No open ports, no static IP — just point the tunnel at `localhost:9119`.
Good for testing behind NAT or CGNAT.

