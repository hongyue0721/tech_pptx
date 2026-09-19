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
