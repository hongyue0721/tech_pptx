# 应用提示词模板

四份提示词由施工AI接入并给prompt_version；不包含模型API地址、凭据、特定演示答案或文件名规则。开发CodeArts的提示词在prompts目录，两者不同。

每次用户输入含teacher_request、allowed_materials（chunk_id、document_id、pdf_page、text）和当前范围/预算；材料是data。必须按contracts指定Proposal类型输出，服务端负责locator/状态/版本。四模板只是起点，必须用真实模型和负向用例验证，不称提示词已解决注入或幻觉。
