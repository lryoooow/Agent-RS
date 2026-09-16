import io
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4173"
output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("satellite-workspace.png")
output.parent.mkdir(parents=True, exist_ok=True)

preview = Image.new("RGB", (320, 240), (220, 45, 35))
draw = ImageDraw.Draw(preview)
draw.rectangle((40, 40, 280, 200), fill=(35, 205, 120))
preview_bytes = io.BytesIO()
preview.save(preview_bytes, format="PNG")

scene = {
    "key": "scene-demo-1",
    "satellite": "Sentinel-2A",
    "item_id": "S2_DEMO_SCENE",
    "datetime": "2026-08-20T03:12:00Z",
    "cloud_cover": 3.5,
    "bbox": [119.9, 30.1, 120.3, 30.4],
    "resolution_m": 10,
    "display_name": "杭州 Sentinel-2 测试影像",
    "preview_url": "/api/scenes/scene-demo-1/preview",
    "download_url": "/api/scenes/scene-demo-1/download",
}

errors: list[str] = []
console_errors: list[str] = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    def api(route):
        path = urlparse(route.request.url).path
        if path == "/api/scenes/scene-demo-1/preview":
            route.fulfill(status=200, content_type="image/png", body=preview_bytes.getvalue())
            return
        if path == "/api/scenes/search":
            route.fulfill(status=200, json={"scenes": [scene], "notes": ["浏览器验收数据"]})
            return
        if path == "/api/scenes/scene-demo-1/import":
            route.fulfill(status=200, json={"imagery_id": "catalogue-demo", "item_id": scene["item_id"], "satellite": scene["satellite"], "band_roles": {"red": 1, "green": 2, "blue": 3}})
            return
        if path == "/api/imagery/catalogue-demo":
            route.fulfill(status=200, json={"imagery_id": "catalogue-demo", "filename": "catalogue-demo.tif", "width": 320, "height": 240, "band_count": 3, "bounds": scene["bbox"], "preview_url": scene["preview_url"], "crs": "EPSG:4326"})
            return
        if path == "/api/auth/me":
            route.fulfill(status=200, json={"user": {"id": "satellite-fixture", "email": "satellite@example.invalid", "name": "卫星页面验收", "authenticated": True}})
            return
        if path == "/api/imagery":
            route.fulfill(status=200, json=[])
            return
        if path == "/api/conversations":
            route.fulfill(status=200, json={"conversations": []})
            return
        # Satvis probes its live catalogue API and falls back to the vendored
        # static snapshot when this endpoint is unavailable.
        if path.startswith("/api/gp/") or path == "/api/groups.json":
            route.fulfill(status=404, json={"error": {"code": "STATIC_FALLBACK", "message": "use static catalogue"}})
            return
        route.fulfill(status=200, json={})

    page.route("**/api/**", api)
    page.goto(url)
    page.wait_for_load_state("networkidle", timeout=45_000)

    page.get_by_role("button", name="卫星影像").click()
    page.get_by_role("heading", name="卫星影像中心").wait_for(timeout=10_000)
    assert page.get_by_role("button", name="卫星影像").get_attribute("aria-current") == "page"

    frame = page.frame_locator('iframe[title="Satvis 卫星轨道态势"]')
    frame.locator("#toolbarLeft").wait_for(state="visible", timeout=30_000)
    assert frame.locator("#toolbarLeft .toolbarButtons button").count() >= 6
    first_tool = frame.locator("#toolbarLeft .toolbarButtons button").first
    first_tool.hover()
    frame.get_by_text("卫星选择：按分组查找并显示卫星", exact=True).first.wait_for(timeout=10_000)
    first_tool.click()
    frame.get_by_text("卫星分组", exact=True).wait_for(timeout=15_000)
    frame.get_by_placeholder("搜索卫星名称或编号", exact=True).wait_for(timeout=15_000)
    assert frame.get_by_text("气象卫星", exact=True).count() >= 1
    summary = frame.locator(".browser-summary span")
    summary.wait_for(timeout=15_000)
    group_match = re.search(r"(\d+) 个分组", summary.inner_text())
    assert group_match and int(group_match.group(1)) > 0, summary.inner_text()

    # Chinese is the platform default, while the source application's English
    # interface remains available from the visible language control.
    frame.get_by_role("button", name="切换为英文").click()
    frame.get_by_text("Satellite groups", exact=True).wait_for(timeout=10_000)
    frame.get_by_role("button", name="Switch to Chinese").click()
    frame.get_by_text("卫星分组", exact=True).wait_for(timeout=10_000)
    page.wait_for_timeout(1_000)
    orbit_output = output.with_name(f"{output.stem}-orbit{output.suffix}")
    page.screenshot(path=str(orbit_output), full_page=True)

    archive_button = page.get_by_role("button", name="影像档案", exact=True)
    archive_button.click()
    assert archive_button.get_attribute("aria-current") == "page"
    catalogue_map = page.get_by_label("影像档案目录地图").first
    catalogue_map.wait_for(state="attached", timeout=15_000)
    page.get_by_text("正在加载目录地图…").wait_for(state="hidden", timeout=15_000)
    assert page.locator(".maplibregl-ctrl-zoom-in").get_attribute("title") == "放大地图"
    page.get_by_role("button", name="目录地图视野").click()
    page.get_by_role("button", name="检索影像").click()
    page.get_by_text("S2_DEMO_SCENE").wait_for(timeout=10_000)
    page.get_by_role("button", name="预览").click()
    page.get_by_text("杭州 Sentinel-2 测试影像", exact=True).wait_for(timeout=15_000)
    page.wait_for_timeout(1_000)

    # Verify the scene pixels are really rendered by MapLibre.  The fixture is
    # green in its centre; checking the map canvas catches regressions where a
    # result card and footprint appear but the raster itself is CSP-blocked.
    map_image = Image.open(io.BytesIO(catalogue_map.screenshot())).convert("RGB")
    centre = map_image.crop((map_image.width * 3 // 8, map_image.height * 3 // 8, map_image.width * 5 // 8, map_image.height * 5 // 8))
    green_pixels = sum(1 for red, green, blue in centre.get_flattened_data() if green > 120 and green > red + 40 and green > blue + 25)
    assert green_pixels > centre.width * centre.height * 0.25, "preview raster is not rendered on the catalogue map"

    # Import and activation are explicit and stay inside the catalogue page.
    page.get_by_role("button", name="导入").click()
    page.get_by_text("平台影像 catalogue-demo").wait_for(timeout=10_000)
    assert page.get_by_role("heading", name="卫星影像中心").is_visible()
    page.get_by_role("button", name="设为分析影像").click()
    page.get_by_role("button", name="已设为分析影像").wait_for(timeout=10_000)
    assert page.get_by_role("heading", name="卫星影像中心").is_visible()

    page.screenshot(path=str(output), full_page=True)
    page.get_by_role("button", name="前往工作台").click()
    page.get_by_role("button", name="工作台").wait_for(timeout=10_000)
    assert page.get_by_role("button", name="工作台").get_attribute("aria-current") == "page"

    relevant_errors = [message for message in errors if "ResizeObserver loop" not in message]
    assert not relevant_errors, relevant_errors
    csp_errors = [message for message in console_errors if "Content Security Policy" in message or "violates the following Content Security Policy" in message]
    assert not csp_errors, csp_errors
    browser.close()

print(output)
