from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from scraper.ai import classify_business, suggest_outreach_angle
from scraper.contacts import enrich_business
from scraper.maps import GooglePlacesClient
from scraper.postcode import validate_london_postcode

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB = DATA / "py_scrape.db"
DATA.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
state = {"running": False, "message": "Ready", "found": 0, "target": 0}
state_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, business_name TEXT NOT NULL, category TEXT,
        address TEXT, postcode TEXT, phone TEXT, email TEXT, website TEXT, rating TEXT,
        reviews TEXT, maps_url TEXT, has_website TEXT, lead_score INTEGER, outreach TEXT,
        status TEXT DEFAULT 'new', source TEXT DEFAULT 'Google Places', created_at TEXT,
        updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, message TEXT, created_at TEXT
    )""")
    conn.commit()
    return conn


def log(message: str, level: str = "info"):
    now = datetime.now(timezone.utc).isoformat()
    conn = db()
    conn.execute("INSERT INTO logs(level,message,created_at) VALUES(?,?,?)", (level, message, now))
    conn.commit(); conn.close()
    with state_lock:
        state["message"] = message


def all_leads():
    conn = db(); rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]


def run_scrape(postcode: str, target: int):
    with state_lock:
        state.update(running=True, found=0, target=target, message="Starting search…")
    try:
        key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")
        client = GooglePlacesClient(key)
        log(f"Searching Google Places around {postcode}")
        candidates = client.search(postcode, min(target * 3, 100))
        log(f"Received {len(candidates)} place records")
        conn = db()
        for idx, business in enumerate(candidates, 1):
            if business.get("website"):
                log(f"Skipped {business.get('name', 'Unknown')} — website listed")
                continue
            lead = enrich_business(business)
            # AI is deliberately optional: it only enriches the final lead and never blocks it.
            category = classify_business(lead["business_name"], lead["category"]) or lead["category"]
            outreach = suggest_outreach_angle(lead["business_name"], category)
            lead["category"] = category
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""INSERT INTO leads
                (business_name,category,address,postcode,phone,email,website,rating,reviews,maps_url,
                 has_website,lead_score,outreach,status,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                lead["business_name"], category, lead["address"], lead["postcode"], lead["phone"],
                lead["email"], lead["website"], lead["rating"], lead["reviews"], lead["maps_url"],
                lead["has_website"], lead["lead_score"], outreach, "new", "Google Places", now, now
            ))
            with state_lock:
                state["found"] += 1
            log(f"Lead {state['found']}/{target}: {lead['business_name']}")
            if state["found"] >= target:
                break
        conn.commit(); conn.close()
        log(f"Finished — {state['found']} leads created")
    except Exception as exc:
        log(f"Error: {exc}", "error")
        traceback.print_exc()
    finally:
        with state_lock:
            state["running"] = False


@app.get("/")
def index():
    db().close()
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    with state_lock:
        return jsonify(state)


@app.get("/api/leads")
def api_leads():
    return jsonify(all_leads())


@app.post("/api/scrape")
def api_scrape():
    payload = request.get_json(silent=True) or {}
    try:
        postcode = validate_london_postcode(str(payload.get("postcode", "")).upper().strip())
        target = int(payload.get("count", 10))
        if not 1 <= target <= 1000:
            raise ValueError("Count must be between 1 and 1000")
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    with state_lock:
        if state["running"]:
            return jsonify(error="A scrape is already running"), 409
    threading.Thread(target=run_scrape, args=(postcode, target), daemon=True).start()
    return jsonify(ok=True)


@app.patch("/api/leads/<int:lead_id>")
def api_update_lead(lead_id: int):
    payload = request.get_json(silent=True) or {}
    allowed = {"status", "phone", "email", "notes"}
    fields = {k: str(v) for k, v in payload.items() if k in allowed}
    if "status" in fields and fields["status"] not in {"new", "contacted", "qualified", "won", "lost"}:
        return jsonify(error="Invalid status"), 400
    if not fields:
        return jsonify(error="No editable fields"), 400
    conn = db(); row = conn.execute("SELECT id FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row: conn.close(); return jsonify(error="Not found"), 404
    # notes is stored in outreach so the schema stays compact.
    if "notes" in fields: fields["outreach"] = fields.pop("notes")
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=?"
    conn.execute(f"UPDATE leads SET {sets} WHERE id=?", (*fields.values(), datetime.now(timezone.utc).isoformat(), lead_id))
    conn.commit(); conn.close(); log(f"Updated lead #{lead_id}")
    return jsonify(ok=True)


@app.post("/api/leads")
def api_create_lead():
    p = request.get_json(silent=True) or {}
    name = str(p.get("business_name", "")).strip()
    if not name: return jsonify(error="Business name is required"), 400
    now = datetime.now(timezone.utc).isoformat(); conn = db()
    cur = conn.execute("""INSERT INTO leads(business_name,category,address,postcode,phone,email,website,
        has_website,lead_score,outreach,status,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name,p.get("category",""),p.get("address",""),p.get("postcode",""),p.get("phone",""),
         p.get("email",""),p.get("website",""),"yes" if p.get("website") else "no",int(p.get("lead_score",0) or 0),
         p.get("notes", ""),"new","Manual",now,now))
    conn.commit(); lead_id = cur.lastrowid; conn.close(); log(f"Created lead #{lead_id}")
    return jsonify(id=lead_id), 201


@app.delete("/api/leads/<int:lead_id>")
def api_delete_lead(lead_id: int):
    conn = db(); cur = conn.execute("DELETE FROM leads WHERE id=?", (lead_id,)); conn.commit(); conn.close()
    if not cur.rowcount: return jsonify(error="Not found"), 404
    log(f"Deleted lead #{lead_id}")
    return jsonify(ok=True)


@app.get("/api/logs")
def api_logs():
    conn = db(); rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200").fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])


@app.get("/api/export.csv")
def export_csv():
    rows = all_leads(); output = io.StringIO(); fields = [
        "business_name","category","address","postcode","phone","email","website","rating",
        "reviews","maps_url","has_website","lead_score","outreach","status","source","created_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv", as_attachment=True, download_name="py-scrape-leads.csv")


if __name__ == "__main__":
    db().close()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "81")), threaded=True)
