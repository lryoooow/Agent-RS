"""Serve the release frontend and API on one origin without modifying upstream."""
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from app.main import app


# Only the HTML document needs permission to load the map's external resources.
# Keep the API's policy intact and limit these permissions to known providers.
FRONTEND_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https://server.arcgisonline.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "script-src 'self'; "
    "connect-src 'self' blob: https://server.arcgisonline.com "
    "https://demotiles.maplibre.org https://nominatim.openstreetmap.org https://tiles.openfreemap.org; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)

# Cesium and satellite.js initialize WebAssembly and a small generated-function
# path. Grant eval only to the vendored satvis document; the main platform keeps
# the stricter policy above.
SATVIS_CSP = FRONTEND_CSP.replace(
    "script-src 'self';",
    "script-src 'self' 'unsafe-eval';",
)


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path == 'api' or path.startswith('api/') or any(part.startswith('.') for part in Path(path).parts):
            raise HTTPException(status_code=404)
        request_path = str(scope.get('path') or '').lstrip('/')
        is_satvis_document = request_path.rstrip('/') == 'satvis' or (request_path.startswith('satvis/') and Path(request_path).suffix.lower() == '.html')
        is_document = path in ('', '.', 'index.html') or Path(path).suffix.lower() == '.html' or is_satvis_document
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix:
                raise
            response = await super().get_response('index.html', scope)
            is_document = True
        if is_document:
            # StaticFiles normalizes a directory request such as /satvis/ to '.'
            # before this method sees `path`. Use the original ASGI request path
            # so both /satvis/ and /satvis/index.html receive the Cesium policy.
            # Also set these on 304 responses, which have no content-type header,
            # so cached documents do not regain the API's restrictive policy.
            response.headers['Content-Security-Policy'] = SATVIS_CSP if is_satvis_document else FRONTEND_CSP
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Cache-Control'] = 'no-cache'
        return response


RELEASE_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIRECTORY = RELEASE_ROOT / 'Agent-frontend' / 'dist'

app.mount('/', FrontendFiles(directory=str(FRONTEND_DIRECTORY), html=True), name='frontend')
