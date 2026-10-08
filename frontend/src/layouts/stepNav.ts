import { computed } from "vue";
import { useRoute } from "vue-router";

import type { Project } from "../types/models";

export const STEPS = [
  { key: "materials", index: "01", label: "资料设置" },
  { key: "outline", index: "02", label: "大纲确认" },
  { key: "review", index: "03", label: "课件审阅" },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

export function useStepNav(projectId: () => string | undefined) {
  const route = useRoute();
  const active = computed<StepKey>(() => {
    const name = String(route.name ?? "");
    if (name === "outline") return "outline";
    if (name === "review") return "review";
    return "materials";
  });
  const steps = computed(() =>
    STEPS.map((s) => ({
      ...s,
      to: projectId()
        ? { name: s.key, params: { id: projectId() } }
        : { name: "intake" },
      enabled: Boolean(projectId()),
    })),
  );
  return { active, steps };
}

export function projectSummary(project: Project | null): string {
  if (!project) return "";
  return `${project.course.topic} · ${project.current_version > 0 ? `正式 v${project.current_version}` : "尚无正式版本"}`;
}
