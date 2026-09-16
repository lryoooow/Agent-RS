"""Production frontend, isolated API replay: report button/chat/history/download."""
import hashlib,json,pathlib,sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

url=sys.argv[1]
prefix=pathlib.Path(sys.argv[2])
docx=pathlib.Path(sys.argv[3]).read_bytes()
image='abcdef012345'
artifact={'imagery_id':image,'filename':'report_verified.docx','download_url':f'/api/imagery/{image}/results/report_verified.docx'}
geo={'type':'segmentation','imagery_id':image,'result_url':'/unused.png','bounds':[114.18,24.84,114.23,24.90],'total_pixels':233837,'classes':[{'name':'building','label':'建筑','percentage':1.39,'pixel_count':233837,'color':'#e6194b'}]}
messages=[{'role':'user','content':'提取建筑'},{'role':'assistant','content':'分类完成。','metadata':{'geospatial_result':geo}}]
calls=[]
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,reduced_motion='reduce')
 context.add_init_script("localStorage.setItem('agent-rs.chat-panel-size.v1', JSON.stringify({width:600,height:650}));")
 page=context.new_page();errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 def api(route):
  path=urlparse(route.request.url).path
  if path=='/api/auth/me': payload={'user':{'id':'layout-fixture','email':'layout@example.invalid','name':'报告验收','authenticated':True}}
  elif path=='/api/imagery': payload=[]
  elif path==f'/api/imagery/{image}': payload={'imagery_id':image,'filename':'report-fixture.tif','width':4096,'height':4096,'band_count':4}
  elif path=='/api/conversations': payload={'conversations':[{'id':'report-history','title':'报告下载验收','message_count':len(messages),'created_at':'2026-09-15T00:00:00Z','updated_at':'2026-09-15T00:00:00Z'}]}
  elif path=='/api/conversations/report-history/messages': payload={'messages':messages}
  elif path=='/api/reports':
   calls.append(route.request.post_data_json)
   messages.append({'role':'assistant','content':'分析报告已生成','metadata':{'geospatial_result':{'type':'report',**artifact}}})
   payload=artifact
  elif path==artifact['download_url']:
   route.fulfill(status=200,content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename=report_verified.docx'},body=docx);return
  elif path=='/api/chat':
   payload='event: delta\ndata: '+json.dumps({'content':'报告已生成。'},ensure_ascii=False)+'\n\nevent: done\ndata: '+json.dumps({'finish_reason':'stop','geospatial_result':{'type':'report',**artifact}})+'\n\n'
   route.fulfill(status=200,content_type='text/event-stream',body=payload);return
  else: payload={}
  route.fulfill(status=200,json=payload)
 page.route('**/api/**',api)
 page.goto(url);page.wait_for_load_state('networkidle',timeout=45000)
 prefix.with_suffix('.initial.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
 def history():
  page.get_by_role('button',name='数据管理',exact=True).click()
  page.get_by_role('tab',name='历史',exact=True).click()
  page.get_by_title('载入此会话').filter(has_text='报告下载验收').click()
 history()
 panel=page.get_by_test_id('chat-panel')
 expect(panel.get_by_role('button',name='生成 Word 报告')).to_be_visible()
 panel.get_by_role('button',name='生成 Word 报告').click()
 link=panel.get_by_role('link',name='下载报告',exact=True)
 expect(link).to_be_visible()
 assert calls==[{'conversation_id':'report-history','imagery_id':image}],calls
 expect(link).to_have_attribute('href',artifact['download_url'])
 # Validate the linked bytes through the browser's HTTP stack. The actual
 # authenticated production download is tested separately without API replay.
 content=bytes(page.evaluate('async u => Array.from(new Uint8Array(await (await fetch(u)).arrayBuffer()))',artifact['download_url']))
 assert hashlib.sha256(content).digest()==hashlib.sha256(docx).digest()
 panel.screenshot(path=str(prefix.with_suffix('.button.png')))
 page.get_by_title('返回主页查看历史').click()
 history()
 expect(panel.get_by_role('link',name='下载报告',exact=True)).to_be_visible()
 panel.locator('textarea').fill('生成提取报告。')
 panel.get_by_role('button',name='发送',exact=True).click()
 expect(panel.get_by_role('link',name='下载报告',exact=True)).to_have_count(2)
 expect(panel.get_by_role('button',name='发送',exact=True)).to_be_enabled()
 assert not errors,errors
 panel.screenshot(path=str(prefix.with_suffix('.chat-history.png')))
 result={'url':url,'button_request':calls[0],'download_card_visible':True,'download_hash_verified':True,'history_restored_link':True,'chat_sse_report_card':True,'javascript_errors':errors,'method':'Browser-only API fixtures; production JS/CSS and actual DOCX bytes.'}
 prefix.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))
 browser.close()
