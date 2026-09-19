import { ref } from "vue";

import { ApiError, api } from "../api/client";
import type { Project } from "../types/models";

export type LoadState = "loading" | "ready" | "failed" | "not_found" | "unauthorized";

export function useProject(projectId: string) {
  const project = ref<Project | null>(null);
  const state = ref<LoadState>("loading");
  const errorMessage = ref("");
  const controller = new AbortController();

  async function load(): Promise<void> {
    state.value = "loading";
    try {
      project.value = await api.getProject(projectId, controller.signal);
      state.value = "ready";
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        state.value = "unauthorized";
      } else if (err instanceof ApiError && err.status === 404) {
        state.value = "not_found";
      } else {
        state.value = "failed";
        errorMessage.value = err instanceof Error ? err.message : String(err);
      }
    }
  }

  void load();

  return { project, state, errorMessage, abort: () => controller.abort() };
}
