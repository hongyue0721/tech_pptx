import AnyUI from "@any-design/anyui/vue";
import "@any-design/anyui/styles/index.css";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./router";
import "./styles/base.css";

createApp(App).use(AnyUI).use(router).mount("#app");
