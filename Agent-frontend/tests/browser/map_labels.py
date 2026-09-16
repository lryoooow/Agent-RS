"""Real map tiles + production UI, browser-only history fixtures, no user writes."""
import io, json, pathlib, sys, time
from urllib.parse import urlparse
from PIL import Image
from playwright.sync_api import sync_playwright, expect
sys.stdout.reconfigure(encoding='utf-8')
url=sys.argv[1]; prefix=pathlib.Path(sys.argv[2]); prefix.parent.mkdir(parents=True,exist_ok=True)
img=io.BytesIO(); Image.new('RGBA',(256,256),(75,97,87,255)).save(img,format='PNG')
bounds=[116.38,39.88,116.43,39.93]
preview={'type':'preview','imagery_id':'map-check','result_url':'/api/map-check/image.png','bounds':bounds}
result={'type':'segmentation','imagery_id':'map-check','result_url':'/api/map-check/result.png','bounds':bounds,'total_pixels':100,'classes':[{'name':'woodland','label':'林地','percentage':100,'pixel_count':100,'color':'#228833'}]}
messages=[{'role':'user','content':'地图名称与图层验收'},{'role':'assistant','content':'影像已上传','metadata':{'geospatial_result':preview}},{'role':'assistant','content':'地图名称与道路显示验收','metadata':{'geospatial_result':result}}]
extract="""() => {
  const el=document.querySelector('.maplibregl-map');
  let fiber=el[Object.keys(el).find(k=>k.startsWith('__reactFiber'))];
  for(;fiber;fiber=fiber.return) {
    let maps=[];
    for(let hook=fiber.memoizedState;hook;hook=hook.next) {
      const v=hook.memoizedState;
      if(v?.current && typeof v.current.getStyle==='function') maps.push(v.current);
    }
    if(maps.length) {
      window.__maps=maps;window.__mapErrors??=[];window.__watchedMaps??=new WeakSet();
      for(const map of maps) if(!window.__watchedMaps.has(map)) {
        window.__watchedMaps.add(map);map.on('error',e=>window.__mapErrors.push(String(e.error)));
      }
      return maps.length;
    }
  }
  throw Error('Map refs not found');
}"""
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
 context.add_init_script("localStorage.setItem('agent-rs.chat-panel-size.v1',JSON.stringify({width:360,height:400}));")
 page=context.new_page(); errors=[]; map_errors=[];responses=[];checks=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('response',lambda r:responses.append({'url':r.url,'status':r.status}) if 'tiles.openfreemap.org' in r.url else None)
 def api(route):
  path=urlparse(route.request.url).path
  if path.endswith('.png'):route.fulfill(status=200,content_type='image/png',body=img.getvalue());return
  if path=='/api/auth/me': payload={'user':{'id':'map-fixture','email':'map@example.invalid','name':'地图验收','authenticated':True}}
  elif path=='/api/imagery':payload=[]
  elif path=='/api/imagery/map-check':payload={'imagery_id':'map-check','filename':'地图叠加验收.tif','width':256,'height':256,'band_count':3,'bounds':bounds,'preview_url':preview['result_url'],'crs':'EPSG:4326'}
  elif path=='/api/conversations':payload={'conversations':[{'id':'map-history','title':'地图名称验收','message_count':2,'created_at':'2026-09-16T00:00:00Z','updated_at':'2026-09-16T00:00:00Z'}]}
  elif path=='/api/conversations/map-history/messages':payload={'messages':messages}
  else:payload={}
  route.fulfill(status=200,json=payload)
 page.route('**/api/**',api)
 def wait_map(expression, timeout=45):
  # Poll via the devtools evaluation API: Playwright's wait_for_function can
  # invoke eval under the page CSP. Do not weaken production script-src.
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   if page.evaluate('() => ('+expression+')'):return
   page.wait_for_timeout(250)
  raise TimeoutError(expression+' '+str(page.evaluate('window.__mapErrors||[]')))
 page.goto(url);page.wait_for_load_state('networkidle',timeout=45000)
 prefix.with_suffix('.initial.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
 page.evaluate(extract)
 toggle=page.get_by_role('button',name='地名道路',exact=True);expect(toggle).to_have_attribute('aria-pressed','true')
 def position(name,center,zoom):
  page.evaluate('([center,zoom])=>window.__maps[0].jumpTo({center,zoom})',[center,zoom])
  wait_map("window.__maps[0].loaded() && window.__maps[0].areTilesLoaded()")
  page.wait_for_timeout(350)
  names=page.evaluate("[...new Set(window.__maps[0].queryRenderedFeatures().filter(f=>f.layer.id.startsWith('map-reference-')&&f.layer.type==='symbol').map(f=>f.properties['name:zh']||f.properties.name||f.properties['name:en']))].filter(Boolean)")
  assert names,(name,page.evaluate('window.__mapErrors'),responses)
  checks.append({'view':name,'zoom':zoom,'names':names[:50]});print(name,names[:12],flush=True)
 def order():
  ids=page.evaluate("window.__maps[0].getStyle().layers.map(l=>l.id)")
  rasters=[i for i,id in enumerate(ids) if id.startswith('rs-img-')]
  refs=[i for i,id in enumerate(ids) if id.startswith('map-reference-')]
  assert len(rasters)==2,ids
  assert max(rasters)<min(refs),ids
  return ids
 position('北京城市',[116.4074,39.9042],10)
 toggle.click();expect(toggle).to_have_attribute('aria-pressed','false')
 page.reload();page.wait_for_load_state('networkidle',timeout=45000);page.evaluate(extract)
 expect(toggle).to_have_attribute('aria-pressed','false')
 assert page.evaluate("window.__maps[0].getStyle().layers.filter(l=>l.id.startsWith('map-reference-')).every(l=>l.layout.visibility==='none')")
 toggle.click()
 page.get_by_role('button',name='数据管理',exact=True).click()
 page.get_by_role('tab',name='历史',exact=True).click()
 page.get_by_title('载入此会话').filter(has_text='地图名称验收').click()
 expect(page.get_by_test_id('chat-panel')).to_be_visible()
 page.wait_for_timeout(1200);page.evaluate(extract)
 position('北京街区',[116.4074,39.9042],15)
 order()
 page.screenshot(path=str(prefix.with_suffix('.beijing.png')))
 # Make the ROI through the public UI and ensure it stays above reference names.
 prefix.with_suffix('.history.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
 page.get_by_role('button',name='隐藏影像预览 imagery-map-check',exact=True).click()
 page.get_by_role('button',name='显示影像预览 imagery-map-check',exact=True).click()
 page.wait_for_timeout(350)
 page.get_by_role('button',name='框选',exact=True).click()
 page.mouse.move(700,400);page.mouse.down();page.mouse.move(850,550,steps=5);page.mouse.up()
 page.wait_for_timeout(200)
 ids=order()
 assert min(i for i,id in enumerate(ids) if id.startswith('rs-roi')) > max(i for i,id in enumerate(ids) if id.startswith('map-reference-')),ids
 checks.append({'order':order()})
 # Compare renders the same reference group above its background imagery.
 swipe=page.get_by_title('卷帘对比')
 if swipe.count()==0: swipe=page.get_by_role('button',name='卷帘',exact=True)
 swipe.click();page.wait_for_timeout(1000);page.evaluate(extract)
 wait_map("window.__maps.length===2 && window.__maps[1].loaded()")
 second=page.evaluate("window.__maps[1].getStyle().layers.map(l=>l.id)")
 assert max(i for i,id in enumerate(second) if id.startswith('rs-img-'))<min(i for i,id in enumerate(second) if id.startswith('map-reference-')),second
 toggle.click();page.wait_for_timeout(800);page.evaluate(extract)
 wait_map("window.__maps.length===2 && window.__maps[1].loaded()")
 assert page.evaluate("window.__maps.every(m=>m.getStyle().layers.filter(l=>l.id.startsWith('map-reference-')).every(l=>l.layout.visibility==='none'))")
 toggle.click();swipe.click();page.wait_for_timeout(300);page.evaluate(extract)
 # Hide the fixture rasters for the real satellite street screenshot.
 page.get_by_role('button',name='隐藏影像预览 imagery-map-check',exact=True).click()
 page.get_by_role('button',name='隐藏地物分类',exact=False).click()
 position('北京卫星街道',[116.4074,39.9042],15)
 page.screenshot(path=str(prefix.with_suffix('.satellite.png')))
 position('粤北影像区域',[114.2049,24.8708],13)
 page.screenshot(path=str(prefix.with_suffix('.guangdong.png')))
 position('广东区域地名',[114.2049,24.8708],10)
 page.screenshot(path=str(prefix.with_suffix('.region.png')))
 map_errors=page.evaluate('window.__mapErrors||[]')
 page.set_viewport_size({'width':375,'height':812})
 page.wait_for_timeout(300)
 box=toggle.bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=375,box
 assert toggle.evaluate("e=>e.innerText.replace(/\\s/g,'')")=='地名道路'
 assert not errors,errors
 assert not map_errors,map_errors
 assert not [r for r in responses if r['status']>=400],responses
 checks.extend([{'default_on':True,'toggle_remembered':True,'swipe_order':True,'swipe_toggle_synced':True},{'errors':errors,'map_errors':map_errors,'source_requests':len(responses),'source_http_statuses':sorted(set(r['status'] for r in responses))}])
 prefix.with_suffix('.json').write_text(json.dumps({'url':url,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
 browser.close()
