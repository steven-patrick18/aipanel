/**
 * Mirror of selected backend response shapes. Hand-maintained; long-term
 * generate from /api/openapi.json.
 */

export type Role = "admin" | "operator" | "viewer";

export interface UserPublic {
  id: string;
  tenant_id: string;
  email: string;
  role: Role;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  access_expires_at: string;
  refresh_expires_at: string;
  token_type: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type AgentStatus = "draft" | "ready" | "archived";

export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  persona: Record<string, any>;
  script: Record<string, any>;
  scenario_tree: Record<string, any>;
  voice_id: string | null;
  language: string;
  kb_collection_id: string | null;
  campaign_id: string | null;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

export type VoiceStatus = "pending" | "training" | "ready" | "error";

export interface Voice {
  id: string;
  tenant_id: string;
  name: string;
  sample_path: string | null;
  embedding_path: string | null;
  status: VoiceStatus;
  created_at: string;
}

export interface KnowledgeBase {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  embedding_model: string;
  created_at: string;
}

export interface KbDocument {
  id: string;
  kb_id: string;
  filename: string;
  content_hash: string;
  chunk_count: number;
  status: "pending" | "processing" | "ready" | "error";
  created_at: string;
}

export interface VicidialServer {
  id: string;
  tenant_id: string;
  name: string;
  asterisk_host: string;
  asterisk_port: number;
  web_url: string;
  ami_user: string;
  web_user_admin: string;
  created_at: string;
}

export type DeploymentStatus = "stopped" | "starting" | "running" | "error";

export interface Deployment {
  id: string;
  tenant_id: string;
  agent_id: string;
  vicidial_server_id: string;
  vici_user: string;
  phone_login: string;
  campaign_id: string;
  allowed_transfer_ingroups: string[];
  dispo_mapping: Record<string, any>;
  status: DeploymentStatus;
  last_heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallSummary {
  id: string;
  deployment_id: string;
  vici_uniqueid: string;
  vici_lead_id: string | null;
  phone_number: string | null;
  started_at: string;
  ended_at: string | null;
  duration_sec: number | null;
  outcome: string | null;
  dispo_code: string | null;
  transfer_target: string | null;
}

export interface CallEvent {
  id: string;
  call_id: string;
  ts: string;
  event_type: string;
  payload: Record<string, any>;
}

export interface TranscriptTurn {
  ts: string;
  role: "user" | "agent" | "system";
  text: string;
  extra: Record<string, any>;
}

export interface CallTranscript {
  call_id: string;
  turns: TranscriptTurn[];
}

export interface OverviewResponse {
  total_calls: number;
  avg_duration_sec: number;
  transfer_rate: number;
  dispo_breakdown: Record<string, number>;
  period_start: string;
  period_end: string;
}

export interface TimeseriesPoint {
  ts: string;
  calls: number;
  transfers: number;
  avg_duration_sec: number;
}

export interface TimeseriesResponse {
  bucket: "hour" | "day";
  points: TimeseriesPoint[];
}

export interface AgentRollup {
  agent_id: string;
  agent_name: string;
  total_calls: number;
  avg_duration_sec: number;
  transfer_rate: number;
  dispo_top: string | null;
}

export interface ServiceHealth {
  name: string;
  status: "ok" | "degraded" | "down";
  detail: string;
}

export interface SystemHealth {
  overall: string;
  services: ServiceHealth[];
  checked_at: string;
}

export interface NodeRow {
  id: string;
  hostname: string;
  role: "primary" | "secondary";
  services: string[];
  status: string;
  last_heartbeat_at: string | null;
  joined_at: string;
}

export interface LoginResponse {
  tokens: TokenPair;
  user: UserPublic;
}

export interface SafeConfig {
  panel_public_url: string;
  sip_listen_port: number;
  llm_model: string;
  stt_model: string;
  tts_backend: string;
}

export type CampaignStatus      = "draft" | "active" | "paused" | "archived";
export type CampaignMethodology =
  | "spin" | "bant" | "meddpicc"
  | "consultative" | "value_based" | "custom";

export interface MethodologySummary {
  key: CampaignMethodology;
  name: string;
  tagline: string;
  when_to_use: string;
}

export interface CallStage {
  name: string;
  goal: string;
  success_markers: string[];
}

export interface MethodologyDetail extends MethodologySummary {
  system_prompt: string;
  stages: CallStage[];
  priority_signals: string[];
  common_objections: Record<string, string>;
}

export interface Campaign {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  methodology: CampaignMethodology;
  objective: string;
  success_dispos: string[];
  kb_collection_id: string | null;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
  few_shot_updated_at: string | null;
  few_shot_count: number;
}

export interface FewShotExample {
  user: string;
  agent: string;
  score: number;
  call_id: string;
  mined_at: string;
}

export interface CampaignDetail extends Campaign {
  persona_template: Record<string, any>;
  script_template: Record<string, any>;
  few_shot_pool: FewShotExample[];
}

export interface CampaignMetrics {
  campaign_id: string;
  period_days: number;
  total_calls: number;
  successful_calls: number;
  conversion_rate: number;
  by_dispo: Record<string, number>;
  avg_duration_sec: number;
}
