# Local-dev backend

This folder lets you run the **real** FastAPI backend on your laptop
against a real Postgres + Redis + MinIO — no Linux VM, no production
secrets, no `install.sh` required. Use it when the mock backend
(`mock-backend.mjs`) isn't faithful enough — for example, when working
on auth, JWT denylist, audit log, RAG / pgvector, or anything that
touches the actual database.

## What you need

- Docker Desktop (running)
- Python 3.11+
- Node 20+ (for the frontend, same as before)

## Bring it up

```powershell
# from the repo root
.\dev\start.ps1
```

What `start.ps1` does:

1. `docker compose -f dev/docker-compose.yml up -d` — Postgres (with
   pgvector), Redis, MinIO. The Postgres container auto-applies the
   SQL migrations from `installer/migrations/` on first boot.
2. Waits for Postgres to be reachable.
3. Creates `panel/backend/.venv` and `pip install -e panel/backend`
   the first time only.
4. Bootstraps a `Default` tenant + `admin@local` / `changeme` admin if
   the `users` table is empty.
5. Starts uvicorn on `http://127.0.0.1:8000` with `--reload`.

In a second terminal, point Vite at the real backend:

```powershell
cd panel/frontend
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm run dev
```

(or just edit `panel/frontend/vite.config.ts` to proxy `/api` to
`8000` instead of `8800`).

## Sign in

- URL: <http://127.0.0.1:8055/login>
- Email: `admin@local`
- Password: `changeme`

Re-run `dev/bootstrap_admin.py --email …` to add more users, or invite
them through the panel after first login.

## Tear down

```powershell
docker compose -f dev/docker-compose.yml down       # stop containers, keep data
docker compose -f dev/docker-compose.yml down -v    # also drop the data volumes
```

`-v` is the right move when you want to re-apply migrations from
scratch — Postgres only runs `db-init/` on a fresh data volume.

## Files

- `docker-compose.yml` — Postgres+Redis+MinIO containers, all on
  `127.0.0.1` only.
- `db-init/00-run-migrations.sh` — runs `installer/migrations/*.sql`
  inside the Postgres container on first boot.
- `aipanel.dev.conf` — the dev variant of `/etc/aipanel/aipanel.conf`,
  pointing at the local containers. The backend picks it up via
  `AIPANEL_CONF`.
- `secrets.dev.env` — passwords + JWT key + Fernet key, matching the
  values baked into `docker-compose.yml`. The backend loads it via
  `AIPANEL_SECRETS`. **Do not use these values anywhere other than
  the local docker-compose.**
- `bootstrap_admin.py` — pure-Python equivalent of
  `scripts/bootstrap_admin.sh`. Creates the first tenant + admin
  without needing the bash tooling.
- `start.ps1` — Windows convenience launcher (see above).

## Why MinIO too?

The recording-download endpoint signs URLs with the Minio SDK. If you
never plan to test that path, you can comment out the `minio` service
in `docker-compose.yml` — calls without a `recording_path` work fine
without it.
