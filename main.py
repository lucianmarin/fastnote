import hashlib
import json
import time
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, Optional
from local import DEBUG, PASSWORD_HASH

async def set_auth_state(request: Request):
    auth_cookie = request.cookies.get("auth")
    request.state.auth = auth_cookie == PASSWORD_HASH

app = FastAPI(dependencies=[Depends(set_auth_state)])

if DEBUG:
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.filters['email_format'] = lambda ts: formatdate(ts)
templates.env.filters['date_format'] = lambda ts, f: datetime.fromtimestamp(ts).strftime(f)

DATA_FILE = Path("data/notes.json")

def get_notes() -> Dict[str, dict]:
    if not DATA_FILE.exists():
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def put_notes(notes: Dict[str, dict]):
    # Sort by key (timestamp) descending
    sorted_notes = dict(sorted(notes.items(), key=lambda item: item[0], reverse=True))

    with open(DATA_FILE, "w") as f:
        json.dump(sorted_notes, f, indent=4, ensure_ascii=False)


def get_common_context(request: Request):
    return {
        "request": request,
        "auth": request.state.auth,
        "current_year": datetime.now().year
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, p: int = 1):
    notes = get_notes()
    page = p if p > 0 else 1
    limit = 8
    offset = limit * (page - 1)

    # Slice dict items
    notes_items = list(notes.items())
    count = len(notes_items)
    pages = (count + limit - 1) // limit  # ceil(count / limit)

    sliced_items = notes_items[offset:offset + limit]
    sliced_notes = dict(sliced_items)

    context = get_common_context(request)
    context.update({
        "notes": sliced_notes,
        "page": page,
        "pages": pages
    })
    return templates.TemplateResponse("index.html", context)

@app.get("/note/{id}", response_class=HTMLResponse)
async def note(request: Request, id: str):
    notes = get_notes()
    if id not in notes:
        raise HTTPException(status_code=404, detail="Note not found")

    note_data = notes[id]

    # Calculate prev/next
    ids = list(notes.keys())
    try:
        index = ids.index(id)
        prev_id = ids[index + 1] if index + 1 < len(ids) else None
        next_id = ids[index - 1] if index > 0 else None
    except ValueError:
        prev_id = None
        next_id = None

    context = get_common_context(request)
    context.update({
        "note": note_data,
        "id": id,
        "previous_id": prev_id,
        "next_id": next_id
    })
    return templates.TemplateResponse("note.html", context)

@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    notes = get_notes()
    limit = 16

    results = {}
    if q:
        q_lower = q.lower()
        for id, note in notes.items():
            content = f"{note['url']} {note['title']} {note['quote']} {note['note']}".lower()
            if q_lower in content:
                results[id] = note
    else:
        results = notes

    label = f"{len(results)} recent notes"
    sliced_results = dict(list(results.items())[:limit])

    context = get_common_context(request)
    context.update({
        "results": sliced_results,
        "q": q,
        "label": label
    })
    return templates.TemplateResponse("search.html", context)

@app.get("/products", response_class=HTMLResponse)
async def products(request: Request):
    return templates.TemplateResponse("products.html", get_common_context(request))

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", get_common_context(request))

@app.get("/rss")
async def rss(request: Request):
    notes = get_notes()
    limit = 16
    sliced_notes = dict(list(notes.items())[:limit])
    last_id = list(notes.keys())[0] if notes else int(time.time())

    context = {
        "request": request,
        "notes": sliced_notes,
        "last_id": last_id
    }
    return templates.TemplateResponse("rss.xml", context, media_type="application/rss+xml")

# Auth Routes

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.state.auth:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("login.html", get_common_context(request))

@app.post("/login")
async def login(request: Request, key: str = Form(...)):
    key_hash = hashlib.md5(key.encode()).hexdigest()

    if key_hash == PASSWORD_HASH:
        response = RedirectResponse(url="/", status_code=303)
        # Set cookie for 1 year
        response.set_cookie(key="auth", value=PASSWORD_HASH, max_age=31536000)
        return response
    else:
        return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("auth")
    return response

# Protected Routes

@app.get("/edit", response_class=HTMLResponse)
async def edit_form(request: Request, id: Optional[str] = None):
    if not request.state.auth:
        return RedirectResponse(url="/")

    notes = get_notes()
    note_data = {"url": "", "title": "", "quote": "", "note": ""}

    if id and id in notes:
        note_data = notes[id]

    context = get_common_context(request)
    context.update({
        "note": note_data,
        "id": id if id else ""
    })
    return templates.TemplateResponse("edit.html", context)

@app.post("/edit")
async def edit_post(request: Request, url: str = Form(), title: str = Form(),
                    quote: str = Form(), note: str = Form(), id: str = Form()):
    if not request.state.auth:
        raise HTTPException(status_code=403, detail="Not authenticated")

    notes = get_notes()

    new_note = {
        "url": url,
        "title": title,
        "quote": quote,
        "note": note
    }

    # If ID exists (edit), keep it. If not (new), generate timestamp.
    # PHP logic: $id = $_POST['id'] ? $_POST['id'] : time();
    note_id = id if id else str(int(time.time()))

    notes[note_id] = new_note
    put_notes(notes)

    return RedirectResponse(url=f"/note/{note_id}", status_code=303)

@app.get("/delete/{id}")
async def delete_note(request: Request, id: str):
    if not request.state.auth:
        return RedirectResponse(url="/")

    notes = get_notes()
    if id in notes:
        del notes[id]
        put_notes(notes)

    return RedirectResponse(url="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
