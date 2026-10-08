# F4 零外部请求实证（2026-09-21，浏览器 performance.getEntriesByType('resource') 导出）

检查方式：Playwright evaluate 过滤非 localhost:5173 资源。修复前基线：review 页加载触发
api.iconify.design 4 请求（fluent/ic/ph/si-glyph，AMessage.install 预取，commit e9a6446 前）。

1. review 页（change+version 正式视图，ADrawer 打开原文后关闭）：2026-09-21T03:24Z 实测 `[]`
2. materials 压力页（8 目标+长标题+5 资料，/project/100312d4f0c2fad6424303d030251a87/materials）：
   {"externalRequests":[],"count":0,"checkedAt":"2026-09-21T04:21:50.313Z"}
3. outline 页（plan 视图）：2026-09-21T03:55Z 导航 console 0 错误、网络清单仅 localhost API。

结论：docs/09 §1"禁运行时远端 Iconify/字体/图片"达成（消除手段=去 app.use 全量注册，
组件具名按需导入；见 main.ts 注释与 e9a6446）。
