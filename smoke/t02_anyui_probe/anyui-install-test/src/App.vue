<script setup lang="ts">
import { toast } from "@any-design/anyui";
import { ref } from "vue";

const text = ref("AnyUI 0.5.2 安装探针");
const drawerOpen = ref(false);

function ping(): void {
  toast({ content: "探针按钮被点击" });
}
</script>

<template>
  <div style="padding: 2rem">
    <AInput v-model="text" placeholder="输入框" />
    <AButton type="primary" @click="ping">按钮</AButton>
    <AButton @click="drawerOpen = true">打开抽屉</AButton>
    <ADrawer v-model="drawerOpen" title="来源抽屉">
      <p>抽屉内容</p>
    </ADrawer>
  </div>
</template>
