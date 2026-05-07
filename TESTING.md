# Testing & training the panel

Three ways to run the panel — pick the one that matches what you want:

| Mode | Backs onto | Use when |
|------|-----------|----------|
| **Mock** | tiny Node script with persistent JSON state | exploring + clicking through the UI on Windows; no Docker needed |
| **Real local** | Postgres + Redis + MinIO in Docker | exercising auth, audit log, RAG, real schema |
| **Production** | the full Linux install (`install.sh`) | actually placing calls — needs ViciDial, vLLM, faster-whisper, GPU |

---

## Admin credentials

### Mock mode (default — what's running on your laptop)

The mock backend accepts **any email + any non-empty password**. Whatever
email you sign in with, the seeded user looks like this in the UI:

```
email:    admin@aipanel.local
role:     admin
tenant:   Default
```

So: just use **`admin@aipanel.local`** and any password (e.g. `admin`).
Role checks pass because the mock always stamps you as admin.

### Real local mode (Docker)

`dev/start.ps1` bootstraps the first admin if the `users` table is empty:

```
email:     admin@local
password:  changeme
```

Change it after first login from **System → Users**, or seed your own:

```powershell
$env:AIPANEL_CONF    = "D:\aipanel\dev\aipanel.dev.conf"
$env:AIPANEL_SECRETS = "D:\aipanel\dev\secrets.dev.env"
& D:\aipanel\panel\backend\.venv\Scripts\python.exe `
    D:\aipanel\dev\bootstrap_admin.py `
    --tenant Default --email you@example.com --password 'pick-something-strong'
```

### Production

```bash
sudo ./scripts/bootstrap_admin.sh \
    --tenant=Acme --email=ops@acme.com --password='change-me-strong'
```

---

## Mode 1 — Mock (what you're using now)

```powershell
# Terminal A — mock backend (port 8800)
cd D:\aipanel
node mock-backend.mjs

# Terminal B — Vite (port 8055)
cd D:\aipanel\panel\frontend
npm run dev
```

Open <http://127.0.0.1:8055/login>. **All seed data is empty** — you add
your own real entries from the start. Everything you add persists to
`mock-state.json` next to `mock-backend.mjs`, so restarts don't lose
your work. Delete `mock-state.json` to wipe and start fresh.

### The bring-up flow

The order matters because each step unlocks dropdowns in the next:

1. **System → Users** — invite your team (admin / operator / viewer)
2. **Knowledge bases** — upload product PDFs, FAQs (optional)
3. **Voices** — clone a voice from a 30-60s mic recording (optional)
4. **Campaigns** — create a campaign with a sales methodology
   (consultative / SPIN / BANT / MEDDPICC / value-based / custom)
5. **Agents** — `New agent`, fill in Persona / Voice / Script /
   Scenarios / Knowledge base. **Save**, then **Promote to ready**.
   Use the **Training** tab to upload real call recordings.
6. **ViciDial servers** — register your dialler (web URL + AMI creds)
7. **Deployments** — `New deployment`. The form pulls available
   campaigns + ingroups straight from the ViciDial server you pick —
   no need to type codes by hand. Pair it with one of your agents.
8. Open the deployment → **Start**. Once Session Manager is running
   (real backend), the AI agent logs into ViciDial and starts handling
   inbound calls.

### Training agents from real conversations

**Agents → any agent → Training tab → Upload**

Drop a recording (WAV / MP3 / M4A / OPUS / OGG / FLAC) of a real
conversation — ideally one of your top human agents handling a tough
call. The backend transcribes it (faster-whisper large-v3) and feeds
the resulting `{user, agent}` pairs into this agent's few-shot pool.

The LLM sees those pairs as in-context examples on every call, so it
learns tone, pacing, and the moves that actually convert. Upload as
many as you have — more good examples = better mimicry.

That's it. No transcript-marking, no typed examples — just upload
audio and let transcription do the work.

---

## Mode 2 — Real local (needs Docker Desktop)

The system uses Postgres-only features (pgvector, JSONB, partitioned
tables, ENUM types) so SQLite isn't an option. You need Docker.

### One-time install

1. Install **Docker Desktop for Windows**
   (<https://docs.docker.com/desktop/install/windows-install/>) and
   make sure the whale icon in the system tray is green.
2. Confirm from PowerShell:
   ```powershell
   docker --version
   docker compose version
   ```

### Bring it up

```powershell
cd D:\aipanel
.\dev\start.ps1
```

What happens:

1. `docker compose up -d` — Postgres (with pgvector), Redis, MinIO
2. Postgres init script applies `installer/migrations/*.sql`
3. `panel\backend\.venv` is created + `pip install -e` (first run only)
4. Bootstraps `admin@local` / `changeme`
5. uvicorn starts on `http://127.0.0.1:8000` with `--reload`

In a second terminal point Vite at the real backend:

```powershell
cd D:\aipanel\panel\frontend
$env:VITE_API_TARGET="http://127.0.0.1:8000"
npm run dev
```

Sign in at <http://127.0.0.1:8055/login> with **`admin@local` /
`changeme`**.

### Tear down

```powershell
docker compose -f dev\docker-compose.yml down       # stops, keeps data
docker compose -f dev\docker-compose.yml down -v    # also drops volumes
```

---

## Mode 3 — Production (Linux + ViciDial)

On Ubuntu 22.04 with NVIDIA + a ViciDial 2.14 dialler reachable on
the network:

```bash
sudo ./install.sh
sudo ./scripts/bootstrap_admin.sh \
    --tenant=Acme --email=ops@acme.com --password='change-me-strong'
```

Then bring up the platform through the UI exactly as in Mode 1's
bring-up flow above. Real ViciDial returns real campaigns + ingroups in
the discovery dropdowns. Real recordings get real transcripts. Real
calls hit PJSIP, get transcribed by faster-whisper, run through vLLM,
TTS'd back, and disposed in ViciDial.

---

## What's NOT in the box

- A softphone — recommend [Zoiper](https://www.zoiper.com/) for SIP testing
- A ViciDial install — get one from <https://vicidial.com> or build from source
- Trained voice samples — clone from a 30-60s reference clip via
  **Voices → Clone voice**
- Tuned LLM weights — defaults to `Qwen/Qwen2.5-14B-Instruct-AWQ`;
  swap via `[llm].model` in `aipanel.conf`
