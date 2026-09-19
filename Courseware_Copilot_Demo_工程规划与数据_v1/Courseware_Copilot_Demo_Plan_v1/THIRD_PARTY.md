# 第三方组件与内容登记

这是规划阶段清单，不是完整法律意见或已完成软件物料表。实际引入前保存版本、来源URL、许可证文件、用途、是否修改、是否分发；锁定后补checksum。[docs/sources.md](docs/sources.md)

| 项目 | 已知信息 | 处理状态 |
|---|---|---|
| AnyUI | 仓库package声明MIT、版本0.5.2，Vue入口 | 候选；发布/安装/构建待实测，保留许可 |
| ppt-edit-skill | package1.3.0、作者binaryify；LICENSE版权Binaryify Zhuang、MIT | 候选；用户贡献边界待厘清，不冒充原创 |
| neo-ppt镜像/本地patched WASM | local-export README明确提到patched与no-sign | 授权/来源逐项待核验；不因root MIT自动放行，不在本包重分发 |
| PptxGenJS | 官方导出工具候选 | ppt-edit未过门禁时备选；实际license/version再核验 |
| pypdf | BSD-3-Clause许可证文件已读 | 默认解析候选；锁实际版本、保留NOTICE |
| PyMuPDF | 官方列AGPL和商业许可选择 | 不作为默认业务依赖，改用需批准许可策略 |
| Vue/Vite/FastAPI/Pydantic/jieba/rank-bm25 | 技术候选 | M0锁版本并核对实际分发许可，不凭记忆汇总 |
| 字体/图标 | 原则上系统字体与本地静态图标 | 每一项独立许可；不提交容器字体文件 |

本包demo文字为原创编排的教学演示材料，事实参考ST/Arm官方文档，课堂事件和活动时间为显式假设，不是实测板卡数据。没有复制整本教材、原厂插图、商标素材或上游源码。

允许把本包原创规划、模板和自编演示材料用于本项目开发、演示与参赛；第三方内容仍受其各自条件约束。不要把这里的规划附件当作官方教学教材/授权证书。自动化生成PDF时嵌入的字体子集用于文档显示，不提供任何独立字体文件。
