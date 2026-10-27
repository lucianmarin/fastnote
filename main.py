import calendar
import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from typing import Dict, Optional

import feedparser
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemBytecodeCache, FileSystemLoader

from local import DEBUG, PASSWORD_HASH

DATA_FILE = Path("notes.json")
FEED_URL = "https://lucianmarin.github.io/feed.rss"
NOTES = {}
ARTICLES = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global NOTES, ARTICLES
    NOTES = get_notes()
    ARTICLES = get_articles()
    yield

async def set_auth_state(request: Request):
    auth_cookie = request.cookies.get("auth")
    request.state.auth = auth_cookie == PASSWORD_HASH

app = FastAPI(dependencies=[Depends(set_auth_state)], lifespan=lifespan)
env = Environment(
    autoescape=True,
    auto_reload=DEBUG,
    loader=FileSystemLoader("templates"),
    bytecode_cache=FileSystemBytecodeCache(),
    enable_async=True
)
env.filters['email_format'] = lambda ts: formatdate(ts)
env.filters['date_format'] = lambda ts, f: datetime.fromtimestamp(ts).strftime(f)

if DEBUG:
    app.mount("/static", StaticFiles(directory="static"), name="static")

def get_notes() -> Dict[str, dict]:
    if not DATA_FILE.exists():
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def get_articles() -> Dict[str, dict]:
    feed = feedparser.parse(FEED_URL)
    articles = {}
    for entry in feed.entries:
        ts = str(int(calendar.timegm(entry.published_parsed)))
        articles[ts] = {
            "url": entry.link,
            "title": entry.title,
            "quote": entry.summary,
        }
    return articles

def put_notes(notes: Dict[str, dict]):
    global NOTES
    # Sort by key (timestamp) descending
    sorted_notes = dict(sorted(notes.items(), key=lambda item: item[0], reverse=True))
    NOTES = sorted_notes
    with open(DATA_FILE, "w") as f:
        json.dump(sorted_notes, f, indent=4, ensure_ascii=False)

def get_common_context(request: Request):
    return {
        "request": request,
        "auth": request.state.auth,
        "path": request.url.path,
        "year": datetime.now().year
    }

@app.get("/")
async def index(request: Request, p: int = 1):
    combined = {**NOTES, **ARTICLES}
    items = dict(sorted(combined.items(), key=lambda item: int(item[0]), reverse=True))
    page = p if p > 0 else 1
    limit = 10
    offset = limit * (page - 1)

    stream_items = list(items.items())
    count = len(stream_items)
    pages = (count + limit - 1) // limit  # ceil(count / limit)

    sliced_items = stream_items[offset:offset + limit]
    sliced_stream = dict(sliced_items)

    context = get_common_context(request)
    context.update({
        "title": "Lucian's stream",
        "notes": sliced_stream,
        "page": page,
        "pages": pages
    })
    content = await env.get_template("index.html").render_async(context)
    return HTMLResponse(content)

@app.get("/notes")
async def notes(request: Request, p: int = 1):
    items = NOTES.copy()
    page = p if p > 0 else 1
    limit = 10
    offset = limit * (page - 1)

    notes_items = list(items.items())
    count = len(notes_items)
    pages = (count + limit - 1) // limit  # ceil(count / limit)

    sliced_items = notes_items[offset:offset + limit]
    sliced_notes = dict(sliced_items)

    context = get_common_context(request)
    context.update({
        "title": "Lucian's notes",
        "notes": sliced_notes,
        "page": page,
        "pages": pages
    })
    content = await env.get_template("index.html").render_async(context)
    return HTMLResponse(content)

@app.get("/{id:int}")
async def note(request: Request, id: int):
    id = str(id)
    if id in NOTES:
        notes = NOTES.copy()
    elif id in ARTICLES:
        notes = ARTICLES.copy()
    else:
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
        "title": note_data["title"],
        "note": note_data,
        "id": id,
        "previous_id": prev_id,
        "next_id": next_id
    })
    content = await env.get_template("note.html").render_async(context)
    return HTMLResponse(content)

@app.get("/search")
async def search(request: Request, q: str = ""):
    combined = {**NOTES, **ARTICLES}
    items = dict(sorted(combined.items(), key=lambda item: int(item[0]), reverse=True))
    limit = 20

    results = {}
    notes_count = 0
    articles_count = 0
    if q:
        q_lower = q.lower()
        for id, item in items.items():
            content = f"{item['url']} {item['title']} {item['quote']} {item.get('note', '')}".lower()
            if q_lower in content:
                results[id] = item
                if id in NOTES:
                    notes_count += 1
                else:
                    articles_count += 1
    else:
        results = items
        notes_count = len(NOTES)
        articles_count = len(ARTICLES)

    sliced_results = dict(list(results.items())[:limit])

    context = get_common_context(request)
    context.update({
        "title": "Search notes and articles",
        "results": sliced_results,
        "notes": notes_count,
        "articles": articles_count,
        "q": q
    })
    content = await env.get_template("search.html").render_async(context)
    return HTMLResponse(content)

@app.get("/articles")
async def articles(request: Request, p: int = 1):
    items = ARTICLES.copy()
    page = p if p > 0 else 1
    limit = 10
    offset = limit * (page - 1)

    articles_items = list(items.items())
    count = len(articles_items)
    pages = (count + limit - 1) // limit

    sliced_items = articles_items[offset:offset + limit]
    sliced_articles = dict(sliced_items)

    context = get_common_context(request)
    context.update({
        "title": "Lucian's articles",
        "notes": sliced_articles,
        "page": page,
        "pages": pages
    })
    content = await env.get_template("index.html").render_async(context)
    return HTMLResponse(content)

@app.get("/about")
async def about(request: Request):
    context = get_common_context(request)
    context.update({
        "title": "About Lucian"
    })
    content = await env.get_template("about.html").render_async(context)
    return HTMLResponse(content)

@app.get("/rss")
async def rss(request: Request):
    combined = {**NOTES, **ARTICLES}
    notes = dict(sorted(combined.items(), key=lambda item: int(item[0]), reverse=True))
    limit = 20
    sliced_notes = dict(list(notes.items())[:limit])
    last_id = list(notes.keys())[0] if notes else int(time.time())

    context = {
        "request": request,
        "notes": sliced_notes,
        "last_id": last_id
    }
    content = await env.get_template("rss.xml").render_async(context)
    return HTMLResponse(content, media_type="application/rss+xml")

# Auth Routes

@app.get("/login")
async def login_form(request: Request):
    if request.state.auth:
        return RedirectResponse(url="/")
    context = get_common_context(request)
    context.update({
        "title": "Login"
    })
    content = await env.get_template("login.html").render_async(context)
    return HTMLResponse(content)

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

@app.get("/edit")
async def edit_form(request: Request, id: Optional[str] = None):
    if not request.state.auth:
        return RedirectResponse(url="/")

    notes = NOTES.copy()
    note_data = {"url": "", "title": "", "quote": "", "note": ""}

    if id and id in notes:
        note_data = notes[id]

    context = get_common_context(request)
    context.update({
        "title": "Edit note" if id else "Add note",
        "note": note_data,
        "id": id if id else ""
    })
    content = await env.get_template("edit.html").render_async(context)
    return HTMLResponse(content)

@app.post("/edit")
async def edit_post(request: Request, url: str = Form(""), title: str = Form(""),
                    quote: str = Form(""), note: str = Form(""), id: int = Form(0)):
    global ARTICLES
    if not request.state.auth:
        raise HTTPException(status_code=403, detail="Not authenticated")

    notes = NOTES.copy()
    new_note = {"url": url, "title": title, "quote": quote, "note": note}

    # If ID exists (edit), keep it. If not (new), generate timestamp.
    # PHP logic: $id = $_POST['id'] ? $_POST['id'] : time();
    note_id = id if id else int(time.time())

    notes[str(note_id)] = new_note
    put_notes(notes)
    ARTICLES = get_articles()

    return RedirectResponse(url=f"/{note_id}", status_code=303)

@app.get("/delete/{id}")
async def delete_note(request: Request, id: str):
    if not request.state.auth:
        return RedirectResponse(url="/")

    notes = NOTES.copy()
    if id in notes:
        del notes[id]
        put_notes(notes)

    return RedirectResponse(url="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
