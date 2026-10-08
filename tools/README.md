# 本包附带工具

`python tools/validate_pack.py`：无需网络，验证规划包Schema、引用、数据PDF、任务DAG、文件清单和示例业务关系，输出validation-report.md/json。它不是未来应用测试，不验证CodeArts权限、API模型、PPTX导出或云部署。

`python tools/build_demo_data.py`：重新构建原创PDF和测试fixture，依赖ReportLab、pypdf、Pillow和本地合法中文TrueType字体（CW_PDF_FONT）。不提供字体文件，不访问网络，不使用OCR；会覆盖本包demo-data中的同名生成文件。

`python tools/build_reader.py`：把Markdown与机器契约索引整理成离线HTML，依赖markdown-it-py。不会连接任何远端CSS、JS或字体。

重建数据后再次运行validate_pack，清单自动校验。tools/requirements-tested.txt记录本次包工具环境版本，不是未来业务环境锁文件，也不证明这些包在你的网络当前可下载。
