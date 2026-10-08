# 工作流与目标CLI契约

以下子命令需要施工实现，并与Web使用相同service/model/validation。不是当前可执行工具。

`doctor`：输出依赖/配置是否可用，但不输出Key。
`project create --request request.json --data-dir DIR`：建立独立任务。
`material add --project ID --file FILE`：受限导入；逐文件执行。
`plan create --project ID --corpus-revision N`：返回计划与覆盖。
`plan confirm --project ID --plan ID --corpus-revision N`：只在教师确认后调用。
`deck generate --project ID --plan ID --base-version N --corpus-revision N`：生成候选。
`change show --project ID --change ID`：展示diff/验证。
`change commit --project ID --change ID --base-version N --corpus-revision N`：教师同意才应用。
`deck edit --project ID --request edit.json`：目标页与版本受限。
`deck restore --project ID --request restore.json`：创建新版本。
`deck export --project ID --version N`：产出PPTX和真实检查结果。

命令使用类型化JSON结果、明确退出码，复用错误码而不是解析随意的聊天文字。data-dir锁阻止与另一个CLI/Web实例并行写。未实现命令应显式失败，不能静默返回示例。
