// mock-backend.mjs — local stand-in for the FastAPI backend.
//
// What it gives you:
//   - Every endpoint the SPA calls, no Postgres / Redis required
//   - Persistent state in mock-state.json (survives restarts)
//   - Empty seeds — you add your own real data
//   - Synthetic ViciDial discovery (campaigns + ingroups) so the
//     "New deployment" form behaves like the real backend would
//
// Run:   node mock-backend.mjs
// Port:  127.0.0.1:8800  (Vite proxies /api → here)
// Login: any email + any non-empty password.
//        The seeded admin is admin@aipanel.local — see "Admin" below.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const PORT = 8800;
const TENANT_ID = "11111111-1111-1111-1111-111111111111";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_FILE = path.join(__dirname, "mock-state.json");

// ---------------------------------------------------------------------------
// Admin user — local-dev login.
// Mock auth accepts ANY email + ANY non-empty password and stamps the
// signed-in user with `admin@aipanel.local` so role checks pass.
// ---------------------------------------------------------------------------
const USER = {
  id: "22222222-2222-2222-2222-222222222222",
  tenant_id: TENANT_ID,
  email: "admin@aipanel.local",
  role: "admin",
  created_at: "2026-01-15T10:00:00Z",
};

// ---------------------------------------------------------------------------
// Persistent state — JSON file next to this script.
// Loaded on boot, written after every mutation. Empty by default so the
// operator works with their own real entries from the start.
// ---------------------------------------------------------------------------
function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return null;
  }
}
function defaultState() {
  return {
    agents: [],
    voices: [],
    kbs: [],
    campaigns: [],
    vici_servers: [],
    deployments: [],
    calls: [],
    users: [USER],
    audit: [],
    audit_next_id: 1,
    // Synthetic ViciDial discovery results, keyed by vici_server.id.
    // Populated when a server is added; the operator can then pick a
    // campaign + ingroups when creating a deployment without typing IDs.
    vici_catalog: {},
    // Per-agent training recordings — operator-uploaded audio that the
    // worker pipeline transcribes + adds to the few-shot pool.
    training_recordings: {},   // agent_id → [recording, ...]
    // Per-agent saved chat training — exchanges the operator thumbed-up
    // from the in-editor chat sandbox.
    training_chats: {},        // agent_id → [{user, agent, saved_at}, ...]
  };
}

const state = loadState() || defaultState();

// Migrate old shape on first boot: add fields that didn't exist before.
const _defaults = defaultState();
for (const k of Object.keys(_defaults)) {
  if (state[k] === undefined) state[k] = _defaults[k];
}

function persist() {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (e) {
    console.error("[mock-backend] persist failed:", e.message);
  }
}

function pushAudit(action, payload = {}, target_type = null, target_id = null) {
  state.audit.unshift({
    id: state.audit_next_id++,
    ts: new Date().toISOString(),
    user_id: USER.id,
    action, target_type, target_id, payload,
  });
  persist();
}

// ---------------------------------------------------------------------------
// Reference data — always available, not user-edited.
// ---------------------------------------------------------------------------

const METHODOLOGIES = [
  {
    key: "consultative",
    name: "Consultative selling",
    tagline: "Discover their context first. Propose only when their problem is clear. Tailor every recommendation.",
    when_to_use: "Default for most outbound calls.",
    system_prompt: "CONSULTATIVE SELLING — TRUSTED-ADVISOR FRAMING\nYou are calling as a consultant, not a salesperson.\n\nCORE STANCE\n- Curiosity over conviction.\n- Patience over pace. A great consultative call is 70% them talking.\n\nTHE RHYTHM\n1. Earn the right to ask (one warm sentence about why you're calling).\n2. Ask one good open-ended question.\n3. Listen. Reflect back what you heard.\n4. Ask the next question based on their answer, not your script.\n5. Only after 3-4 substantive exchanges, offer a tailored recommendation.\n6. Confirm the recommendation lands before pitching next steps.",
    stages: [
      { name: "Earn the right", goal: "One-sentence warm opener.", success_markers: ["customer_engaged"] },
      { name: "Discover", goal: "3-4 open-ended questions, real listening.", success_markers: ["context_established"] },
      { name: "Recommend", goal: "Tailored next step.", success_markers: ["recommendation_landed"] },
      { name: "Confirm", goal: "Check the recommendation lands.", success_markers: ["confirmation_received"] },
    ],
    priority_signals: ["Yeah, that's basically it", "Tell me more"],
    common_objections: { "Just send me the info.": "Reframe to a question." },
  },
  {
    key: "spin",
    name: "SPIN selling",
    tagline: "Ask Situation, Problem, Implication, Need-payoff questions in order. The customer sells themselves.",
    when_to_use: "Best when the customer doesn't yet know they have a problem you can solve.",
    system_prompt: "SPIN SELLING\nFour question types in order. Make the customer state the value of your solution themselves before you ever mention it.\n\nSITUATION (gather facts) — at most two.\nPROBLEM (find pain) — listen for irritation.\nIMPLICATION (amplify pain) — most important step.\nNEED-PAYOFF (let them sell themselves) — get them to state value in their own words.\n\nNEVER skip phases. ONE question at a time. Use silence as a tool.",
    stages: [
      { name: "Situation", goal: "Confirm basics.", success_markers: ["confirmed_current_tool"] },
      { name: "Problem", goal: "Surface dissatisfaction.", success_markers: ["pain_admitted"] },
      { name: "Implication", goal: "Amplify cost of problem.", success_markers: ["cost_named"] },
      { name: "Need-payoff", goal: "Customer states value.", success_markers: ["value_stated"] },
    ],
    priority_signals: ["I hate that we have to…", "We waste so much time on…"],
    common_objections: { "We're already using X.": "Restate the problem you suspect they have." },
  },
  {
    key: "bant",
    name: "BANT qualification",
    tagline: "Confirm Budget, Authority, Need, Timeline before advancing the deal.",
    when_to_use: "Best as a qualification filter at the top of a high-volume pipeline.",
    system_prompt: "BANT QUALIFICATION\nDetermine politely whether this prospect is worth advancing.\n\nB — BUDGET: Frame around current spend.\nA — AUTHORITY: Decision maker, or path to one?\nN — NEED: Real and important right now?\nT — TIMELINE: Specific date or event-driven deadline.\n\nWeave BANT into a normal conversation. Never advance to a transfer unless you have ALL FOUR.",
    stages: [
      { name: "Budget", goal: "Confirm spend range.", success_markers: ["budget_range_stated"] },
      { name: "Authority", goal: "Identify decision path.", success_markers: ["decision_maker_identified"] },
      { name: "Need", goal: "Concrete pain + urgency.", success_markers: ["pain_with_consequence"] },
      { name: "Timeline", goal: "Date or event-driven deadline.", success_markers: ["timeline_stated"] },
    ],
    priority_signals: ["We've allocated $X for this", "I make these calls"],
    common_objections: { "We don't have a budget.": "Reframe to cost of inaction." },
  },
  {
    key: "meddpicc",
    name: "MEDDPICC",
    tagline: "Surface Metrics, Economic buyer, Decision criteria + process, Paper process, Identified pain, Champion, Competition.",
    when_to_use: "Best for enterprise / multi-stakeholder deals with $50k+ ACV.",
    system_prompt: "MEDDPICC — ENTERPRISE QUALIFICATION\n\nM — METRICS — measurable success criteria\nE — ECONOMIC BUYER — who controls the budget\nD — DECISION CRITERIA — explicit list to evaluate against\nD — DECISION PROCESS — every step from demo to signature\nP — PAPER PROCESS — procurement / legal / security\nI — IDENTIFIED PAIN — measurable consequence of inaction\nC — CHAMPION — internal advocate\nC — COMPETITION — including 'doing nothing'\n\nQualification, not interrogation. Surface 2-3 per call.",
    stages: [
      { name: "Discover", goal: "Identify pain + metrics.", success_markers: ["pain_identified"] },
      { name: "Map", goal: "Decision process + economic buyer.", success_markers: ["economic_buyer_named"] },
      { name: "Validate", goal: "Criteria + competition.", success_markers: ["criteria_listed"] },
      { name: "Champion", goal: "Identify champion.", success_markers: ["champion_identified"] },
    ],
    priority_signals: ["Our CFO would need to sign off", "The criteria we care about are…"],
    common_objections: {},
  },
  {
    key: "value_based",
    name: "Value-based selling",
    tagline: "Frame everything in measurable customer outcomes — time saved, dollars made, risk avoided. Never lead with features.",
    when_to_use: "Best for products with quantifiable ROI.",
    system_prompt: "VALUE-BASED SELLING — OUTCOMES, NOT FEATURES\n\nFeature → Benefit → measurable Outcome.\n\nALWAYS QUANTIFY\nTime saved → hours/week. Money saved → dollars/month.\n\nDO THE MATH OUT LOUD. Numbers spoken aloud get challenged.\n\nNEVER quote a feature without a benefit. NEVER use 'robust', 'best-in-class', 'leverage'.",
    stages: [
      { name: "Inputs", goal: "Gather numbers for ROI.", success_markers: ["volume_known"] },
      { name: "Quantify", goal: "State value in dollars.", success_markers: ["value_quantified"] },
      { name: "Validate", goal: "Customer confirms math.", success_markers: ["math_acknowledged"] },
      { name: "Anchor", goal: "Tie price to value.", success_markers: ["price_to_value_stated"] },
    ],
    priority_signals: ["That's actually a lot of money", "If that's true, this is a no-brainer"],
    common_objections: { "It's too expensive.": "Re-anchor to value." },
  },
  {
    key: "custom",
    name: "Custom",
    tagline: "Follow the campaign's script verbatim. No additional methodology scaffolding.",
    when_to_use: "When the campaign has a hand-tuned script.",
    system_prompt: "CUSTOM CONVERSATION PATTERN\nFollow the campaign's script faithfully. Adapt only when the customer's response makes the next scripted line nonsensical.",
    stages: [
      { name: "Script", goal: "Walk through the scripted conversation.", success_markers: ["script_completed"] },
    ],
    priority_signals: [],
    common_objections: {},
  },
];

// ---------------------------------------------------------------------------
// Synthetic ViciDial discovery — when a server is added, we cache a list
// of plausible campaigns + ingroups for it. The "New deployment" form
// reads from these instead of asking the operator to type IDs.
// In the real backend, this lookup goes through session-mgr → ViciDial
// (campaigns table + vicidial_inbound_groups table).
// ---------------------------------------------------------------------------

function defaultViciCatalog() {
  return {
    // Edit these in the panel as you bring up real ViciDial campaigns;
    // for now they're sensible defaults so the dropdowns aren't empty.
    campaigns: [
      { code: "TESTCAMP",  name: "Test campaign" },
    ],
    ingroups: [
      { code: "SALES",     name: "Sales (general)" },
      { code: "SUPPORT",   name: "Customer support" },
      { code: "BILLING",   name: "Billing" },
    ],
  };
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

function json(res, body, status = 200) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(JSON.stringify(body));
}

function pageOf(items, query) {
  const limit = Number(query.get("limit") ?? 50);
  const offset = Number(query.get("offset") ?? 0);
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

const routes = [
  // ---------- Auth ----------
  ["POST", /^\/api\/v1\/auth\/login$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.email || !body?.password) return json(res, { detail: "invalid credentials" }, 401);
    const tokens = {
      access_token: "mock-access-token",
      refresh_token: "mock-refresh-token",
      access_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
      refresh_expires_at: new Date(Date.now() + 7 * 24 * 60 * 60_000).toISOString(),
      token_type: "bearer",
    };
    json(res, { tokens, user: { ...USER, email: body.email } });
  }],
  ["POST", /^\/api\/v1\/auth\/refresh$/, async (_req, res) => json(res, {
    access_token: "mock-access-token",
    refresh_token: "mock-refresh-token",
    access_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    refresh_expires_at: new Date(Date.now() + 7 * 24 * 60 * 60_000).toISOString(),
    token_type: "bearer",
  })],
  ["POST", /^\/api\/v1\/auth\/logout$/, (_req, res) => json(res, { ok: true })],
  ["GET",  /^\/api\/v1\/auth\/me$/, (_req, res) => json(res, USER)],

  // ---------- Agents ----------
  ["GET", /^\/api\/v1\/agents$/, (_req, res, _m, q) => json(res, pageOf(state.agents, q))],
  ["GET", /^\/api\/v1\/agents\/([^/]+)$/, (_req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    json(res, a);
  }],
  ["POST", /^\/api\/v1\/agents$/, async (req, res) => {
    const body = await readJson(req);
    const a = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      name: body?.name || "Untitled agent",
      campaign_id: body?.campaign_id || null,
      persona: body?.persona || { name: "", age_range: "", gender: "neutral", accent: "", backstory: "" },
      script: body?.script || { opening_variants: [""], sections: [], closing: "", objections: [] },
      scenario_tree: body?.scenario_tree || { rules: [] },
      training_script: body?.training_script || "",
      voice_id: body?.voice_id || null,
      language: body?.language || "en",
      kb_collection_id: body?.kb_collection_id || null,
      status: "draft",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    state.agents.unshift(a);
    pushAudit("agent.create", { name: a.name }, "agent", a.id);
    json(res, a, 201);
  }],
  ["PATCH", /^\/api\/v1\/agents\/([^/]+)$/, async (req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    const body = await readJson(req);
    Object.assign(a, body, { updated_at: new Date().toISOString() });
    pushAudit("agent.update", body, "agent", a.id);
    persist();
    json(res, a);
  }],
  ["DELETE", /^\/api\/v1\/agents\/([^/]+)$/, (_req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    a.status = "archived";
    pushAudit("agent.archive", {}, "agent", a.id);
    persist();
    json(res, { ok: true });
  }],
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/duplicate$/, (_req, res, m) => {
    const src = state.agents.find(x => x.id === m[1]);
    if (!src) return json(res, { detail: "agent not found" }, 404);
    const dup = { ...src, id: randomUUID(), name: `${src.name} (copy)`, status: "draft" };
    state.agents.unshift(dup);
    pushAudit("agent.duplicate", { source_id: src.id }, "agent", dup.id);
    json(res, dup, 201);
  }],
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/promote$/, (_req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    a.status = "ready";
    pushAudit("agent.promote", {}, "agent", a.id);
    json(res, a);
  }],
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/test-call$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.phone_number) return json(res, { detail: "phone_number required" }, 422);
    json(res, { ok: true, dialed: body.phone_number });
  }],

  // ---------- Training: audio recordings (operator-uploaded) ----------
  ["GET", /^\/api\/v1\/agents\/([^/]+)\/training-recordings$/, (_req, res, m) => {
    json(res, state.training_recordings[m[1]] ?? []);
  }],
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/training-recordings$/, async (req, res, m) => {
    // multipart: file=<audio>, label=<optional text>
    const ct = req.headers["content-type"] || "";
    if (!ct.startsWith("multipart/form-data")) {
      return json(res, { detail: "multipart upload required" }, 415);
    }
    const { fields, file } = await readMultipart(req);
    if (!file) return json(res, { detail: "file part required" }, 422);
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    const entry = {
      id: randomUUID(),
      agent_id: m[1],
      filename: file.filename || "recording.wav",
      content_type: file.contentType || "application/octet-stream",
      size_bytes: file.size,
      label: fields.label || "",
      // In real backend this becomes an s3:// URL after MinIO upload, then
      // a transcription job extracts {user, agent} pairs into the agent's
      // few-shot pool. Mock just records the metadata.
      status: "queued",       // queued → transcribing → ready | error
      transcript: null,
      uploaded_at: new Date().toISOString(),
      uploaded_by: USER.id,
    };
    state.training_recordings[m[1]] = state.training_recordings[m[1]] || [];
    state.training_recordings[m[1]].unshift(entry);
    pushAudit("agent.training_recording_upload",
              { filename: entry.filename, size: entry.size_bytes },
              "agent", m[1]);
    // Pretend the transcription completes after a beat.
    setTimeout(() => {
      entry.status = "ready";
      entry.transcript = "[mock transcript — real backend runs faster-whisper here]";
      persist();
    }, 2000);
    json(res, entry, 201);
  }],
  ["DELETE", /^\/api\/v1\/agents\/([^/]+)\/training-recordings\/([^/]+)$/, (_req, res, m) => {
    const list = state.training_recordings[m[1]] || [];
    const before = list.length;
    state.training_recordings[m[1]] = list.filter(x => x.id !== m[2]);
    if (state.training_recordings[m[1]].length === before) {
      return json(res, { detail: "recording not found" }, 404);
    }
    pushAudit("agent.training_recording_delete", { recording_id: m[2] }, "agent", m[1]);
    persist();
    json(res, { ok: true });
  }],

  // ---------- Training: script (single text blob) ----------
  // The operator pastes the whole script as one block here. The worker
  // reads it as system context. This is the simple alternative to the
  // Script tab's structured Openings/Sections/Closing fields.
  ["GET", /^\/api\/v1\/agents\/([^/]+)\/training-script$/, (_req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    json(res, { script: a.training_script || "" });
  }],
  ["PUT", /^\/api\/v1\/agents\/([^/]+)\/training-script$/, async (req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    const body = await readJson(req);
    a.training_script = (body?.script || "").trim();
    a.updated_at = new Date().toISOString();
    pushAudit("agent.training_script_update",
              { length: a.training_script.length }, "agent", a.id);
    persist();
    json(res, { script: a.training_script });
  }],

  // ---------- Training: chat sandbox ----------
  // The operator chats with the agent like a real customer would. The
  // mock returns canned responses based on what's in the script. The
  // real backend routes through vLLM with the agent's full prompt.
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/chat$/, async (req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    const body = await readJson(req);
    const message = (body?.message || "").trim();
    if (!message) return json(res, { detail: "message required" }, 422);
    json(res, { reply: mockReply(a, message) });
  }],

  // Saved chat exchanges that count toward training.
  ["GET", /^\/api\/v1\/agents\/([^/]+)\/training-chats$/, (_req, res, m) => {
    json(res, state.training_chats[m[1]] ?? []);
  }],
  ["POST", /^\/api\/v1\/agents\/([^/]+)\/training-chats$/, async (req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    const body = await readJson(req);
    if (!body?.user || !body?.agent) {
      return json(res, { detail: "user and agent required" }, 422);
    }
    state.training_chats[m[1]] = state.training_chats[m[1]] || [];
    const entry = {
      id: randomUUID(),
      user: body.user, agent: body.agent,
      saved_at: new Date().toISOString(),
    };
    state.training_chats[m[1]].unshift(entry);
    pushAudit("agent.training_chat_save", {}, "agent", a.id);
    persist();
    json(res, entry, 201);
  }],
  ["DELETE", /^\/api\/v1\/agents\/([^/]+)\/training-chats\/([^/]+)$/, (_req, res, m) => {
    const list = state.training_chats[m[1]] || [];
    const before = list.length;
    state.training_chats[m[1]] = list.filter(x => x.id !== m[2]);
    if (state.training_chats[m[1]].length === before) {
      return json(res, { detail: "training chat not found" }, 404);
    }
    persist();
    json(res, { ok: true });
  }],

  // ---------- Capability score — how trained is this agent? ----------
  // Deterministic, transparent breakdown so the operator knows exactly
  // what to do next to bump the number up.
  ["GET", /^\/api\/v1\/agents\/([^/]+)\/capability$/, (_req, res, m) => {
    const a = state.agents.find(x => x.id === m[1]);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    json(res, computeCapability(a));
  }],

  // ---------- Voices ----------
  ["GET", /^\/api\/v1\/voices$/, (_req, res, _m, q) => json(res, pageOf(state.voices, q))],
  ["GET", /^\/api\/v1\/voices\/([^/]+)$/, (_req, res, m) => {
    const v = state.voices.find(x => x.id === m[1]);
    if (!v) return json(res, { detail: "voice not found" }, 404);
    json(res, v);
  }],
  ["POST", /^\/api\/v1\/voices$/, async (req, res) => {
    // Multipart accept — the upload payload includes name + audio file.
    const ct = req.headers["content-type"] || "";
    let name = "Uploaded voice";
    let ref_text = "";
    if (ct.startsWith("multipart/form-data")) {
      const { fields } = await readMultipart(req);
      name = fields.name || name;
      ref_text = fields.ref_text || "";
    } else {
      const body = await readJson(req);
      name = body?.name || name;
      ref_text = body?.ref_text || "";
    }
    const v = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      name,
      ref_text,
      sample_path: `mock://voices/${randomUUID()}/ref.wav`,
      embedding_path: null,
      status: "training",
      created_at: new Date().toISOString(),
    };
    state.voices.unshift(v);
    pushAudit("voice.create", { name }, "voice", v.id);
    setTimeout(() => { v.status = "ready"; persist(); }, 2500);
    json(res, v, 202);
  }],
  ["DELETE", /^\/api\/v1\/voices\/([^/]+)$/, (_req, res, m) => {
    const before = state.voices.length;
    state.voices = state.voices.filter(v => v.id !== m[1]);
    if (state.voices.length === before) return json(res, { detail: "voice not found" }, 404);
    pushAudit("voice.delete", {}, "voice", m[1]);
    persist();
    json(res, { ok: true });
  }],

  // ---------- Knowledge bases ----------
  ["GET", /^\/api\/v1\/kb$/, (_req, res, _m, q) => json(res, pageOf(state.kbs, q))],
  ["GET", /^\/api\/v1\/kb\/([^/]+)$/, (_req, res, m) => {
    const k = state.kbs.find(x => x.id === m[1]);
    if (!k) return json(res, { detail: "kb not found" }, 404);
    json(res, k);
  }],
  ["POST", /^\/api\/v1\/kb$/, async (req, res) => {
    const body = await readJson(req);
    const k = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      name: body?.name || "Untitled KB",
      description: body?.description || "",
      embedding_model: body?.embedding_model || "BAAI/bge-m3",
      created_at: new Date().toISOString(),
    };
    state.kbs.unshift(k);
    pushAudit("kb.create", { name: k.name }, "kb", k.id);
    json(res, k, 201);
  }],
  ["GET", /^\/api\/v1\/kb\/([^/]+)\/documents$/, (_req, res) => json(res, [])],
  ["POST", /^\/api\/v1\/kb\/([^/]+)\/documents$/, async (_req, res) => {
    json(res, { id: randomUUID(), filename: "doc.pdf", chunk_count: 0,
                status: "processing", created_at: new Date().toISOString() }, 202);
  }],
  ["DELETE", /^\/api\/v1\/kb\/([^/]+)\/documents\/([^/]+)$/, (_req, res) => json(res, { ok: true })],
  ["POST", /^\/api\/v1\/kb\/([^/]+)\/search$/, (_req, res) => json(res, { hits: [] })],

  // ---------- Methodologies (read-only reference data) ----------
  ["GET", /^\/api\/v1\/methodologies$/, (_req, res) => json(res, METHODOLOGIES)],
  ["GET", /^\/api\/v1\/methodologies\/([^/]+)$/, (_req, res, m) => {
    const meth = METHODOLOGIES.find(x => x.key === m[1]);
    if (!meth) return json(res, { detail: "methodology not found" }, 404);
    json(res, meth);
  }],

  // ---------- Campaigns ----------
  ["GET", /^\/api\/v1\/campaigns$/, (_req, res, _m, q) => json(res, pageOf(state.campaigns, q))],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)$/, (_req, res, m) => {
    const c = state.campaigns.find(x => x.id === m[1]);
    if (!c) return json(res, { detail: "campaign not found" }, 404);
    json(res, c);
  }],
  ["POST", /^\/api\/v1\/campaigns$/, async (req, res) => {
    const body = await readJson(req);
    const c = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      name: body?.name || "Untitled campaign",
      description: body?.objective || "",
      methodology: body?.methodology || "consultative",
      objective: body?.objective || "",
      success_dispos: body?.success_dispos || ["QUAL"],
      persona_template: {},
      script_template: {},
      kb_collection_id: null,
      few_shot_pool: [],
      few_shot_updated_at: null,
      few_shot_count: 0,
      status: "active",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    state.campaigns.unshift(c);
    pushAudit("campaign.create", { name: c.name }, "campaign", c.id);
    json(res, c, 201);
  }],
  ["PATCH", /^\/api\/v1\/campaigns\/([^/]+)$/, async (req, res, m) => {
    const c = state.campaigns.find(x => x.id === m[1]);
    if (!c) return json(res, { detail: "campaign not found" }, 404);
    Object.assign(c, await readJson(req), { updated_at: new Date().toISOString() });
    persist();
    json(res, c);
  }],
  ["DELETE", /^\/api\/v1\/campaigns\/([^/]+)$/, (_req, res, m) => {
    const c = state.campaigns.find(x => x.id === m[1]);
    if (c) c.status = "archived";
    persist();
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)\/metrics$/, (_req, res, m) => json(res, {
    campaign_id: m[1], period_days: 30, total_calls: 0, successful_calls: 0,
    conversion_rate: 0, by_dispo: {}, avg_duration_sec: 0,
  })],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)\/few-shot-pool$/, (_req, res, m) => {
    const c = state.campaigns.find(x => x.id === m[1]);
    json(res, c?.few_shot_pool ?? []);
  }],
  ["POST", /^\/api\/v1\/campaigns\/([^/]+)\/refresh-few-shot$/, (_req, res) => {
    json(res, { ok: true });
  }],

  // ---------- ViciDial servers ----------
  ["GET", /^\/api\/v1\/vicidial-servers$/, (_req, res, _m, q) => json(res, pageOf(state.vici_servers, q))],
  ["POST", /^\/api\/v1\/vicidial-servers$/, async (req, res) => {
    const body = await readJson(req);
    const s = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      name: body?.name || "ViciDial server",
      asterisk_host: body?.asterisk_host || "",
      asterisk_port: body?.asterisk_port || 5038,
      web_url: body?.web_url || "",
      ami_user: body?.ami_user || "",
      web_user_admin: body?.web_user_admin || "",
      created_at: new Date().toISOString(),
    };
    state.vici_servers.unshift(s);
    state.vici_catalog[s.id] = defaultViciCatalog();
    pushAudit("vicidial_server.create", { name: s.name }, "vicidial_server", s.id);
    json(res, s, 201);
  }],
  ["POST", /^\/api\/v1\/vicidial-servers\/([^/]+)\/test-connection$/, (_req, res) => json(res, {
    web_login_ok: true, web_error: null, ami_ok: true, ami_error: null,
  })],
  // Discovery — what campaigns + ingroups does this server expose?
  // The "New deployment" form fills its dropdowns from these.
  ["GET", /^\/api\/v1\/vicidial-servers\/([^/]+)\/campaigns$/, (_req, res, m) => {
    const cat = state.vici_catalog[m[1]];
    if (!cat) return json(res, { detail: "server not found" }, 404);
    json(res, cat.campaigns);
  }],
  ["GET", /^\/api\/v1\/vicidial-servers\/([^/]+)\/ingroups$/, (_req, res, m) => {
    const cat = state.vici_catalog[m[1]];
    if (!cat) return json(res, { detail: "server not found" }, 404);
    json(res, cat.ingroups);
  }],

  // ---------- Deployments ----------
  ["GET", /^\/api\/v1\/deployments$/, (_req, res, _m, q) => json(res, pageOf(state.deployments, q))],
  ["GET", /^\/api\/v1\/deployments\/([^/]+)$/, (_req, res, m) => {
    const d = state.deployments.find(x => x.id === m[1]);
    if (!d) return json(res, { detail: "deployment not found" }, 404);
    json(res, d);
  }],
  ["POST", /^\/api\/v1\/deployments$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.agent_id || !body?.vicidial_server_id || !body?.vici_user) {
      return json(res, { detail: "agent_id, vicidial_server_id, vici_user required" }, 422);
    }
    const d = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      agent_id: body.agent_id,
      vicidial_server_id: body.vicidial_server_id,
      vici_user: body.vici_user,
      phone_login: body.phone_login || "",
      campaign_id: body.campaign_id || "",
      allowed_transfer_ingroups: body.allowed_transfer_ingroups || [],
      dispo_mapping: body.dispo_mapping || {},
      status: "stopped",
      last_heartbeat_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    state.deployments.unshift(d);
    pushAudit("deployment.create", { vici_user: d.vici_user }, "deployment", d.id);
    json(res, d, 201);
  }],
  ["POST", /^\/api\/v1\/deployments\/([^/]+)\/(start|stop|pause)$/, (_req, res, m) => {
    const d = state.deployments.find(x => x.id === m[1]);
    if (!d) return json(res, { detail: "deployment not found" }, 404);
    d.status = m[2] === "start" ? "running"
              : m[2] === "stop" ? "stopped"
              : "running";
    d.last_heartbeat_at = m[2] === "stop" ? null : new Date().toISOString();
    pushAudit(`deployment.${m[2]}`, {}, "deployment", d.id);
    persist();
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/deployments\/([^/]+)\/live$/, sseLiveDeployment],

  // ---------- Calls ----------
  ["GET", /^\/api\/v1\/calls$/, (_req, res, _m, q) => json(res, pageOf(state.calls, q))],
  ["GET", /^\/api\/v1\/calls\/([^/]+)$/, (_req, res, m) => {
    const c = state.calls.find(x => x.id === m[1]);
    if (!c) return json(res, { detail: "call not found" }, 404);
    json(res, c);
  }],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/transcript$/, (_req, res, m) =>
    json(res, { call_id: m[1], turns: [] })],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/events$/, (_req, res) => json(res, [])],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/recording$/, (_req, res) =>
    json(res, { detail: "no recording for this call" }, 404)],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/transfer-options$/, (_req, res, m) => {
    const c = state.calls.find(x => x.id === m[1]);
    if (!c) return json(res, []);
    const dep = state.deployments.find(d => d.id === c.deployment_id);
    const ingroups = dep?.allowed_transfer_ingroups ?? [];
    json(res, ingroups.map(id => ({ id, label: id })));
  }],
  ["POST", /^\/api\/v1\/calls\/([^/]+)\/transfer$/, async (req, res, m) => {
    const body = await readJson(req);
    if (!body?.ingroup_id) return json(res, { detail: "ingroup_id required" }, 422);
    const c = state.calls.find(x => x.id === m[1]);
    if (!c) return json(res, { detail: "call not found" }, 404);
    if (c.ended_at) return json(res, { detail: "call has ended" }, 409);
    c.transfer_target = body.ingroup_id;
    pushAudit("call.transfer", { ingroup_id: body.ingroup_id }, "call", c.id);
    persist();
    json(res, { ok: true });
  }],

  // ---------- Analytics (computed from real state) ----------
  ["GET", /^\/api\/v1\/analytics\/overview$/, (_req, res) => {
    const completed = state.calls.filter(c => c.ended_at);
    const transfers = completed.filter(c => c.transfer_target).length;
    const avgDur = completed.length
      ? Math.round(completed.reduce((s, c) => s + (c.duration_sec || 0), 0) / completed.length)
      : 0;
    const byDispo = {};
    for (const c of completed) {
      if (c.dispo_code) byDispo[c.dispo_code] = (byDispo[c.dispo_code] || 0) + 1;
    }
    json(res, {
      total_calls: completed.length,
      avg_duration_sec: avgDur,
      transfer_rate: completed.length ? +(transfers / completed.length).toFixed(3) : 0,
      dispo_breakdown: byDispo,
      period_start: new Date(Date.now() - 7 * 86400_000).toISOString().slice(0, 10),
      period_end: new Date().toISOString().slice(0, 10),
    });
  }],
  ["GET", /^\/api\/v1\/analytics\/agents$/, (_req, res) => {
    const rows = state.agents.map(a => ({
      agent_id: a.id, agent_name: a.name,
      total_calls: 0, avg_duration_sec: 0, transfer_rate: 0, dispo_top: null,
    }));
    json(res, { rows });
  }],
  ["GET", /^\/api\/v1\/analytics\/timeseries$/, (_req, res) => json(res, {
    bucket: "day", points: [],
  })],

  // ---------- System / cluster ----------
  ["GET", /^\/api\/v1\/system\/health$/, (_req, res) => json(res, {
    overall: "ok",
    checked_at: new Date().toISOString(),
    services: [
      { name: "panel", status: "ok", detail: "mock backend" },
    ],
  })],
  ["GET", /^\/api\/v1\/system\/version$/, (_req, res) => json(res, { version: "1.0.0-mock" })],

  // ---------- Updates (mock — fakes update.sh in 6 lines over 4 seconds) ----------
  ["GET", /^\/api\/v1\/system\/updates\/info$/, (_req, res) => {
    json(res, {
      current_version: "1.0.0-mock",
      current_sha: "mock0000000000000000000000000000000000000",
      latest_tag: "1.0.0-mock",
      behind_count: 0,
      available_tags: ["1.0.0-mock"],
      has_previous: false,
      update_in_progress: !!state.active_update_id,
    });
  }],
  ["POST", /^\/api\/v1\/system\/updates\/apply$/, async (req, res) => {
    if (state.active_update_id) {
      return json(res, { detail: "another update is in progress" }, 409);
    }
    const body = await readJson(req);
    const id = randomUUID();
    state.active_update_id = id;
    state.update_runs = state.update_runs || {};
    state.update_runs[id] = {
      id, status: "running", exit_code: null,
      started_at: new Date().toISOString(),
      lines: [`$ sudo update.sh${body?.rollback ? " --rollback" : ""}${body?.target ? ` --to=${body.target}` : ""}`],
    };
    persist();
    pushAudit("system.update_start", { run_id: id, target: body?.target, rollback: !!body?.rollback }, "system");
    // Fake progress.
    const steps = [
      "[step] Update plan",
      "  Current: 1.0.0-mock",
      "  Target:  1.0.0-mock",
      "[step] Pre-update backup",
      "  pg_dump → /var/lib/aipanel/backups/pre-update-mock.sql.gz",
      "[step] Fetch code",
      "[step] Detect changes",
      "[step] Rolling restart",
      "  ✓ aipanel-web active",
      "  ✓ aipanel-llm active",
      "[step] Post-update health",
      "[mock] Done.",
    ];
    let i = 0;
    const tick = setInterval(() => {
      const run = state.update_runs[id];
      if (!run) { clearInterval(tick); return; }
      if (i >= steps.length) {
        run.status = "ok";
        run.exit_code = 0;
        state.active_update_id = null;
        persist();
        clearInterval(tick);
        return;
      }
      run.lines.push(steps[i++]);
      persist();
    }, 350);
    json(res, { run_id: id }, 202);
  }],
  ["GET", /^\/api\/v1\/system\/updates\/runs\/([^/]+)$/, (_req, res, m) => {
    const r = (state.update_runs || {})[m[1]];
    if (!r) return json(res, { detail: "run not found" }, 404);
    json(res, r);
  }],
  ["GET", /^\/api\/v1\/system\/updates\/runs\/([^/]+)\/stream$/, (_req, res, m) => {
    const id = m[1];
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    let cursor = 0;
    const push = () => {
      const r = (state.update_runs || {})[id];
      if (!r) { res.write("event: done\ndata: error|-1\n\n"); res.end(); return true; }
      while (cursor < r.lines.length) {
        res.write(`data: ${r.lines[cursor++]}\n\n`);
      }
      if (r.status !== "running") {
        res.write(`event: done\ndata: ${r.status}|${r.exit_code}\n\n`);
        res.end();
        return true;
      }
      return false;
    };
    if (push()) return;
    const tick = setInterval(() => { if (push()) clearInterval(tick); }, 250);
    res.on("close", () => clearInterval(tick));
  }],
  ["GET", /^\/api\/v1\/system\/config$/, (_req, res) => json(res, {
    panel_public_url: "http://127.0.0.1:8055",
    sip_listen_port: 5060,
    llm_model: "Qwen/Qwen2.5-14B-Instruct-AWQ",
    stt_model: "large-v3",
    tts_backend: "f5",
  })],
  ["GET", /^\/api\/v1\/cluster\/nodes$/, (_req, res) => json(res, [{
    id: "node-local", hostname: "localhost.dev", role: "primary",
    services: ["aipanel-mock"],
    status: "ok",
    last_heartbeat_at: new Date().toISOString(),
    joined_at: "2026-01-01T00:00:00Z",
  }])],

  // ---------- Tenants / Users ----------
  ["GET", /^\/api\/v1\/tenants$/, (_req, res) => json(res, [{
    id: TENANT_ID, name: "Default", settings: {},
    created_at: "2026-01-01T00:00:00Z",
  }])],
  ["GET", /^\/api\/v1\/tenants\/([^/]+)\/users$/, (_req, res) => json(res, state.users)],
  ["POST", /^\/api\/v1\/tenants\/([^/]+)\/users$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.email || !body?.password) {
      return json(res, { detail: "email and password required" }, 422);
    }
    const email = body.email.toLowerCase();
    if (state.users.some(u => u.email === email)) {
      return json(res, { detail: "email already in use" }, 409);
    }
    const u = {
      id: randomUUID(), tenant_id: TENANT_ID,
      email, role: body.role || "viewer",
      created_at: new Date().toISOString(),
    };
    state.users.push(u);
    pushAudit("user.invite", { email, role: u.role }, "user", u.id);
    json(res, u, 201);
  }],
  ["PATCH", /^\/api\/v1\/tenants\/([^/]+)\/users\/([^/]+)$/, async (req, res, m) => {
    const body = await readJson(req);
    const u = state.users.find(x => x.id === m[2]);
    if (!u) return json(res, { detail: "user not found" }, 404);
    if (!body?.role) return json(res, { detail: "role required" }, 422);
    const old = u.role;
    u.role = body.role;
    pushAudit("user.role_change", { from: old, to: u.role }, "user", u.id);
    persist();
    json(res, u);
  }],
  ["DELETE", /^\/api\/v1\/tenants\/([^/]+)\/users\/([^/]+)$/, (_req, res, m) => {
    const idx = state.users.findIndex(x => x.id === m[2]);
    if (idx < 0) return json(res, { detail: "user not found" }, 404);
    if (state.users[idx].id === USER.id) {
      return json(res, { detail: "cannot delete the seeded admin" }, 400);
    }
    const removed = state.users.splice(idx, 1)[0];
    pushAudit("user.delete", { email: removed.email }, "user", removed.id);
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/tenants\/([^/]+)\/audit$/, (_req, res, _m, q) => {
    const limit = Math.min(parseInt(q.get("limit") ?? "100", 10) || 100, 1000);
    const offset = parseInt(q.get("offset") ?? "0", 10) || 0;
    const prefix = q.get("action_prefix") || "";
    let rows = state.audit;
    if (prefix) rows = rows.filter(r => r.action.startsWith(prefix));
    json(res, rows.slice(offset, offset + limit));
  }],
];

// ---------------------------------------------------------------------------
// SSE: live deployment stream — stays empty until real calls arrive.
// ---------------------------------------------------------------------------

function sseLiveDeployment(_req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });
  res.write(": connected\n\n");
  // Heartbeat so the client knows we're alive.
  const tick = setInterval(() => {
    try { res.write(": heartbeat\n\n"); }
    catch { clearInterval(tick); }
  }, 15_000);
  res.on("close", () => clearInterval(tick));
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Capability score: 0–100. Transparent breakdown so the operator can
// see exactly what to add next to push the number up.
function computeCapability(a) {
  const recordings = (state.training_recordings[a.id] || [])
    .filter(r => r.status === "ready").length;
  const chats = (state.training_chats[a.id] || []).length;
  const hasScript = !!(a.training_script?.trim()
    || a.script?.opening_variants?.[0]?.trim());
  const hasPersona = !!(a.persona?.name?.trim() && a.persona?.backstory?.trim());
  const hasVoice = !!a.voice_id;

  const recordingsPts = Math.min(recordings, 6) * 5;   // up to 30
  const chatsPts      = Math.min(chats, 5) * 4;        // up to 20
  const scriptPts     = hasScript  ? 25 : 0;
  const personaPts    = hasPersona ? 15 : 0;
  const voicePts      = hasVoice   ? 10 : 0;

  const score = recordingsPts + chatsPts + scriptPts + personaPts + voicePts;
  return {
    score,
    breakdown: [
      { key: "script",     label: "Script provided",            points: scriptPts,     max: 25, done: hasScript },
      { key: "persona",    label: "Persona filled in",          points: personaPts,    max: 15, done: hasPersona },
      { key: "recordings", label: `${recordings} call recording${recordings===1?"":"s"} transcribed`,
                                                                points: recordingsPts, max: 30, done: recordings >= 6 },
      { key: "chats",      label: `${chats} chat exchange${chats===1?"":"s"} saved`,
                                                                points: chatsPts,      max: 20, done: chats >= 5 },
      { key: "voice",      label: "Voice cloned",               points: voicePts,      max: 10, done: hasVoice },
    ],
  };
}

// Mock reply — pretends to be a customer-care AI. Uses the agent's name
// + script content so the operator can sanity-check tone. The real
// backend routes this through vLLM with the full agent prompt.
function mockReply(a, message) {
  const name = a.persona?.name || "the agent";
  const lower = message.toLowerCase();
  const script = (a.training_script || "").toLowerCase();
  const looksLikeOrderQ  = /(order|tracking|where|delivery|shipped)/.test(lower);
  const looksLikeRefund  = /(refund|return|money back)/.test(lower);
  const looksLikeBroken  = /(broken|damaged|not working|defect|crack)/.test(lower);
  const looksLikeBilling = /(charge|bill|invoice|payment)/.test(lower);
  const looksLikeHi      = /(hi|hello|hey|good (morning|afternoon))\b/.test(lower);

  if (looksLikeHi)      return `Hi! This is ${name}. How can I help you today?`;
  if (looksLikeOrderQ)  return `Sure — can I get your order number to look that up? It's in your confirmation email.`;
  if (looksLikeRefund)  return `Absolutely. Refunds within 30 days are no problem. What's your order number?`;
  if (looksLikeBroken)  return `I'm sorry to hear that. Can you share the order number and a quick description of the damage?`;
  if (looksLikeBilling) return `Happy to look at that. Can you share your order number and roughly when you were charged?`;

  // Generic fallback that pulls a hint from the script if available.
  const hint = script ? " Based on the script you uploaded, I'll route this through the standard playbook." : "";
  return `Got it.${hint} Could you tell me a bit more so I can help you properly?`;
}

function readJson(req) {
  return new Promise((resolve) => {
    const bufs = [];
    req.on("data", (c) => bufs.push(c));
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(bufs).toString("utf8") || "{}")); }
      catch { resolve(null); }
    });
  });
}

// Tiny multipart parser — single binary file + a few text fields.
// Returns { fields: {name: value}, file: { filename, contentType, size } | null }.
function readMultipart(req) {
  return new Promise((resolve, reject) => {
    const ct = req.headers["content-type"] || "";
    const boundary = (ct.match(/boundary=(?:"([^"]+)"|([^;]+))/) || [])
      .slice(1).find(Boolean);
    if (!boundary) return resolve({ fields: {}, file: null });
    const bufs = [];
    req.on("data", (c) => bufs.push(c));
    req.on("end", () => {
      const buf = Buffer.concat(bufs);
      const sep = Buffer.from(`--${boundary}`);
      let pos = 0;
      const fields = {};
      let file = null;
      while (true) {
        const start = buf.indexOf(sep, pos);
        if (start < 0) break;
        const headerStart = start + sep.length;
        if (buf.slice(headerStart, headerStart + 2).toString() === "--") break;
        const headerEnd = buf.indexOf("\r\n\r\n", headerStart);
        if (headerEnd < 0) break;
        const headers = buf.slice(headerStart, headerEnd).toString();
        const bodyStart = headerEnd + 4;
        const next = buf.indexOf(sep, bodyStart);
        if (next < 0) break;
        const body = buf.slice(bodyStart, next - 2); // strip CRLF before next boundary
        const cd = headers.match(/Content-Disposition:[^\r\n]+/i)?.[0] || "";
        const name = (cd.match(/name="([^"]+)"/) || [])[1];
        const filename = (cd.match(/filename="([^"]*)"/) || [])[1];
        const ctMatch = (headers.match(/Content-Type:\s*([^\r\n]+)/i) || [])[1];
        if (filename !== undefined) {
          file = { filename, contentType: ctMatch || "application/octet-stream", size: body.length };
        } else if (name) {
          fields[name] = body.toString("utf8");
        }
        pos = next;
      }
      resolve({ fields, file });
    });
    req.on("error", reject);
  });
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

const server = http.createServer(async (req, res) => {
  // Preflight + CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }

  const url = new URL(req.url, `http://${req.headers.host}`);
  for (const [method, regex, handler] of routes) {
    if (req.method === method) {
      const m = url.pathname.match(regex);
      if (m) {
        try { await handler(req, res, m, url.searchParams); }
        catch (e) { console.error(e); json(res, { detail: "mock-backend error" }, 500); }
        return;
      }
    }
  }
  json(res, { detail: `mock-backend: no route for ${req.method} ${url.pathname}` }, 404);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[mock-backend] listening on http://127.0.0.1:${PORT}`);
  console.log(`[mock-backend] state file: ${STATE_FILE}`);
  console.log(`[mock-backend] login: any email + any non-empty password`);
  console.log(`[mock-backend] seeded admin: ${USER.email}`);
});
