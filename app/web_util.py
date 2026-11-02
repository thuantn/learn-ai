"""Small helpers shared by the app and the admin routes."""
import json
import pathlib

from fastapi.responses import FileResponse, JSONResponse

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
JSON_LIMIT = 16 * 1024


def bad(status, code, message):
    return JSONResponse({"code": code, "error": message}, status_code=status)


async def read_json(request, limit=JSON_LIMIT):
    """Reads at most limit bytes, even if the client lies about or omits Content-Length."""
    if "application/json" not in request.headers.get("content-type", ""):
        return None
    size, parts = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        parts.append(chunk)
    try:
        data = json.loads(b"".join(parts))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def page(name, status=200):
    return FileResponse(WEB / name, media_type="text/html; charset=utf-8", status_code=status)
