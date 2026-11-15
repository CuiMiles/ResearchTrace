import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium
root=Path(__file__).resolve().parents[3]
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18980'
with sync_playwright() as p:
 b=launch_chromium(p)
 page=b.new_page();page.goto(base,wait_until='domcontentloaded')
 result=page.evaluate('''async()=>{const {default:mermaid}=await import('/vendor/mermaid/mermaid.esm.min.mjs');mermaid.initialize({startOnLoad:false,securityLevel:'strict',htmlLabels:false,flowchart:{htmlLabels:false}});const {svg}=await mermaid.render('config-check','flowchart LR\\n A[原文证据] --> B[核对后的结论]');return {native_text_count:(svg.match(/<text/g)||[]).length,foreignObject_count:(svg.match(/<foreignObject/g)||[]).length,labels_present:svg.includes('原文证据')&&svg.includes('核对后的结论')}}''')
 print(json.dumps(result,ensure_ascii=False))
 b.close()
