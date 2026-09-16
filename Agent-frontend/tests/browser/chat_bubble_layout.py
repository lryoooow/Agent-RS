"""Real production JS/CSS, isolated API fixtures; no account or model writes.

Usage: python work/ui_bubble_audit.py URL OUTPUT_PREFIX
"""
import json
import pathlib
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

url = sys.argv[1]
prefix = pathlib.Path(sys.argv[2])
prefix.parent.mkdir(parents=True, exist_ok=True)
question = '很好，当前上传的这张影像提取一下河流吧'
answer = '已收到，将在当前影像中提取河流。'
long_question = '请分析影像，并说明各类别的面积和依据。' * 24 + '\n' + 'raster_file_' * 50
table = '## 分类结果\n\n|类别|像素|面积|说明|\n|---|---|---|---|\n' + ''.join(
    f'|建筑 {i}|233837|0.339 平方公里|边界需要核验，类别不代表实测精度。|\n' for i in range(20))
table += '\n```text\n' + 'source/file/' * 60 + '\n```\n\n' + '`' + 'long-raster-name-' * 30 + '`'
messages = [
    {'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer},
    {'role': 'user', 'content': long_question}, {'role': 'assistant', 'content': table},
]
stream_fixture = """(() => {
  const originalFetch = window.fetch.bind(window);
  const encoder = new TextEncoder();
  window.fetch = async (...args) => {
    const requestUrl = typeof args[0] === 'string' ? args[0] : args[0].url;
    if (new URL(requestUrl, location.href).pathname !== '/api/chat') return originalFetch(...args);
    return new Response(new ReadableStream({start(controller) {
      window.__layoutStream = {
        emit(event, data) { controller.enqueue(encoder.encode('event: ' + event + '\\ndata: ' + JSON.stringify(data) + '\\n\\n')); },
        close() { controller.close(); }
      };
    }}), {headers: {'content-type': 'text/event-stream'}});
  };
})();"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    context.add_init_script(stream_fixture)
    context.add_init_script("localStorage.setItem('agent-rs.chat-panel-size.v1', JSON.stringify({width:600,height:650}));")
    page = context.new_page()
    errors, checks, api_paths = [], [], []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def api(route):
        path = urlparse(route.request.url).path
        api_paths.append(path)
        if path == '/api/auth/me':
            payload = {'user': {'id': 'layout-fixture', 'email': 'layout@example.invalid', 'name': '布局验收', 'authenticated': True}}
        elif path == '/api/imagery':
            payload = []
        elif path == '/api/conversations':
            payload = {'conversations': [{'id': 'layout-history', 'title': '气泡布局历史验收', 'message_count': 4, 'created_at': '2026-09-15T00:00:00Z', 'updated_at': '2026-09-15T00:00:00Z'}]}
        elif path == '/api/conversations/layout-history/messages':
            payload = {'messages': messages}
        else:
            payload = {}
        route.fulfill(status=200, json=payload)

    page.route('**/api/**', api)
    page.goto(url)
    page.wait_for_load_state('networkidle', timeout=45000)
    prefix.with_suffix('.initial.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
    page.get_by_placeholder('描述你的分析任务，开始一段新对话…').fill(question)
    page.get_by_role('button', name='开始对话', exact=True).click()
    panel = page.get_by_test_id('chat-panel')
    viewport = page.get_by_test_id('chat-messages')
    expect(panel).to_be_visible()
    page.wait_for_function('!!window.__layoutStream')
    page.wait_for_timeout(550)

    def emit(event, data):
        page.evaluate('([event,data]) => window.__layoutStream.emit(event,data)', [event, data])
        page.wait_for_timeout(80)

    def finish():
        emit('done', {'finish_reason': 'stop'})
        expect(panel.get_by_role('button', name='发送', exact=True)).to_be_enabled()

    def send(text):
        page.evaluate('window.__layoutStream = null')
        panel.locator('textarea').fill(text)
        panel.get_by_role('button', name='发送', exact=True).click()
        page.wait_for_function('!!window.__layoutStream')

    def check_fit(locator, role):
        result = locator.evaluate("""(e) => {
          const text = e.querySelector('p') || e;
          const range = document.createRange(); range.selectNodeContents(text);
          const rect = e.getBoundingClientRect(), t = range.getBoundingClientRect();
          const style = getComputedStyle(e);
          const inset = ['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((v,k)=>v+parseFloat(style[k]),0);
          const row = e.parentElement.parentElement;
          const avatar = row.firstElementChild.getBoundingClientRect();
          return {width:rect.width,text:t.width,inset,extra:rect.width-t.width-inset,
            expectedGap:parseFloat(getComputedStyle(row).columnGap),rightGap:avatar.left-rect.right,leftGap:rect.left-avatar.right};
        }""")
        assert abs(result['extra']) < 2, (role, result)
        assert abs(result['rightGap' if role == 'user' else 'leftGap'] - result['expectedGap']) < 1, (role, result)
        return result

    def check_tool():
        result = page.get_by_test_id('tool-bubble').last.evaluate("""(e) => {
          const row=e.firstElementChild, brand=row.children[0], status=row.children[1];
          const r=e.getBoundingClientRect(), b=brand.getBoundingClientRect(), s=status.getBoundingClientRect();
          const style=getComputedStyle(e);
          return {width:r.width,gap:s.left-b.right,expectedGap:parseFloat(getComputedStyle(row).columnGap),
            tail:r.right-s.right,expectedTail:parseFloat(style.paddingRight)+parseFloat(style.borderRightWidth),scroll:e.scrollWidth,client:e.clientWidth};
        }""")
        assert abs(result['gap'] - result['expectedGap']) < 1, result
        assert abs(result['tail'] - result['expectedTail']) < 1, result
        assert result['scroll'] <= result['client'] + 1, result
        return result

    def check_bounds():
        result = viewport.evaluate("""(e) => {
          const r=e.getBoundingClientRect();
          const bad=[...e.querySelectorAll('[data-testid$="bubble"],table,pre')].filter(n=>{
            const b=n.getBoundingClientRect(); return b.left<r.left-1 || b.right>r.right+1 || n.scrollWidth>n.clientWidth+1;
          }).map(n=>({tag:n.tagName,test:n.dataset.testid,client:n.clientWidth,scroll:n.scrollWidth}));
          return {width:e.clientWidth,scroll:e.scrollWidth,height:e.clientHeight,bad};
        }""")
        assert result['scroll'] <= result['width'] + 1 and not result['bad'], result
        assert result['height'] > 45, result
        return result

    def resize(width, height):
        box = panel.bounding_box()
        handle = panel.get_by_role('button', name='调整对话框宽高', exact=True).bounding_box()
        x, y = handle['x'] + handle['width']/2, handle['y'] + handle['height']/2
        page.mouse.move(x,y); page.mouse.down()
        page.mouse.move(x+width-box['width'],y+height-box['height'],steps=6); page.mouse.up()
        page.wait_for_timeout(100)
        actual = panel.bounding_box()
        assert abs(actual['width']-width)<2 and abs(actual['height']-height)<2, actual
        return check_bounds()

    emit('agent_status', {'status':'tool_execution_started','label':'正在进行地物分类'})
    for width,height in [(360,340),(497,500),(600,600),(900,700)]:
        dimensions = resize(width,height)
        checks.append({'phase':'running','dimensions':dimensions,'user':check_fit(page.get_by_test_id('user-message-bubble').first,'user'),'tool':check_tool()})
    emit('delta', {'content':answer})
    check_fit(page.get_by_test_id('assistant-message-bubble').last,'assistant')
    emit('agent_status', {'status':'tool_execution_completed','label':'分类结果已生成'})
    finish()
    resize(600,520)
    check_tool()
    checks.append({'phase':'short-answer','assistant':check_fit(page.get_by_test_id('assistant-message-bubble').last,'assistant')})
    panel.screenshot(path=str(prefix.with_suffix('.short.png')))

    send(long_question)
    emit('delta', {'content':table})
    for width,height in [(360,340),(497,500),(600,600),(900,700)]:
        dimensions = resize(width,height)
        full = page.get_by_test_id('assistant-message-bubble').last.evaluate('(e)=>({bubble:e.clientWidth,parent:e.parentElement.clientWidth})')
        assert abs(full['bubble'] - full['parent']) <= 2, full
        checks.append({'phase':'long-text-table-code-streaming','dimensions':dimensions,'full':full})
    finish()
    resize(497,600)
    viewport.evaluate('(e)=>e.scrollTop=180')
    page.wait_for_timeout(100)
    before = viewport.evaluate('(e)=>e.scrollTop')
    panel.get_by_role('button',name='调整对话框宽度',exact=True).press('ArrowRight')
    page.wait_for_timeout(100)
    after = viewport.evaluate('(e)=>e.scrollTop')
    assert abs(after-before)<5, (before,after)
    viewport.evaluate('(e)=>e.scrollTop=e.scrollHeight')
    panel.screenshot(path=str(prefix.with_suffix('.long.png')))

    send('检查失败状态')
    emit('agent_status', {'status':'tool_execution_failed','label':'暂时无法完成推理，请检查任务参数。' + 'raster_model_error_'*30})
    resize(360,500)
    check_tool(); check_bounds()
    emit('error', {'message':'本次分析失败，请稍后重试。'})
    expect(panel.get_by_role('button', name='发送', exact=True)).to_be_enabled()
    check_fit(page.get_by_test_id('assistant-message-bubble').last,'assistant')
    checks.append({'phase':'error-and-long-status','tool':check_tool()})

    # Open an actual history UI entry; fixtures replace only the HTTP data.
    page.get_by_role('button', name='数据管理', exact=True).click()
    page.get_by_role('tab', name='历史', exact=True).click()
    page.get_by_title('载入此会话').filter(has_text='气泡布局历史验收').click()
    expect(page.get_by_test_id('user-message-bubble')).to_have_count(2)
    expect(page.get_by_test_id('assistant-message-bubble')).to_have_count(2)
    resize(600,600)
    check_fit(page.get_by_test_id('user-message-bubble').first,'user')
    check_fit(page.get_by_test_id('assistant-message-bubble').first,'assistant')
    check_bounds()
    viewport.evaluate('(e)=>e.scrollTop=0')
    panel.screenshot(path=str(prefix.with_suffix('.history.png')))
    checks.append({'phase':'restored-history','short_bubbles_fit':True,'long_content_contained':True})
    # A small browser viewport clamps the panel and still wraps the message text.
    page.set_viewport_size({'width':375,'height':800})
    page.wait_for_timeout(200)
    check_bounds()
    checks.append({'phase':'mobile-viewport','dimensions':check_bounds()})
    assert not errors, errors
    result={'url':url,'checks':checks,'reader_scroll_preserved':True,'javascript_errors':errors,'api_paths':sorted(set(api_paths)),
        'method':'Production assets with browser-only auth/history/SSE fixtures; no real accounts, imagery changes or model requests.'}
    prefix.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(checks),'javascript_errors':errors,'report':str(prefix.with_suffix('.json'))},ensure_ascii=False))
    browser.close()
