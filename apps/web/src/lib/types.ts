export type Role =
  | "patient"
  | "caregiver"
  | "doctor"
  | "front_desk"
  | "pharmacist"
  | "compliance"
  | "admin"
  | "service";

export interface Me {
  subject: string;
  roles: string[];
  primary_role: Role;
  patient_linked: boolean;
  patient_id: string | null;
  consent_id: string | null;
  clinic_ids: string[];
  locale: string;
  traffic_class: string;
  preferred_username?: string | null;
  display_name?: string | null;
  doctor_display_name?: string | null;
}

export interface CareContext {
  consent_id: string;
  patient_id: string;
  patient_name: string | null;
  scopes: string[];
  expires_at: string | null;
}

export interface Consent {
  id: string;
  patient_id: string;
  patient_name: string | null;
  grantor_subject: string;
  caregiver_subject: string;
  scopes: string[];
  purpose: string;
  status: string;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface DeletionRequest {
  id: string;
  status: string;
  reason: string | null;
  requested_at: string;
  scheduled_for: string;
  completed_at: string | null;
}

export interface GridMeta {
  total: number;
  page: number;
  page_size: number;
  sort: string;
  order: "asc" | "desc";
  pages: number;
}

export interface GridResponse<T> {
  items: T[];
  meta: GridMeta;
}

export interface Meta {
  app: {
    name: string;
    version: string;
    environment: string;
    profile: string;
    locales: string[];
    default_locale: string;
    timezone?: string;
  };
  clinics: { code: string; name: string; timezone: string }[];
  specialties: { code: string; en: string; hi: string; mr: string }[];
  features: Record<
    string,
    { value: boolean; source: string; class: string; owner: string; expires: string | null }
  >;
  purposes: Record<string, { alias: string; egress: string; timeout_seconds?: number }>;
  adapters: Record<
    string,
    { status: string; adapter: string; mode?: string; certified?: boolean }
  >;
  disclaimer: string;
  capabilities: Record<string, boolean | string | { certified?: boolean }>;
}

export type SourceType =
  | "document"
  | "tool"
  | "memory"
  | "conversation"
  | "rule"
  | "general";

export interface SourceRef {
  id: string;
  type: SourceType;
  title: string;
  locator?: string | null;
  observed_at?: string | null;
  status: "resolved" | "stale" | "missing" | "forbidden";
  snippet?: string | null;
  metadata?: Record<string, string>;
}

export interface ChatSession {
  id: string;
  title: string;
  title_source?: string;
  locale: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  language: string;
  sources: SourceRef[];
  safety?: {
    red_flag?: boolean;
    rule_ids?: string[];
    severity?: string;
    guidance?: string;
    handoff_id?: string;
    blocked?: boolean;
    code?: string;
    document_indexed?: boolean;
    document_id?: string;
  };
  trace_id: string | null;
  model_alias: string | null;
  created_at: string;
}

export interface ChatInterrupt {
  run_id: string;
  interrupt_id: string;
  interrupt_type: string;
  payload: {
    specialty_code?: string | null;
    specialty_label?: string | null;
    preferred_starts_at?: string | null;
    choice_expires_at?: string | null;
    candidates?: Array<{
      doctor_name?: string;
      name?: string;
      clinic_code?: string;
      specialty_code?: string;
      locale?: string;
      starts_at?: string | null;
      next_slot?: string | null;
      label?: string | null;
      duration_minutes?: number;
    }>;
  };
}

export interface HeldAppointment {
  id: string;
  doctor_name: string;
  clinic_code: string;
  specialty_code: string;
  starts_at: string;
  duration_minutes: number;
  status: string;
  source: string;
  hold_expires_at: string;
}

export interface SendResult {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  red_flag?: { rule_ids: string[]; severity: string; guidance: string } | null;
  run_id?: string | null;
  interrupt?: ChatInterrupt | null;
  appointment?: HeldAppointment | null;
}

export interface Appointment {
  id: string;
  patient_id: string | null;
  patient_display_name?: string | null;
  clinic_code: string;
  doctor_name: string;
  specialty_code: string;
  specialty_label?: string | null;
  starts_at: string;
  duration_minutes: number;
  status: string;
  source?: "assistant" | "front_desk" | string;
  traffic_class: string;
  visit_kind?: "first" | "repeat" | "unknown" | null;
  no_show_risk?: number | null;
  no_show_band?: "low" | "medium" | "high" | string | null;
  waitlist_suggested?: boolean;
  confirm_by_reply?: boolean;
  waitlist_status?: "open" | "claimed" | "closed" | string | null;
  waitlist_owner_subject?: string | null;
  waitlist_claimed_at?: string | null;
  waitlist_closed_at?: string | null;
  waitlist_resolution?: "kept" | "offered" | "dismissed" | string | null;
  waitlist_notes?: string | null;
  waitlist_offer_patient_id?: string | null;
  waitlist_offer_appointment_id?: string | null;
  created_at: string;
}

export interface WaitlistItem extends Appointment {
  offer_patient_display_name?: string | null;
}

export interface AuditChainStatus {
  status: "ok" | "broken" | "empty" | "unhashed" | "never_run" | string;
  job_status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  detail?: {
    checked?: number;
    unhashed?: number;
    broken_count?: number;
    tip_hash?: string | null;
    verified_at?: string;
    broken?: { id: string; action: string; issues: string[] }[];
  };
  error_code?: string | null;
}

export interface PreconsultBrief {
  status: string;
  as_of?: string;
  patient_id?: string;
  appointment?: {
    id: string;
    starts_at: string;
    doctor_name: string;
    clinic_code: string;
    specialty_code: string;
    specialty_label?: string | null;
    status: string;
    no_show_risk?: number | null;
    no_show_band?: string | null;
    waitlist_suggested?: boolean;
  } | null;
  active_medications?: {
    id: string;
    name: string;
    dose?: string | null;
    frequency?: string | null;
    status: string;
  }[];
  documents?: {
    id: string;
    title: string;
    kind: string;
    status: string;
    citation: string;
    quarantined?: boolean;
    created_at: string;
  }[];
  last_signed_note?: {
    note_id: string;
    signed_at?: string | null;
    title: string;
    assessment?: string[];
    plan?: string[];
    follow_up?: string | null;
    content_hash?: string | null;
  } | null;
  upcoming_appointments?: {
    id: string;
    starts_at: string;
    doctor_name: string;
    status: string;
    no_show_band?: string | null;
  }[];
  provenance?: { sources: string[]; synthetic: boolean };
}

export interface Doctor {
  doctor_name: string;
  specialty_code: string;
  specialty_label: string;
  clinic_code: string;
  appointments: number;
  last_seen_at: string | null;
}

export interface SlotsResponse {
  doctor_name: string;
  clinic_code: string;
  timezone: string;
  generated_for_days: number;
  slots: string[];
}

export interface Patient {
  id: string;
  display_name: string | null;
  locale: string;
  linked: boolean;
  created_at: string;
}

export interface DocumentRow {
  id: string;
  patient_id: string;
  kind: string;
  title: string;
  content_type: string;
  size_bytes: number;
  language: string;
  status: string;
  error_code: string | null;
  page_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentChunk {
  id: string;
  document_id: string;
  chunk_index: number;
  page: number | null;
  section: string | null;
  content: string;
}

export interface SearchHit {
  document_id: string;
  document_title: string;
  chunk_id: string;
  chunk_index: number;
  page: number | null;
  snippet: string;
  score: number;
  source: SourceRef;
}

export interface AskResult {
  question: string;
  patient_id: string;
  status: "answered" | "no_evidence" | "model_unavailable";
  answer: string;
  sources: SourceRef[];
  evidence_count: number;
  grounded: boolean;
  model_alias: string | null;
  note: string | null;
}

export interface Medication {
  id: string;
  name: string;
  dose: string | null;
  frequency: string | null;
  status: string;
  started_on: string | null;
  ended_on: string | null;
  source_document_id: string | null;
}

export interface NotificationRow {
  id: string;
  patient_id: string | null;
  recipient_subject: string;
  recipient_role: string;
  template_id: string;
  template_version: number;
  channel: string;
  status: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface DeliveryRow {
  id: string;
  channel: string;
  status: string;
  attempts: number;
  last_error_code: string | null;
  provider_message_id: string | null;
  scheduled_at: string;
  sent_at: string | null;
}

export interface NotificationDetail extends NotificationRow {
  deliveries: DeliveryRow[];
}

export interface Template {
  id: string;
  version: number;
  channels: string[];
  clinical_detail: boolean;
}

export interface ContactChannel {
  id: string;
  subject: string;
  patient_id: string | null;
  channel: string;
  address: string;
  verified: boolean;
  opt_in: boolean;
  workspace_id: string | null;
  created_at: string;
}

export interface Encounter {
  id: string;
  patient_id: string;
  patient_display_name: string | null;
  doctor_subject: string;
  doctor_name: string;
  clinic_code: string;
  appointment_id: string | null;
  kind: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  latest_run_id: string | null;
  latest_run_status: string | null;
  note_id: string | null;
}

export interface TranscriptTurn {
  id: string;
  turn_index: number;
  speaker: string;
  start_ms: number;
  end_ms: number;
  text: string;
  language: string;
}

export interface Transcript {
  id: string;
  encounter_id: string;
  status: string;
  source: string;
  language: string;
  duration_ms: number | null;
  error_code: string | null;
  audio_deleted_at: string | null;
  created_at: string;
  turns: TranscriptTurn[];
}

export interface DraftLine {
  text: string;
  source_turn_ids: number[];
  unsourced: boolean;
}

export interface MedicineDraft {
  name: string;
  dose?: string | null;
  frequency?: string | null;
  duration?: string | null;
  instructions?: string | null;
  source_turn_ids: number[];
  unsourced: boolean;
  stock?: {
    status?: string;
    drug_name?: string;
    quantity?: number | null;
    as_of?: string | null;
    source?: string;
    stale?: boolean;
    reason?: string;
  };
}

export interface ScribeDraft {
  id: string;
  revision: number;
  schema_version: string;
  content: {
    subjective: DraftLine[];
    objective: DraftLine[];
    assessment: DraftLine[];
    plan: DraftLine[];
    follow_up: DraftLine | null;
    medicines: MedicineDraft[];
  };
  created_at: string;
}

export interface ScribeSource {
  id: string;
  field: string;
  line_index: number;
  source_type: string;
  source_ref: Record<string, unknown>;
  status: string;
  as_of: string | null;
}

export interface ScribeRun {
  id: string;
  encounter_id: string;
  transcript_id: string;
  status: string;
  revision: number;
  model_alias: string | null;
  trace_id: string | null;
  error_code: string | null;
  error_detail: string | null;
  rejection_reason: string | null;
  rejection_category: string | null;
  red_flag_ids: string[];
  started_at: string;
  completed_at: string | null;
  draft: ScribeDraft | null;
  sources: ScribeSource[];
  red_flags: { rule_id: string; name: string; severity: string; guidance: string }[];
  elapsed_seconds: number | null;
}

export interface SignatureResult {
  note_id: string;
  version: number;
  content_hash: string;
  signed_at: string;
  stock_flags: { name: string; stock?: { status?: string } }[];
  patient_notified: boolean;
}

export interface NoteRow {
  id: string;
  encounter_id: string;
  patient_id: string;
  patient_display_name: string | null;
  author_subject: string;
  status: string;
  title: string;
  language: string;
  current_version: number;
  signed_by: string;
  signed_at: string;
  signed_hash: string;
  content?: ScribeDraft["content"] | null;
  sources?: ScribeSource[];
  metadata_only: boolean;
}

export interface NoteVersion {
  version: number;
  content_hash: string;
  parent_version: number | null;
  signed_by: string;
  signed_at: string;
  signature_ref: Record<string, unknown>;
}

export interface ReviewTask {
  id: string;
  patient_id: string | null;
  patient_display_name: string | null;
  created_by_subject: string;
  assigned_role: string;
  reason: string;
  status: string;
  owner_subject: string | null;
  resource_type: string | null;
  resource_id: string | null;
  due_at: string | null;
  resolution: string | null;
  closed_at: string | null;
  created_at: string;
}

export interface MetricTile {
  id: string;
  version?: number;
  label: string;
  description?: string;
  source: string;
  formula?: string;
  dimensions?: string[];
  freshness_hours?: number;
  unit: string;
  value: number | string | null;
  status: string;
  suppressed: boolean;
  note?: string;
  as_of: string;
}

export interface OverviewResponse {
  period: { days: number; start: string; end: string };
  as_of: string;
  small_cell_minimum: number;
  tiles: MetricTile[];
  active_users_by_role: { role?: string; count?: number }[];
  traffic_class: string;
}

export interface TilesResponse {
  period?: { days: number; start: string; end: string };
  as_of?: string;
  tiles: MetricTile[];
  [key: string]: unknown;
}

export interface FinOpsResponse {
  period: { days: number; start: string; end: string };
  status: string;
  traffic_class: string;
  observed: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
  };
  by_purpose: { purpose: string; calls: number; cost_usd: number; prompt_tokens?: number; completion_tokens?: number }[];
  monthly_run_rate_usd: number;
  budgets_usd: Record<string, number>;
  price_version: string;
  price_basis_date: string;
  fx_usd_inr: number;
  finops_model_version: string;
  reconciliation: { status: string; note: string };
  as_of: string;
}

export interface WhatIfResponse {
  label: "estimate";
  model_version: string;
  price_basis_date: string;
  profile: string;
  hosting: string;
  horizon_months: number;
  currency: string;
  fx_usd_inr: number;
  assumptions: Record<string, number | string | boolean>;
  capex_inr_lakh: Record<string, number>;
  opex_inr_month: Record<string, number>;
  tco_inr_lakh: Record<string, number>;
  revenue_inr_lakh: number | null;
  gross_margin_pct: number | null;
  unit_economics: Record<string, number | null>;
  growth_curve: { month?: number; users?: number; cost_usd?: number; [key: string]: unknown }[];
  notes: string[];
}

export interface InsightResponse {
  generator: string;
  ai_generated: boolean;
  note: string;
  as_of: string;
  items: {
    id: string;
    area: string;
    recommendation: string;
    impact: string;
    confidence: string;
    effort: string;
    owner: string;
    status: string;
    advisory: boolean;
    evidence: string[];
  }[];
}

export interface EvalRunSummary {
  id: string;
  suite: string;
  framework: string;
  framework_version: string;
  status: string;
  dataset_hash: string;
  git_sha: string | null;
  prompt_version: string | null;
  graph_version: string | null;
  judge_alias: string | null;
  case_count: number;
  passed_cases: number;
  failed_cases: number;
  metrics: Record<string, number>;
  artifact_key: string | null;
  error_message: string | null;
  created_at: string;
}

export interface EvaluationsResponse {
  runs: EvalRunSummary[];
  metrics: MetricTile[];
  frameworks: { rag: string; non_rag: string };
  status: string;
  as_of: string;
}

export interface FlagRow {
  key: string;
  value: boolean;
  default: boolean;
  source: string;
  flag_class: string;
  owner: string;
  expires: string | null;
  description: string;
  runtime_changeable: boolean;
}

export interface AuditEvent {
  id: string;
  actor_subject: string;
  actor_role: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  patient_id?: string | null;
  trace_id: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}
