"""Optional read-only API: uvicorn packrecorder.admin_app:app --port 8765"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
_DB = Path(os.environ.get("PACKRECORDER_INDEX_DB", ""))


@app.get("/api/health")
def health() -> JSONResponse:
    ok = _DB.is_file()
    return JSONResponse({"index_db_ok": ok})


@app.get("/api/recordings")
def recordings(q: str = "", limit: int = 100) -> JSONResponse:
    from packrecorder.recording_index import RecordingIndex

    if not _DB.is_file():
        return JSONResponse({"items": []})
    idx = RecordingIndex(_DB)
    idx.connect(uri_readonly=True)
    try:
        rows = idx.search(order_substring=q)[: max(1, min(limit, 500))]
    finally:
        idx.close()
    return JSONResponse({"items": rows})
