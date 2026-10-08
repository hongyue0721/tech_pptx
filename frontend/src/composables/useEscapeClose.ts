// 抽屉可访问性收口（FRONTEND_SPEC"抽屉 Escape 关闭、焦点返回"）：
// open 期间监听 Escape → onClose 负责关抽屉并把焦点还给触发元素。
import { onBeforeUnmount, watch } from "vue";

export function useEscapeClose(open: { value: boolean }, onClose: () => void): void {
  function handler(event: KeyboardEvent): void {
    if (event.key === "Escape" && open.value) {
      event.preventDefault();
      onClose();
    }
  }
  watch(
    open,
    (isOpen) => {
      if (typeof document !== "undefined") {
        document.removeEventListener("keydown", handler);
        if (isOpen) document.addEventListener("keydown", handler);
      }
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    if (typeof document !== "undefined") document.removeEventListener("keydown", handler);
  });
}
