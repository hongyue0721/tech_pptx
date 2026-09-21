export interface CourseBrief {
  topic: string;
  audience: string;
  duration_minutes: number;
  goals: string[];
  target_slides: number;
}

export interface CreateProjectRequest {
  course: CourseBrief;
  consent_to_cloud_processing: boolean;
}

export interface Project {
  id: string;
  course: CourseBrief;
  current_version: number;
  corpus_revision: number;
  active_job_id: string | null;
  consent_to_cloud_processing: boolean;
  created_at: string;
  updated_at: string;
}

export interface Health {
  status: "ok";
  service: "courseware-copilot";
  version: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id: string;
  details: Record<string, unknown>;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "blocked"
  | "interrupted";

export type JobStage =
  | "queued"
  | "parsing"
  | "retrieving"
  | "planning"
  | "generating"
  | "validating"
  | "rendering"
  | "exporting"
  | "previewing"
  | "finished";

export interface JobResultRef {
  type: "material" | "plan" | "change" | "artifact";
  id: string;
}

export interface Job {
  id: string;
  project_id: string;
  kind: "parse" | "plan" | "generate" | "edit" | "export";
  status: JobStatus;
  stage: JobStage;
  cancel_requested: boolean;
  base_version: number;
  corpus_revision: number;
  result_ref: JobResultRef | null;
  error: ErrorResponse | null;
  created_at: string;
  updated_at: string;
  llm_calls: number;
}

export interface JobAccepted {
  job_id: string;
}

export interface PageWarning {
  pdf_page: number;
  code: string;
  message: string;
}

export interface Material {
  id: string;
  project_id: string;
  original_name: string;
  sha256: string;
  status: "queued" | "parsing" | "ready" | "failed";
  pdf_pages: number | null;
  usable_pages: number | null;
  corpus_revision: number | null;
  warnings: PageWarning[];
  error_code: string | null;
}

export interface MaterialList {
  materials: Material[];
  corpus_revision: number;
}

export interface MaterialUploadAccepted {
  material_id: string;
  job_id: string | null;
  duplicate: boolean;
}

export interface DocumentChunk {
  chunk_id: string;
  project_id: string;
  document_id: string;
  corpus_revision: number;
  document_name: string;
  pdf_page: number;
  printed_page_label: string | null;
  page_start: number;
  page_end: number;
  text: string;
  text_sha256: string;
  extractor_version: string;
  tokenizer_version: string;
}

export interface EvidenceSpan {
  chunk_id: string;
  document_id: string;
  pdf_page: number;
  start: number;
  end: number;
  quote: string;
}

export interface Claim {
  id: string;
  text: string;
  kind: "direct" | "derived";
  evidence_refs: EvidenceSpan[];
  rationale: string | null;
}

export type LayoutName = "title" | "concept" | "two_column" | "process_example";

export type SlideBlock =
  | { type: "fact"; claim_id: string }
  | { type: "teaching"; text: string }
  | {
      type: "illustration";
      text: string;
      assumptions: string[];
      evidence_refs: EvidenceSpan[];
    };

export interface Slide {
  id: string;
  title: string;
  layout: LayoutName;
  blocks: SlideBlock[];
}

export interface DeckSpec {
  schema_version: string;
  project_id: string;
  version: number;
  corpus_revision: number;
  course: CourseBrief;
  claims: Claim[];
  slides: Slide[];
}

export interface DeckVersion {
  project_id: string;
  version: number;
  corpus_revision: number;
  parent_version: number;
  restored_from: number | null;
  created_at: string;
  content_sha256: string;
}

export interface ObjectiveCoverage {
  goal_index: number;
  status: "supported" | "partial" | "unsupported" | "conflict";
  chunk_ids: string[];
  note: string;
}

export interface PlanSlide {
  id: string;
  title: string;
  purpose: string;
  layout: LayoutName;
  goal_indices: number[];
  evidence_chunk_ids: string[];
}

export interface LessonPlan {
  id: string;
  project_id: string;
  corpus_revision: number;
  status: "draft" | "needs_material" | "confirmed" | "stale";
  coverage: ObjectiveCoverage[];
  slides: PlanSlide[];
  accepted_goal_indices: number[];
  created_at: string;
}

export interface ConfirmPlanRequest {
  corpus_revision: number;
  slides: PlanSlide[];
  accepted_goal_indices: number[];
  acknowledged: true;
}

export interface GenerateRequest {
  plan_id: string;
  base_version: number;
  corpus_revision: number;
}

export interface ClaimVerification {
  claim_id: string;
  locator_status: "located" | "invalid";
  semantic_status: "supported" | "partial" | "unsupported" | "conflict" | "not_checked";
  reason: string;
}

export interface UnboundAssertion {
  slide_id: string;
  field_path: string;
  text: string;
  reason: string;
}

export interface ValidationReport {
  schema_valid: boolean;
  relations_valid: boolean;
  layout_valid: boolean;
  claim_checks: ClaimVerification[];
  warnings: string[];
  can_commit: boolean;
  model_id: string | null;
  prompt_version: string;
  checked_at: string;
  raw_result_sha256: string | null;
  unbound_assertions: UnboundAssertion[];
}

export type CandidateStatus =
  | "ready"
  | "blocked"
  | "committed"
  | "discarded"
  | "stale";

export interface CandidateChange {
  id: string;
  project_id: string;
  base_version: number;
  corpus_revision: number;
  status: CandidateStatus;
  kind: "generation" | "edit";
  affected_slide_ids: string[];
  summary: string;
  candidate: DeckSpec;
  validation: ValidationReport;
  created_at: string;
}

export interface CommitRequest {
  base_version: number;
  corpus_revision: number;
  acknowledged: true;
}

export interface EditRequest {
  instruction: string;
  target_slide_ids: string[];
  base_version: number;
  corpus_revision: number;
}

export interface RestoreRequest {
  target_version: number;
  base_version: number;
  corpus_revision: number;
  acknowledged: true;
}
