#!/usr/bin/env python3
"""Build an offline HTML reading edition. No network resources are required."""
from pathlib import Path
from html import escape
from markdown_it import MarkdownIt
import re,json
ROOT=Path(__file__).resolve().parents[1]
md=MarkdownIt('commonmark',{'html':False}).enable('table')
first=['README.md','docs/00-owner-guide.md','AGENTS.md','process.md']
paths=[ROOT/p for p in first]
paths += sorted(p for p in (ROOT/'docs').glob('*.md') if p not in paths and p.name not in ('sources.md','pdf-visual-review.md','traceability.md'))
paths += [ROOT/'api.md',ROOT/'contracts/README.md',ROOT/'tasks/README.md',ROOT/'docs/traceability.md']
paths += sorted((ROOT/'prompts').glob('*.md'))
paths += [ROOT/'app-prompts/README.md']+sorted(p for p in (ROOT/'app-prompts').glob('*.md') if p.name!='README.md')
paths += [ROOT/'skill-template/teacher-courseware/SKILL.md']+sorted((ROOT/'skill-template/teacher-courseware/references').glob('*.md'))
paths += [ROOT/'demo-data/README.md',ROOT/'demo-data/expected/README.md',ROOT/'demo-data/evaluation/README.md',ROOT/'demo-data/sources.md']
paths += sorted((ROOT/'demo-data/source-pages').glob('*.md'))
paths += [ROOT/'THIRD_PARTY.md',ROOT/'docs/sources.md',ROOT/'validation-report.md',ROOT/'docs/pdf-visual-review.md',ROOT/'tools/README.md',ROOT/'CHANGELOG.md']
paths += sorted((ROOT/'templates').glob('*.md'))
paths=list(dict.fromkeys(p for p in paths if p.is_file()))
ids={p.resolve():f'chapter-{i:02d}' for i,p in enumerate(paths,1)}
nav=[];sections=[]
for i,p in enumerate(paths,1):
 text=p.read_text();title=next((x.lstrip('# ').strip() for x in text.splitlines() if x.startswith('# ')),p.stem)
 html=md.render(text)
 def link(m):
  raw=m.group(1)
  if ':' in raw or raw.startswith('#'):return m.group(0)
  target=(p.parent/raw.split('#')[0]).resolve()
  if target in ids:return 'href="#'+ids[target]+'"'
  return m.group(0)
 html=re.sub(r'href="([^"]+)"',link,html)
 cid=ids[p.resolve()];rel=p.relative_to(ROOT).as_posix()
 nav.append(f'<a href="#{cid}"><span>{i:02d}</span>{escape(title)}</a>')
 sections.append(f'<section id="{cid}"><div class="path">{escape(rel)}</div>{html}<a class="back" href="#top">返回总览 ↑</a></section>')
# Machine-readable assets, including task cards, remain inspectable in a standalone downloaded HTML.
appendix=['contracts/models.schema.json','contracts/openapi.json','tasks/tasks.json','demo-data/lesson_request.json','demo-data/evaluation/cases.json','demo-data/expected/reference_deck.json','demo-data/expected/split_patch.json','demo-data/data_manifest.json']
for p in appendix:
 q=ROOT/p
 sections.append('<section><details><summary>'+escape(p)+'</summary><pre>'+escape(q.read_text())+'</pre></details></section>')
css='''
:root{--ink:#243445;--muted:#63788a;--accent:#215a78;--line:#dce5eb;--paper:#fff;--bg:#f2f6f8}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif;font-size:16px;line-height:1.85}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}aside{position:fixed;top:0;left:0;bottom:0;width:285px;padding:26px 19px;overflow:auto;border-right:1px solid var(--line);background:#f8fafb}aside b{display:block;margin-bottom:14px;font-size:17px}nav a{display:block;padding:6px 0;line-height:1.55;font-size:12px;color:#4b657a}nav span{display:inline-block;width:25px;color:#8a9ca9}main{margin-left:285px;padding:45px 5vw 80px;max-width:1500px}header{margin:0 0 35px}header .kicker{letter-spacing:.13em;font-size:12px;color:var(--accent)}header h1{font-size:36px;line-height:1.3;margin:13px 0 20px}.lead{font-size:19px;max-width:850px}.notice{border-left:4px solid #7095aa;background:#e9f1f5;padding:14px 20px;margin:22px 0}.chips{display:flex;gap:9px;flex-wrap:wrap}.chips span{border:1px solid #cbdbe4;padding:3px 11px;border-radius:20px;font-size:12px}section{padding:32px 40px;margin:24px 0;background:var(--paper);border:1px solid var(--line);border-radius:12px;scroll-margin-top:20px}section h1{font-size:26px;line-height:1.45;margin:6px 0 23px}h2{font-size:21px;margin-top:30px;line-height:1.45}h3{font-size:18px;margin-top:22px}.path{font-family:ui-monospace,monospace;color:#8296a6;font-size:11px;margin-bottom:16px;overflow-wrap:anywhere}p{margin:12px 0}table{display:block;overflow-x:auto;border-collapse:collapse;width:100%;font-size:13px;line-height:1.75;margin:18px 0}th{background:#eef4f7}th,td{border:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:top}code{background:#eef3f6;padding:2px 5px;border-radius:3px;font-family:ui-monospace,"Noto Sans CJK SC",monospace;font-size:.88em}pre{padding:18px;background:#f0f5f8;border:1px solid var(--line);overflow-x:auto;line-height:1.65;font-size:12px;white-space:pre}pre code{background:none;padding:0}blockquote{border-left:3px solid #9cb4c2;padding-left:17px;color:#4b6272;margin-left:0}ul,ol{padding-left:25px}.back{display:inline-block;margin-top:25px;font-size:12px;color:#7a919f}summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere}.foot{color:var(--muted);font-size:12px}
@media(max-width:950px){aside{position:static;width:auto;max-height:280px;border-right:0;border-bottom:1px solid var(--line)}main{margin:0;padding:25px 16px}section{padding:22px 20px}header h1{font-size:28px}}
@media print{aside,.back{display:none}main{margin:0;max-width:none;padding:0}body{background:white;font-size:10pt;line-height:1.5}section{border:0;padding:0;margin:0;page-break-before:always}table{display:table;font-size:8pt}pre{white-space:pre-wrap}header{page-break-after:always}}
'''
html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Courseware Copilot｜Demo 工程规划与演示数据</title><style>'''+css+'''</style></head><body id="top"><aside><b>Courseware Copilot</b><div class="foot">Demo 规划 v1.0.0 · 离线阅读版<br>2026-09-18</div><nav>'''+''.join(nav)+'''</nav></aside><main><header><div class="kicker">BUILD WITH EVIDENCE · REVIEW BEFORE COMMIT</div><h1>教师资料驱动的课件助手<br>Demo 工程规划与施工手册</h1><p class="lead">给鸿岳的执行路线、给 AI 的施工契约，以及可以直接用于演示与反例验收的中文 PDF 数据。</p><div class="notice"><strong>交付状态：</strong>规划、契约、模板与测试数据。尚未实现应用，尚未验证码道账号、真实模型、PPTX 导出或云部署。第一轮只做 M0 技术准入。</div><div class="chips"><span>Vue + AnyUI</span><span>FastAPI + SQLite</span><span>teacher-courseware</span><span>引用与语义核验分离</span><span>候选确认 + 不可变版本</span></div><p class="foot">使用浏览器查找可搜索全文。本文不依赖远程字体、脚本或样式；来源链接仅在主动点击时联网。JSON 契约与评估定义附在末尾。</p></header>'''+''.join(sections)+'''</main></body></html>'''
(ROOT/'阅读版.html').write_text(html,encoding='utf-8')
print(json.dumps({'markdown_sections':len(paths),'machine_appendices':len(appendix),'html_bytes':len(html.encode())}))
