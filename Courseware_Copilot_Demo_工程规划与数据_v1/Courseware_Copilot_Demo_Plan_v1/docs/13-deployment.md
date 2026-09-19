# 运行环境与云端交付

## 目标拓扑

单台Ubuntu主机，同源Nginx静态前端和/api/v1反代FastAPI；SQLite与项目文件位于私有本地磁盘。单API进程内一个受管Worker；不可直接把uvicorn workers改成多个，否则需要重新设计锁、任务领取和数据所有权。

建议验收起点2—4 vCPU、4—8GiB内存、20GiB可用盘，是容量建议不是最低兼容性承诺。无需GPU；云API费用另算。Chromium存在时优先8GiB并实际测峰值。华为云ECS是演示优选部署方案，不把“云部署”自行扩大成官方强制购买某型号ECS。[S01]

## 环境锁定

M0记录Ubuntu版本/架构、Python3.11或3.12、Node22.12+候选、实际包版本。Vite当前文档要求Node20.19+或22.12+，不能以ppt-edit的Node18门槛代替前端要求。[S17]

包只在可信构建阶段安装，使用lockfile和固定依赖。禁止请求过程中npx latest、pip install、远程字体或自动下载浏览器。requirements/lock与前端lock进入Git，真实.env不进入。整个镜像/目录的构建结果可复现，不拿本机home里偶然存在的Skill当系统依赖。

## 上线顺序

先本地可离线启动结构预览和fixture测试；然后在授权预算内接真实APP模型；再在目标Ubuntu导出PPTX；最后公网保护演示。公网发布属于负责人确认项，未经允许不自动创建收费资源。

用专用非root用户运行服务；前后端同源；本地后端端口仅loopback；对外只开必要HTTP(S)。TLS证书、域名或已有平台HTTPS入口由负责人提供；没有可信HTTPS入口时不公开发Basic Auth凭据。不要以永久关闭TLS验证排错。

启动流程：校验配置→检查磁盘/Schema版本→独占data-dir锁→清理临时文件→标记遗留job为interrupted→启动Worker→ready。/health不调用外部模型；必要时新增/ready必须同步OpenAPI。

## 运行与观察

systemd管理重启；禁止生产reload。日志含request/job/version/stage与耗时，敏感字段脱敏。单项目上限和全局磁盘上限同时设，预览/导出缓存有限额；空间不足明确拒绝新任务，不删除教师有效版本来腾空间。

备份SQLite需要一致性方式，不能复制正在写入的单个db忽略WAL。备份与项目文件version目录配套；恢复验证引用与产物存在。Demo可采用停服务后全目录备份，避免额外工程。

## 交付验证

从干净环境安装；上传本包inputs两份资料；真实生成、编辑、来源、导出、PPT软件打开；再重启服务恢复项目；再测试扫描件/取消/冲突。保留视频及实际命令记录。

Docker是可选封装，不为赶进度引Kubernetes、RDS、Redis或对象存储。若不做Docker，提供systemd/Nginx示例和一页可复现安装记录同样要经过新环境复测。

本次规划包不含已运行的ECS、不分配公网端口、不创建任何云资源、不声称已部署。
