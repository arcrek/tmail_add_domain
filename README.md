# tmail-add-domain

Auto-provisions domains in Stalwart mail server when the first email arrives for a domain whose MX points to `mail.tm-mails.com`. All mail is caught and forwarded to a configured address — no manual domain setup needed.

## How It Works

```
Postfix (:25) → Policy Daemon (:10030) → DNS MX check → Stalwart JMAP API → Stalwart LMTP (:24)
```

1. Postfix receives an inbound SMTP connection and consults the policy daemon.
2. The daemon checks whether the recipient domain's MX record points to this server.
3. If it does and the domain isn't yet known, it calls the Stalwart JMAP API to create the domain with a catch-all address.
4. The domain is cached locally so subsequent emails skip the API call.
5. Postfix accepts the mail and delivers it to Stalwart via LMTP.

## Requirements

- Python 3.8+
- Postfix
- Stalwart mail server (remote or local) with JMAP enabled
- A Bearer token with permission to create domains

## Installation

```bash
sudo bash deploy/install.sh
```

The installer:
- Installs Python dependencies
- Copies config and source files
- Registers and starts the `tmail-policy` systemd service
- Emits the Postfix snippet you need to add to `main.cf`

## Configuration

Copy `config.example.json` to `/etc/tmail-policy/config.json` and fill in your values:

```json
{
  "jmap_url": "",
  "jmap_token": "YOUR_API_TOKEN",
  "mx_hostname": "",
  "catchall_address": "",
  "listen_addr": "127.0.0.1",
  "listen_port": 10030,
  "cache_file": "/var/lib/tmail-policy/domains.json"
}
```

## Postfix Integration

Add the following to `/etc/postfix/main.cf` (see `deploy/postfix_main_snippet.cf`):

```
smtpd_recipient_restrictions =
    check_policy_service inet:127.0.0.1:10030,
    permit_mynetworks,
    reject_unauth_destination
```

Stalwart must not listen on port 25 — move its SMTP listener so Postfix can bind it.

## Service Management

```bash
systemctl status tmail-policy
journalctl -u tmail-policy -f
```
