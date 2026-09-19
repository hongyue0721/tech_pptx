import { createApp, ref } from 'vue'
const app = createApp({
  setup() {
    const msg = ref('T02 Vue+Vite 构建探针：中文渲染正常')
    return { msg }
  },
  template: '<h1>{{ msg }}</h1>'
})
app.mount('#app')
