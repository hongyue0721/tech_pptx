# T11-F4 独立 Review 记录（2026-09-21）

- 执行模型：**huaweicloud/qwen3.8-flash**（Task 子代理干净会话，继承主会话模型，显式标注）。
- 审查方式：只读子代理，审 F4 diff（database.py connect 改动、test_database_thread_safety.py 新增、main.ts 去全量注册 e9a6446）+ 全局四项假捷径扫描（frontend/src 全部生产代码）+ 后端修复自洽性 + main.ts 回归。
- 结论：**1 阻塞 + 3 非阻塞**，全部当场闭环。

## 阻塞项与闭环

| # | 问题 | 闭环 |
|---|---|---|
| B1 | `check_same_thread=False` 的安全性 100% 押在 `sqlite3.threadsafety==3`，前提仅存注释/docstring，无运行时校验——threadsafety<3 环境会静默失去保护 | `connect()` 开头 `threadsafety!=3 → RuntimeError` 拒绝启动；测试文件顶置 assert；定向+全量 534 绿复验 |

## 非阻塞项处置（全当场闭环）

- N1：反例测试 docstring 归因错位（自称"回退守卫"实为"必要性论证"，回退时它仍绿；真正守卫是两个调生产 connect() 的正向测试，回退实证变红）。docstring 修正归位。
- N2：iconify 零请求实测证据未归档 → docs/screenshots/f4/network-zero-external.md（三页 performance entries 导出+时间戳）。
- N3：docs/09 §9 记录的闭环方式（本地打包/禁用图标）与实际手段（去全量注册）不一致 → 已补记实际手段。

## Reviewer 确认 CLOSED（要点）

- 全局四项：①未接 API 零伪成功（client.ts 非 2xx 必抛；导出 disabled 无 @click；commit await 成功才 push）②localStorage/sessionStorage/indexedDB 全 src 零命中③无硬编码演示答案（枚举分支非特判；.pdf 为格式校验）④display:none 仅纯响应式抽屉切换、功能不丢失。
- 后端修复自洽：get_conn 每请求连接与线程池/teardown 模式对症；worker 独立连接中性兼容；并发写=每请求连接+WAL+busy_timeout+CAS+worker flock 四层论据成立。
- main.ts 回归：模板 A* 标签与具名 import 一一对应，无全局注册依赖残留。

## 留痕

- 本轮抓到的是**后端生产 bug**（并发 GET 500，TestClient 结构上测不到）——"Fake/单线程测试掩盖生产路径"教训第三例（前两例：OUTPUT_SCHEMAS 注册缺失、prompt 契约字面错位）。
