
from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os
import base64
import uuid
from datetime import datetime
from difflib import SequenceMatcher

app = Flask(__name__)

DATABASE = "lost_found.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")
MAX_IMAGE_BYTES = 2 * 1024 * 1024


# =========================================================
# DATABASE
# =========================================================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def create_database():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            colour TEXT,
            location TEXT NOT NULL,
            item_date TEXT NOT NULL,
            description TEXT,
            contact TEXT,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            image_path TEXT,
            reporter_name TEXT,
            item_condition TEXT,
            identifying_features TEXT,
            claimed_by TEXT,
            resolved_at TEXT
        )
    """)

    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(items)").fetchall()
    }

    extra = {
        "image_path": "TEXT",
        "reporter_name": "TEXT",
        "item_condition": "TEXT",
        "identifying_features": "TEXT",
        "claimed_by": "TEXT",
        "resolved_at": "TEXT"
    }

    for name, definition in extra.items():
        if name not in columns:
            db.execute(
                f"ALTER TABLE items ADD COLUMN {name} {definition}"
            )

    db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            message TEXT NOT NULL,
            notification_type TEXT DEFAULT 'Match',
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    db.close()


create_database()


# =========================================================
# HELPERS
# =========================================================

def normal(value):
    return str(value or "").strip().lower()


def similarity(a, b):
    a = normal(a)
    b = normal(b)

    if not a or not b:
        return 0

    if a == b:
        return 1

    ratio = SequenceMatcher(None, a, b).ratio()

    wa = set(a.split())
    wb = set(b.split())
    common = wa.intersection(wb)

    word_score = (
        len(common) / max(len(wa), len(wb))
        if wa and wb else 0
    )

    if a in b or b in a:
        ratio = max(ratio, 0.90)

    return max(ratio, word_score)


def date_similarity(a, b):
    if not a or not b:
        return 0

    if a == b:
        return 1

    try:
        d1 = datetime.strptime(a, "%Y-%m-%d")
        d2 = datetime.strptime(b, "%Y-%m-%d")
        days = abs((d1 - d2).days)

        if days == 1:
            return 0.70
        if days <= 3:
            return 0.40
    except ValueError:
        pass

    return 0


def save_image(data_url):
    if not data_url:
        return ""

    if not data_url.startswith("data:image/"):
        raise ValueError("Invalid image.")

    try:
        header, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded)

        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Image must be 2 MB or smaller.")

        if "image/png" in header:
            ext = ".png"
        elif "image/jpeg" in header or "image/jpg" in header:
            ext = ".jpg"
        elif "image/webp" in header:
            ext = ".webp"
        else:
            raise ValueError("Only PNG, JPG and WEBP are supported.")

        filename = uuid.uuid4().hex + ext
        path = os.path.join(UPLOAD_FOLDER, filename)

        with open(path, "wb") as f:
            f.write(raw)

        return "/static/uploads/" + filename

    except ValueError:
        raise
    except Exception:
        raise ValueError("Could not process image.")


def delete_image(path):
    if not path or not path.startswith("/static/uploads/"):
        return

    local = path.lstrip("/").replace("/", os.sep)

    if os.path.exists(local):
        try:
            os.remove(local)
        except OSError:
            pass


# =========================================================
# SMART MATCHING
# =========================================================

def find_matches(new_item):
    db = get_db()

    opposite = (
        "Found Item"
        if new_item["record_type"] == "Lost Item"
        else "Lost Item"
    )

    rows = db.execute("""
        SELECT * FROM items
        WHERE record_type = ?
          AND status = 'Active'
          AND id != ?
    """, (opposite, new_item.get("id", -1))).fetchall()

    matches = []

    for row in rows:
        score = 0

        # Name 30%
        score += round(
            similarity(new_item.get("item_name"), row["item_name"]) * 30
        )

        # Category 20%
        if normal(new_item.get("category")) == normal(row["category"]):
            score += 20

        # Colour 15%
        c1 = normal(new_item.get("colour"))
        c2 = normal(row["colour"])

        if c1 and c2:
            if c1 == c2:
                score += 15
            elif similarity(c1, c2) >= 0.70:
                score += 8

        # Location 20%
        l1 = normal(new_item.get("location"))
        l2 = normal(row["location"])

        if l1 == l2:
            score += 20
        elif similarity(l1, l2) >= 0.75:
            score += 10

        # Date 15%
        score += round(
            date_similarity(
                new_item.get("item_date"),
                row["item_date"]
            ) * 15
        )

        if score >= 40:
            matches.append({
                "id": row["id"],
                "item_name": row["item_name"],
                "record_type": row["record_type"],
                "category": row["category"],
                "colour": row["colour"],
                "location": row["location"],
                "item_date": row["item_date"],
                "image_path": row["image_path"],
                "score": min(score, 100)
            })

    db.close()

    matches.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return matches[:10]


def create_notifications(item, matches):
    if not matches:
        return

    best = matches[0]
    db = get_db()

    db.execute("""
        INSERT INTO notifications
        (item_id, message, notification_type)
        VALUES (?, ?, 'Match')
    """, (
        item["id"],
        f"Possible match for '{item['item_name']}' "
        f"with '{best['item_name']}' — {best['score']}% match."
    ))

    db.execute("""
        INSERT INTO notifications
        (item_id, message, notification_type)
        VALUES (?, ?, 'Match')
    """, (
        best["id"],
        f"A possible match was found for "
        f"'{best['item_name']}' — {best['score']}% match."
    ))

    db.commit()
    db.close()


# =========================================================
# PAGE
# =========================================================

@app.route("/")
def home():
    return render_template_string(HTML)


# =========================================================
# ITEMS
# =========================================================

@app.route("/api/items", methods=["GET"])
def get_items():
    db = get_db()

    rows = db.execute("""
        SELECT * FROM items
        ORDER BY id DESC
    """).fetchall()

    db.close()

    return jsonify([dict(row) for row in rows])


@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "No data received"
        }), 400

    required = [
        "record_type",
        "item_name",
        "category",
        "location",
        "item_date"
    ]

    for field in required:
        if not str(data.get(field, "")).strip():
            return jsonify({
                "success": False,
                "message": f"{field} is required"
            }), 400

    try:
        image_path = save_image(data.get("image_data", ""))
    except ValueError as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    db = get_db()

    cursor = db.execute("""
        INSERT INTO items (
            record_type, item_name, category, colour,
            location, item_date, description, contact,
            status, image_path, reporter_name,
            item_condition, identifying_features
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?)
    """, (
        data["record_type"],
        data["item_name"].strip(),
        data["category"],
        data.get("colour", "").strip(),
        data["location"],
        data["item_date"],
        data.get("description", "").strip(),
        data.get("contact", "").strip(),
        image_path,
        data.get("reporter_name", "").strip(),
        data.get("item_condition", ""),
        data.get("identifying_features", "").strip()
    ))

    item_id = cursor.lastrowid
    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    item = dict(row)
    matches = find_matches(item)
    create_notifications(item, matches)

    return jsonify({
        "success": True,
        "message": "Item saved successfully",
        "item": item,
        "matches": matches
    })


@app.route("/api/items/<int:item_id>", methods=["GET"])
def get_item(item_id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify(dict(row))


@app.route("/api/items/<int:item_id>", methods=["PUT"])
def update_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    old = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    if not old:
        db.close()
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    old_image = old["image_path"] or ""
    image_path = old_image

    try:
        if data.get("image_data"):
            image_path = save_image(data["image_data"])
    except ValueError as e:
        db.close()
        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    db.execute("""
        UPDATE items SET
            record_type=?,
            item_name=?,
            category=?,
            colour=?,
            location=?,
            item_date=?,
            description=?,
            contact=?,
            image_path=?,
            reporter_name=?,
            item_condition=?,
            identifying_features=?
        WHERE id=?
    """, (
        data.get("record_type", ""),
        data.get("item_name", "").strip(),
        data.get("category", ""),
        data.get("colour", "").strip(),
        data.get("location", ""),
        data.get("item_date", ""),
        data.get("description", "").strip(),
        data.get("contact", "").strip(),
        image_path,
        data.get("reporter_name", "").strip(),
        data.get("item_condition", ""),
        data.get("identifying_features", "").strip(),
        item_id
    ))

    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if image_path != old_image:
        delete_image(old_image)

    return jsonify({
        "success": True,
        "message": "Item updated successfully",
        "item": dict(row)
    })


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    db = get_db()

    old = db.execute(
        "SELECT image_path FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    cursor = db.execute(
        "DELETE FROM items WHERE id=?",
        (item_id,)
    )

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    if old:
        delete_image(old["image_path"])

    return jsonify({
        "success": True,
        "message": "Item deleted successfully"
    })


# =========================================================
# RESOLVE / CLAIM
# =========================================================

@app.route("/api/items/<int:item_id>/resolve", methods=["PUT"])
def resolve_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    cursor = db.execute("""
        UPDATE items
        SET status='Resolved',
            claimed_by=?,
            resolved_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        data.get("claimed_by", "").strip(),
        item_id
    ))

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify({
        "success": True,
        "message": "Item marked as resolved"
    })


@app.route("/api/items/<int:item_id>/claim", methods=["PUT"])
def claim_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    cursor = db.execute("""
        UPDATE items
        SET status='Claimed',
            claimed_by=?,
            resolved_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        data.get("claimed_by", "").strip(),
        item_id
    ))

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify({
        "success": True,
        "message": "Item marked as claimed"
    })


# =========================================================
# MATCHES
# =========================================================

@app.route("/api/matches/<int:item_id>")
def matches(item_id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify([])

    return jsonify(find_matches(dict(row)))


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/api/notifications")
def notifications():
    db = get_db()

    rows = db.execute("""
        SELECT *
        FROM notifications
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    unread = db.execute("""
        SELECT COUNT(*) AS n
        FROM notifications
        WHERE is_read=0
    """).fetchone()["n"]

    db.close()

    return jsonify({
        "notifications": [dict(x) for x in rows],
        "unread": unread
    })


@app.route("/api/notifications/read", methods=["PUT"])
def notifications_read():
    db = get_db()

    db.execute(
        "UPDATE notifications SET is_read=1 WHERE is_read=0"
    )

    db.commit()
    db.close()

    return jsonify({"success": True})


# =========================================================
# ANALYTICS
# =========================================================

@app.route("/api/analytics")
def analytics():
    db = get_db()

    total = db.execute(
        "SELECT COUNT(*) n FROM items"
    ).fetchone()["n"]

    lost = db.execute(
        "SELECT COUNT(*) n FROM items WHERE record_type='Lost Item'"
    ).fetchone()["n"]

    found = db.execute(
        "SELECT COUNT(*) n FROM items WHERE record_type='Found Item'"
    ).fetchone()["n"]

    active = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Active'"
    ).fetchone()["n"]

    resolved = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Resolved'"
    ).fetchone()["n"]

    claimed = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Claimed'"
    ).fetchone()["n"]

    match_notifications = db.execute("""
        SELECT COUNT(*) n
        FROM notifications
        WHERE notification_type='Match'
    """).fetchone()["n"]

    categories = db.execute("""
        SELECT category, COUNT(*) count
        FROM items
        GROUP BY category
        ORDER BY count DESC
    """).fetchall()

    locations = db.execute("""
        SELECT location, COUNT(*) count
        FROM items
        GROUP BY location
        ORDER BY count DESC
        LIMIT 8
    """).fetchall()

    db.close()

    return jsonify({
        "total": total,
        "lost": lost,
        "found": found,
        "active": active,
        "resolved": resolved,
        "claimed": claimed,
        "match_rate": round(
            (match_notifications / total) * 100, 1
        ) if total else 0,
        "categories": [dict(x) for x in categories],
        "locations": [dict(x) for x in locations]
    })


# =========================================================
# FRONTEND
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FINDLY | Smart Lost & Found</title>

<style>
:root {
    --bg:#f4f7fb;
    --card:#fff;
    --text:#172033;
    --muted:#718096;
    --border:#e2e8f0;
    --soft:#f7f9fc;
    --primary:#2f6fed;
}

* { box-sizing:border-box; }

body {
    margin:0;
    font-family:Arial,Helvetica,sans-serif;
    background:var(--bg);
    color:var(--text);
}

body.dark {
    --bg:#111827;
    --card:#1f2937;
    --text:#f3f4f6;
    --muted:#aab4c5;
    --border:#374151;
    --soft:#273449;
}

header {
    background:var(--card);
    border-bottom:1px solid var(--border);
    padding:16px 6%;
    display:flex;
    justify-content:space-between;
    align-items:center;
    position:sticky;
    top:0;
    z-index:50;
}

.logo {
    display:flex;
    align-items:center;
    gap:10px;
    font-size:23px;
    font-weight:800;
    color:var(--primary);
}

.logo-icon {
    width:38px;
    height:38px;
    border-radius:10px;
    background:var(--primary);
    color:#fff;
    display:flex;
    align-items:center;
    justify-content:center;
}

.header-actions {
    display:flex;
    gap:8px;
}

button {
    border:0;
    border-radius:8px;
    padding:10px 14px;
    cursor:pointer;
    font-weight:600;
}

.icon-btn,.secondary {
    background:var(--soft);
    color:var(--text);
    border:1px solid var(--border);
}

.primary {
    background:var(--primary);
    color:#fff;
}

.danger {
    background:#fff0f0;
    color:#c53030;
}

.resolve {
    background:#edf8f1;
    color:#287d48;
}

.claim {
    background:#f0eaff;
    color:#6941c6;
}

.container {
    width:88%;
    max-width:1300px;
    margin:30px auto;
}

.hero h1 {
    margin:0;
    font-size:34px;
}

.hero p {
    color:var(--muted);
}

.stats {
    display:grid;
    grid-template-columns:repeat(6,1fr);
    gap:12px;
    margin:24px 0;
}

.stat,.card {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:14px;
}

.stat {
    padding:17px;
}

.stat-title {
    color:var(--muted);
    font-size:11px;
    text-transform:uppercase;
}

.stat-value {
    font-size:25px;
    font-weight:700;
    margin-top:7px;
}

.card {
    padding:25px;
    margin-bottom:22px;
}

.subtitle {
    color:var(--muted);
    font-size:14px;
    margin-bottom:20px;
}

.form-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:17px;
}

.field {
    display:flex;
    flex-direction:column;
}

.full {
    grid-column:1/-1;
}

label {
    font-size:13px;
    font-weight:600;
    margin-bottom:7px;
}

input,select,textarea {
    width:100%;
    padding:12px 13px;
    border:1px solid var(--border);
    border-radius:8px;
    background:var(--card);
    color:var(--text);
    outline:none;
}

textarea {
    min-height:85px;
    resize:vertical;
}

input:focus,select:focus,textarea:focus {
    border-color:var(--primary);
}

.form-actions,.actions {
    display:flex;
    gap:7px;
    flex-wrap:wrap;
    margin-top:20px;
}

.actions { margin-top:0; }

.filters {
    display:grid;
    grid-template-columns:2fr 1fr 1fr 1fr;
    gap:10px;
}

.table-wrapper {
    overflow-x:auto;
}

table {
    width:100%;
    border-collapse:collapse;
    min-width:1050px;
}

th {
    text-align:left;
    padding:12px;
    background:var(--soft);
    color:var(--muted);
    font-size:11px;
    text-transform:uppercase;
}

td {
    padding:12px;
    border-top:1px solid var(--border);
    font-size:13px;
}

.badge {
    display:inline-block;
    padding:5px 9px;
    border-radius:20px;
    font-size:10px;
    font-weight:700;
}

.badge-lost {
    background:#fff4e5;
    color:#a85d00;
}

.badge-found {
    background:#edf8f1;
    color:#287d48;
}

.badge-resolved {
    background:#eef1f5;
    color:#667085;
}

.badge-claimed {
    background:#f0eaff;
    color:#6941c6;
}

.thumb {
    width:48px;
    height:48px;
    object-fit:cover;
    border-radius:7px;
    border:1px solid var(--border);
}

.preview {
    display:none;
    margin-top:8px;
    max-width:180px;
    max-height:130px;
    border-radius:8px;
}

.match-box {
    display:none;
    margin-top:20px;
    padding:15px;
    background:var(--soft);
    border-left:4px solid var(--primary);
    border-radius:8px;
}

.match-item {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:8px;
    padding:12px;
    margin-top:8px;
}

.match-score {
    color:var(--primary);
    font-weight:800;
}

.analytics-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:20px;
}

.analytics-list div {
    display:flex;
    justify-content:space-between;
    padding:9px 0;
    border-bottom:1px solid var(--border);
}

.notification-panel {
    position:fixed;
    right:20px;
    top:72px;
    width:min(390px,calc(100vw - 30px));
    max-height:70vh;
    overflow:auto;
    background:var(--card);
    border:1px solid var(--border);
    box-shadow:0 15px 40px rgba(0,0,0,.18);
    border-radius:12px;
    z-index:100;
    display:none;
    padding:16px;
}

.notification {
    padding:11px 0;
    border-bottom:1px solid var(--border);
    font-size:13px;
}

.notification-btn {
    position:relative;
}

.notification-count {
    position:absolute;
    right:-5px;
    top:-6px;
    background:#e53e3e;
    color:#fff;
    min-width:18px;
    height:18px;
    border-radius:20px;
    display:none;
    align-items:center;
    justify-content:center;
    font-size:10px;
}

.empty {
    text-align:center;
    padding:40px;
    color:var(--muted);
}

.small-note {
    color:var(--muted);
    font-size:11px;
    margin-top:5px;
}

.toast {
    position:fixed;
    right:20px;
    bottom:20px;
    background:#172b4d;
    color:#fff;
    padding:12px 17px;
    border-radius:8px;
    display:none;
    z-index:999;
}

@media(max-width:1050px) {
    .stats { grid-template-columns:repeat(3,1fr); }
    .filters { grid-template-columns:1fr 1fr; }
}

@media(max-width:750px) {
    .container { width:94%; }
    .stats { grid-template-columns:1fr 1fr; }
    .form-grid { grid-template-columns:1fr; }
    .full { grid-column:auto; }
    .filters { grid-template-columns:1fr; }
    .analytics-grid { grid-template-columns:1fr; }
    .header-text { display:none; }
    .hero h1 { font-size:28px; }
}
</style>
</head>

<body>

<header>
    <div class="logo">
        <div class="logo-icon">✓</div>
        FINDLY
    </div>

    <div class="header-text">
        Smart Lost & Found Management System
    </div>

    <div class="header-actions">
        <button class="icon-btn notification-btn"
                onclick="toggleNotifications()">
            🔔
            <span id="notificationCount"
                  class="notification-count">0</span>
        </button>

        <button class="icon-btn"
                id="themeButton"
                onclick="toggleDarkMode()">
            🌙
        </button>
    </div>
</header>

<div id="notificationPanel" class="notification-panel">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>Notifications</strong>
        <button class="secondary"
                onclick="markNotificationsRead()">
            Mark read
        </button>
    </div>
    <div id="notificationList"></div>
</div>

<div class="container">

    <div class="hero">
        <h1>Smart Lost & Found</h1>
        <p>
            Report, manage and intelligently identify possible matches.
        </p>
    </div>

    <div class="stats">
        <div class="stat">
            <div class="stat-title">Total Records</div>
            <div class="stat-value" id="totalRecords">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Lost Items</div>
            <div class="stat-value" id="lostItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Found Items</div>
            <div class="stat-value" id="foundItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Active Items</div>
            <div class="stat-value" id="activeItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Resolved / Claimed</div>
            <div class="stat-value" id="resolvedItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Match Rate</div>
            <div class="stat-value" id="matchRate">0%</div>
        </div>
    </div>

    <div class="card">
        <h2 id="formTitle">Report Lost / Found Item</h2>
        <div class="subtitle">
            Add complete details to improve matching accuracy.
        </div>

        <form id="itemForm">

            <div class="form-grid">

                <div class="field">
                    <label>Record Type *</label>
                    <select id="record_type" required>
                        <option>Lost Item</option>
                        <option>Found Item</option>
                    </select>
                </div>

                <div class="field">
                    <label>Item Name *</label>
                    <input id="item_name"
                           placeholder="Example: Black Wallet"
                           required>
                </div>

                <div class="field">
                    <label>Category *</label>
                    <select id="category" required>
                        <option value="">Select Category</option>
                        <option>Wallet</option>
                        <option>Mobile Phone</option>
                        <option>Laptop</option>
                        <option>Bag</option>
                        <option>ID Card</option>
                        <option>Keys</option>
                        <option>Book</option>
                        <option>Earphones</option>
                        <option>Watch</option>
                        <option>Water Bottle</option>
                        <option>Umbrella</option>
                        <option>Other</option>
                    </select>
                </div>

                <div class="field">
                    <label>Colour</label>
                    <input id="colour" placeholder="Example: Black">
                </div>

                <div class="field">
                    <label>College Location *</label>
                    <select id="location" required>
                        <option value="">Select Location</option>
                        <option>College Canteen</option>
                        <option>Library</option>
                        <option>Computer Lab</option>
                        <option>Classroom</option>
                        <option>Seminar Hall</option>
                        <option>Auditorium</option>
                        <option>Parking Area</option>
                        <option>Hostel</option>
                        <option>Bus / Transport</option>
                        <option>Sports Ground</option>
                        <option>Administrative Block</option>
                        <option>Department Block</option>
                        <option>Other</option>
                    </select>
                </div>

                <div class="field">
                    <label>Date *</label>
                    <input id="item_date" type="date" required>
                </div>

                <div class="field">
                    <label>Condition</label>
                    <select id="item_condition">
                        <option value="">Select Condition</option>
                        <option>New</option>
                        <option>Good</option>
                        <option>Used</option>
                        <option>Damaged</option>
                        <option>Unknown</option>
                    </select>
                </div>

                <div class="field">
                    <label>Reporter Name</label>
                    <input id="reporter_name"
                           placeholder="Your name">
                </div>

                <div class="field full">
                    <label>Identifying Features</label>
                    <input id="identifying_features"
                           placeholder="Sticker, initials, scratch, cover, unique mark...">
                </div>

                <div class="field full">
                    <label>Description</label>
                    <textarea id="description"
                              placeholder="Describe the item..."></textarea>
                </div>

                <div class="field">
                    <label>Contact</label>
                    <input id="contact"
                           placeholder="Phone / Email">
                </div>

                <div class="field">
                    <label>Item Photo</label>
                    <input id="image"
                           type="file"
                           accept="image/png,image/jpeg,image/webp"
                           onchange="previewImage()">
                    <img id="imagePreview" class="preview">
                    <div class="small-note">
                        PNG/JPG/WEBP, maximum 2 MB
                    </div>
                </div>

            </div>

            <div class="form-actions">
                <button class="primary"
                        type="submit"
                        id="saveButton">
                    Save Item
                </button>

                <button class="secondary"
                        type="button"
                        onclick="resetForm()">
                    Clear
                </button>
            </div>

        </form>

        <div class="match-box" id="matchBox">
            <strong>🎯 Possible Matching Items</strong>
            <div id="matchResults"></div>
        </div>
    </div>

    <div class="card">
        <h2>🔍 Advanced Search & Filters</h2>

        <div class="filters">

            <input id="search"
                   placeholder="Search item, category, location..."
                   oninput="displayItems()">

            <select id="filterType" onchange="displayItems()">
                <option value="">All Types</option>
                <option>Lost Item</option>
                <option>Found Item</option>
            </select>

            <select id="filterCategory" onchange="displayItems()">
                <option value="">All Categories</option>
                <option>Wallet</option>
                <option>Mobile Phone</option>
                <option>Laptop</option>
                <option>Bag</option>
                <option>ID Card</option>
                <option>Keys</option>
                <option>Book</option>
                <option>Earphones</option>
                <option>Watch</option>
                <option>Other</option>
            </select>

            <select id="filterLocation" onchange="displayItems()">
                <option value="">All Locations</option>
                <option>College Canteen</option>
                <option>Library</option>
                <option>Computer Lab</option>
                <option>Classroom</option>
                <option>Seminar Hall</option>
                <option>Auditorium</option>
                <option>Parking Area</option>
                <option>Hostel</option>
                <option>Bus / Transport</option>
                <option>Sports Ground</option>
                <option>Administrative Block</option>
                <option>Department Block</option>
                <option>Other</option>
            </select>

        </div>

        <br>

        <select id="filterStatus"
                onchange="displayItems()"
                style="max-width:250px;">
            <option value="">All Status</option>
            <option>Active</option>
            <option>Resolved</option>
            <option>Claimed</option>
        </select>

        <button class="secondary"
                onclick="clearFilters()">
            Clear Filters
        </button>
    </div>

    <div class="card">
        <h2>📋 Item Records</h2>
        <div class="subtitle">
            Manage all reported items.
        </div>

        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Photo</th>
                        <th>ID</th>
                        <th>Type</th>
                        <th>Item</th>
                        <th>Category</th>
                        <th>Colour</th>
                        <th>Location</th>
                        <th>Date</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>

                <tbody id="itemTable"></tbody>
            </table>
        </div>
    </div>

    <div class="card">
        <h2>📊 Admin Analytics Dashboard</h2>
        <div class="subtitle">
            Quick overview of FINDLY activity.
        </div>

        <div class="analytics-grid">

            <div>
                <h3>Top Categories</h3>
                <div id="categoryAnalytics"
                     class="analytics-list"></div>
            </div>

            <div>
                <h3>Top Locations</h3>
                <div id="locationAnalytics"
                     class="analytics-list"></div>
            </div>

        </div>
    </div>

</div>

<div class="toast" id="toast"></div>

<script>
let allItems = [];
let editingId = null;


function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.style.display = "block";

    setTimeout(() => {
        toast.style.display = "none";
    }, 2800);
}


async function loadItems() {
    try {
        const response = await fetch("/api/items");

        if (!response.ok) {
            throw new Error("Server error");
        }

        allItems = await response.json();

        displayItems();
        updateStats();
        loadAnalytics();
        loadNotifications();

    } catch (error) {
        console.error(error);
        showToast("Unable to load records.");
    }
}


function displayItems() {
    const table = document.getElementById("itemTable");

    const search = document
        .getElementById("search")
        .value
        .toLowerCase()
        .trim();

    const type =
        document.getElementById("filterType").value;

    const category =
        document.getElementById("filterCategory").value;

    const location =
        document.getElementById("filterLocation").value;

    const status =
        document.getElementById("filterStatus").value;

    const filtered = allItems.filter(item => {

        const text = [
            item.item_name,
            item.category,
            item.location,
            item.record_type,
            item.colour,
            item.description,
            item.identifying_features,
            item.reporter_name
        ].join(" ").toLowerCase();

        return (
            text.includes(search) &&
            (!type || item.record_type === type) &&
            (!category || item.category === category) &&
            (!location || item.location === location) &&
            (!status || item.status === status)
        );
    });

    if (!filtered.length) {
        table.innerHTML = `
            <tr>
                <td colspan="10" class="empty">
                    No records found.
                </td>
            </tr>
        `;
        return;
    }

    table.innerHTML = filtered.map(item => {

        let statusClass = "badge-found";

        if (item.status === "Resolved") {
            statusClass = "badge-resolved";
        }

        if (item.status === "Claimed") {
            statusClass = "badge-claimed";
        }

        const typeClass =
            item.record_type === "Lost Item"
            ? "badge-lost"
            : "badge-found";

        return `
            <tr>

                <td>
                    ${
                        item.image_path
                        ? `<img class="thumb"
                                src="${escapeHtml(item.image_path)}">`
                        : "—"
                    }
                </td>

                <td>${item.id}</td>

                <td>
                    <span class="badge ${typeClass}">
                        ${escapeHtml(item.record_type)}
                    </span>
                </td>

                <td>
                    <strong>
                        ${escapeHtml(item.item_name)}
                    </strong>
                </td>

                <td>${escapeHtml(item.category)}</td>

                <td>${escapeHtml(item.colour || "-")}</td>

                <td>${escapeHtml(item.location)}</td>

                <td>${escapeHtml(item.item_date)}</td>

                <td>
                    <span class="badge ${statusClass}">
                        ${escapeHtml(item.status)}
                    </span>
                </td>

                <td>
                    <div class="actions">

                        <button class="secondary"
                                onclick="viewItem(${item.id})">
                            View
                        </button>

                        <button class="primary"
                                onclick="editItem(${item.id})">
                            Edit
                        </button>

                        ${
                            item.status === "Active"
                            ? `
                            <button class="resolve"
                                    onclick="resolveItem(${item.id})">
                                Resolve
                            </button>

                            <button class="claim"
                                    onclick="claimItem(${item.id})">
                                Claim
                            </button>
                            `
                            : ""
                        }

                        <button class="danger"
                                onclick="deleteItem(${item.id})">
                            Delete
                        </button>

                    </div>
                </td>

            </tr>
        `;
    }).join("");
}


function fileToDataUrl(file) {
    if (!file) {
        return Promise.resolve("");
    }

    if (file.size > 2 * 1024 * 1024) {
        return Promise.reject(
            new Error("Image must be 2 MB or smaller.")
        );
    }

    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => resolve(reader.result);
        reader.onerror = () =>
            reject(new Error("Could not read image."));

        reader.readAsDataURL(file);
    });
}


function previewImage() {
    const input = document.getElementById("image");
    const preview = document.getElementById("imagePreview");

    if (!input.files.length) {
        preview.style.display = "none";
        return;
    }

    if (input.files[0].size > 2 * 1024 * 1024) {
        showToast("Image must be 2 MB or smaller.");
        input.value = "";
        preview.style.display = "none";
        return;
    }

    preview.src =
        URL.createObjectURL(input.files[0]);

    preview.style.display = "block";
}


document.getElementById("itemForm")
.addEventListener("submit", async event => {

    event.preventDefault();

    const button =
        document.getElementById("saveButton");

    button.disabled = true;
    button.innerText =
        editingId ? "Updating..." : "Saving...";

    try {

        const image =
            document.getElementById("image").files[0];

        const imageData =
            await fileToDataUrl(image);

        const data = {
            record_type:
                document.getElementById("record_type").value,

            item_name:
                document.getElementById("item_name").value.trim(),

            category:
                document.getElementById("category").value,

            colour:
                document.getElementById("colour").value.trim(),

            location:
                document.getElementById("location").value,

            item_date:
                document.getElementById("item_date").value,

            item_condition:
                document.getElementById("item_condition").value,

            reporter_name:
                document.getElementById("reporter_name").value.trim(),

            identifying_features:
                document
                .getElementById("identifying_features")
                .value.trim(),

            description:
                document.getElementById("description").value.trim(),

            contact:
                document.getElementById("contact").value.trim(),

            image_data: imageData
        };

        let response;

        if (editingId) {

            response = await fetch(
                `/api/items/${editingId}`,
                {
                    method:"PUT",
                    headers:{
                        "Content-Type":"application/json"
                    },
                    body:JSON.stringify(data)
                }
            );

        } else {

            response = await fetch(
                "/api/items",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":"application/json"
                    },
                    body:JSON.stringify(data)
                }
            );
        }

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.message || "Operation failed"
            );
        }

        if (editingId) {
            showToast("Item updated successfully.");
        } else {
            showToast("Item saved successfully.");

            if (result.matches &&
                result.matches.length) {
                showMatches(result.matches);
                showToast(
                    "Item saved — possible match found!"
                );
            }
        }

        editingId = null;
        resetForm(false);
        await loadItems();

    } catch (error) {
        console.error(error);
        showToast(error.message);

    } finally {
        button.disabled = false;
        button.innerText = "Save Item";
    }
});


function showMatches(matches) {
    const box =
        document.getElementById("matchBox");

    const results =
        document.getElementById("matchResults");

    box.style.display = "block";

    if (!matches.length) {
        results.innerHTML =
            "<p>No possible matches found.</p>";
        return;
    }

    results.innerHTML = matches.map(match => `
        <div class="match-item">

            ${
                match.image_path
                ? `<img class="thumb"
                        src="${escapeHtml(match.image_path)}">`
                : ""
            }

            <strong>
                ${escapeHtml(match.item_name)}
            </strong>

            <br>

            <small>
                ${escapeHtml(match.record_type)}
                · ${escapeHtml(match.category)}
                · ${escapeHtml(match.location)}
                · ${escapeHtml(match.item_date)}
            </small>

            <br>

            <span class="match-score">
                Match Score: ${match.score}%
            </span>

        </div>
    `).join("");
}


async function viewItem(id) {
    const response =
        await fetch(`/api/items/${id}`);

    const item = await response.json();

    alert(
        "ITEM DETAILS\n\n" +
        "Type: " + item.record_type + "\n" +
        "Item: " + item.item_name + "\n" +
        "Category: " + item.category + "\n" +
        "Colour: " + (item.colour || "-") + "\n" +
        "Location: " + item.location + "\n" +
        "Date: " + item.item_date + "\n" +
        "Condition: " + (item.item_condition || "-") + "\n" +
        "Reporter: " + (item.reporter_name || "-") + "\n" +
        "Features: " +
        (item.identifying_features || "-") +
        "\n\nDescription: " +
        (item.description || "-") +
        "\n\nContact: " +
        (item.contact || "-") +
        "\nStatus: " + item.status +
        "\nClaimed By: " +
        (item.claimed_by || "-")
    );
}


async function editItem(id) {
    const response =
        await fetch(`/api/items/${id}`);

    const item = await response.json();

    editingId = id;

    document.getElementById("record_type").value =
        item.record_type;

    document.getElementById("item_name").value =
        item.item_name;

    document.getElementById("category").value =
        item.category;

    document.getElementById("colour").value =
        item.colour || "";

    document.getElementById("location").value =
        item.location;

    document.getElementById("item_date").value =
        item.item_date;

    document.getElementById("item_condition").value =
        item.item_condition || "";

    document.getElementById("reporter_name").value =
        item.reporter_name || "";

    document.getElementById("identifying_features").value =
        item.identifying_features || "";

    document.getElementById("description").value =
        item.description || "";

    document.getElementById("contact").value =
        item.contact || "";

    document.getElementById("formTitle").innerText =
        "Edit Lost / Found Item";

    document.getElementById("saveButton").innerText =
        "Update Item";

    window.scrollTo({
        top:0,
        behavior:"smooth"
    });
}


async function deleteItem(id) {
    if (!confirm(
        "Are you sure you want to delete this item?"
    )) {
        return;
    }

    try {
        const response = await fetch(
            `/api/items/${id}`,
            {method:"DELETE"}
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item deleted successfully.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


async function resolveItem(id) {
    const name = prompt(
        "Enter claimant / receiver name (optional):"
    );

    try {
        const response = await fetch(
            `/api/items/${id}/resolve`,
            {
                method:"PUT",
                headers:{
                    "Content-Type":"application/json"
                },
                body:JSON.stringify({
                    claimed_by:name || ""
                })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item marked as resolved.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


async function claimItem(id) {
    const name = prompt("Enter claimant name:");

    if (name === null) {
        return;
    }

    try {
        const response = await fetch(
            `/api/items/${id}/claim`,
            {
                method:"PUT",
                headers:{
                    "Content-Type":"application/json"
                },
                body:JSON.stringify({
                    claimed_by:name
                })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item marked as claimed.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


function resetForm(clearMatch=true) {
    document.getElementById("itemForm").reset();

    editingId = null;

    document.getElementById("formTitle").innerText =
        "Report Lost / Found Item";

    document.getElementById("saveButton").innerText =
        "Save Item";

    document.getElementById("item_date").value =
        new Date().toISOString().split("T")[0];

    const preview =
        document.getElementById("imagePreview");

    preview.src = "";
    preview.style.display = "none";

    if (clearMatch) {
        document.getElementById("matchBox")
            .style.display = "none";
    }
}


function clearFilters() {
    document.getElementById("search").value = "";
    document.getElementById("filterType").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterLocation").value = "";
    document.getElementById("filterStatus").value = "";
    displayItems();
}


function updateStats() {
    document.getElementById("totalRecords").innerText =
        allItems.length;

    document.getElementById("lostItems").innerText =
        allItems.filter(
            x => x.record_type === "Lost Item"
        ).length;

    document.getElementById("foundItems").innerText =
        allItems.filter(
            x => x.record_type === "Found Item"
        ).length;

    document.getElementById("activeItems").innerText =
        allItems.filter(
            x => x.status === "Active"
        ).length;

    document.getElementById("resolvedItems").innerText =
        allItems.filter(
            x => x.status === "Resolved" ||
                 x.status === "Claimed"
        ).length;
}


async function loadAnalytics() {
    try {
        const response =
            await fetch("/api/analytics");

        const data = await response.json();

        document.getElementById("matchRate").innerText =
            data.match_rate + "%";

        document.getElementById("categoryAnalytics")
            .innerHTML =
            data.categories.length
            ? data.categories.map(x => `
                <div>
                    <span>${escapeHtml(x.category)}</span>
                    <strong>${x.count}</strong>
                </div>
            `).join("")
            : "<p>No data yet.</p>";

        document.getElementById("locationAnalytics")
            .innerHTML =
            data.locations.length
            ? data.locations.map(x => `
                <div>
                    <span>${escapeHtml(x.location)}</span>
                    <strong>${x.count}</strong>
                </div>
            `).join("")
            : "<p>No data yet.</p>";

    } catch(error) {
        console.error(error);
    }
}


async function loadNotifications() {
    try {
        const response =
            await fetch("/api/notifications");

        const data = await response.json();

        const badge =
            document.getElementById("notificationCount");

        badge.innerText = data.unread;
        badge.style.display =
            data.unread ? "flex" : "none";

        const list =
            document.getElementById("notificationList");

        if (!data.notifications.length) {
            list.innerHTML =
                "<p style='color:#718096;'>No notifications yet.</p>";
            return;
        }

        list.innerHTML =
            data.notifications.map(n => `
                <div class="notification">
                    <strong>${escapeHtml(n.notification_type)}</strong>
                    <br>
                    ${escapeHtml(n.message)}
                    <br>
                    <small>${escapeHtml(n.created_at)}</small>
                </div>
            `).join("");

    } catch(error) {
        console.error(error);
    }
}


function toggleNotifications() {
    const panel =
        document.getElementById("notificationPanel");

    panel.style.display =
        panel.style.display === "block"
        ? "none"
        : "block";

    loadNotifications();
}


async function markNotificationsRead() {
    await fetch(
        "/api/notifications/read",
        {method:"PUT"}
    );

    loadNotifications();
}


function toggleDarkMode() {
    document.body.classList.toggle("dark");

    const dark =
        document.body.classList.contains("dark");

    localStorage.setItem(
        "findlyDarkMode",
        dark ? "1" : "0"
    );

    document.getElementById("themeButton")
        .innerText = dark ? "☀️" : "🌙";
}


if (localStorage.getItem("findlyDarkMode") === "1") {
    document.body.classList.add("dark");
    document.getElementById("themeButton")
        .innerText = "☀️";
}


document.getElementById("item_date").value =
    new Date().toISOString().split("T")[0];

loadItems();
loadNotifications();
loadAnalytics();
</script>

</body>
</html>
"""


# =======
from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os
import base64
import uuid
from datetime import datetime
from difflib import SequenceMatcher

app = Flask(__name__)

DATABASE = "lost_found.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")
MAX_IMAGE_BYTES = 2 * 1024 * 1024


# =========================================================
# DATABASE
# =========================================================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def create_database():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            colour TEXT,
            location TEXT NOT NULL,
            item_date TEXT NOT NULL,
            description TEXT,
            contact TEXT,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            image_path TEXT,
            reporter_name TEXT,
            item_condition TEXT,
            identifying_features TEXT,
            claimed_by TEXT,
            resolved_at TEXT
        )
    """)

    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(items)").fetchall()
    }

    extra = {
        "image_path": "TEXT",
        "reporter_name": "TEXT",
        "item_condition": "TEXT",
        "identifying_features": "TEXT",
        "claimed_by": "TEXT",
        "resolved_at": "TEXT"
    }

    for name, definition in extra.items():
        if name not in columns:
            db.execute(
                f"ALTER TABLE items ADD COLUMN {name} {definition}"
            )

    db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            message TEXT NOT NULL,
            notification_type TEXT DEFAULT 'Match',
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    db.close()


create_database()


# =========================================================
# HELPERS
# =========================================================

def normal(value):
    return str(value or "").strip().lower()


def similarity(a, b):
    a = normal(a)
    b = normal(b)

    if not a or not b:
        return 0

    if a == b:
        return 1

    ratio = SequenceMatcher(None, a, b).ratio()

    wa = set(a.split())
    wb = set(b.split())
    common = wa.intersection(wb)

    word_score = (
        len(common) / max(len(wa), len(wb))
        if wa and wb else 0
    )

    if a in b or b in a:
        ratio = max(ratio, 0.90)

    return max(ratio, word_score)


def date_similarity(a, b):
    if not a or not b:
        return 0

    if a == b:
        return 1

    try:
        d1 = datetime.strptime(a, "%Y-%m-%d")
        d2 = datetime.strptime(b, "%Y-%m-%d")
        days = abs((d1 - d2).days)

        if days == 1:
            return 0.70
        if days <= 3:
            return 0.40
    except ValueError:
        pass

    return 0


def save_image(data_url):
    if not data_url:
        return ""

    if not data_url.startswith("data:image/"):
        raise ValueError("Invalid image.")

    try:
        header, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded)

        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Image must be 2 MB or smaller.")

        if "image/png" in header:
            ext = ".png"
        elif "image/jpeg" in header or "image/jpg" in header:
            ext = ".jpg"
        elif "image/webp" in header:
            ext = ".webp"
        else:
            raise ValueError("Only PNG, JPG and WEBP are supported.")

        filename = uuid.uuid4().hex + ext
        path = os.path.join(UPLOAD_FOLDER, filename)

        with open(path, "wb") as f:
            f.write(raw)

        return "/static/uploads/" + filename

    except ValueError:
        raise
    except Exception:
        raise ValueError("Could not process image.")


def delete_image(path):
    if not path or not path.startswith("/static/uploads/"):
        return

    local = path.lstrip("/").replace("/", os.sep)

    if os.path.exists(local):
        try:
            os.remove(local)
        except OSError:
            pass


# =========================================================
# SMART MATCHING
# =========================================================

def find_matches(new_item):
    db = get_db()

    opposite = (
        "Found Item"
        if new_item["record_type"] == "Lost Item"
        else "Lost Item"
    )

    rows = db.execute("""
        SELECT * FROM items
        WHERE record_type = ?
          AND status = 'Active'
          AND id != ?
    """, (opposite, new_item.get("id", -1))).fetchall()

    matches = []

    for row in rows:
        score = 0

        # Name 30%
        score += round(
            similarity(new_item.get("item_name"), row["item_name"]) * 30
        )

        # Category 20%
        if normal(new_item.get("category")) == normal(row["category"]):
            score += 20

        # Colour 15%
        c1 = normal(new_item.get("colour"))
        c2 = normal(row["colour"])

        if c1 and c2:
            if c1 == c2:
                score += 15
            elif similarity(c1, c2) >= 0.70:
                score += 8

        # Location 20%
        l1 = normal(new_item.get("location"))
        l2 = normal(row["location"])

        if l1 == l2:
            score += 20
        elif similarity(l1, l2) >= 0.75:
            score += 10

        # Date 15%
        score += round(
            date_similarity(
                new_item.get("item_date"),
                row["item_date"]
            ) * 15
        )

        if score >= 40:
            matches.append({
                "id": row["id"],
                "item_name": row["item_name"],
                "record_type": row["record_type"],
                "category": row["category"],
                "colour": row["colour"],
                "location": row["location"],
                "item_date": row["item_date"],
                "image_path": row["image_path"],
                "score": min(score, 100)
            })

    db.close()

    matches.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return matches[:10]


def create_notifications(item, matches):
    if not matches:
        return

    best = matches[0]
    db = get_db()

    db.execute("""
        INSERT INTO notifications
        (item_id, message, notification_type)
        VALUES (?, ?, 'Match')
    """, (
        item["id"],
        f"Possible match for '{item['item_name']}' "
        f"with '{best['item_name']}' — {best['score']}% match."
    ))

    db.execute("""
        INSERT INTO notifications
        (item_id, message, notification_type)
        VALUES (?, ?, 'Match')
    """, (
        best["id"],
        f"A possible match was found for "
        f"'{best['item_name']}' — {best['score']}% match."
    ))

    db.commit()
    db.close()


# =========================================================
# PAGE
# =========================================================

@app.route("/")
def home():
    return render_template_string(HTML)


# =========================================================
# ITEMS
# =========================================================

@app.route("/api/items", methods=["GET"])
def get_items():
    db = get_db()

    rows = db.execute("""
        SELECT * FROM items
        ORDER BY id DESC
    """).fetchall()

    db.close()

    return jsonify([dict(row) for row in rows])


@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "No data received"
        }), 400

    required = [
        "record_type",
        "item_name",
        "category",
        "location",
        "item_date"
    ]

    for field in required:
        if not str(data.get(field, "")).strip():
            return jsonify({
                "success": False,
                "message": f"{field} is required"
            }), 400

    try:
        image_path = save_image(data.get("image_data", ""))
    except ValueError as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    db = get_db()

    cursor = db.execute("""
        INSERT INTO items (
            record_type, item_name, category, colour,
            location, item_date, description, contact,
            status, image_path, reporter_name,
            item_condition, identifying_features
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?)
    """, (
        data["record_type"],
        data["item_name"].strip(),
        data["category"],
        data.get("colour", "").strip(),
        data["location"],
        data["item_date"],
        data.get("description", "").strip(),
        data.get("contact", "").strip(),
        image_path,
        data.get("reporter_name", "").strip(),
        data.get("item_condition", ""),
        data.get("identifying_features", "").strip()
    ))

    item_id = cursor.lastrowid
    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    item = dict(row)
    matches = find_matches(item)
    create_notifications(item, matches)

    return jsonify({
        "success": True,
        "message": "Item saved successfully",
        "item": item,
        "matches": matches
    })


@app.route("/api/items/<int:item_id>", methods=["GET"])
def get_item(item_id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify(dict(row))


@app.route("/api/items/<int:item_id>", methods=["PUT"])
def update_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    old = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    if not old:
        db.close()
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    old_image = old["image_path"] or ""
    image_path = old_image

    try:
        if data.get("image_data"):
            image_path = save_image(data["image_data"])
    except ValueError as e:
        db.close()
        return jsonify({
            "success": False,
            "message": str(e)
        }), 400

    db.execute("""
        UPDATE items SET
            record_type=?,
            item_name=?,
            category=?,
            colour=?,
            location=?,
            item_date=?,
            description=?,
            contact=?,
            image_path=?,
            reporter_name=?,
            item_condition=?,
            identifying_features=?
        WHERE id=?
    """, (
        data.get("record_type", ""),
        data.get("item_name", "").strip(),
        data.get("category", ""),
        data.get("colour", "").strip(),
        data.get("location", ""),
        data.get("item_date", ""),
        data.get("description", "").strip(),
        data.get("contact", "").strip(),
        image_path,
        data.get("reporter_name", "").strip(),
        data.get("item_condition", ""),
        data.get("identifying_features", "").strip(),
        item_id
    ))

    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if image_path != old_image:
        delete_image(old_image)

    return jsonify({
        "success": True,
        "message": "Item updated successfully",
        "item": dict(row)
    })


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    db = get_db()

    old = db.execute(
        "SELECT image_path FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    cursor = db.execute(
        "DELETE FROM items WHERE id=?",
        (item_id,)
    )

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    if old:
        delete_image(old["image_path"])

    return jsonify({
        "success": True,
        "message": "Item deleted successfully"
    })


# =========================================================
# RESOLVE / CLAIM
# =========================================================

@app.route("/api/items/<int:item_id>/resolve", methods=["PUT"])
def resolve_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    cursor = db.execute("""
        UPDATE items
        SET status='Resolved',
            claimed_by=?,
            resolved_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        data.get("claimed_by", "").strip(),
        item_id
    ))

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify({
        "success": True,
        "message": "Item marked as resolved"
    })


@app.route("/api/items/<int:item_id>/claim", methods=["PUT"])
def claim_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()

    cursor = db.execute("""
        UPDATE items
        SET status='Claimed',
            claimed_by=?,
            resolved_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        data.get("claimed_by", "").strip(),
        item_id
    ))

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify({
        "success": True,
        "message": "Item marked as claimed"
    })


# =========================================================
# MATCHES
# =========================================================

@app.route("/api/matches/<int:item_id>")
def matches(item_id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id=?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify([])

    return jsonify(find_matches(dict(row)))


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/api/notifications")
def notifications():
    db = get_db()

    rows = db.execute("""
        SELECT *
        FROM notifications
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    unread = db.execute("""
        SELECT COUNT(*) AS n
        FROM notifications
        WHERE is_read=0
    """).fetchone()["n"]

    db.close()

    return jsonify({
        "notifications": [dict(x) for x in rows],
        "unread": unread
    })


@app.route("/api/notifications/read", methods=["PUT"])
def notifications_read():
    db = get_db()

    db.execute(
        "UPDATE notifications SET is_read=1 WHERE is_read=0"
    )

    db.commit()
    db.close()

    return jsonify({"success": True})


# =========================================================
# ANALYTICS
# =========================================================

@app.route("/api/analytics")
def analytics():
    db = get_db()

    total = db.execute(
        "SELECT COUNT(*) n FROM items"
    ).fetchone()["n"]

    lost = db.execute(
        "SELECT COUNT(*) n FROM items WHERE record_type='Lost Item'"
    ).fetchone()["n"]

    found = db.execute(
        "SELECT COUNT(*) n FROM items WHERE record_type='Found Item'"
    ).fetchone()["n"]

    active = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Active'"
    ).fetchone()["n"]

    resolved = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Resolved'"
    ).fetchone()["n"]

    claimed = db.execute(
        "SELECT COUNT(*) n FROM items WHERE status='Claimed'"
    ).fetchone()["n"]

    match_notifications = db.execute("""
        SELECT COUNT(*) n
        FROM notifications
        WHERE notification_type='Match'
    """).fetchone()["n"]

    categories = db.execute("""
        SELECT category, COUNT(*) count
        FROM items
        GROUP BY category
        ORDER BY count DESC
    """).fetchall()

    locations = db.execute("""
        SELECT location, COUNT(*) count
        FROM items
        GROUP BY location
        ORDER BY count DESC
        LIMIT 8
    """).fetchall()

    db.close()

    return jsonify({
        "total": total,
        "lost": lost,
        "found": found,
        "active": active,
        "resolved": resolved,
        "claimed": claimed,
        "match_rate": round(
            (match_notifications / total) * 100, 1
        ) if total else 0,
        "categories": [dict(x) for x in categories],
        "locations": [dict(x) for x in locations]
    })


# =========================================================
# FRONTEND
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FINDLY | Smart Lost & Found</title>

<style>
:root {
    --bg:#f4f7fb;
    --card:#fff;
    --text:#172033;
    --muted:#718096;
    --border:#e2e8f0;
    --soft:#f7f9fc;
    --primary:#2f6fed;
}

* { box-sizing:border-box; }

body {
    margin:0;
    font-family:Arial,Helvetica,sans-serif;
    background:var(--bg);
    color:var(--text);
}

body.dark {
    --bg:#111827;
    --card:#1f2937;
    --text:#f3f4f6;
    --muted:#aab4c5;
    --border:#374151;
    --soft:#273449;
}

header {
    background:var(--card);
    border-bottom:1px solid var(--border);
    padding:16px 6%;
    display:flex;
    justify-content:space-between;
    align-items:center;
    position:sticky;
    top:0;
    z-index:50;
}

.logo {
    display:flex;
    align-items:center;
    gap:10px;
    font-size:23px;
    font-weight:800;
    color:var(--primary);
}

.logo-icon {
    width:38px;
    height:38px;
    border-radius:10px;
    background:var(--primary);
    color:#fff;
    display:flex;
    align-items:center;
    justify-content:center;
}

.header-actions {
    display:flex;
    gap:8px;
}

button {
    border:0;
    border-radius:8px;
    padding:10px 14px;
    cursor:pointer;
    font-weight:600;
}

.icon-btn,.secondary {
    background:var(--soft);
    color:var(--text);
    border:1px solid var(--border);
}

.primary {
    background:var(--primary);
    color:#fff;
}

.danger {
    background:#fff0f0;
    color:#c53030;
}

.resolve {
    background:#edf8f1;
    color:#287d48;
}

.claim {
    background:#f0eaff;
    color:#6941c6;
}

.container {
    width:88%;
    max-width:1300px;
    margin:30px auto;
}

.hero h1 {
    margin:0;
    font-size:34px;
}

.hero p {
    color:var(--muted);
}

.stats {
    display:grid;
    grid-template-columns:repeat(6,1fr);
    gap:12px;
    margin:24px 0;
}

.stat,.card {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:14px;
}

.stat {
    padding:17px;
}

.stat-title {
    color:var(--muted);
    font-size:11px;
    text-transform:uppercase;
}

.stat-value {
    font-size:25px;
    font-weight:700;
    margin-top:7px;
}

.card {
    padding:25px;
    margin-bottom:22px;
}

.subtitle {
    color:var(--muted);
    font-size:14px;
    margin-bottom:20px;
}

.form-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:17px;
}

.field {
    display:flex;
    flex-direction:column;
}

.full {
    grid-column:1/-1;
}

label {
    font-size:13px;
    font-weight:600;
    margin-bottom:7px;
}

input,select,textarea {
    width:100%;
    padding:12px 13px;
    border:1px solid var(--border);
    border-radius:8px;
    background:var(--card);
    color:var(--text);
    outline:none;
}

textarea {
    min-height:85px;
    resize:vertical;
}

input:focus,select:focus,textarea:focus {
    border-color:var(--primary);
}

.form-actions,.actions {
    display:flex;
    gap:7px;
    flex-wrap:wrap;
    margin-top:20px;
}

.actions { margin-top:0; }

.filters {
    display:grid;
    grid-template-columns:2fr 1fr 1fr 1fr;
    gap:10px;
}

.table-wrapper {
    overflow-x:auto;
}

table {
    width:100%;
    border-collapse:collapse;
    min-width:1050px;
}

th {
    text-align:left;
    padding:12px;
    background:var(--soft);
    color:var(--muted);
    font-size:11px;
    text-transform:uppercase;
}

td {
    padding:12px;
    border-top:1px solid var(--border);
    font-size:13px;
}

.badge {
    display:inline-block;
    padding:5px 9px;
    border-radius:20px;
    font-size:10px;
    font-weight:700;
}

.badge-lost {
    background:#fff4e5;
    color:#a85d00;
}

.badge-found {
    background:#edf8f1;
    color:#287d48;
}

.badge-resolved {
    background:#eef1f5;
    color:#667085;
}

.badge-claimed {
    background:#f0eaff;
    color:#6941c6;
}

.thumb {
    width:48px;
    height:48px;
    object-fit:cover;
    border-radius:7px;
    border:1px solid var(--border);
}

.preview {
    display:none;
    margin-top:8px;
    max-width:180px;
    max-height:130px;
    border-radius:8px;
}

.match-box {
    display:none;
    margin-top:20px;
    padding:15px;
    background:var(--soft);
    border-left:4px solid var(--primary);
    border-radius:8px;
}

.match-item {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:8px;
    padding:12px;
    margin-top:8px;
}

.match-score {
    color:var(--primary);
    font-weight:800;
}

.analytics-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:20px;
}

.analytics-list div {
    display:flex;
    justify-content:space-between;
    padding:9px 0;
    border-bottom:1px solid var(--border);
}

.notification-panel {
    position:fixed;
    right:20px;
    top:72px;
    width:min(390px,calc(100vw - 30px));
    max-height:70vh;
    overflow:auto;
    background:var(--card);
    border:1px solid var(--border);
    box-shadow:0 15px 40px rgba(0,0,0,.18);
    border-radius:12px;
    z-index:100;
    display:none;
    padding:16px;
}

.notification {
    padding:11px 0;
    border-bottom:1px solid var(--border);
    font-size:13px;
}

.notification-btn {
    position:relative;
}

.notification-count {
    position:absolute;
    right:-5px;
    top:-6px;
    background:#e53e3e;
    color:#fff;
    min-width:18px;
    height:18px;
    border-radius:20px;
    display:none;
    align-items:center;
    justify-content:center;
    font-size:10px;
}

.empty {
    text-align:center;
    padding:40px;
    color:var(--muted);
}

.small-note {
    color:var(--muted);
    font-size:11px;
    margin-top:5px;
}

.toast {
    position:fixed;
    right:20px;
    bottom:20px;
    background:#172b4d;
    color:#fff;
    padding:12px 17px;
    border-radius:8px;
    display:none;
    z-index:999;
}

@media(max-width:1050px) {
    .stats { grid-template-columns:repeat(3,1fr); }
    .filters { grid-template-columns:1fr 1fr; }
}

@media(max-width:750px) {
    .container { width:94%; }
    .stats { grid-template-columns:1fr 1fr; }
    .form-grid { grid-template-columns:1fr; }
    .full { grid-column:auto; }
    .filters { grid-template-columns:1fr; }
    .analytics-grid { grid-template-columns:1fr; }
    .header-text { display:none; }
    .hero h1 { font-size:28px; }
}
</style>
</head>

<body>

<header>
    <div class="logo">
        <div class="logo-icon">✓</div>
        FINDLY
    </div>

    <div class="header-text">
        Smart Lost & Found Management System
    </div>

    <div class="header-actions">
        <button class="icon-btn notification-btn"
                onclick="toggleNotifications()">
            🔔
            <span id="notificationCount"
                  class="notification-count">0</span>
        </button>

        <button class="icon-btn"
                id="themeButton"
                onclick="toggleDarkMode()">
            🌙
        </button>
    </div>
</header>

<div id="notificationPanel" class="notification-panel">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>Notifications</strong>
        <button class="secondary"
                onclick="markNotificationsRead()">
            Mark read
        </button>
    </div>
    <div id="notificationList"></div>
</div>

<div class="container">

    <div class="hero">
        <h1>Smart Lost & Found</h1>
        <p>
            Report, manage and intelligently identify possible matches.
        </p>
    </div>

    <div class="stats">
        <div class="stat">
            <div class="stat-title">Total Records</div>
            <div class="stat-value" id="totalRecords">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Lost Items</div>
            <div class="stat-value" id="lostItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Found Items</div>
            <div class="stat-value" id="foundItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Active Items</div>
            <div class="stat-value" id="activeItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Resolved / Claimed</div>
            <div class="stat-value" id="resolvedItems">0</div>
        </div>
        <div class="stat">
            <div class="stat-title">Match Rate</div>
            <div class="stat-value" id="matchRate">0%</div>
        </div>
    </div>

    <div class="card">
        <h2 id="formTitle">Report Lost / Found Item</h2>
        <div class="subtitle">
            Add complete details to improve matching accuracy.
        </div>

        <form id="itemForm">

            <div class="form-grid">

                <div class="field">
                    <label>Record Type *</label>
                    <select id="record_type" required>
                        <option>Lost Item</option>
                        <option>Found Item</option>
                    </select>
                </div>

                <div class="field">
                    <label>Item Name *</label>
                    <input id="item_name"
                           placeholder="Example: Black Wallet"
                           required>
                </div>

                <div class="field">
                    <label>Category *</label>
                    <select id="category" required>
                        <option value="">Select Category</option>
                        <option>Wallet</option>
                        <option>Mobile Phone</option>
                        <option>Laptop</option>
                        <option>Bag</option>
                        <option>ID Card</option>
                        <option>Keys</option>
                        <option>Book</option>
                        <option>Earphones</option>
                        <option>Watch</option>
                        <option>Water Bottle</option>
                        <option>Umbrella</option>
                        <option>Other</option>
                    </select>
                </div>

                <div class="field">
                    <label>Colour</label>
                    <input id="colour" placeholder="Example: Black">
                </div>

                <div class="field">
                    <label>College Location *</label>
                    <select id="location" required>
                        <option value="">Select Location</option>
                        <option>College Canteen</option>
                        <option>Library</option>
                        <option>Computer Lab</option>
                        <option>Classroom</option>
                        <option>Seminar Hall</option>
                        <option>Auditorium</option>
                        <option>Parking Area</option>
                        <option>Hostel</option>
                        <option>Bus / Transport</option>
                        <option>Sports Ground</option>
                        <option>Administrative Block</option>
                        <option>Department Block</option>
                        <option>Other</option>
                    </select>
                </div>

                <div class="field">
                    <label>Date *</label>
                    <input id="item_date" type="date" required>
                </div>

                <div class="field">
                    <label>Condition</label>
                    <select id="item_condition">
                        <option value="">Select Condition</option>
                        <option>New</option>
                        <option>Good</option>
                        <option>Used</option>
                        <option>Damaged</option>
                        <option>Unknown</option>
                    </select>
                </div>

                <div class="field">
                    <label>Reporter Name</label>
                    <input id="reporter_name"
                           placeholder="Your name">
                </div>

                <div class="field full">
                    <label>Identifying Features</label>
                    <input id="identifying_features"
                           placeholder="Sticker, initials, scratch, cover, unique mark...">
                </div>

                <div class="field full">
                    <label>Description</label>
                    <textarea id="description"
                              placeholder="Describe the item..."></textarea>
                </div>

                <div class="field">
                    <label>Contact</label>
                    <input id="contact"
                           placeholder="Phone / Email">
                </div>

                <div class="field">
                    <label>Item Photo</label>
                    <input id="image"
                           type="file"
                           accept="image/png,image/jpeg,image/webp"
                           onchange="previewImage()">
                    <img id="imagePreview" class="preview">
                    <div class="small-note">
                        PNG/JPG/WEBP, maximum 2 MB
                    </div>
                </div>

            </div>

            <div class="form-actions">
                <button class="primary"
                        type="submit"
                        id="saveButton">
                    Save Item
                </button>

                <button class="secondary"
                        type="button"
                        onclick="resetForm()">
                    Clear
                </button>
            </div>

        </form>

        <div class="match-box" id="matchBox">
            <strong>🎯 Possible Matching Items</strong>
            <div id="matchResults"></div>
        </div>
    </div>

    <div class="card">
        <h2>🔍 Advanced Search & Filters</h2>

        <div class="filters">

            <input id="search"
                   placeholder="Search item, category, location..."
                   oninput="displayItems()">

            <select id="filterType" onchange="displayItems()">
                <option value="">All Types</option>
                <option>Lost Item</option>
                <option>Found Item</option>
            </select>

            <select id="filterCategory" onchange="displayItems()">
                <option value="">All Categories</option>
                <option>Wallet</option>
                <option>Mobile Phone</option>
                <option>Laptop</option>
                <option>Bag</option>
                <option>ID Card</option>
                <option>Keys</option>
                <option>Book</option>
                <option>Earphones</option>
                <option>Watch</option>
                <option>Other</option>
            </select>

            <select id="filterLocation" onchange="displayItems()">
                <option value="">All Locations</option>
                <option>College Canteen</option>
                <option>Library</option>
                <option>Computer Lab</option>
                <option>Classroom</option>
                <option>Seminar Hall</option>
                <option>Auditorium</option>
                <option>Parking Area</option>
                <option>Hostel</option>
                <option>Bus / Transport</option>
                <option>Sports Ground</option>
                <option>Administrative Block</option>
                <option>Department Block</option>
                <option>Other</option>
            </select>

        </div>

        <br>

        <select id="filterStatus"
                onchange="displayItems()"
                style="max-width:250px;">
            <option value="">All Status</option>
            <option>Active</option>
            <option>Resolved</option>
            <option>Claimed</option>
        </select>

        <button class="secondary"
                onclick="clearFilters()">
            Clear Filters
        </button>
    </div>

    <div class="card">
        <h2>📋 Item Records</h2>
        <div class="subtitle">
            Manage all reported items.
        </div>

        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Photo</th>
                        <th>ID</th>
                        <th>Type</th>
                        <th>Item</th>
                        <th>Category</th>
                        <th>Colour</th>
                        <th>Location</th>
                        <th>Date</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>

                <tbody id="itemTable"></tbody>
            </table>
        </div>
    </div>

    <div class="card">
        <h2>📊 Admin Analytics Dashboard</h2>
        <div class="subtitle">
            Quick overview of FINDLY activity.
        </div>

        <div class="analytics-grid">

            <div>
                <h3>Top Categories</h3>
                <div id="categoryAnalytics"
                     class="analytics-list"></div>
            </div>

            <div>
                <h3>Top Locations</h3>
                <div id="locationAnalytics"
                     class="analytics-list"></div>
            </div>

        </div>
    </div>

</div>

<div class="toast" id="toast"></div>

<script>
let allItems = [];
let editingId = null;


function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.style.display = "block";

    setTimeout(() => {
        toast.style.display = "none";
    }, 2800);
}


async function loadItems() {
    try {
        const response = await fetch("/api/items");

        if (!response.ok) {
            throw new Error("Server error");
        }

        allItems = await response.json();

        displayItems();
        updateStats();
        loadAnalytics();
        loadNotifications();

    } catch (error) {
        console.error(error);
        showToast("Unable to load records.");
    }
}


function displayItems() {
    const table = document.getElementById("itemTable");

    const search = document
        .getElementById("search")
        .value
        .toLowerCase()
        .trim();

    const type =
        document.getElementById("filterType").value;

    const category =
        document.getElementById("filterCategory").value;

    const location =
        document.getElementById("filterLocation").value;

    const status =
        document.getElementById("filterStatus").value;

    const filtered = allItems.filter(item => {

        const text = [
            item.item_name,
            item.category,
            item.location,
            item.record_type,
            item.colour,
            item.description,
            item.identifying_features,
            item.reporter_name
        ].join(" ").toLowerCase();

        return (
            text.includes(search) &&
            (!type || item.record_type === type) &&
            (!category || item.category === category) &&
            (!location || item.location === location) &&
            (!status || item.status === status)
        );
    });

    if (!filtered.length) {
        table.innerHTML = `
            <tr>
                <td colspan="10" class="empty">
                    No records found.
                </td>
            </tr>
        `;
        return;
    }

    table.innerHTML = filtered.map(item => {

        let statusClass = "badge-found";

        if (item.status === "Resolved") {
            statusClass = "badge-resolved";
        }

        if (item.status === "Claimed") {
            statusClass = "badge-claimed";
        }

        const typeClass =
            item.record_type === "Lost Item"
            ? "badge-lost"
            : "badge-found";

        return `
            <tr>

                <td>
                    ${
                        item.image_path
                        ? `<img class="thumb"
                                src="${escapeHtml(item.image_path)}">`
                        : "—"
                    }
                </td>

                <td>${item.id}</td>

                <td>
                    <span class="badge ${typeClass}">
                        ${escapeHtml(item.record_type)}
                    </span>
                </td>

                <td>
                    <strong>
                        ${escapeHtml(item.item_name)}
                    </strong>
                </td>

                <td>${escapeHtml(item.category)}</td>

                <td>${escapeHtml(item.colour || "-")}</td>

                <td>${escapeHtml(item.location)}</td>

                <td>${escapeHtml(item.item_date)}</td>

                <td>
                    <span class="badge ${statusClass}">
                        ${escapeHtml(item.status)}
                    </span>
                </td>

                <td>
                    <div class="actions">

                        <button class="secondary"
                                onclick="viewItem(${item.id})">
                            View
                        </button>

                        <button class="primary"
                                onclick="editItem(${item.id})">
                            Edit
                        </button>

                        ${
                            item.status === "Active"
                            ? `
                            <button class="resolve"
                                    onclick="resolveItem(${item.id})">
                                Resolve
                            </button>

                            <button class="claim"
                                    onclick="claimItem(${item.id})">
                                Claim
                            </button>
                            `
                            : ""
                        }

                        <button class="danger"
                                onclick="deleteItem(${item.id})">
                            Delete
                        </button>

                    </div>
                </td>

            </tr>
        `;
    }).join("");
}


function fileToDataUrl(file) {
    if (!file) {
        return Promise.resolve("");
    }

    if (file.size > 2 * 1024 * 1024) {
        return Promise.reject(
            new Error("Image must be 2 MB or smaller.")
        );
    }

    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => resolve(reader.result);
        reader.onerror = () =>
            reject(new Error("Could not read image."));

        reader.readAsDataURL(file);
    });
}


function previewImage() {
    const input = document.getElementById("image");
    const preview = document.getElementById("imagePreview");

    if (!input.files.length) {
        preview.style.display = "none";
        return;
    }

    if (input.files[0].size > 2 * 1024 * 1024) {
        showToast("Image must be 2 MB or smaller.");
        input.value = "";
        preview.style.display = "none";
        return;
    }

    preview.src =
        URL.createObjectURL(input.files[0]);

    preview.style.display = "block";
}


document.getElementById("itemForm")
.addEventListener("submit", async event => {

    event.preventDefault();

    const button =
        document.getElementById("saveButton");

    button.disabled = true;
    button.innerText =
        editingId ? "Updating..." : "Saving...";

    try {

        const image =
            document.getElementById("image").files[0];

        const imageData =
            await fileToDataUrl(image);

        const data = {
            record_type:
                document.getElementById("record_type").value,

            item_name:
                document.getElementById("item_name").value.trim(),

            category:
                document.getElementById("category").value,

            colour:
                document.getElementById("colour").value.trim(),

            location:
                document.getElementById("location").value,

            item_date:
                document.getElementById("item_date").value,

            item_condition:
                document.getElementById("item_condition").value,

            reporter_name:
                document.getElementById("reporter_name").value.trim(),

            identifying_features:
                document
                .getElementById("identifying_features")
                .value.trim(),

            description:
                document.getElementById("description").value.trim(),

            contact:
                document.getElementById("contact").value.trim(),

            image_data: imageData
        };

        let response;

        if (editingId) {

            response = await fetch(
                `/api/items/${editingId}`,
                {
                    method:"PUT",
                    headers:{
                        "Content-Type":"application/json"
                    },
                    body:JSON.stringify(data)
                }
            );

        } else {

            response = await fetch(
                "/api/items",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":"application/json"
                    },
                    body:JSON.stringify(data)
                }
            );
        }

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.message || "Operation failed"
            );
        }

        if (editingId) {
            showToast("Item updated successfully.");
        } else {
            showToast("Item saved successfully.");

            if (result.matches &&
                result.matches.length) {
                showMatches(result.matches);
                showToast(
                    "Item saved — possible match found!"
                );
            }
        }

        editingId = null;
        resetForm(false);
        await loadItems();

    } catch (error) {
        console.error(error);
        showToast(error.message);

    } finally {
        button.disabled = false;
        button.innerText = "Save Item";
    }
});


function showMatches(matches) {
    const box =
        document.getElementById("matchBox");

    const results =
        document.getElementById("matchResults");

    box.style.display = "block";

    if (!matches.length) {
        results.innerHTML =
            "<p>No possible matches found.</p>";
        return;
    }

    results.innerHTML = matches.map(match => `
        <div class="match-item">

            ${
                match.image_path
                ? `<img class="thumb"
                        src="${escapeHtml(match.image_path)}">`
                : ""
            }

            <strong>
                ${escapeHtml(match.item_name)}
            </strong>

            <br>

            <small>
                ${escapeHtml(match.record_type)}
                · ${escapeHtml(match.category)}
                · ${escapeHtml(match.location)}
                · ${escapeHtml(match.item_date)}
            </small>

            <br>

            <span class="match-score">
                Match Score: ${match.score}%
            </span>

        </div>
    `).join("");
}


async function viewItem(id) {
    const response =
        await fetch(`/api/items/${id}`);

    const item = await response.json();

    alert(
        "ITEM DETAILS\n\n" +
        "Type: " + item.record_type + "\n" +
        "Item: " + item.item_name + "\n" +
        "Category: " + item.category + "\n" +
        "Colour: " + (item.colour || "-") + "\n" +
        "Location: " + item.location + "\n" +
        "Date: " + item.item_date + "\n" +
        "Condition: " + (item.item_condition || "-") + "\n" +
        "Reporter: " + (item.reporter_name || "-") + "\n" +
        "Features: " +
        (item.identifying_features || "-") +
        "\n\nDescription: " +
        (item.description || "-") +
        "\n\nContact: " +
        (item.contact || "-") +
        "\nStatus: " + item.status +
        "\nClaimed By: " +
        (item.claimed_by || "-")
    );
}


async function editItem(id) {
    const response =
        await fetch(`/api/items/${id}`);

    const item = await response.json();

    editingId = id;

    document.getElementById("record_type").value =
        item.record_type;

    document.getElementById("item_name").value =
        item.item_name;

    document.getElementById("category").value =
        item.category;

    document.getElementById("colour").value =
        item.colour || "";

    document.getElementById("location").value =
        item.location;

    document.getElementById("item_date").value =
        item.item_date;

    document.getElementById("item_condition").value =
        item.item_condition || "";

    document.getElementById("reporter_name").value =
        item.reporter_name || "";

    document.getElementById("identifying_features").value =
        item.identifying_features || "";

    document.getElementById("description").value =
        item.description || "";

    document.getElementById("contact").value =
        item.contact || "";

    document.getElementById("formTitle").innerText =
        "Edit Lost / Found Item";

    document.getElementById("saveButton").innerText =
        "Update Item";

    window.scrollTo({
        top:0,
        behavior:"smooth"
    });
}


async function deleteItem(id) {
    if (!confirm(
        "Are you sure you want to delete this item?"
    )) {
        return;
    }

    try {
        const response = await fetch(
            `/api/items/${id}`,
            {method:"DELETE"}
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item deleted successfully.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


async function resolveItem(id) {
    const name = prompt(
        "Enter claimant / receiver name (optional):"
    );

    try {
        const response = await fetch(
            `/api/items/${id}/resolve`,
            {
                method:"PUT",
                headers:{
                    "Content-Type":"application/json"
                },
                body:JSON.stringify({
                    claimed_by:name || ""
                })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item marked as resolved.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


async function claimItem(id) {
    const name = prompt("Enter claimant name:");

    if (name === null) {
        return;
    }

    try {
        const response = await fetch(
            `/api/items/${id}/claim`,
            {
                method:"PUT",
                headers:{
                    "Content-Type":"application/json"
                },
                body:JSON.stringify({
                    claimed_by:name
                })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message);
        }

        showToast("Item marked as claimed.");
        await loadItems();

    } catch(error) {
        showToast(error.message);
    }
}


function resetForm(clearMatch=true) {
    document.getElementById("itemForm").reset();

    editingId = null;

    document.getElementById("formTitle").innerText =
        "Report Lost / Found Item";

    document.getElementById("saveButton").innerText =
        "Save Item";

    document.getElementById("item_date").value =
        new Date().toISOString().split("T")[0];

    const preview =
        document.getElementById("imagePreview");

    preview.src = "";
    preview.style.display = "none";

    if (clearMatch) {
        document.getElementById("matchBox")
            .style.display = "none";
    }
}


function clearFilters() {
    document.getElementById("search").value = "";
    document.getElementById("filterType").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterLocation").value = "";
    document.getElementById("filterStatus").value = "";
    displayItems();
}


function updateStats() {
    document.getElementById("totalRecords").innerText =
        allItems.length;

    document.getElementById("lostItems").innerText =
        allItems.filter(
            x => x.record_type === "Lost Item"
        ).length;

    document.getElementById("foundItems").innerText =
        allItems.filter(
            x => x.record_type === "Found Item"
        ).length;

    document.getElementById("activeItems").innerText =
        allItems.filter(
            x => x.status === "Active"
        ).length;

    document.getElementById("resolvedItems").innerText =
        allItems.filter(
            x => x.status === "Resolved" ||
                 x.status === "Claimed"
        ).length;
}


async function loadAnalytics() {
    try {
        const response =
            await fetch("/api/analytics");

        const data = await response.json();

        document.getElementById("matchRate").innerText =
            data.match_rate + "%";

        document.getElementById("categoryAnalytics")
            .innerHTML =
            data.categories.length
            ? data.categories.map(x => `
                <div>
                    <span>${escapeHtml(x.category)}</span>
                    <strong>${x.count}</strong>
                </div>
            `).join("")
            : "<p>No data yet.</p>";

        document.getElementById("locationAnalytics")
            .innerHTML =
            data.locations.length
            ? data.locations.map(x => `
                <div>
                    <span>${escapeHtml(x.location)}</span>
                    <strong>${x.count}</strong>
                </div>
            `).join("")
            : "<p>No data yet.</p>";

    } catch(error) {
        console.error(error);
    }
}


async function loadNotifications() {
    try {
        const response =
            await fetch("/api/notifications");

        const data = await response.json();

        const badge =
            document.getElementById("notificationCount");

        badge.innerText = data.unread;
        badge.style.display =
            data.unread ? "flex" : "none";

        const list =
            document.getElementById("notificationList");

        if (!data.notifications.length) {
            list.innerHTML =
                "<p style='color:#718096;'>No notifications yet.</p>";
            return;
        }

        list.innerHTML =
            data.notifications.map(n => `
                <div class="notification">
                    <strong>${escapeHtml(n.notification_type)}</strong>
                    <br>
                    ${escapeHtml(n.message)}
                    <br>
                    <small>${escapeHtml(n.created_at)}</small>
                </div>
            `).join("");

    } catch(error) {
        console.error(error);
    }
}


function toggleNotifications() {
    const panel =
        document.getElementById("notificationPanel");

    panel.style.display =
        panel.style.display === "block"
        ? "none"
        : "block";

    loadNotifications();
}


async function markNotificationsRead() {
    await fetch(
        "/api/notifications/read",
        {method:"PUT"}
    );

    loadNotifications();
}


function toggleDarkMode() {
    document.body.classList.toggle("dark");

    const dark =
        document.body.classList.contains("dark");

    localStorage.setItem(
        "findlyDarkMode",
        dark ? "1" : "0"
    );

    document.getElementById("themeButton")
        .innerText = dark ? "☀️" : "🌙";
}


if (localStorage.getItem("findlyDarkMode") === "1") {
    document.body.classList.add("dark");
    document.getElementById("themeButton")
        .innerText = "☀️";
}


document.getElementById("item_date").value =
    new Date().toISOString().split("T")[0];

loadItems();
loadNotifications();
loadAnalytics();
</script>

</body>
</html>
"""


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    create_database()

    port = int(os.environ.get("PORT", 5000))

    print()
    print("-------------------------------------------")
    print(" FINDLY - SMART LOST & FOUND")
    print("-------------------------------------------")
    print(" Open: http://127.0.0.1:" + str(port))
    print("-------------------------------------------")
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
 
