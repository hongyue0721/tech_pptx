<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import type { CreateProjectRequest } from "../types/models";

const router = useRouter();

const topic = ref("");
const audience = ref("");
const durationMinutes = ref(45);
const goalsText = ref("");
const targetSlides = ref(8);
const consent = ref(false);
const submitting = ref(false);
const formError = ref("");
const fieldErrors = ref<Record<string, string>>({});

function parseFieldErrors(err: ApiError): Record<string, string> {
  const out: Record<string, string> = {};
  const fields = (err.details as { fields?: Array<{ location: (string | number)[]; message: string }> }).fields;
  if (Array.isArray(fields)) {
    for (const f of fields) {
      const key = f.location.filter((p) => typeof p === "string").join(".");
      out[key] = f.message;
    }
  }
  return out;
}

async function submit(): Promise<void> {
  submitting.value = true;
  formError.value = "";
  fieldErrors.value = {};
  const goals = goalsText.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const body: CreateProjectRequest = {
    course: {
      topic: topic.value,
      audience: audience.value,
      duration_minutes: durationMinutes.value,
      goals,
      target_slides: targetSlides.value,
    },
    consent_to_cloud_processing: consent.value,
  };
  try {
    const project = await api.createProject(body, crypto.randomUUID());
    await router.push({ name: "workspace", params: { id: project.id } });
  } catch (err) {
    if (err instanceof ApiError) {
      formError.value = `${err.message}（${err.code}）`;
      fieldErrors.value = parseFieldErrors(err);
    } else {
      formError.value = String(err);
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <main class="create-page">
    <h1>创建课件项目</h1>
    <form @submit.prevent="submit">
      <div class="field">
        <label for="topic">课程主题</label>
        <input id="topic" v-model="topic" maxlength="120" required />
        <p v-if="fieldErrors['course.topic']" class="field-error">{{ fieldErrors['course.topic'] }}</p>
      </div>
      <div class="field">
        <label for="audience">授课对象</label>
        <input id="audience" v-model="audience" maxlength="120" required />
      </div>
      <div class="field">
        <label for="duration">课时（分钟，10—120）</label>
        <input id="duration" v-model.number="durationMinutes" type="number" min="10" max="120" required />
      </div>
      <div class="field">
        <label for="goals">教学目标（每行一条，最多8条）</label>
        <textarea id="goals" v-model="goalsText" rows="4" required></textarea>
      </div>
      <div class="field">
        <label for="slides">目标页数（4—12）</label>
        <input id="slides" v-model.number="targetSlides" type="number" min="4" max="12" required />
      </div>
      <div class="field consent">
        <input id="consent" v-model="consent" type="checkbox" required />
        <label for="consent">
          我知悉：云模型模式下课程资料将经服务端处理；本地解析不向外发送内容。
        </label>
      </div>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <button type="submit" :disabled="submitting">
        {{ submitting ? "创建中…" : "创建项目" }}
      </button>
    </form>
  </main>
</template>

<style scoped>
.create-page {
  max-width: 640px;
  margin: 2rem auto;
  padding: 0 1rem;
}
.field {
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.field.consent {
  flex-direction: row;
  align-items: flex-start;
}
.field label {
  font-weight: 600;
}
input,
textarea {
  font: inherit;
  padding: 0.4rem;
  border: 1px solid #bbb;
  border-radius: 4px;
}
.field-error,
.form-error {
  color: #b3261e;
  margin: 0;
}
button {
  font: inherit;
  padding: 0.5rem 1.5rem;
  background: #1a56c4;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
