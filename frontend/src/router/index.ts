import { createRouter, createWebHistory } from "vue-router";

import IntakePage from "../pages/IntakePage.vue";
import OutlinePage from "../pages/OutlinePage.vue";
import ReviewPage from "../pages/ReviewPage.vue";
import WorkspaceEntry from "../pages/WorkspaceEntry.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "intake", component: IntakePage },
    {
      path: "/project/:id",
      name: "workspace",
      // 兼容入口：按服务器真值（active_job_id/current_version）转入相应页；
      // 不猜 plan/change id——接口未提供"最新候选"查询，猜测即伪造定位状态。
      component: WorkspaceEntry,
      props: true,
    },
    { path: "/project/:id/materials", name: "materials", component: IntakePage, props: true },
    { path: "/project/:id/outline", name: "outline", component: OutlinePage, props: true },
    { path: "/project/:id/review", name: "review", component: ReviewPage, props: true },
  ],
});
