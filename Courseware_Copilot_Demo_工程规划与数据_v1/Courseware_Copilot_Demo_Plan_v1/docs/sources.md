# 来源与核实边界

核实日期：2026-09-18。以下链接支撑外部事实；架构、限额、工时是本项目设计，不是官方强制要求。来源并不证明本项目已经运行。私有仓库内容未在包内转载，未修改或推送原仓库。

## S01 · 华为命题页面

来源：<https://cy.ncss.cn/mtcontest/detail?id=2c93f4c6a00f063201a03d77f6721089>

性质：企业原始题面。

用途：教育场景；全程码道开发；开发记录、Demo视频、原创Skill与AtomGit；云端部署目标。

## S02 · 2026产业赛道方案（高校转载官方附件）

来源：<https://cxcy.cczu.edu.cn/_upload/article/files/1f/f5/70bf69134a32b315af4da124b331/11d2a896-6aa1-4266-80f1-d83e864ebc83.pdf>

性质：官方方案附件，已查阅4页。

用途：团队3—15人且须实际核心成员；9月25日12时截止；揭榜项目少于5项的命题原则上不列入后续评审。

## S03 · 码道CLI：自定义模型

来源：<https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_00022.html>

性质：华为官方，页面更新2026-09-10。

用途：Chat Completions / Anthropic Messages；席位与部分套餐管理员权限；自定义模型配置。

## S04 · 码道：技能用户指南

来源：<https://support.huaweicloud.com/intl/zh-cn/usermanual-codeartsagent/codeartsagent_ug_0024.html>

性质：华为官方IDE指南。

用途：SKILL.md元数据、目录；本地项目目录；ZIP导入上限5M。不能直接当CLI所有行为的保证。

## S05 · 码道CLI：命令

来源：<https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0034.html>

性质：华为官方。

用途：models、session list、export；CLI的SDD命令不带斜杠；仍以安装版本help为准。

## S06 · 码道SDD标准工作流

来源：<https://support.huaweicloud.com/intl/zh-cn/bestpractice-codeartsagent/codeartsagent_bp_0011.html>

性质：华为官方。

用途：spec→design→tasks→实现，阶段确认。

## S07 · 什么是码道CLI

来源：<https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0001.html>

性质：华为官方。

用途：支持Ubuntu 22.04/24.04等；不把未列出的Arch说成已受支持。

## S08 · AnyUI package.json

来源：<https://github.com/any-design/anyui/blob/main/package.json>

性质：GitHub连接器只读核查，blob 88dd904f4b2564341e8187084b3551b527a69a16。

用途：仓库版本0.5.2、Vue入口和peerDependencies；不等于npm包已安装验证。

## S09 · AnyUI README与组件源码

来源：<https://github.com/any-design/anyui>

性质：此前当前会话已读取README及AUpload/ASplit/AChat源码。

用途：WIP；Vue用法；Upload只是文件选择、Split不是拖拽分栏、Chat不是业务Agent。

## S10 · ppt-edit包元数据

来源：<https://github.com/hongyue0721/ppt-edit-skill/blob/main/package.json>

性质：私有仓库连接器只读，blob 0d522c1e7f16cb93a79b24ded2d59996f719dc13。

用途：1.3.0；作者字段binaryify；独立核查贡献来源，字段本身不是作者归属判决。

## S11 · ppt-edit local-export说明

来源：<https://github.com/hongyue0721/ppt-edit-skill/blob/main/skills/ppt-edit/scripts/local-export/README.md>

性质：私有仓库连接器只读，blob 8c0e4c006ccee71649bd994e6ec4befa89e922a5。

用途：说明存在patched WASM。分发前必须明确其上游来源、许可、可复现构建及使用授权，不直接背书。

## S12 · ppt-edit LICENSE

来源：<https://github.com/hongyue0721/ppt-edit-skill/blob/main/LICENSE>

性质：私有仓库连接器只读，blob acdaf25b17b3e0367c525ba2509abef05962876c。

用途：根目录MIT声明；不能自动覆盖未知第三方编辑器、WASM和素材。

## S13 · pypdf LICENSE

来源：<https://github.com/py-pdf/pypdf/blob/main/LICENSE>

性质：GitHub连接器已读。

用途：BSD式三条款；分发保留许可与声明。

## S14 · pypdf文本提取

来源：<https://pypdf.readthedocs.io/en/stable/user/extract-text.html>

性质：官方文档。

用途：文本提取不是OCR；布局、字符顺序及扫描件限制。

## S15 · PyMuPDF许可说明

来源：<https://pymupdf.readthedocs.io/en/latest/about.html>

性质：官方文档License and Copyright。

用途：AGPL/商业双许可；此前未评估许可就锁定是不充分的。

## S16 · PptxGenJS

来源：<https://gitbrent.github.io/PptxGenJS/>

性质：项目官方文档。

用途：备选PPTX生成实现；本轮未安装/未运行。

## S17 · Vite Getting Started

来源：<https://vite.dev/guide/>

性质：官方文档。

用途：Node兼容要求20.19+或22.12+；不能沿用ppt-edit的Node18最低要求给整个项目。

## S18 · FastAPI Background Tasks

来源：<https://fastapi.tiangolo.com/tutorial/background-tasks/>

性质：官方文档。

用途：支持响应后任务；不能因此推导持久化任务队列或崩溃恢复保证。

## D01 · STM32 Cortex-M4 PM0214 Rev10

来源：<https://www.st.com/resource/en/programming_manual/pm0214-stm32-cortexm4-mcus-and-mpus-programming-manual-stmicroelectronics.pdf>

性质：ST原始手册；已查看41—43页图像与相关文本。

用途：异常进入/返回、优先级与分组。演示讲义是重新编写的简化材料，不分发官方手册全文。

## D02 · CMSIS-Core Interrupts and Exceptions (NVIC)

来源：<https://arm-software.github.io/CMSIS_6/main/Core/group__NVIC__gr.html>

性质：Arm官方API文档。

用途：NVIC优先级、pending/active及CMSIS接口。

## D03 · Cutting Through the Confusion with Arm Cortex-M Interrupt Priorities

来源：<https://developer.arm.com/community/arm-community-blogs/b/embedded-and-microcontrollers-blog/posts/cutting-through-the-confusion-with-arm-cortex-m-interrupt-priorities>

性质：Arm官方技术社区署名技术文章。

用途：优先级数值与紧迫性、CMSIS参数对齐；只用事实进行独立编写，不复制文章或图。

## 尚未获得的证据

学校截止/推荐窗口、命题当前有效揭榜数、码道账号席位和自定义模型权限、比赛对CLI加自定义推理模型的书面口径、实际模型协议/额度/费用、完整导出依赖许可、AnyUI registry可安装性、实际云部署与Office打开测试均未验证。容器对npm/PyPI域名解析失败，不以GitHub中的版本号替代安装成功。
