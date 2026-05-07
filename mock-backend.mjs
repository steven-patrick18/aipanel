// mock-backend.mjs — local dev stand-in for the FastAPI backend.
//
// Serves realistic canned data for every endpoint the SPA touches, so you
// can explore the GUI without Postgres/Redis/the real backend. Streams
// fake SSE events on the live-deployment endpoint.
//
// Run:   node mock-backend.mjs
// Port:  127.0.0.1:8000  (Vite proxies /api → here)
// Login: any email + any non-empty password.

import http from "node:http";
import { randomUUID } from "node:crypto";

const PORT = 8800;
const TENANT_ID = "11111111-1111-1111-1111-111111111111";

// ---------------------------------------------------------------------------
// Seed data
// ---------------------------------------------------------------------------

const USER = {
  id: "22222222-2222-2222-2222-222222222222",
  tenant_id: TENANT_ID,
  email: "admin@aipanel.local",
  role: "admin",
  created_at: "2026-01-15T10:00:00Z",
};

const USERS = [
  USER,
  {
    id: "33333333-3333-3333-3333-333333333333",
    tenant_id: TENANT_ID,
    email: "ops@aipanel.local",
    role: "operator",
    created_at: "2026-02-02T09:30:00Z",
  },
  {
    id: "44444444-4444-4444-4444-444444444444",
    tenant_id: TENANT_ID,
    email: "viewer@aipanel.local",
    role: "viewer",
    created_at: "2026-02-12T14:15:00Z",
  },
];

let AUDIT_NEXT_ID = 1;
const AUDIT = [
  {
    id: AUDIT_NEXT_ID++, ts: "2026-04-30T10:14:01Z",
    user_id: USER.id, action: "agent.create", target_type: "agent",
    target_id: randomUUID(), payload: { name: "Solar outbound v3" },
  },
  {
    id: AUDIT_NEXT_ID++, ts: "2026-05-01T08:02:55Z",
    user_id: USER.id, action: "deployment.start", target_type: "deployment",
    target_id: randomUUID(), payload: {},
  },
  {
    id: AUDIT_NEXT_ID++, ts: "2026-05-03T15:42:11Z",
    user_id: USERS[1].id, action: "voice.create", target_type: "voice",
    target_id: randomUUID(), payload: { name: "Sam v2" },
  },
  {
    id: AUDIT_NEXT_ID++, ts: "2026-05-05T09:01:00Z",
    user_id: USER.id, action: "user.invite", target_type: "user",
    target_id: USERS[2].id, payload: { email: "viewer@aipanel.local", role: "viewer" },
  },
];

function pushAudit(action, payload = {}, target_type = null, target_id = null) {
  AUDIT.unshift({
    id: AUDIT_NEXT_ID++,
    ts: new Date().toISOString(),
    user_id: USER.id,
    action, target_type, target_id, payload,
  });
}

const VOICES = [
  voice("Sam (warm female)",   "ready"),
  voice("Marcus (calm male)",  "ready"),
  voice("Priya (UK accent)",   "ready"),
  voice("Demo voice",          "training"),
];

const KBS = [
  kb("Solar panel FAQ", "Product specs + warranty + financing"),
  kb("Insurance objections", "Common rebuttals + comparisons"),
];

const METHODOLOGIES = [
  {
    key: "consultative",
    name: "Consultative selling",
    tagline: "Discover their context first. Propose only when their problem is clear. Tailor every recommendation.",
    when_to_use: "Default for most outbound calls.",
    system_prompt: "CONSULTATIVE SELLING — TRUSTED-ADVISOR FRAMING\nYou are calling as a consultant, not a salesperson. Your goal is to help the customer get clarity on their situation. If your product fits, they'll notice; if it doesn't, you save everyone time.\n\nCORE STANCE\n- Curiosity over conviction.\n- Patience over pace. A great consultative call is 70% them talking.\n- 'Based on what you've shared…' is the strongest sentence in this methodology.\n\nTHE RHYTHM\n1. Earn the right to ask (one warm sentence about why you're calling).\n2. Ask one good open-ended question.\n3. Listen — actually listen. Reflect back what you heard.\n4. Ask the next question based on their answer, not your script.\n5. Only after 3-4 substantive exchanges, offer a tailored recommendation.\n6. Confirm the recommendation lands before pitching next steps.",
    stages: [
      { name: "Earn the right", goal: "One-sentence warm opener.", success_markers: ["customer_engaged"] },
      { name: "Discover", goal: "3-4 open-ended questions, real listening.", success_markers: ["context_established"] },
      { name: "Recommend", goal: "Tailored next step.", success_markers: ["recommendation_landed"] },
      { name: "Confirm", goal: "Check the recommendation lands.", success_markers: ["confirmation_received"] },
    ],
    priority_signals: ["Yeah, that's basically it", "Tell me more", "How would that work for us?"],
    common_objections: { "Just send me the info.": "Reframe to a question." },
  },
  {
    key: "spin",
    name: "SPIN selling",
    tagline: "Ask Situation, Problem, Implication, Need-payoff questions in order. The customer sells themselves.",
    when_to_use: "Best when the customer doesn't yet know they have a problem you can solve, or doesn't realise its cost.",
    system_prompt: "SPIN SELLING — DISCOVERY FRAMEWORK\nFour question types in order. The goal is to make the customer state the value of your solution themselves before you ever mention it.\n\nPHASE 1 — SITUATION questions (gather facts) — at most two, customers find too many tedious.\n\nPHASE 2 — PROBLEM questions (find pain) — listen for irritation in their voice.\n\nPHASE 3 — IMPLICATION questions (amplify pain) — the most important step. Makes the customer FEEL the cost of inaction.\n\nPHASE 4 — NEED-PAYOFF questions (let them sell themselves) — get them to state the value of solving the problem in their own words.\n\nNEVER skip phases. ONE question at a time. Use silence as a tool.",
    stages: [
      { name: "Situation", goal: "Confirm basics.", success_markers: ["confirmed_current_tool"] },
      { name: "Problem", goal: "Surface dissatisfaction.", success_markers: ["pain_admitted"] },
      { name: "Implication", goal: "Amplify cost of problem.", success_markers: ["cost_named"] },
      { name: "Need-payoff", goal: "Customer states value.", success_markers: ["value_stated"] },
    ],
    priority_signals: ["I hate that we have to…", "We waste so much time on…", "If we could just…"],
    common_objections: { "We're already using X.": "Restate the problem you suspect they have with X." },
  },
  {
    key: "bant",
    name: "BANT qualification",
    tagline: "Confirm Budget, Authority, Need, Timeline before advancing the deal.",
    when_to_use: "Best as a qualification filter at the top of a high-volume pipeline.",
    system_prompt: "BANT QUALIFICATION\nDetermine — politely but clearly — whether this prospect is worth advancing.\n\nB — BUDGET: Frame around current spend.\nA — AUTHORITY: Decision maker, or path to one?\nN — NEED: Real and important right now?\nT — TIMELINE: Specific date or event-driven deadline.\n\nDon't interrogate. Weave BANT into a normal conversation. Never advance to a transfer unless you have ALL FOUR.",
    stages: [
      { name: "Budget", goal: "Confirm spend range.", success_markers: ["budget_range_stated"] },
      { name: "Authority", goal: "Identify decision path.", success_markers: ["decision_maker_identified"] },
      { name: "Need", goal: "Concrete pain + urgency.", success_markers: ["pain_with_consequence"] },
      { name: "Timeline", goal: "Date or event-driven deadline.", success_markers: ["timeline_stated"] },
    ],
    priority_signals: ["We've allocated $X for this", "I'd want this live by [date]", "I make these calls"],
    common_objections: { "We don't have a budget.": "Reframe to cost of inaction." },
  },
  {
    key: "meddpicc",
    name: "MEDDPICC",
    tagline: "Surface Metrics, Economic buyer, Decision criteria + process, Paper process, Identified pain, Champion, Competition.",
    when_to_use: "Best for enterprise / multi-stakeholder deals with $50k+ ACV.",
    system_prompt: "MEDDPICC — ENTERPRISE QUALIFICATION\nAnswer all eight by call end (or follow-up).\n\nM — METRICS — measurable success criteria\nE — ECONOMIC BUYER — who controls the budget\nD — DECISION CRITERIA — explicit list to evaluate against\nD — DECISION PROCESS — every step from demo to signature\nP — PAPER PROCESS — procurement / legal / security\nI — IDENTIFIED PAIN — measurable consequence of inaction\nC — CHAMPION — internal advocate\nC — COMPETITION — including 'doing nothing'\n\nQualification, not interrogation. Surface 2-3 per call.",
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
    system_prompt: "VALUE-BASED SELLING — OUTCOMES, NOT FEATURES\n\nTHE TRANSLATION RULE\nFeature → Benefit → measurable Outcome.\n\nALWAYS QUANTIFY\nTime saved → hours / week. Money saved → dollars / month. Money made → incremental revenue. Risk → fines avoided.\n\nDO THE MATH OUT LOUD\nNumbers spoken aloud get challenged — that's good, the customer co-creates the value with you.\n\nNEVER quote a feature without a benefit. NEVER use 'robust', 'best-in-class', 'leverage', 'synergy'.",
    stages: [
      { name: "Inputs", goal: "Gather numbers for ROI.", success_markers: ["volume_known"] },
      { name: "Quantify", goal: "State value in dollars.", success_markers: ["value_quantified"] },
      { name: "Validate", goal: "Customer confirms math.", success_markers: ["math_acknowledged"] },
      { name: "Anchor", goal: "Tie price to value.", success_markers: ["price_to_value_stated"] },
    ],
    priority_signals: ["That's actually a lot of money", "If that's true, this is a no-brainer"],
    common_objections: { "It's too expensive.": "Re-anchor to value: 'At your volume, this pays back in X weeks.'" },
  },
  {
    key: "custom",
    name: "Custom",
    tagline: "Follow the campaign's script verbatim. No additional methodology scaffolding.",
    when_to_use: "When the campaign has a hand-tuned script.",
    system_prompt: "CUSTOM CONVERSATION PATTERN\nFollow the campaign's script faithfully. Adapt only when the customer's response makes the next scripted line nonsensical. When in doubt, ask one clarifying question and return to the script.",
    stages: [
      { name: "Script", goal: "Walk through the scripted conversation.", success_markers: ["script_completed"] },
    ],
    priority_signals: [],
    common_objections: {},
  },
];

const CAMPAIGNS = [
  campaign("Q2 solar push",
           "consultative",
           "Book a 15-minute roof assessment with the senior consultant.",
           ["QUAL", "XFER"], 8),
  campaign("Insurance renewal — auto",
           "bant",
           "Confirm renewal intent and qualify by budget + timing.",
           ["QUAL", "DONE"], 6),
  campaign("Cold lead reactivation",
           "spin",
           "Surface latent need by walking through SPIN questions.",
           ["QUAL", "CALLBK"], 4),
  campaign("Enterprise renewal upsell",
           "meddpicc",
           "Identify economic buyer + decision criteria, hand to AE.",
           ["QUAL", "XFER"], 5),
];

const VICI_SERVERS = [
  viciServer("Acme dialer (prod)",  "vici01.acme.com"),
  viciServer("Acme dialer (stage)", "vici-stg.acme.com"),
];

const AGENTS = [
  agent("Sarah – Solar outreach",      "ready",    "en"),
  agent("Mark – Insurance follow-up",  "ready",    "en"),
  agent("Priya – Lead qualification",  "draft",    "en"),
  agent("Demo agent",                  "archived", "en"),
];
// Wire agents to campaigns so the editor can show the link.
AGENTS[0].campaign_id = CAMPAIGNS[0]?.id ?? null;   // Sarah → Q2 solar
AGENTS[1].campaign_id = CAMPAIGNS[1]?.id ?? null;   // Mark  → Insurance renewal
AGENTS[2].campaign_id = CAMPAIGNS[2]?.id ?? null;   // Priya → Cold reactivation

const DEPLOYMENTS = [
  deployment(AGENTS[0].id, VICI_SERVERS[0].id, "agent01", "9001", "SOLAR",  "running"),
  deployment(AGENTS[1].id, VICI_SERVERS[0].id, "agent02", "9002", "INSURE", "running"),
  deployment(AGENTS[2].id, VICI_SERVERS[1].id, "agent03", "9003", "QUAL",   "stopped"),
];

const CALLS = Array.from({ length: 28 }, (_, i) => mockCall(i));

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function isoMinusMin(min) {
  return new Date(Date.now() - min * 60_000).toISOString();
}

function voice(name, status) {
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    name,
    sample_path: `/var/lib/aipanel/voices/${randomUUID()}/ref.wav`,
    embedding_path: `/var/lib/aipanel/voices/${randomUUID()}/ref.wav`,
    status,
    created_at: isoMinusMin(60 * 24 * 7 * Math.random()),
  };
}

function kb(name, description) {
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    name,
    description,
    embedding_model: "BAAI/bge-base-en-v1.5",
    created_at: isoMinusMin(60 * 24 * 14 * Math.random()),
  };
}

function campaign(name, methodology, objective, success_dispos, fewShotN = 6) {
  const sample_pairs = [
    ["How much does it actually cost?",
     "Most installs run twenty to thirty thousand. Federal and state rebates "
     + "knock about a third off, and we have financing that comes in under "
     + "what you currently pay the utility."],
    ["I'm honestly not interested.",
     "Totally fair. Quick question before I let you go — is it the price, the "
     + "install, or just bad timing? Helps me know if a callback in six months "
     + "would be worth either of our time."],
    ["I already have solar.",
     "Nice — when did you install? Most systems older than seven years are "
     + "leaving real money on the table with new battery options. Worth a "
     + "five-minute look?"],
    ["Send me an email and I'll think about it.",
     "Happy to. While I have you, what's the one thing about the offer that "
     + "would make this a clear yes — savings, warranty, or install timeline?"],
    ["I need to talk to my spouse first.",
     "Of course. What time tomorrow works for both of you? I can lock a "
     + "fifteen-minute slot so you don't have to remember to call back."],
    ["This sounds like a scam.",
     "Hear you. We're licensed in your state — license number is publicly "
     + "searchable. Want me to text you the link before we go any further?"],
  ];
  const pool = sample_pairs.slice(0, fewShotN).map(([u, a], i) => ({
    user: u,
    agent: a,
    score: +(0.92 - i * 0.04).toFixed(3),
    call_id: randomUUID(),
    mined_at: isoMinusMin(60 * 24 * (1 + i)),
  }));
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    name,
    description: objective,
    methodology,
    objective,
    success_dispos,
    persona_template: {},
    script_template: {},
    kb_collection_id: null,
    few_shot_pool: pool,
    few_shot_updated_at: pool.length ? pool[0].mined_at : null,
    few_shot_count: pool.length,
    status: "active",
    created_at: isoMinusMin(60 * 24 * 30),
    updated_at: isoMinusMin(60 * 4),
  };
}

function viciServer(name, host) {
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    name,
    asterisk_host: host,
    asterisk_port: 5038,
    web_url: `https://${host}/`,
    ami_user: "aipanel",
    web_user_admin: "aipanel-admin",
    created_at: isoMinusMin(60 * 24 * 90),
  };
}

function agent(name, status, language) {
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    name,
    campaign_id: null,
    persona: {
      name: name.split(" ")[0],
      age_range: "30-40",
      gender: "neutral",
      accent: "neutral US",
      backstory: "Friendly outreach specialist with 5 years of experience.",
      guidelines: "",
      disclosure_response: "I'm an AI assistant.",
    },
    script: {
      opening_variants: [
        `Hi, this is ${name.split(" ")[0]}. Got a quick minute?`,
        `Hey, ${name.split(" ")[0]} here. Have a sec?`,
      ],
      sections: [
        { id: "s1", title: "Intro",   content: "Quick intro + reason for call.", expected_response_keywords: [] },
        { id: "s2", title: "Pitch",   content: "Core value prop.",               expected_response_keywords: [] },
      ],
      closing: "Thanks for your time — have a great day.",
      objections: [],
    },
    scenario_tree: { rules: [] },
    voice_id: VOICES[0]?.id ?? null,
    language,
    kb_collection_id: null,
    status,
    created_at: isoMinusMin(60 * 24 * 30),
    updated_at: isoMinusMin(60 * Math.random() * 48),
  };
}

function deployment(agentId, serverId, viciUser, phoneLogin, campaign, status) {
  return {
    id: randomUUID(),
    tenant_id: TENANT_ID,
    agent_id: agentId,
    vicidial_server_id: serverId,
    vici_user: viciUser,
    phone_login: phoneLogin,
    campaign_id: campaign,
    allowed_transfer_ingroups: ["SALES", "RETENTION"],
    dispo_mapping: { QUAL: "QUALIFIED", NI: "NOT_INTERESTED" },
    status,
    last_heartbeat_at: status === "running" ? isoMinusMin(0.05) : null,
    created_at: isoMinusMin(60 * 24 * 14),
    updated_at: isoMinusMin(60 * 2),
  };
}

function mockCall(i) {
  const dur = 60 + Math.floor(Math.random() * 240);
  const startedAt = new Date(Date.now() - i * 17 * 60_000 - 5 * 60_000);
  const dispos = ["QUAL", "NI", "DNC", "CALLBK", "XFER", "DONE"];
  const dispo = dispos[Math.floor(Math.random() * dispos.length)];
  // First two entries are "live" — useful for testing the transfer flow.
  const isLive = i < 2;
  return {
    id: randomUUID(),
    deployment_id: DEPLOYMENTS[i % DEPLOYMENTS.length].id,
    vici_uniqueid: `${1700000000 + i}.${i}`,
    vici_lead_id: String(900000 + i),
    phone_number: `+1415${String(5550000 + i).padStart(7, "0")}`,
    started_at: isLive
      ? new Date(Date.now() - 90_000).toISOString()
      : startedAt.toISOString(),
    ended_at: isLive
      ? null
      : new Date(startedAt.getTime() + dur * 1000).toISOString(),
    duration_sec: isLive ? null : dur,
    outcome: isLive
      ? null
      : dispo === "DONE" || dispo === "QUAL" ? "completed"
        : dispo === "XFER" ? "transferred" : "abandoned",
    dispo_code: isLive ? null : dispo,
    transfer_target: !isLive && dispo === "XFER" ? "SALES" : null,
    transcript_path: null,
    recording_path:
      !isLive && i % 3 === 0
        ? `s3://aipanel-recordings/${TENANT_ID}/call-${i}.wav` : null,
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
  ["GET", /^\/api\/v1\/agents$/, (req, res, _m, q) => json(res, pageOf(AGENTS, q))],
  ["GET", /^\/api\/v1\/agents\/([^/]+)$/, (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]) ?? AGENTS[0];
    json(res, a);
  }],
  ["POST",   /^\/api\/v1\/agents$/, async (req, res) => {
    const body = await readJson(req);
    const a = { ...AGENTS[0], id: randomUUID(), name: body.name ?? "New agent", status: "draft", updated_at: new Date().toISOString() };
    AGENTS.unshift(a);
    json(res, a, 201);
  }],
  ["PATCH",  /^\/api\/v1\/agents\/([^/]+)$/, async (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]) ?? AGENTS[0];
    json(res, { ...a, updated_at: new Date().toISOString() });
  }],
  ["DELETE", /^\/api\/v1\/agents\/([^/]+)$/, (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]); if (a) a.status = "archived";
    json(res, { ok: true });
  }],
  ["POST",   /^\/api\/v1\/agents\/([^/]+)\/duplicate$/, (_req, res, m) => {
    const src = AGENTS.find(x => x.id === m[1]) ?? AGENTS[0];
    const dup = { ...src, id: randomUUID(), name: `${src.name} (copy)`, status: "draft" };
    AGENTS.unshift(dup);
    json(res, dup, 201);
  }],
  ["POST",   /^\/api\/v1\/agents\/([^/]+)\/promote$/, (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]) ?? AGENTS[0];
    a.status = "ready";
    json(res, a);
  }],
  ["POST",   /^\/api\/v1\/agents\/([^/]+)\/test-call$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.phone_number) return json(res, { detail: "phone_number required" }, 422);
    // Pretend the dialler accepted it.
    json(res, { ok: true, dialed: body.phone_number });
  }],
  ["GET",    /^\/api\/v1\/agents\/([^/]+)\/training-examples$/, (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]);
    json(res, (a?.training_examples ?? []));
  }],
  ["POST",   /^\/api\/v1\/agents\/([^/]+)\/training-examples$/, async (req, res, m) => {
    const body = await readJson(req);
    if (!body?.user || !body?.agent) {
      return json(res, { detail: "user and agent are required" }, 422);
    }
    const a = AGENTS.find(x => x.id === m[1]); if (!a) return json(res, { detail: "agent not found" }, 404);
    a.training_examples = a.training_examples || [];
    const entry = {
      id: randomUUID(), kind: "manual",
      user: body.user, agent: body.agent, notes: body.notes || "",
      added_at: new Date().toISOString(), added_by: USER.id,
    };
    a.training_examples.push(entry);
    pushAudit("agent.training_example_add", { kind: "manual" }, "agent", a.id);
    json(res, entry, 201);
  }],
  ["DELETE", /^\/api\/v1\/agents\/([^/]+)\/training-examples\/([^/]+)$/, (_req, res, m) => {
    const a = AGENTS.find(x => x.id === m[1]); if (!a) return json(res, { detail: "agent not found" }, 404);
    const before = (a.training_examples || []).length;
    a.training_examples = (a.training_examples || []).filter(x => x.id !== m[2]);
    if (a.training_examples.length === before) return json(res, { detail: "training example not found" }, 404);
    pushAudit("agent.training_example_delete", { example_id: m[2] }, "agent", a.id);
    json(res, { ok: true });
  }],

  // ---------- Voices ----------
  ["GET",    /^\/api\/v1\/voices$/, (req, res, _m, q) => json(res, pageOf(VOICES, q))],
  ["GET",    /^\/api\/v1\/voices\/([^/]+)$/, (_req, res, m) => json(res, VOICES.find(v => v.id === m[1]) ?? VOICES[0])],
  ["POST",   /^\/api\/v1\/voices$/, (_req, res) => {
    const v = voice("Uploaded voice", "training"); VOICES.unshift(v); json(res, v, 202);
  }],
  ["DELETE", /^\/api\/v1\/voices\/([^/]+)$/, (_req, res) => json(res, { ok: true })],

  // ---------- Knowledge bases ----------
  ["GET",  /^\/api\/v1\/kb$/, (req, res, _m, q) => json(res, pageOf(KBS, q))],
  ["POST", /^\/api\/v1\/kb$/, async (req, res) => {
    const body = await readJson(req); const k = kb(body?.name ?? "New KB", body?.description ?? "");
    KBS.unshift(k); json(res, k, 201);
  }],
  ["GET",    /^\/api\/v1\/kb\/([^/]+)$/, (_req, res, m) =>
    json(res, KBS.find(k => k.id === m[1]) ?? KBS[0])],
  ["GET",    /^\/api\/v1\/kb\/([^/]+)\/documents$/, (_req, res) => json(res, [])],
  ["POST",   /^\/api\/v1\/kb\/([^/]+)\/documents$/, (_req, res) => json(res, {
    id: randomUUID(), kb_id: "x", filename: "uploaded.pdf", content_hash: "—",
    chunk_count: 0, status: "pending", created_at: new Date().toISOString(),
  }, 202)],
  ["DELETE", /^\/api\/v1\/kb\/([^/]+)\/documents\/([^/]+)$/, (_req, res) => json(res, { ok: true })],
  ["POST",   /^\/api\/v1\/kb\/([^/]+)\/search$/, (_req, res) => json(res, { hits: [] })],

  // ---------- Methodologies (catalog) ----------
  ["GET", /^\/api\/v1\/methodologies$/, (_req, res) =>
    json(res, METHODOLOGIES.map(({ system_prompt, stages, priority_signals,
                                   common_objections, ...rest }) => rest))],
  ["GET", /^\/api\/v1\/methodologies\/([^/]+)$/, (_req, res, m) => {
    const found = METHODOLOGIES.find(x => x.key === m[1]);
    if (!found) return json(res, { detail: "unknown methodology" }, 404);
    json(res, found);
  }],

  // ---------- Campaigns ----------
  ["GET", /^\/api\/v1\/campaigns$/, (req, res, _m, q) => json(res, pageOf(CAMPAIGNS, q))],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)$/, (_req, res, m) =>
    json(res, CAMPAIGNS.find(c => c.id === m[1]) ?? CAMPAIGNS[0])],
  ["POST", /^\/api\/v1\/campaigns$/, async (req, res) => {
    const body = await readJson(req);
    const c = campaign(body?.name ?? "New campaign",
                       body?.methodology ?? "consultative",
                       body?.objective ?? "",
                       body?.success_dispos ?? ["QUAL"],
                       0);
    c.status = "draft";
    CAMPAIGNS.unshift(c);
    json(res, c, 201);
  }],
  ["PATCH",  /^\/api\/v1\/campaigns\/([^/]+)$/, async (req, res, m) => {
    const c = CAMPAIGNS.find(x => x.id === m[1]) ?? CAMPAIGNS[0];
    const body = await readJson(req);
    Object.assign(c, body, { updated_at: new Date().toISOString() });
    json(res, c);
  }],
  ["DELETE", /^\/api\/v1\/campaigns\/([^/]+)$/, (_req, res, m) => {
    const c = CAMPAIGNS.find(x => x.id === m[1]); if (c) c.status = "archived";
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)\/metrics$/, (req, res, m, q) => {
    const c = CAMPAIGNS.find(x => x.id === m[1]) ?? CAMPAIGNS[0];
    const total = 80 + Math.floor(Math.random() * 600);
    const by_dispo = { QUAL: Math.floor(total * 0.18), NI: Math.floor(total * 0.42),
                       DNC: Math.floor(total * 0.05), CALLBK: Math.floor(total * 0.12),
                       XFER: Math.floor(total * 0.15), DONE: Math.floor(total * 0.08) };
    const successful = (c.success_dispos || []).reduce(
      (n, d) => n + (by_dispo[d] || 0), 0);
    json(res, {
      campaign_id: c.id,
      period_days: Number(q.get("period_days") ?? 30),
      total_calls: total,
      successful_calls: successful,
      conversion_rate: total ? successful / total : 0,
      by_dispo,
      avg_duration_sec: 90 + Math.floor(Math.random() * 180),
    });
  }],
  ["GET", /^\/api\/v1\/campaigns\/([^/]+)\/few-shot-pool$/, (_req, res, m) => {
    const c = CAMPAIGNS.find(x => x.id === m[1]) ?? CAMPAIGNS[0];
    json(res, c.few_shot_pool || []);
  }],
  ["POST", /^\/api\/v1\/campaigns\/([^/]+)\/refresh-few-shot$/, (_req, res, m) => {
    const c = CAMPAIGNS.find(x => x.id === m[1]); if (c) c.few_shot_updated_at = new Date().toISOString();
    json(res, { ok: true });
  }],

  // ---------- ViciDial servers ----------
  ["GET",  /^\/api\/v1\/vicidial-servers$/, (req, res, _m, q) => json(res, pageOf(VICI_SERVERS, q))],
  ["POST", /^\/api\/v1\/vicidial-servers$/, async (req, res) => {
    const body = await readJson(req); const s = viciServer(body?.name ?? "New server", body?.asterisk_host ?? "host.example");
    VICI_SERVERS.unshift(s); json(res, s, 201);
  }],
  ["POST", /^\/api\/v1\/vicidial-servers\/([^/]+)\/test-connection$/, (_req, res) => json(res, {
    web_login_ok: true, web_error: null, ami_ok: true, ami_error: null,
  })],

  // ---------- Deployments ----------
  ["GET", /^\/api\/v1\/deployments$/, (req, res, _m, q) => json(res, pageOf(DEPLOYMENTS, q))],
  ["GET", /^\/api\/v1\/deployments\/([^/]+)$/, (_req, res, m) =>
    json(res, DEPLOYMENTS.find(d => d.id === m[1]) ?? DEPLOYMENTS[0])],
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
    DEPLOYMENTS.unshift(d);
    pushAudit("deployment.create", { vici_user: d.vici_user }, "deployment", d.id);
    json(res, d, 201);
  }],
  ["POST", /^\/api\/v1\/deployments\/([^/]+)\/(start|stop|pause)$/, (_req, res, m) => {
    const d = DEPLOYMENTS.find(x => x.id === m[1]); if (d) d.status = m[2] === "start" ? "running" : (m[2] === "stop" ? "stopped" : "running");
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/deployments\/([^/]+)\/live$/, sseLiveDeployment],

  // ---------- Calls ----------
  ["GET", /^\/api\/v1\/calls$/, (req, res, _m, q) => json(res, pageOf(CALLS, q))],
  ["GET", /^\/api\/v1\/calls\/([^/]+)$/, (_req, res, m) =>
    json(res, CALLS.find(c => c.id === m[1]) ?? CALLS[0])],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/transcript$/, (_req, res, m) => {
    const lines = [
      ["agent", "Hi, this is Sarah from Acme Solar. Do you have a quick minute?"],
      ["user",  "Uh, sure, what's this about?"],
      ["agent", "I noticed your home is in a great area for rooftop solar. We're offering a free shading assessment this week."],
      ["user",  "Hmm, I've actually thought about it. What does it cost?"],
      ["agent", "The assessment is free. Installs typically run twenty to thirty thousand, but state and federal rebates cover about a third."],
      ["user",  "Okay, send me some info."],
      ["agent", "Will do. Best email to use?"],
    ];
    json(res, {
      call_id: m[1],
      turns: lines.map(([role, text], i) => ({
        ts: new Date(Date.now() - (lines.length - i) * 7000).toISOString(),
        role, text, extra: {},
      })),
    });
  }],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/events$/, (_req, res) => json(res, [])],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/recording$/, (_req, res) =>
    json(res, { url: "https://example.com/mock-recording.wav", expires_in: 3600 })],
  ["GET", /^\/api\/v1\/calls\/([^/]+)\/transfer-options$/, (_req, res, m) => {
    const c = CALLS.find((x) => x.id === m[1]);
    const dep = c && DEPLOYMENTS.find((d) => d.id === c.deployment_id);
    const ingroups = (dep?.allowed_transfer_ingroups ?? ["SALES", "RETENTION"]);
    json(res, ingroups.map((id) => ({ id, label: id })));
  }],
  ["POST", /^\/api\/v1\/calls\/([^/]+)\/mark-exemplar$/, async (req, res, m) => {
    const body = await readJson(req);
    if (!body?.user_turn || !body?.agent_turn) {
      return json(res, { detail: "user_turn and agent_turn required" }, 422);
    }
    const c = CALLS.find(x => x.id === m[1]); if (!c) return json(res, { detail: "call not found" }, 404);
    const dep = DEPLOYMENTS.find(d => d.id === c.deployment_id);
    const agentId = body.agent_id || dep?.agent_id;
    const a = AGENTS.find(x => x.id === agentId);
    if (!a) return json(res, { detail: "agent not found" }, 404);
    a.training_examples = a.training_examples || [];
    a.training_examples.push({
      id: randomUUID(), kind: "call",
      call_id: c.id,
      user: body.user_turn, agent: body.agent_turn,
      notes: body.notes || "",
      recording_path: c.recording_path,
      added_at: new Date().toISOString(), added_by: USER.id,
    });
    pushAudit("call.mark_exemplar", { agent_id: a.id }, "call", c.id);
    json(res, { ok: true });
  }],
  ["POST", /^\/api\/v1\/calls\/([^/]+)\/transfer$/, async (req, res, m) => {
    const body = await readJson(req);
    if (!body?.ingroup_id) {
      return json(res, { detail: "ingroup_id required" }, 422);
    }
    const c = CALLS.find((x) => x.id === m[1]);
    if (!c) return json(res, { detail: "call not found" }, 404);
    if (c.ended_at) {
      return json(res, { detail: "this call has already ended — cannot transfer" }, 409);
    }
    const dep = DEPLOYMENTS.find((d) => d.id === c.deployment_id);
    const allowed = new Set(dep?.allowed_transfer_ingroups ?? []);
    if (allowed.size > 0 && !allowed.has(body.ingroup_id)) {
      return json(res, {
        detail: `ingroup '${body.ingroup_id}' is not in this deployment's allow-list (${[...allowed].sort()})`,
      }, 400);
    }
    c.transfer_target = body.ingroup_id;
    pushAudit("call.transfer", {
      ingroup_id: body.ingroup_id, summary: body.summary || "",
    }, "call", c.id);
    json(res, { ok: true });
  }],

  // ---------- Analytics ----------
  ["GET", /^\/api\/v1\/analytics\/overview$/, (_req, res) => json(res, {
    total_calls: 4217,
    avg_duration_sec: 142,
    transfer_rate: 0.18,
    dispo_breakdown: { QUAL: 612, NI: 1483, DNC: 184, CALLBK: 391, XFER: 759, DONE: 788 },
    period_start: new Date(Date.now() - 7 * 86400_000).toISOString().slice(0, 10),
    period_end: new Date().toISOString().slice(0, 10),
  })],
  ["GET", /^\/api\/v1\/analytics\/agents$/, (_req, res) => json(res, {
    rows: AGENTS.filter(a => a.status !== "archived").map(a => ({
      agent_id: a.id, agent_name: a.name,
      total_calls: 200 + Math.floor(Math.random() * 1500),
      avg_duration_sec: 90 + Math.floor(Math.random() * 180),
      transfer_rate: Math.random() * 0.3,
      dispo_top: "QUAL",
    })),
  })],
  ["GET", /^\/api\/v1\/analytics\/timeseries$/, (_req, res) => {
    const points = Array.from({ length: 14 }, (_, i) => {
      const d = new Date(Date.now() - (13 - i) * 86400_000);
      return {
        ts: d.toISOString(),
        calls: 200 + Math.floor(Math.random() * 400),
        transfers: 30 + Math.floor(Math.random() * 80),
        avg_duration_sec: 110 + Math.floor(Math.random() * 60),
      };
    });
    json(res, { bucket: "day", points });
  }],

  // ---------- System / cluster ----------
  ["GET", /^\/api\/v1\/system\/health$/, (_req, res) => json(res, {
    overall: "ok",
    checked_at: new Date().toISOString(),
    services: [
      { name: "llm", status: "ok", detail: "Qwen2.5-14B-Instruct-AWQ ready" },
      { name: "stt", status: "ok", detail: "faster-whisper large-v3 on cuda" },
      { name: "tts", status: "ok", detail: "f5-tts ready" },
    ],
  })],
  ["GET", /^\/api\/v1\/system\/version$/, (_req, res) => json(res, { version: "1.0.0" })],
  ["GET", /^\/api\/v1\/system\/config$/, (_req, res) => json(res, {
    panel_public_url: "https://aipanel.local",
    sip_listen_port: 5060,
    llm_model: "Qwen/Qwen2.5-14B-Instruct-AWQ",
    stt_model: "large-v3",
    tts_backend: "f5",
  })],
  ["GET", /^\/api\/v1\/cluster\/nodes$/, (_req, res) => json(res, [{
    id: "node-1", hostname: "dialer01.acme.local", role: "primary",
    services: ["aipanel-web", "aipanel-llm", "aipanel-stt", "aipanel-tts", "aipanel-sip"],
    status: "ok",
    last_heartbeat_at: new Date().toISOString(),
    joined_at: isoMinusMin(60 * 24 * 90),
  }])],

  // ---------- Tenants / Users ----------
  ["GET", /^\/api\/v1\/tenants$/, (_req, res) => json(res, [{
    id: TENANT_ID, name: "Acme Inc.", settings: {},
    created_at: "2026-01-01T00:00:00Z",
  }])],
  ["GET", /^\/api\/v1\/tenants\/([^/]+)\/users$/, (_req, res) => json(res, USERS)],
  ["POST", /^\/api\/v1\/tenants\/([^/]+)\/users$/, async (req, res) => {
    const body = await readJson(req);
    if (!body?.email || !body?.password) {
      return json(res, { detail: "email and password required" }, 422);
    }
    if (USERS.some((u) => u.email === body.email.toLowerCase())) {
      return json(res, { detail: "email already in use" }, 409);
    }
    const u = {
      id: randomUUID(),
      tenant_id: TENANT_ID,
      email: body.email.toLowerCase(),
      role: body.role || "viewer",
      created_at: new Date().toISOString(),
    };
    USERS.push(u);
    pushAudit("user.invite", { email: u.email, role: u.role }, "user", u.id);
    json(res, u, 201);
  }],
  ["PATCH", /^\/api\/v1\/tenants\/([^/]+)\/users\/([^/]+)$/, async (req, res, m) => {
    const body = await readJson(req);
    const u = USERS.find((x) => x.id === m[2]);
    if (!u) return json(res, { detail: "user not found" }, 404);
    if (!body?.role) return json(res, { detail: "role required" }, 422);
    const old = u.role;
    u.role = body.role;
    pushAudit("user.role_change", { from: old, to: u.role }, "user", u.id);
    json(res, u);
  }],
  ["DELETE", /^\/api\/v1\/tenants\/([^/]+)\/users\/([^/]+)$/, (_req, res, m) => {
    const idx = USERS.findIndex((x) => x.id === m[2]);
    if (idx < 0) return json(res, { detail: "user not found" }, 404);
    if (USERS[idx].id === USER.id) {
      return json(res, { detail: "you cannot delete yourself" }, 400);
    }
    const removed = USERS.splice(idx, 1)[0];
    pushAudit("user.delete", { email: removed.email }, "user", removed.id);
    json(res, { ok: true });
  }],
  ["GET", /^\/api\/v1\/tenants\/([^/]+)\/audit$/, (_req, res, _m, q) => {
    const limit = Math.min(parseInt(q.limit ?? "100", 10) || 100, 1000);
    const offset = parseInt(q.offset ?? "0", 10) || 0;
    const prefix = q.action_prefix || "";
    let rows = AUDIT;
    if (prefix) rows = rows.filter((r) => r.action.startsWith(prefix));
    json(res, rows.slice(offset, offset + limit));
  }],
];

// ---------------------------------------------------------------------------
// SSE: live deployment stream
// ---------------------------------------------------------------------------

function sseLiveDeployment(_req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });
  res.write(": connected\n\n");

  const script = [
    { type: "call_started" },
    { type: "agent_response",  text: "Hi, this is Sarah from Acme Solar. Got a quick minute?" },
    { type: "transcript_partial", text: "uh sure", stability: 0.6 },
    { type: "transcript_final",   text: "Uh, sure, what's this about?" },
    { type: "agent_response",  text: "I noticed your home is in a great area for rooftop solar." },
    { type: "tool_call",       name: "search_kb", args: { query: "average install cost" } },
    { type: "agent_response",  text: "Most installs run twenty to thirty thousand, with rebates covering about a third." },
    { type: "transcript_final", text: "Okay, send me some info." },
    { type: "agent_response",  text: "Will do. Best email to use?" },
    { type: "call_ended",      outcome: "qualified" },
  ];

  let i = 0;
  const send = () => {
    if (res.writableEnded) return;
    const evt = script[i % script.length];
    res.write(`data: ${JSON.stringify(evt)}\n\n`);
    i += 1;
  };
  send();
  const id = setInterval(send, 2500);
  const ka = setInterval(() => { if (!res.writableEnded) res.write(": ka\n\n"); }, 15_000);
  res.on("close", () => { clearInterval(id); clearInterval(ka); });
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

function readJson(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString() || "{}")); }
      catch { resolve({}); }
    });
  });
}

const server = http.createServer(async (req, res) => {
  // CORS preflight + headers (Vite dev proxy + direct browser both happy).
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin":  "*",
      "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, X-AIPanel-Token",
    });
    return res.end();
  }

  const url = new URL(req.url, `http://${req.headers.host}`);
  for (const [method, pattern, handler] of routes) {
    if (req.method !== method) continue;
    const m = url.pathname.match(pattern);
    if (m) {
      try {
        await handler(req, res, m, url.searchParams);
      } catch (err) {
        console.error("handler error", err);
        if (!res.writableEnded) json(res, { detail: "mock error" }, 500);
      }
      return;
    }
  }
  json(res, { detail: `mock-backend: no route for ${req.method} ${url.pathname}` }, 404);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[mock-backend] listening on http://127.0.0.1:${PORT}`);
  console.log(`[mock-backend] login with ANY email + ANY non-empty password`);
});
