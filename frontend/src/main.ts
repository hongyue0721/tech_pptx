import "@any-design/anyui/styles/index.css";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./router";
import "./styles/base.css";

// 不 app.use(AnyUI) 全量注册：AMessage.install 会 loadIcons 预取远程 Iconify
// 图标（违反 docs/09 §1 禁运行时远端图标）；组件一律具名导入按需使用。
createApp(App).use(router).mount("#app");
