#!/usr/bin/env python3
"""Static planning/data checks only. Does NOT test the future application or models."""
from __future__ import annotations
import hashlib,json,re,subprocess,sys,unicodedata,logging
from datetime import datetime,timezone
from pathlib import Path
from pypdf import PdfReader
from jsonschema import Draft202012Validator,FormatChecker
import yaml
ROOT=Path(__file__).resolve().parents[1]
logging.getLogger('pypdf').setLevel(logging.CRITICAL)
checks=[]
def check(name, fn, category='PACK_STATIC'):
 try:
  detail=fn();checks.append({'check':name,'category':category,'status':'PASS','detail':detail or ''})
 except Exception as exc:
  checks.append({'check':name,'category':category,'status':'FAIL','detail':f'{type(exc).__name__}: {exc}'})
def expect(ok,message):
 if not ok:raise AssertionError(message)
def load(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def sha(b):return hashlib.sha256(b).hexdigest()
def norm(t):return unicodedata.normalize('NFC',t.replace('\r\n','\n').replace('\r','\n').replace('\0','')).strip()
def distribution_files():
 # PACK静态校验的对象是将被分发的内容（git跟踪+未跟踪非ignore），不是本机运行时环境（node_modules/.venv等被gitignore排除）
 out=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,capture_output=True,text=True)
 expect(out.returncode==0,'git repository required for distribution view: '+out.stderr.strip())
 return [ROOT/l for l in out.stdout.splitlines() if l]
def distribution_md_files():
 return [p for p in distribution_files() if p.suffix.lower()=='.md']

schema=load('contracts/models.schema.json')
D=schema['$defs']
def validate_type(name,value):
 wrapped={'$schema':schema['$schema'],'$ref':'#/$defs/'+name,'$defs':D}
 Draft202012Validator(wrapped,format_checker=FormatChecker()).validate(value)
def all_refs(doc):
 if isinstance(doc,dict):
  if '$ref' in doc:yield doc['$ref']
  for v in doc.values():yield from all_refs(v)
 elif isinstance(doc,list):
  for v in doc:yield from all_refs(v)
def resolve(doc,ptr):
 expect(ptr.startswith('#/'),'Only local refs supported in this package checker')
 node=doc
 for piece in ptr[2:].split('/'):node=node[piece.replace('~1','/').replace('~0','~')]
 return node

def schema_checks():
 Draft202012Validator.check_schema(schema)
 for v in all_refs(schema):resolve(schema,v)
 return f'{len(D)} definitions, internal refs resolve'
check('JSON Schema definitions and references',schema_checks)
openapi=load('contracts/openapi.json')
def openapi_checks():
 expect(openapi['openapi']=='3.1.0','OpenAPI dialect')
 ids=[];count=0
 for path,methods in openapi['paths'].items():
  for method,op in methods.items():
   count+=1;ids.append(op['operationId'])
   expected=set(re.findall(r'\{([^}]+)\}',path))
   actual={p['name'] for p in op.get('parameters',[]) if p['in']=='path' and p.get('required')}
   expect(expected==actual,f'Path params {path}')
   if method!='get':expect(any(p['name']=='Idempotency-Key' and p['required'] for p in op['parameters']),f'Idempotency {path}')
 for ref in all_refs(openapi):resolve(openapi,ref)
 expect(len(ids)==len(set(ids)),'Unique operation IDs')
 for row in load('contracts/routes.json'):
  op=openapi['paths'][row['path']][row['method'].lower()]
  expect(str(row['status']) in op['responses'],'Success status')
  expect(f"{row['method']} {row['path']}" in (ROOT/'api.md').read_text(),'api.md route drift')
 return f'{count} route operations, parameters/responses/local refs checked (not full external OpenAPI conformance certification)'
check('OpenAPI and api.md route consistency',openapi_checks)
for name,rel in [('CreateProjectRequest','demo-data/lesson_request.json'),('CreateProjectRequest','contracts/examples/create_project.json'),('Job','contracts/examples/job_interrupted.json'),('DeckSpec','demo-data/expected/reference_deck.json'),('DeckPatch','demo-data/expected/split_patch.json'),('Claim','demo-data/expected/semantic_wrong_quote_claim.json'),('DeckSpec','demo-data/expected/relation_invalid_deck.json')]:
 check('Schema sample: '+rel,lambda n=name,p=rel:validate_type(n,load(p)))
chunks=load('demo-data/expected/reference_chunks.json'); bychunk={c['chunk_id']:c for c in chunks}
def chunk_checks():
 for c in chunks:
  validate_type('DocumentChunk',c)
  expect(c['page_end']-c['page_start']==len(c['text']),'Chunk character offsets')
  expect(c['text_sha256']==sha(c['text'].encode()),'Chunk text hash')
  path=ROOT/'demo-data/inputs'/c['document_name']
  text=norm(PdfReader(path).pages[c['pdf_page']-1].extract_text() or '')
  expect(text[c['page_start']:c['page_end']]==c['text'],'PDF extraction and stored chunk differ')
 return f'{len(chunks)} page-bounded chunks validated against actual PDF text'
check('Fixture chunk hashes and physical PDF pages',chunk_checks)

def check_deck_relations(deck):
 slideids=[s['id'] for s in deck['slides']]; claimids=[c['id'] for c in deck['claims']]
 expect(len(set(slideids))==len(slideids),'Duplicate slide IDs')
 expect(len(set(claimids))==len(claimids),'Duplicate claim IDs')
 used=set()
 for sl in deck['slides']:
  for block in sl['blocks']:
   if block['type']=='fact':
    expect(block['claim_id'] in claimids,'Unknown claim ID: '+block['claim_id']);used.add(block['claim_id'])
 expect(set(claimids)==used,'Unreferenced claims in reference deck')
 for c in deck['claims']:
  for ev in c['evidence_refs']:
   ch=bychunk[ev['chunk_id']]
   expect(ch['project_id']==deck['project_id'],'Project mismatch')
   expect(ch['corpus_revision']==deck['corpus_revision'],'Corpus mismatch')
   expect((ev['document_id'],ev['pdf_page'])==(ch['document_id'],ch['pdf_page']),'Evidence location mismatch')
   expect(0<=ev['start']<ev['end']<=len(ch['text']),'Invalid span offsets')
   expect(ch['text'][ev['start']:ev['end']]==ev['quote'],'Quote mismatch')
   expect(ch['text'].count(ev['quote'])==1,'Ambiguous quote')
 return f'{len(deck["claims"])} exact claim references, {len(deck["slides"])} slides; no semantic-model truth claim'
check('Reference Deck relations and exact citations',lambda:check_deck_relations(load('demo-data/expected/reference_deck.json')))
def invalid_relation():
 try:check_deck_relations(load('demo-data/expected/relation_invalid_deck.json'))
 except AssertionError as e:
  expect('Unknown claim' in str(e),'Wrong failure reason');return 'Deliberately invalid relation rejected after schema passes'
 raise AssertionError('Invalid relation was accepted')
check('Schema-valid but relation-invalid negative control',invalid_relation)
def wrong_semantic_locator():
 c=load('demo-data/expected/semantic_wrong_quote_claim.json');e=c['evidence_refs'][0];ch=bychunk[e['chunk_id']]
 expect(ch['text'][e['start']:e['end']]==e['quote'],'The negative semantic fixture must have a valid locator')
 expect('数值越大' in c['text'] and '较小的数值' in e['quote'],'Expected opposing propositions')
 return 'Fixture has valid quote but reversed meaning. Actual semantic verifier NOT_RUN; this test only confirms negative control construction.'
check('Semantic counterexample construction, not semantic verification',wrong_semantic_locator)
def split_fixture():
 original=load('demo-data/expected/reference_deck.json');patch=load('demo-data/expected/split_patch.json')
 op=patch['operations'][0];at=next(i for i,s in enumerate(original['slides']) if s['id']==op['target_slide_id'])
 out=json.loads(json.dumps(original));out['slides'][at:at+1]=op['slides'];out['version']=2
 validate_type('DeckSpec',out);check_deck_relations(out)
 expect(len(out['slides'])==len(original['slides'])+1,'Split page count')
 before={s['id']:s for s in original['slides'] if s['id']!=op['target_slide_id']}
 after={s['id']:s for s in out['slides']}
 expect(all(after[k]==v for k,v in before.items()),'Non-target changes')
 return 'Reference patch construction preserves other slides and claims. Future app patch engine NOT_RUN.'
check('Reference split-patch invariants',split_fixture)
# Actual PDF fixture properties; malformed/encrypted are expected intentionally.
def pdf_checks():
 expected={'inputs/01_stm32_interrupt_notes.pdf':8,'inputs/02_priority_casebook.pdf':4,'optional/03_classroom_log_supplement.pdf':2,'variants/renamed_reordered_notes.pdf':4}
 for rel,n in expected.items():
  rr=PdfReader(ROOT/'demo-data'/rel);expect(len(rr.pages)==n,rel+' page count')
  expect(all(len(norm(p.extract_text() or ''))>=100 for p in rr.pages),rel+' text layer')
 neg=ROOT/'demo-data/negative'
 expect(PdfReader(neg/'encrypted.pdf').is_encrypted,'Encrypted flag')
 expect(not (PdfReader(neg/'scanned_only.pdf').pages[0].extract_text() or '').strip(),'Scan must have no text')
 expect(not (PdfReader(neg/'blank.pdf').pages[0].extract_text() or '').strip(),'Blank must have no text')
 mixed=PdfReader(neg/'mixed_text_scan.pdf')
 expect(len(mixed.pages)==2 and len((mixed.pages[0].extract_text() or ''))>100 and not (mixed.pages[1].extract_text() or '').strip(),'Mixed page quality')
 try:PdfReader(neg/'malformed.pdf')
 except Exception:pass
 else:raise AssertionError('Malformed PDF unexpectedly accepted')
 return 'Main PDFs 12 text pages; supplementary 2; variant 4; deliberate encrypted/scan/blank/malformed/mixed properties checked'
check('Generated PDF positive and negative properties',pdf_checks)

def manifest_checks():
 m=load('demo-data/data_manifest.json');seen=set()
 for f in m['files']:
  p=ROOT/'demo-data'/f['path'];expect(p.is_file(),'Missing '+f['path']);expect(f['path'] not in seen,'Duplicate path');seen.add(f['path'])
  expect(sha(p.read_bytes())==f['sha256'],'Hash mismatch '+f['path']);expect(p.stat().st_size==f['bytes'],'Size mismatch')
 actual={p.relative_to(ROOT/'demo-data').as_posix() for p in (ROOT/'demo-data').rglob('*') if p.is_file() and p.name!='data_manifest.json'}
 expect(seen==actual,'Data manifest completeness')
 return f'{len(seen)} data files checked'
check('Demo data manifest, byte lengths and SHA-256',manifest_checks)
def eval_checks():
 cases=load('demo-data/evaluation/cases.json');ids=[c['id'] for c in cases];expect(len(ids)==len(set(ids)),'Duplicate case ID')
 for c in cases:
  expect(c['expect'] and c['input'],'Empty evaluation case')
  for p in c['files']:expect((ROOT/'demo-data'/p).is_file(),'Unknown evaluation input '+p)
 return f'{len(cases)} evaluation definitions; no application execution implied'
check('Evaluation case references',eval_checks)
def task_checks():
 ts=load('tasks/tasks.json');lookup={t['id']:t for t in ts};expect(len(lookup)==len(ts),'Duplicate tasks')
 visiting=set();done=set()
 def visit(t):
  if t in done:return
  expect(t not in visiting,'Cycle '+t);visiting.add(t)
  for d in lookup[t]['depends_on']:expect(d in lookup,'Missing dependency');visit(d)
  visiting.remove(t);done.add(t)
 for t in ts:
  visit(t['id']);expect(t['status']=='PLANNED','Initial task status must be honest')
  for p in t['read_first']:expect((ROOT/p).is_file(),'Missing task read path '+p)
 return f'{len(ts)} planned task cards, acyclic dependencies and read paths'
check('Task dependency DAG and initial truth state',task_checks)
def skill_checks():
 p=ROOT/'skill-template/teacher-courseware/SKILL.md';raw=p.read_text();front=raw.split('---',2)[1];meta=yaml.safe_load(front)
 expect(meta['name']==p.parent.name,'Skill name-folder mismatch');expect(len(meta['description'])<=1024,'Description length')
 expect('implementation template' in raw,'Template disclosure')
 total=sum(f.stat().st_size for f in p.parent.rglob('*') if f.is_file())
 expect(total<5_000_000,'Template ZIP payload bound estimate')
 return f'Valid frontmatter and template disclosure; {total} source bytes, not a real CodeArts import test'
check('Skill template metadata and scope',skill_checks)
def links_checks():
 broken=[]
 for p in distribution_md_files():
  for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
   target=target.split('#',1)[0]
   if not target or '://' in target or target.startswith('mailto:'):continue
   if not (p.parent/target).exists():broken.append(f'{p.relative_to(ROOT)} -> {target}')
 expect(not broken,'Broken local links: '+'; '.join(broken));return 'Markdown clickable local links resolve'
check('Markdown local links',links_checks)
def source_checks():
 sources=load('docs/sources.json');known={s['id'] for s in sources};bad=[]
 for p in distribution_md_files():
  # source IDs only; evaluation E/R/P/S cases not enclosed source markers in docs except real S01..S18
  if '/demo-data/' in str(p):continue
  for marker in re.findall(r'\[(S\d{2}|D\d{2})(?:[/\],])',p.read_text()):
   if marker not in known:bad.append(str(p)+':'+marker)
 expect(not bad,'Unknown source IDs '+str(bad));return f'{len(known)} source records, marker identifiers checked; relevance manually reviewed'
check('Source marker registration',source_checks)
def safety_checks():
 expect(not any(p.suffix.lower() in ('.ttf','.otf','.ttc','.woff','.woff2') for p in distribution_files()),'Standalone font file in package')
 expect(not (ROOT/'.env').exists(),'Actual .env must not be distributed')
 cfg=load('config/codearts_cli.example.json')
 for x in cfg['provider'].values():expect(x['options']['apiKey']=='REPLACE_LOCALLY_ONLY','Unexpected key')
 expect(not any((ROOT/x).exists() for x in ['node_modules','data','private-evidence']),'Private/runtime data included')
 return 'No standalone font files, live .env, known runtime directories or non-placeholder API key in template'
check('Package exclusion rules and placeholder configuration',safety_checks)
def require_docs():
 req=['AGENTS.md','api.md','process.md','README.md','CHANGELOG.md','THIRD_PARTY.md','prompts/00-start-here.md','docs/18-core-interfaces.md','docs/traceability.md']
 for p in req:expect((ROOT/p).is_file(),'Required doc '+p)
 for p in ['API.md','PROCESS.md']:expect(not (ROOT/p).exists(),'Conflicting case duplicate '+p)
 return 'Required canonical documents present'
check('Required canonical documentation',require_docs)
report={'generated_at':datetime.now(timezone.utc).isoformat(),'scope':'PACK_STATIC_ONLY','passed':sum(c['status']=='PASS' for c in checks),'failed':sum(c['status']=='FAIL' for c in checks),'checks':checks,'not_run':['CodeArts account permissions and custom model tool loop','AnyUI npm installation / Vue production build','Actual runtime model quality / billing / latency','Application API / SQLite jobs / browser E2E','ppt-edit asset authorization and exporter execution','PPTX output / PowerPoint or WPS editing','Cloud deployment / competition eligibility confirmation']}
(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
md=['# 规划包静态校验报告','',f"时间：{report['generated_at']}",f"范围：**PACK_STATIC_ONLY**。通过{report['passed']}项，失败{report['failed']}项。",'','这只验证文档/契约/生成的测试资产，不表示应用、模型、码道或PPTX链路已通过。','', '| 检查 | 结果 | 实际检查内容 |','|---|---|---|']
for c in checks:md.append(f"|{c['check']}|{c['status']}|{str(c['detail']).replace('|','/')}|")
md+=['','## 未运行','']+['- '+x for x in report['not_run']]
visual=ROOT/'docs/pdf-visual-review.md'
if visual.exists():md+=['','PDF页面人工目视抽查见[记录](docs/pdf-visual-review.md)。']
(ROOT/'validation-report.md').write_text('\n'.join(md)+'\n')
print(json.dumps({'passed':report['passed'],'failed':report['failed'],'scope':report['scope']}))
if report['failed']:
 for c in checks:
  if c['status']=='FAIL':print(c)
 sys.exit(1)
