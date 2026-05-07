# aipanel

On-prem AI voice agent platform with ViciDial integration.

> **Status:** v0.1.0 — installer skeleton only. Application services land in
> subsequent releases.

## Requirements

| Resource | Minimum             | Recommended           |
|----------|---------------------|-----------------------|
| OS       | Ubuntu 22.04 LTS    | Ubuntu 22.04 LTS      |
| CPU      | 16 cores            | 32 cores              |
| RAM      | 32 GB (16 GB hard)  | 64 GB                 |
| Disk     | 200 GB free on `/`  | 500 GB+ NVMe          |
| GPU      | optional for dev    | 1× NVIDIA, CUDA 12.x  |

RHEL 9 is detected by the installer but not yet supported.

## Quick start

```bash
git clone <repo-url> /opt/aipanel
cd /opt/aipanel
sudo ./install.sh
```

The installer is **idempotent** — re-running it on the same host is safe and
will only apply missing pieces.

All output is mirrored to `/var/log/aipanel/install.log`.

## Repository layout

```
/opt/aipanel/
├── install.sh          # main entrypoint
├── update.sh           # in-place upgrade
├── uninstall.sh        # remove services + data (prompts first)
├── status.sh           # systemctl status for all aipanel-* services
├── logs.sh             # journalctl tail across services
├── VERSION             # semver string
└── installer/
    ├── lib/            # sourced by install.sh — one module per concern
    ├── systemd/        # service unit templates
    ├── nginx/          # site config template
    └── migrations/     # ordered SQL migrations
```

## Helper scripts

| Script         | Purpose                                                    |
|----------------|------------------------------------------------------------|
| `install.sh`   | Preflight checks, OS deps, system user, base directories.  |
| `update.sh`    | Pull latest code and re-run installer (idempotent).        |
| `uninstall.sh` | Stop services, remove user/dirs (with confirmation).       |
| `status.sh`    | One-shot status of every `aipanel-*` systemd unit.         |
| `logs.sh`      | `journalctl -fu` across aipanel units (Ctrl-C to exit).    |

## Development

This skeleton intentionally stops short of installing application services.
Future commits will populate `installer/systemd/`, `installer/nginx/`, and the
remaining migrations. Each addition is gated behind its own preflight so
re-running `install.sh` continues to be safe.
