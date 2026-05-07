# Testing & training the panel

There are three ways to run the panel — pick the one that matches what
you want to validate:

| Mode | Backs onto | Use when |
|------|-----------|----------|
| **Mock** | a Node script with hard-coded data | clicking through the UI on Windows; no Docker, no Linux |
| **Real local** | Postgres + Redis + MinIO in Docker | exercising auth, audit log, RAG, scenario persistence on real schema |
| **Production** | the full Linux install (`install.sh`) | actually placing calls — needs ViciDial, vLLM, faster-whisper, GPU |

---

## Mode 1 — Mock (zero setup)

Already wired up. Two terminals:

```powershell
# Terminal A — mock backend (port 8800)
cd D:\aipanel
node mock-backend.mjs

# Terminal B — Vite (port 8055)
cd D:\aipanel\panel\frontend
npm run dev
```

Open <http://127.0.0.1:8055/login>. **Sign in with any email + any
non-empty password** — the mock accepts everything and always returns
the seed admin user. Mock seeds:

- 3 agents (Solar, Insurance, Generic) with personas/scripts/scenarios
- 1 ViciDial server, 3 deployments, 28 calls (the first 2 are "live"
  so you can try the live-call Transfer button)
- 4 voices, 2 knowledge bases, 1 campaign with metrics + few-shot pool
- 3 users, 4 audit log entries, 5 sales methodologies

Every page is wired and works. Pages with state-changing dialogs:

- **Agents**: `New agent` creates a draft you can edit (Persona/Voice/
  Script/Scenarios/KB tabs)
- **Voices**: `Clone voice` (record from mic OR upload) — recorder
  needs `https://` or `localhost` for `getUserMedia()`
- **Knowledge bases**: `New KB` + per-KB upload + retrieval test
- **Campaigns**: `New campaign` (pick a methodology) + `Refresh few-shot`
- **ViciDial servers**: `Add server` + `Test connection`
- **Deployments**: `New deployment` (binds an agent + ViciDial seat)
- **Call detail** (live calls only): `Transfer to ingroup`,
  `Test call` from agent detail
- **Users**: invite / change role / remove (admin only)
- **Audit log**: filter by action prefix

What mock mode **cannot** validate: real JWT lifecycle, password
hashing, audit-log persistence across reloads, RAG retrieval against
pgvector, scenario_tree stored in JSONB, real ViciDial integration.

---

## Mode 2 — Real local (needs Docker Desktop)

The system uses Postgres-only features (pgvector, JSONB, partitioned
tables, ENUM types) so SQLite isn't a viable swap. You need Docker.

### One-time install

1. Install **Docker Desktop for Windows** (<https://docs.docker.com/desktop/install/windows-install/>)
   and start it (the whale icon in the system tray must be green).
2. Confirm Docker is on PATH from PowerShell:
   ```powershell
   docker --version
   docker compose version
   ```

### Bring up the stack

```powershell
cd D:\aipanel
.\dev\start.ps1
```

What happens:

1. `docker compose up -d` brings up Postgres (with pgvector), Redis,
   MinIO on `127.0.0.1` only.
2. The Postgres init script applies `installer/migrations/*.sql` on
   first boot.
3. `panel\backend\.venv` is created and the backend is `pip install -e`
   the first time only.
4. **Admin user `admin@local` / `changeme` is bootstrapped** if the
   `users` table is empty.
5. uvicorn starts on `http://127.0.0.1:8000` with `--reload`.

In a second terminal point Vite at the real backend:

```powershell
cd D:\aipanel\panel\frontend
$env:VITE_API_TARGET="http://127.0.0.1:8000"
npm run dev
```

Sign in at <http://127.0.0.1:8055/login> with `admin@local` /
`changeme`. From here the Users page can invite real users; their
password hashes go into Postgres.

### Add another admin

```powershell
$env:AIPANEL_CONF    = "D:\aipanel\dev\aipanel.dev.conf"
$env:AIPANEL_SECRETS = "D:\aipanel\dev\secrets.dev.env"
& D:\aipanel\panel\backend\.venv\Scripts\python.exe `
    D:\aipanel\dev\bootstrap_admin.py `
    --tenant Default --email you@example.com --password 'pick-something-strong'
```

### Tear down

```powershell
docker compose -f dev\docker-compose.yml down       # stops, keeps data
docker compose -f dev\docker-compose.yml down -v    # also drops Postgres + MinIO volumes
```

What real-local mode **cannot** validate: actually placing calls
(needs PJSIP + ViciDial + a softphone), LLM/STT/TTS quality (those
servers need GPU + huge model downloads), end-to-end conversation
loops.

---

## Mode 3 — Production (Linux + ViciDial)

This is what `install.sh` is for. On Ubuntu 22.04 with NVIDIA + a
ViciDial 2.14 dialler reachable on the network:

```bash
sudo ./install.sh
sudo ./scripts/bootstrap_admin.sh \
    --tenant=Acme --email=ops@acme.com --password='change-me-strong'
```

Then you can:

- Add the ViciDial server through the panel (one entry per dialler)
- Create an agent + clone a voice
- Create a deployment that binds the agent to a ViciDial seat
- Start the deployment — Session Manager logs in via Playwright and
  stays in until you stop it
- Inbound calls hit PJSIP, get transcribed, run through the LLM,
  responses are TTS'd back, calls get disposed in ViciDial
- Operator can mid-call **Transfer to ingroup** from the panel

Re-read `installer/README.md` for the install flow, GPU requirements,
and ViciDial side configuration.

---

## What's NOT in the box

- A softphone — recommend [Zoiper](https://www.zoiper.com/) for
  manual SIP testing
- A ViciDial install — get one from <https://vicidial.com> or build
  from source
- Trained voice samples — the F5 TTS server can clone from a 30-60s
  reference clip; feed it through the **Voices → Clone voice** dialog
- Tuned LLM weights — defaults to `Qwen/Qwen2.5-14B-Instruct-AWQ`
  which is good out-of-box for English sales calls; swap via the
  `[llm].model` setting in `aipanel.conf`
