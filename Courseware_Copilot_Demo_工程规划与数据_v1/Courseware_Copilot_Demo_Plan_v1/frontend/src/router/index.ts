import { createRouter, createWebHistory } from "vue-router";

import IntakePage from "../pages/IntakePage.vue";
import OutlinePage from "../pages/OutlinePage.vue";
import ReviewPage from "../pages/ReviewPage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "intake", component: IntakePage },
    {
      path: "/project/:id",
      name: "workspace",
      // 兼容入口：不猜 plan/change，由页面按服务端 current_version/active_job_id 转入。
      redirect: (to) => ({ name: "materials", params: { id: String(to.params.id) } }),
    },
    { path: "/project/:id/materials", name: "materials", component: IntakePage, props: true },
    { path: "/project/:id/outline", name: "outline", component: OutlinePage, props: true },
    { path: "/project/:id/review", name: "review", component: ReviewPage, props: true },
  ],
});
