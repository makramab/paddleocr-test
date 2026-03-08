import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Invoice Viewer")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

OUTPUTS_DIR = Path(__file__).parent / "outputs"


def load_results() -> list[dict]:
    """Load all extraction_result_*.json files from the outputs directory."""
    results = []
    for f in sorted(OUTPUTS_DIR.glob("extraction_result_*.json")):
        with open(f) as fh:
            data = json.load(fh)
            data["_filename"] = f.name
            results.append(data)
    return results


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    results = load_results()
    return templates.TemplateResponse(
        "index.html", {"request": request, "results": results}
    )


@app.get("/invoice/{filename}", response_class=HTMLResponse)
async def invoice_detail(request: Request, filename: str):
    filepath = OUTPUTS_DIR / filename
    if not filepath.exists() or not filepath.name.startswith("extraction_result_"):
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    with open(filepath) as f:
        data = json.load(f)
    return templates.TemplateResponse(
        "invoice.html", {"request": request, "data": data, "filename": filename}
    )
