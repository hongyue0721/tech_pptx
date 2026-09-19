import { createRouter, createWebHistory } from "vue-router";

import CreateProjectPage from "../pages/CreateProjectPage.vue";
import WorkspacePage from "../pages/WorkspacePage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "create", component: CreateProjectPage },
    { path: "/project/:id", name: "workspace", component: WorkspacePage, props: true },
  ],
});
