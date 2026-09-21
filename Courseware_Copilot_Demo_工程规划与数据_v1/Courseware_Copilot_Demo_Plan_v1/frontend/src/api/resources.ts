import { parseResponse, request } from "./client";
import type {
  CandidateChange,
  CommitRequest,
  DeckSpec,
  DeckVersion,
  DocumentChunk,
  EditRequest,
  GenerateRequest,
  Job,
  JobAccepted,
  LessonPlan,
  ConfirmPlanRequest,
  MaterialList,
  MaterialUploadAccepted,
  RestoreRequest,
} from "../types/models";

const enc = encodeURIComponent;

export const jobsApi = {
  get: (jobId: string, signal?: AbortSignal) =>
    request<Job>("GET", `/jobs/${enc(jobId)}`, { signal }),
  cancel: (jobId: string, idempotencyKey: string) =>
    request<Job>("POST", `/jobs/${enc(jobId)}/cancel`, { idempotencyKey }),
};

export const materialsApi = {
  list: (projectId: string, signal?: AbortSignal) =>
    request<MaterialList>("GET", `/projects/${enc(projectId)}/materials`, { signal }),
  upload: (projectId: string, file: File, idempotencyKey: string) => {
    const form = new FormData();
    form.append("file", file);
    return fetchForm<MaterialUploadAccepted>(
      `/api/v1/projects/${enc(projectId)}/materials`,
      form,
      idempotencyKey,
    );
  },
};

async function fetchForm<T>(path: string, form: FormData, idempotencyKey: string): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
      "X-Request-ID": `web_${crypto.randomUUID()}`.slice(0, 128),
    },
    body: form,
  });
  return (await parseResponse(response)) as T;
}

export const plansApi = {
  create: (projectId: string, corpusRevision: number, idempotencyKey: string) =>
    request<JobAccepted>("POST", `/projects/${enc(projectId)}/plans`, {
      body: { corpus_revision: corpusRevision },
      idempotencyKey,
    }),
  get: (projectId: string, planId: string, signal?: AbortSignal) =>
    request<LessonPlan>(
      "GET",
      `/projects/${enc(projectId)}/plans/${enc(planId)}`,
      { signal },
    ),
  confirm: (
    projectId: string,
    planId: string,
    body: ConfirmPlanRequest,
    idempotencyKey: string,
  ) =>
    request<LessonPlan>(
      "POST",
      `/projects/${enc(projectId)}/plans/${enc(planId)}/confirm`,
      { body, idempotencyKey },
    ),
};

export const changesApi = {
  generate: (projectId: string, body: GenerateRequest, idempotencyKey: string) =>
    request<JobAccepted>("POST", `/projects/${enc(projectId)}/generations`, {
      body,
      idempotencyKey,
    }),
  get: (projectId: string, changeId: string, signal?: AbortSignal) =>
    request<CandidateChange>(
      "GET",
      `/projects/${enc(projectId)}/changes/${enc(changeId)}`,
      { signal },
    ),
  commit: (
    projectId: string,
    changeId: string,
    body: CommitRequest,
    idempotencyKey: string,
  ) =>
    request<DeckVersion>(
      "POST",
      `/projects/${enc(projectId)}/changes/${enc(changeId)}/commit`,
      { body, idempotencyKey },
    ),
};

export const deckApi = {
  get: (projectId: string, version: number | null, signal?: AbortSignal) =>
    request<DeckSpec>(
      "GET",
      `/projects/${enc(projectId)}/deck${version !== null ? `?version=${version}` : ""}`,
      { signal },
    ),
};

export const evidenceApi = {
  get: (projectId: string, chunkId: string, corpusRevision: number, signal?: AbortSignal) =>
    request<DocumentChunk>(
      "GET",
      `/projects/${enc(projectId)}/evidence/${enc(chunkId)}?corpus_revision=${corpusRevision}`,
      { signal },
    ),
};

export const editsApi = {
  create: (projectId: string, body: EditRequest, idempotencyKey: string) =>
    request<JobAccepted>("POST", `/projects/${enc(projectId)}/edits`, {
      body,
      idempotencyKey,
    }),
};

export const restoresApi = {
  create: (projectId: string, body: RestoreRequest, idempotencyKey: string) =>
    request<DeckVersion>("POST", `/projects/${enc(projectId)}/restores`, {
      body,
      idempotencyKey,
    }),
};
