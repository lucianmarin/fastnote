import json
import time
from email.utils import formatdate
from datetime import datetime
from pathlib import Path
from typing import Dict
from local import PASSWORD_HASH

# Default password hash for 'admin' (md5)
# You can change this to match your existing setup
# hashlib.md5("admin".encode()).hexdigest()
PASSWORD_HASH = PASSWORD_HASH
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

def time_ago(timestamp: int) -> str:
    now = int(time.time())
    diff = now - timestamp
    if diff < 1:
        diff = 1

    tokens = {
        31536000: 'year',
        2592000: 'month',
        604800: 'week',
        86400: 'day',
        3600: 'hour',
        60: 'minute',
        1: 'second'
    }

    for unit, text in tokens.items():
        if diff < unit:
            continue
        count = round(diff / unit)
        return f"{count} {text}{'s' if count > 1 else ''}"
    return "just now"
