import { z } from "zod";

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Required"),
});
export type LoginInput = z.infer<typeof loginSchema>;

// ---------------------------------------------------------------------------
// Agent — mirrors panel/backend/src/aipanel/schemas/agent_dsl.py.
// Keeping it lean here; the backend re-validates on POST.
// ---------------------------------------------------------------------------

export const personaSchema = z.object({
  name: z.string().min(1).max(200),
  age_range: z.enum(["20-30", "30-40", "40-50", "50+"]),
  gender: z.enum(["female", "male", "neutral"]),
  accent: z.string().min(1).max(80),
  backstory: z.string().min(1).max(2000),
  description: z.string().max(2000).optional().default(""),
  guidelines: z.string().max(2000).optional().default(""),
  disclosure_response: z.string().max(500).optional().default(""),
});
export type PersonaInput = z.infer<typeof personaSchema>;

export const scriptSectionSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  content: z.string().min(1),
  expected_response_keywords: z.array(z.string()).default([]),
});
export type ScriptSectionInput = z.infer<typeof scriptSectionSchema>;

export const objectionSchema = z.object({
  id: z.string().min(1),
  trigger: z.string().min(1),
  response: z.string().min(1),
});
export type ObjectionInput = z.infer<typeof objectionSchema>;

export const scriptSchema = z.object({
  opening_variants: z.array(z.string().min(1)).min(1).max(20),
  sections: z.array(scriptSectionSchema).default([]),
  closing: z.string().min(1),
  objections: z.array(objectionSchema).default([]),
});
export type ScriptInput = z.infer<typeof scriptSchema>;

export const scenarioRuleSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  condition: z.object({
    when: z.enum(["intent_detected", "keyword_match", "sentiment", "custom"]),
    expression: z.string().min(1),
  }),
  action: z.object({
    type: z.enum(["transfer", "dispose", "callback", "continue"]),
    parameters: z.record(z.unknown()).default({}),
  }),
  priority: z.number().int().default(0),
});
export type ScenarioRuleInput = z.infer<typeof scenarioRuleSchema>;

// The scenario tree is persisted as JSONB; the visual builder writes a
// `{ rules, graph }` shape but other clients may write the older
// `{ rules: [scenarioRule, ...] }` form. We accept both.
export const scenarioTreeSchema = z.object({
  rules: z.array(z.unknown()).default([]),
  graph: z
    .object({ nodes: z.array(z.unknown()), edges: z.array(z.unknown()) })
    .optional(),
});
export type ScenarioTreeInput = z.infer<typeof scenarioTreeSchema>;

export const agentCreateSchema = z.object({
  name: z.string().min(1).max(200),
  language: z.string().min(2).max(10).default("en"),
  voice_id: z.string().uuid().nullable().optional(),
  kb_collection_id: z.string().uuid().nullable().optional(),
  persona: personaSchema,
  script: scriptSchema,
  scenario_tree: scenarioTreeSchema.default({ rules: [] }),
});
export type AgentCreateInput = z.infer<typeof agentCreateSchema>;

// ---------------------------------------------------------------------------
// Voice / KB / Vici
// ---------------------------------------------------------------------------

export const cloneVoiceSchema = z.object({
  name: z.string().min(1).max(200),
  ref_text: z.string().min(1).max(2000),
});

export const kbCreateSchema = z.object({
  name: z.string().min(1).max(200),
  description: z.string().max(2000).optional().default(""),
  embedding_model: z.string().default("BAAI/bge-base-en-v1.5"),
});

export const vicidialServerSchema = z.object({
  name: z.string().min(1),
  asterisk_host: z.string().min(1),
  asterisk_port: z.coerce.number().int().min(1).max(65535).default(5038),
  web_url: z.string().url(),
  ami_user: z.string().min(1),
  ami_pass: z.string().min(1),
  web_user_admin: z.string().min(1),
  web_pass: z.string().min(1),
});

export const deploymentCreateSchema = z.object({
  agent_id: z.string().uuid(),
  vicidial_server_id: z.string().uuid(),
  vici_user: z.string().min(1),
  vici_pass: z.string().min(1),
  phone_login: z.string().min(1),
  phone_pass: z.string().min(1),
  campaign_id: z.string().min(1),
  allowed_transfer_ingroups: z.array(z.string()).default([]),
});
