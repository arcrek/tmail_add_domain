# Auto-Add Domain via JMAP — Design Spec

**Date:** 2026-06-17  
**Status:** Approved

## Overview

When Postfix receives an SMTP connection for an unknown domain, a policy daemon checks whether that domain's MX record points to `mail.tm-mails.com`. If it matches, the daemon auto-provisions the domain in Stalwart via JMAP — including a catch-all that delivers all mail to `admin@mail.tm-mails.com`. The first email to a new domain is never lost.

---

## Architecture

```
Internet
   ↓ SMTP :25
Postfix  ──check_policy_service──→  Policy Daemon :10030
   ↓ (after policy DUNNO)              ↑  ↓
   ↓ LMTP :24                     DNS MX  JMAP API
Stalwart (127.0.0.1 only)         lookup   ↓
   ↓                                   Stalwart
catch-all → admin@mail.tm-mails.com
```

All components run on the same remote server.

**Port ownership:**
- Postfix owns `:25` (public-facing SMTP)
- Stalwart's external SMTP listener is moved to `127.0.0.1` only (no longer binds public `:25`)
- Postfix delivers to Stalwart via LMTP on `127.0.0.1:24`

---

## Components

### 1. Policy Daemon (`policy_daemon.py`)

Python TCP server on `127.0.0.1:10030` implementing the Postfix policy protocol.

**Startup sequence:**
1. Load `domains.json` disk cache into memory (set of known domain strings)
2. Fetch all existing domains from Stalwart via `x:Domain/get` JMAP call — merge into cache, save to disk
3. Begin listening for Postfix connections

**Per-request flow:**

```
receive RCPT TO → extract domain
       ↓
   cache hit? → YES → return DUNNO (instant)
       ↓ NO
   DNS MX lookup for domain
       ↓
   any MX == "mail.tm-mails.com"?
       ↓ NO                      ↓ YES
   return DUNNO             JMAP: x:Domain/set (creates domain + catch-all)
   (Stalwart rejects)       add to cache + persist domains.json
                                 ↓
                            return DUNNO
```

**Cache persistence:**  
`domains.json` is a JSON array of domain strings. Written atomically — write to `domains.json.tmp` then `rename()` — to prevent corruption on crash. On corrupt/missing file, rebuilds from Stalwart at startup.

### 2. Postfix Setup (full install + config)

Postfix is untouched on the server and needs to be fully configured as an SMTP gateway.

**Step 1 — Install Postfix:**
```bash
apt install postfix libsasl2-modules -y
# Select "Internet Site" during setup, hostname: mail.tm-mails.com
```

**Step 2 — `/etc/postfix/main.cf` (full relevant config):**
```
myhostname = mail.tm-mails.com
mydomain = tm-mails.com
myorigin = $myhostname

# Listen on all interfaces for inbound SMTP
inet_interfaces = all
inet_protocols = ipv4

# Postfix does NOT own local delivery — Stalwart does
mydestination =
local_recipient_maps =
local_transport = error:local delivery disabled

# Relay all accepted mail to Stalwart via LMTP
virtual_transport = lmtp:127.0.0.1:24
virtual_mailbox_domains = /etc/postfix/accepted_domains

# Trust only localhost as relay
mynetworks = 127.0.0.0/8
relay_domains =

# Policy daemon for auto-domain provisioning
smtpd_recipient_restrictions =
    permit_mynetworks,
    check_policy_service inet:127.0.0.1:10030,
    permit
```

**Step 3 — `/etc/postfix/accepted_domains`:**
```
*    OK
```
A wildcard file that tells Postfix it is the final destination for any domain. The policy daemon enforces MX validation before accepting; Stalwart enforces domain existence for delivery.  
Rebuild map: `postmap /etc/postfix/accepted_domains`

**Step 4 — Reload Postfix:**
```bash
postfix check && systemctl reload postfix
```

### 3. Stalwart Reconfiguration

Stalwart currently owns port 25. It must be moved so Postfix can bind it.

**Required change in Stalwart config** (exact path depends on server, typically `/etc/stalwart/config.toml` or via web admin):
- Change the SMTP listener bind from `0.0.0.0:25` → `127.0.0.1:25` (or disable the SMTP listener entirely if LMTP :24 is used)
- Confirm LMTP listener is enabled on `127.0.0.1:24`

**Sequence to avoid downtime:**
1. Stop Stalwart
2. Edit Stalwart config to move SMTP off port 25
3. Start Postfix (now owns :25)
4. Start Stalwart (now owns :24 LMTP)
5. Verify with `ss -tlnp | grep -E ':25|:24'`

The catch-all per domain (`@newdomain.com → admin@mail.tm-mails.com`) is set by the JMAP call at provisioning time — no manual Stalwart changes per domain.

---

## JMAP API Call

Single call provisions the domain and sets catch-all simultaneously.

**Endpoint:** `POST https://mail.tm-mails.com/jmap/`  
**Auth:** `Authorization: Bearer <API_TOKEN>`  
**Payload:**

```json
{
  "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
  "methodCalls": [[
    "x:Domain/set",
    {
      "accountId": "b",
      "create": {
        "new-0": {
          "name": "<DOMAIN>",
          "isEnabled": true,
          "allowRelaying": true,
          "catchAllAddress": "admin@mail.tm-mails.com",
          "certificateManagement": {"@type": "Manual"},
          "dnsManagement": {"@type": "Manual"},
          "reportAddressUri": "mailto:postmaster",
          "subAddressing": {"@type": "Enabled"},
          "dkimManagement": {"@type": "Manual"}
        }
      }
    },
    "0"
  ]]
}
```

---

## Configuration File

`/opt/tmail-policy/config.json` (chmod 600, owned by `tmail-policy` user):

```json
{
  "jmap_url": "https://mail.tm-mails.com/jmap/",
  "jmap_token": "YOUR_API_TOKEN",
  "mx_hostname": "mail.tm-mails.com",
  "catchall_address": "admin@mail.tm-mails.com",
  "listen_addr": "127.0.0.1",
  "listen_port": 10030,
  "cache_file": "/var/lib/tmail-policy/domains.json"
}
```

---

## File Layout on Remote Server

```
/opt/tmail-policy/
  policy_daemon.py          # main daemon
  config.json               # credentials + settings (chmod 600)

/var/lib/tmail-policy/
  domains.json              # persistent domain cache

/etc/systemd/system/
  tmail-policy.service      # systemd unit
```

---

## Systemd Service

Runs as dedicated `tmail-policy` user (no root). Restarts automatically on crash.

```ini
[Unit]
Description=Tmail Policy Daemon
After=network.target

[Service]
User=tmail-policy
ExecStart=/usr/bin/python3 /opt/tmail-policy/policy_daemon.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Error Handling

| Situation | Behavior |
|---|---|
| DNS timeout / error | Return `DUNNO`, log warning; Stalwart rejects |
| MX doesn't match `mail.tm-mails.com` | Return `DUNNO`; Stalwart rejects unknown domain |
| JMAP call fails (network/auth error) | Return `DUNNO`, log error with domain name for manual recovery |
| JMAP returns error response | Log full response + domain, return `DUNNO` |
| Cache file missing or corrupt | Rebuild from Stalwart `x:Domain/get` on startup |
| Daemon unreachable from Postfix | Postfix falls through to next restriction (safe — no mail lost) |

---

## End-to-End Flow

1. Email arrives for `user@newdomain.com`
2. Postfix calls policy daemon: `recipient=user@newdomain.com`
3. Daemon: cache miss → MX lookup → `mail.tm-mails.com` matches
4. Daemon: JMAP `x:Domain/set` → domain + catch-all created in Stalwart
5. Daemon: saves `newdomain.com` to cache → returns `DUNNO`
6. Postfix accepts, forwards email to Stalwart
7. Stalwart matches catch-all `@newdomain.com` → delivers to `admin@mail.tm-mails.com`

---

## Dependencies

- Python 3.8+ with `dnspython` and `httpx` (or `requests`)
- Postfix (fresh install via `apt install postfix`)
- Stalwart JMAP API accessible at `https://mail.tm-mails.com/jmap/`
- Valid Bearer API token with domain management permissions
