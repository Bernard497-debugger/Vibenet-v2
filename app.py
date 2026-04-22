# app.py - VibeNet  (SQLAlchemy ORM  |  SQLite locally  |  PostgreSQL on Render)
print("==> app.py starting...", flush=True)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, session, render_template_string

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func


# ---------- Config ----------
APP_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["PORT"] = int(os.environ.get("PORT", 5000))
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")



# SQLAlchemy: prefer DATABASE_URL env var (Render PostgreSQL), fall back to SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):          # Render uses legacy scheme
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    DATABASE_URL if DATABASE_URL
    else f"sqlite:///{os.path.join(APP_DIR, 'data', 'vibenet.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280,
    "pool_pre_ping": True,
    "connect_args": {"connect_timeout": 10} if not os.environ.get("DATABASE_URL", "").startswith("sqlite") else {},
}

os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)

db = SQLAlchemy(app)

# ---------- Utilities ----------
def now_ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# ---------- Models ----------

class User(db.Model):
    __tablename__ = "users"
    id                = db.Column(db.Integer, primary_key=True)
    name              = db.Column(db.Text)
    email             = db.Column(db.Text, unique=True, nullable=False)
    password          = db.Column(db.Text, nullable=False)
    profile_pic       = db.Column(db.Text, default="")
    bio               = db.Column(db.Text, default="")
    watch_hours       = db.Column(db.Integer, default=0)
    earnings          = db.Column(db.Float, default=0.0)
    verified          = db.Column(db.Integer, default=0)   # 1 = VibeNet Verified
    banned            = db.Column(db.Integer, default=0)   # 1 = banned
    last_active       = db.Column(db.Text, default=lambda: now_ts())
    created_at        = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "profile_pic": self.profile_pic, "bio": self.bio,
            "watch_hours": self.watch_hours, "earnings": self.earnings,
            "verified": bool(self.verified), "banned": bool(self.banned),
        }


class Follower(db.Model):
    __tablename__ = "followers"
    id             = db.Column(db.Integer, primary_key=True)
    user_email     = db.Column(db.Text, nullable=False)   # the person being followed
    follower_email = db.Column(db.Text, nullable=False)   # the person who follows
    created_at     = db.Column(db.Text, default=lambda: now_ts())
    __table_args__ = (
        db.UniqueConstraint("user_email", "follower_email", name="uq_follow"),
    )


class Post(db.Model):
    __tablename__  = "posts"
    id             = db.Column(db.Integer, primary_key=True)
    author_email   = db.Column(db.Text, nullable=False)
    author_name    = db.Column(db.Text)
    profile_pic    = db.Column(db.Text, default="")
    text           = db.Column(db.Text, default="")
    file_url       = db.Column(db.Text, default="")
    timestamp      = db.Column(db.Text, default=lambda: now_ts())
    reactions_json = db.Column(db.Text, default='{"👍":0,"❤️":0,"😂":0}')
    comments_count = db.Column(db.Integer, default=0)

    def reactions(self):
        try:
            return _json.loads(self.reactions_json or "{}")
        except Exception:
            return {"👍": 0, "❤️": 0, "😂": 0}

    def to_dict(self, user_reaction=None, author_verified=False):
        return {
            "id": self.id, "author_email": self.author_email,
            "author_name": self.author_name, "profile_pic": self.profile_pic,
            "text": self.text, "file_url": self.file_url,
            "timestamp": self.timestamp, "reactions": self.reactions(),
            "comments_count": self.comments_count,
            "user_reaction": user_reaction,
            "author_verified": author_verified,
        }


class UserReaction(db.Model):
    __tablename__ = "user_reactions"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    emoji      = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Text, default=lambda: now_ts())
    __table_args__ = (
        db.UniqueConstraint("user_email", "post_id", name="uq_reaction"),
    )


class Notification(db.Model):
    __tablename__ = "notifications"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    text       = db.Column(db.Text)
    timestamp  = db.Column(db.Text, default=lambda: now_ts())
    seen       = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {"id": self.id, "text": self.text, "timestamp": self.timestamp, "seen": self.seen}


class Ad(db.Model):
    __tablename__ = "ads"
    id               = db.Column(db.Integer, primary_key=True)
    title            = db.Column(db.Text)
    owner_email      = db.Column(db.Text)
    whatsapp_number  = db.Column(db.Text, default="")
    budget           = db.Column(db.Float, default=0.0)
    impressions      = db.Column(db.Integer, default=0)
    clicks           = db.Column(db.Integer, default=0)
    approved         = db.Column(db.Integer, default=0)
    created_at       = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "owner_email": self.owner_email,
            "whatsapp_number": self.whatsapp_number or "",
            "budget": self.budget, "impressions": self.impressions, "clicks": self.clicks,
            "approved": self.approved, "created_at": self.created_at,
        }


class PayoutRequest(db.Model):
    __tablename__ = "payout_requests"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    user_name  = db.Column(db.Text, default="")
    om_number  = db.Column(db.Text, nullable=False)
    amount     = db.Column(db.Float, nullable=False)
    status     = db.Column(db.Text, default="pending")  # pending | paid | rejected
    created_at = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "user_email": self.user_email, "user_name": self.user_name,
            "om_number": self.om_number, "amount": self.amount,
            "status": self.status, "created_at": self.created_at,
        }


# ---------- Create tables ----------
with app.app_context():
    try:
        db.create_all()
        print("✅ Database tables created/verified OK", flush=True)
    except Exception as e:
        print(f"⚠️  DB init warning (non-fatal): {e}", flush=True)

    # Safe migrations — add columns that may not exist in older deployments
    migrations = [
        "ALTER TABLE ads ADD COLUMN approved INTEGER DEFAULT 0",
        "ALTER TABLE ads ADD COLUMN whatsapp_number TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN user_email TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN user_name TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN om_number TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN amount FLOAT DEFAULT 0",
        "ALTER TABLE payout_requests ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE payout_requests ADD COLUMN created_at TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_active TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
            print(f"✅ Migration OK: {sql[:50]}", flush=True)
        except Exception:
            db.session.rollback()
            pass  # Column already exists — that's fine

# ---------- Health check ----------
@app.route("/api/debug/posts")
def api_debug_posts():
    posts = Post.query.order_by(Post.id.desc()).limit(5).all()
    return jsonify([{"id": p.id, "text": p.text, "file_url": p.file_url, "ts": p.timestamp} for p in posts])

@app.route("/health")
def health():
    return "OK", 200


# ---------- Static uploads ----------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- Frontend ----------
HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>VibeNet</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #060910;
  --surface: #0c1018;
  --card: #101520;
  --card2: #131925;
  --border: rgba(255,255,255,0.06);
  --accent: #4DF0C0;
  --accent2: #7B6EF6;
  --accent3: #F06A4D;
  --text: #E8F0FF;
  --muted: #5A6A85;
  --muted2: #8899B4;
  --danger: #F06A4D;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  font-family: 'DM Sans', sans-serif;
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

body::before {
  content: '';
  position: fixed;
  top: -40%;
  left: -20%;
  width: 70%;
  height: 70%;
  background: radial-gradient(ellipse, rgba(77,240,192,0.04) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}
body::after {
  content: '';
  position: fixed;
  bottom: -30%;
  right: -10%;
  width: 60%;
  height: 60%;
  background: radial-gradient(ellipse, rgba(123,110,246,0.05) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

/* ===== AUTH SCREEN ===== */
#authScreen {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  background: var(--bg);
  padding: 20px;
}

.auth-wrap {
  width: 100%;
  max-width: 900px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  background: var(--border);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 40px 120px rgba(0,0,0,0.8);
  animation: fadeUp 0.5s ease both;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(24px); }
  to   { opacity: 1; transform: translateY(0); }
}

.auth-brand {
  background: linear-gradient(145deg, #0d1826, #080f1a);
  padding: 52px 44px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.auth-brand::before {
  content: 'VN';
  position: absolute;
  bottom: -30px;
  right: -20px;
  font-family: 'Syne', sans-serif;
  font-size: 160px;
  font-weight: 800;
  color: rgba(77,240,192,0.04);
  line-height: 1;
  letter-spacing: -8px;
}

.brand-logo {
  font-family: 'Syne', sans-serif;
  font-size: 38px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -1px;
  margin-bottom: 16px;
}

.brand-tag {
  font-size: 15px;
  color: var(--muted2);
  line-height: 1.6;
  max-width: 240px;
}

.brand-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 32px;
}

.pill {
  background: rgba(77,240,192,0.08);
  border: 1px solid rgba(77,240,192,0.15);
  color: var(--accent);
  padding: 5px 12px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
}

.auth-forms {
  background: var(--card);
  padding: 44px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.auth-section h3 {
  font-family: 'Syne', sans-serif;
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 16px;
  color: var(--text);
  letter-spacing: -0.3px;
}

.field {
  margin-bottom: 10px;
}

.field input {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  transition: border-color 0.2s;
  outline: none;
}

.field input:focus {
  border-color: rgba(77,240,192,0.4);
}

.field input::placeholder { color: var(--muted); }

.field-label {
  font-size: 12px;
  color: var(--muted2);
  margin-bottom: 6px;
  font-weight: 500;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.divider {
  height: 1px;
  background: var(--border);
}

/* Buttons */
.btn-primary {
  background: var(--accent);
  color: #030a0e;
  border: none;
  padding: 11px 22px;
  border-radius: 10px;
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.2px;
}
.btn-primary:hover { background: #6bf5d0; transform: translateY(-1px); }

.btn-ghost {
  background: transparent;
  color: var(--muted2);
  border: 1px solid var(--border);
  padding: 10px 20px;
  border-radius: 10px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover { border-color: rgba(255,255,255,0.2); color: var(--text); }

.btn-icon {
  background: var(--card2);
  border: 1px solid var(--border);
  color: var(--muted2);
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}
.btn-icon:hover { border-color: var(--accent); color: var(--accent); }

/* ===== MAIN APP ===== */
#mainApp {
  display: none;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

/* Top Nav */
.topnav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(6,9,16,0.92);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.nav-brand {
  font-family: 'Syne', sans-serif;
  font-size: 20px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -0.5px;
  flex-shrink: 0;
}

.nav-tabs {
  display: flex;
  gap: 2px;
  background: var(--surface);
  padding: 4px;
  border-radius: 12px;
  border: 1px solid var(--border);
  flex-shrink: 0;
}

.nav-tab {
  background: transparent;
  border: none;
  color: var(--muted2);
  padding: 7px 14px;
  border-radius: 9px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  position: relative;
}

.nav-tab:hover { color: var(--text); background: rgba(255,255,255,0.04); }
.nav-tab.active { background: var(--card2); color: var(--text); }
.nav-tab.active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 16px;
  height: 2px;
  background: var(--accent);
  border-radius: 2px;
}

.notif-dot {
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 100px;
  line-height: 16px;
  min-width: 16px;
  text-align: center;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.nav-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 2px solid var(--border);
  cursor: pointer;
}

.nav-signout {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.nav-signout:hover { border-color: rgba(240,106,77,0.5); color: var(--danger); background: rgba(240,106,77,0.07); }

/* ===== USER PANEL (below header, in sidebar) ===== */
.user-panel {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.user-panel-top {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 14px;
}

.user-panel-avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 2px solid rgba(77,240,192,0.25);
  flex-shrink: 0;
}

.user-panel-name {
  font-family: 'Syne', sans-serif;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.user-panel-email {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.user-panel-bio {
  font-size: 13px;
  color: var(--muted2);
  line-height: 1.5;
  margin-bottom: 14px;
  min-height: 18px;
}

.user-panel-actions {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.panel-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 9px 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  font-family: 'DM Sans', sans-serif;
}
.panel-btn:hover { border-color: rgba(77,240,192,0.3); color: var(--accent); background: rgba(77,240,192,0.04); }
.panel-btn.signout { color: var(--muted); }
.panel-btn.signout:hover { border-color: rgba(240,106,77,0.4); color: var(--danger); background: rgba(240,106,77,0.06); }

/* ===== LAYOUT ===== */
.app-layout {
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 16px;
}

.main-col { min-width: 0; }

/* ===== TABS ===== */
.tab { display: none; animation: fadeIn 0.25s ease; }
.tab.visible { display: block; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ===== POST COMPOSER ===== */
.composer {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
}

.composer-top {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.composer-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  flex-shrink: 0;
}

.composer textarea {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14.5px;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
  min-height: 80px;
}
.composer textarea:focus { border-color: rgba(77,240,192,0.3); }
.composer textarea::placeholder { color: var(--muted); }

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.composer-actions { display: flex; gap: 8px; align-items: center; }

.attach-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted2);
  font-size: 13px;
  cursor: pointer;
  padding: 7px 12px;
  border-radius: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  transition: all 0.2s;
}
.attach-label:hover { border-color: rgba(77,240,192,0.3); color: var(--accent); }
.attach-label input { display: none; }

/* ===== POSTS ===== */
.post-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 16px;
  transition: border-color 0.2s;
}
.post-card:hover { border-color: rgba(255,255,255,0.1); }

.post-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.post-author {
  display: flex;
  gap: 10px;
  align-items: center;
}

.post-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
}

.post-author-info strong {
  display: block;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}

.post-ts {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.post-text {
  font-size: 15px;
  line-height: 1.65;
  color: #cad8f0;
  margin-bottom: 12px;
}

.post-media {
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 12px;
}
.post-media img, .post-media video {
  width: 100%;
  display: block;
  max-height: 460px;
  object-fit: cover;
  background: #000;
}

.post-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.reaction-bar { display: flex; gap: 6px; }

.react-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
}
.react-btn:hover { border-color: rgba(255,255,255,0.2); color: var(--text); }
.react-btn.active { background: rgba(77,240,192,0.1); border-color: rgba(77,240,192,0.3); color: var(--accent); }

.follow-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted2);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-family: 'Syne', sans-serif;
  letter-spacing: 0.3px;
}
.follow-btn:hover { border-color: var(--accent); color: var(--accent); }
.follow-btn.active { background: rgba(77,240,192,0.12); border-color: var(--accent); color: var(--accent); }

.comment-count {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 4px;
}


/* Post owner action buttons */
.post-actions {
  display: flex;
  gap: 6px;
}

.action-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  width: 30px;
  height: 30px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.18s;
  flex-shrink: 0;
}
.action-btn:hover { color: var(--text); border-color: rgba(255,255,255,0.2); }
.action-btn.delete:hover { color: var(--danger); border-color: var(--danger); background: rgba(240,106,77,0.08); }
.action-btn.edit-btn:hover { color: var(--accent); border-color: var(--accent); background: rgba(77,240,192,0.08); }

/* Edit modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.72);
  backdrop-filter: blur(6px);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

.modal-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 28px;
  width: 100%;
  max-width: 520px;
  box-shadow: 0 40px 100px rgba(0,0,0,0.8);
  animation: fadeUp 0.25s ease;
}

.modal-title {
  font-family: 'Syne', sans-serif;
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 18px;
  letter-spacing: -0.3px;
}

.modal-footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

/* Video wrapper for autoplay UI */
.video-wrap {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
}
.video-wrap video { width: 100%; display: block; max-height: 460px; object-fit: cover; }
.play-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.32);
  pointer-events: none;
  transition: opacity 0.3s;
}
.play-hint span { font-size: 44px; filter: drop-shadow(0 2px 10px rgba(0,0,0,0.7)); }
.video-wrap.playing .play-hint { opacity: 0; }

.vbadge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4DF0C0, #7B6EF6);
  color: #030a0e;
  font-size: 10px;
  font-weight: 900;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  margin-left: 4px;
  vertical-align: middle;
  line-height: 1;
}

/* ===== SECTION HEADER ===== */
.section-header {
  margin-bottom: 20px;
}
.section-header h2 {
  font-family: 'Syne', sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.5px;
}
.section-header p {
  color: var(--muted2);
  font-size: 13.5px;
  margin-top: 4px;
}

/* ===== NOTIFICATIONS ===== */
.notif-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.notif-item:last-child { border-bottom: none; }

.notif-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(77,240,192,0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.notif-text { font-size: 14px; color: var(--muted2); line-height: 1.5; }
.notif-time { font-size: 12px; color: var(--muted); margin-top: 3px; }

/* ===== MONETIZATION ===== */
.monet-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}

.monet-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}

.monet-card-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted2);
  font-weight: 600;
  margin-bottom: 8px;
}

.monet-card-value {
  font-family: 'Syne', sans-serif;
  font-size: 28px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -1px;
}

.monet-card-value.green { color: var(--accent); }

.monet-section-title {
  font-family: 'Syne', sans-serif;
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.ad-form {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
  align-items: end;
}

.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 12px; color: var(--muted2); font-weight: 500; text-transform: uppercase; letter-spacing: 0.3px; }
.form-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 13px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}
.form-input:focus { border-color: rgba(77,240,192,0.4); }
.form-input::placeholder { color: var(--muted); }

.ad-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ad-item-name { font-size: 14px; font-weight: 500; }
.ad-item-stats { font-size: 12px; color: var(--muted2); display: flex; gap: 12px; }
.ad-stat { display: flex; align-items: center; gap: 4px; }

/* ===== PROFILE ===== */
.profile-header {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 20px;
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.profile-avatar-wrap { position: relative; flex-shrink: 0; }
.profile-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface);
  border: 3px solid var(--border);
}

.profile-info { flex: 1; }
.profile-name {
  font-family: 'Syne', sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin-bottom: 4px;
}
.profile-email { font-size: 13px; color: var(--muted2); margin-bottom: 14px; }

.bio-area {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  color: var(--text);
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  width: 100%;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
}
.bio-area:focus { border-color: rgba(77,240,192,0.4); }
.bio-area::placeholder { color: var(--muted); }

.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--muted2);
}
.empty-state .empty-icon { font-size: 36px; margin-bottom: 12px; }
.empty-state p { font-size: 14px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

/* Terms sidebar */
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to   { transform: translateX(0); opacity: 1; }
}
.tc-section { margin-bottom: 20px; }
.tc-title { font-family: 'Syne', sans-serif; font-size: 13px; font-weight: 700; color: #e8f0ff; margin-bottom: 7px; letter-spacing: 0.2px; }
.tc-text { font-size: 13px; color: #8899b4; line-height: 1.7; }

/* File name display */
#fileNameDisplay {
  font-size: 12px;
  color: var(--accent);
  margin-top: 4px;
}

@media (max-width: 600px) {
  .auth-wrap { grid-template-columns: 1fr; }
  .auth-brand { display: none; }
  .topnav { padding: 0 10px; gap: 6px; }
  .nav-brand { font-size: 17px; }
  .nav-tabs { padding: 3px; gap: 1px; }
  .nav-tab { padding: 6px 8px; font-size: 11px; gap: 3px; }
  .tab-label { display: none; }
  .monet-grid { grid-template-columns: 1fr; }
  .form-row { grid-template-columns: 1fr; }
  .app-layout { padding: 16px 10px; }
}
</style>
</head>
<body>

<!-- ===== AUTH SCREEN ===== -->
<div id="authScreen">
  <div class="auth-wrap">
    <div class="auth-brand">
      <div class="brand-logo">VibeNet</div>
      <div class="brand-tag">Share moments, grow your audience, and earn from your content.</div>
      <div class="brand-pills">
        <span class="pill">📹 Video</span>
        <span class="pill">💰 Earn</span>
        <span class="pill">📈 Grow</span>
        <span class="pill">🌐 Connect</span>
      </div>
    </div>

    <div class="auth-forms">
      <div class="auth-section">
        <h3>Create account</h3>
        <div class="field">
          <div class="field-label">Full Name</div>
          <input id="signupName" placeholder="Your name" />
        </div>
        <div class="field">
          <div class="field-label">Email</div>
          <input id="signupEmail" type="email" placeholder="you@email.com" />
        </div>
        <div class="field">
          <div class="field-label">Password</div>
          <input id="signupPassword" type="password" placeholder="••••••••" />
        </div>
        <div class="field">
          <div class="field-label">Profile photo (optional)</div>
          <input id="signupPic" type="file" accept="image/*" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--muted2);width:100%;font-size:13px;" />
        </div>
        <button class="btn-primary" onclick="signup()" style="width:100%;margin-top:4px;">Create Account →</button>
      </div>

      <div class="divider"></div>

      <div class="auth-section">
        <h3>Sign in</h3>
        <div class="field">
          <div class="field-label">Email</div>
          <input id="loginEmail" type="email" placeholder="you@email.com" />
        </div>
        <div class="field">
          <div class="field-label">Password</div>
          <input id="loginPassword" type="password" placeholder="••••••••" />
        </div>
        <button class="btn-ghost" onclick="login()" style="width:100%;">Sign In</button>
      </div>
    </div>
  </div>
</div>

<!-- ===== MAIN APP ===== -->
<div id="mainApp">
  <!-- Top Nav -->
  <nav class="topnav">
    <div class="nav-brand">VibeNet</div>

    <div class="nav-tabs">
      <button class="nav-tab active" id="navFeed" onclick="showTab('feed')">
        <span>🏠</span><span class="tab-label"> Feed</span>
      </button>
      <button class="nav-tab" id="navNotifs" onclick="showTab('notifications')">
        <span>🔔</span><span class="tab-label"> Alerts</span>
        <span id="notifCount" class="notif-dot" style="display:none"></span>
      </button>
      <button class="nav-tab" id="navMonet" onclick="showTab('monet')">
        <span>💰</span><span class="tab-label"> Earn</span>
      </button>
      <button class="nav-tab" id="navProfile" onclick="showTab('profile')">
        <span>👤</span><span class="tab-label"> Profile</span>
      </button>
      <button class="nav-tab" id="navTerms" onclick="openTerms()">
        <span>📋</span><span class="tab-label"> Terms</span>
      </button>
    </div>

    <div class="nav-right">
      <img class="nav-avatar" id="topAvatar" src="" onerror="this.style.display='none'" />
      <button class="nav-signout" onclick="logout()" title="Sign out">&#8594;</button>
    </div>
  </nav>

  <!-- Layout -->
  <div class="app-layout">
    <!-- Main column -->
    <div class="main-col">

      <!-- Feed Tab -->
      <div id="feed" class="tab visible">
        <div class="composer">
          <div class="composer-top">
            <img class="composer-avatar" id="composerAvatar" src="" onerror="this.style.display='none'" />
            <textarea id="postText" rows="3" placeholder="What's on your mind?"></textarea>
          </div>
          <div class="composer-footer">
            <div class="composer-actions">
              <label class="attach-label">
                📎 Attach media
                <input id="fileUpload" type="file" accept="image/*,video/*" onchange="showFileName(this)" />
              </label>
              <span id="fileNameDisplay"></span>
            </div>
            <button class="btn-primary" id="postBtn" onclick="addPost()">Post →</button>
          </div>
          <div id="uploadProgress" style="display:none;margin-top:10px">
            <div style="font-size:12px;color:var(--muted2);margin-bottom:6px" id="uploadLabel">Uploading...</div>
            <div style="background:rgba(255,255,255,0.06);border-radius:100px;height:6px;overflow:hidden">
              <div id="uploadBar" style="height:100%;width:0%;background:linear-gradient(90deg,#4DF0C0,#00c9ff);border-radius:100px;transition:width 0.3s ease"></div>
            </div>
          </div>
        </div>
        <div id="feedList"></div>
      </div>

      <!-- Notifications Tab -->
      <div id="notifications" class="tab">
        <div class="section-header">
          <h2>Notifications</h2>
          <p>Stay up to date with your community</p>
        </div>
        <div class="post-card" style="padding:0 20px;">
          <div id="notifList"></div>
        </div>
      </div>

      <!-- Monetization / Payments Tab -->
      <div id="monet" class="tab">
        <div class="section-header">
          <h2>Earnings &amp; Payments</h2>
          <p>Grow your revenue, run ads, and get verified</p>
        </div>

        <!-- Stats row -->
        <div class="monet-grid">
          <div class="monet-card">
            <div class="monet-card-label">Followers</div>
            <div class="monet-card-value" id="monFollowers">0</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Watch Hours</div>
            <div class="monet-card-value" id="monWatch">0</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Status</div>
            <div class="monet-card-value" id="monStatus" style="font-size:16px;margin-top:4px;">—</div>
          </div>
          <div class="monet-card">
            <div class="monet-card-label">Total Earnings</div>
            <div class="monet-card-value green">$<span id="monEarnings">0.00</span></div>
          </div>
        </div>

        <!-- Ad Campaign -->
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;margin-bottom:20px">
          <div class="monet-section-title" style="margin-bottom:6px">📣 Advertise on VibeNet</div>
          <div style="font-size:13px;color:var(--muted2);margin-bottom:16px;line-height:1.6">
            Send your budget via Orange Money to <strong style="color:var(--accent);font-size:16px;letter-spacing:2px">72927417</strong>, then fill in your campaign details below. Your campaign goes live once payment is confirmed.
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:1;min-width:160px">
              <div class="form-label" style="margin-bottom:6px">Campaign Title</div>
              <input id="adTitle" class="form-input" placeholder="My awesome campaign" style="width:100%" />
            </div>
            <div style="width:130px">
              <div class="form-label" style="margin-bottom:6px">Budget (BWP)</div>
              <input id="adBudget" class="form-input" type="number" min="1" placeholder="50" style="width:100%" />
            </div>
            <div style="width:100%;margin-top:10px">
              <div class="form-label" style="margin-bottom:6px">WhatsApp Number (with country code)</div>
              <input id="adWhatsapp" class="form-input" type="tel" placeholder="e.g. 26772927417" style="width:100%" />
            </div>
            <button class="btn-primary" onclick="createAd()">Submit →</button>
          </div>
          <div id="adMsg" style="margin-top:12px;font-size:13px;line-height:1.6;display:none"></div>
        </div>

        <!-- Payout Request -->
        <div id="payoutSection" style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;margin-bottom:20px">
          <div class="monet-section-title" style="margin-bottom:6px">💸 Request Payout</div>
          <div style="font-size:13px;color:var(--muted2);margin-bottom:16px;line-height:1.6">
            Enter your Orange Money number and the amount to withdraw. Payouts are sent manually within 24–48 hours.
            <div style="margin-top:8px;padding:10px 14px;background:rgba(77,240,192,0.06);border:1px solid rgba(77,240,192,0.15);border-radius:10px;color:var(--muted2)">
              📋 <strong style="color:var(--text)">Eligibility required:</strong> 1,000 followers + 4,000 watch hours. Check your status in the cards above.
            </div>
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:1;min-width:160px">
              <div class="form-label" style="margin-bottom:6px">Your Orange Money Number</div>
              <input id="payoutNumber" class="form-input" placeholder="7XXXXXXX" style="width:100%" />
            </div>
            <div style="width:130px">
              <div class="form-label" style="margin-bottom:6px">Amount (BWP)</div>
              <input id="payoutAmount" class="form-input" type="number" min="1" placeholder="100" style="width:100%" />
            </div>
            <button class="btn-primary" onclick="requestPayout()">Request →</button>
          </div>
          <div id="payoutMsg" style="margin-top:12px;font-size:13px;line-height:1.6;display:none"></div>
        </div>

        <div class="monet-section-title">Active Campaigns</div>
        <div id="adsList"></div>

        <!-- Admin only -->
        <div id="adminPanel" style="display:none;margin-top:30px;padding:18px;background:rgba(240,106,77,0.07);border:1px solid rgba(240,106,77,0.3);border-radius:14px">
          <div style="font-size:13px;color:var(--danger);font-weight:600;margin-bottom:12px">⚠️ Admin Tools</div>
          <button class="btn-primary" style="background:var(--danger);color:#fff" onclick="adminWipePosts()">🗑 Wipe All Posts</button>
          <div id="adminMsg" style="margin-top:10px;font-size:13px;display:none"></div>
        </div>
      </div><!-- /monet tab -->

      <!-- Profile Tab -->
      <div id="profile" class="tab">
        <div class="section-header">
          <h2>My Profile</h2>
          <p>Manage your identity and content</p>
        </div>

        <div class="profile-header">
          <div class="profile-avatar-wrap">
            <img class="profile-avatar" id="profileAvatar" src="" onerror="this.style.background='var(--surface)'" />
          </div>
          <div class="profile-info">
            <div class="profile-name" id="profileName">—</div>
            <div class="profile-email" id="profileEmail">—</div>
            <textarea id="profileBio" class="bio-area" rows="2" placeholder="Write something about yourself..."></textarea>
            <button class="btn-primary" onclick="updateBio()" style="margin-top:10px;">Save Bio</button>
          </div>
        </div>

        <div class="monet-section-title">My Posts</div>
        <div id="profilePosts"></div>
      </div>

    </div><!-- /main-col -->


  </div><!-- /app-layout -->

<!-- Edit Post Modal -->
<div id="editModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeEditModal()">
  <div class="modal-box">
    <div class="modal-title">Edit Post</div>
    <textarea id="editPostText" class="bio-area" rows="5" placeholder="Update your post..."></textarea>
    <div class="modal-footer">
      <button class="btn-ghost" onclick="closeEditModal()">Cancel</button>
      <button class="btn-primary" onclick="saveEditPost()">Save Changes</button>
    </div>
  </div>
</div>

<!-- Terms & Conditions Sidebar -->
<div id="termsOverlay" onclick="closeTerms()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);z-index:300"></div>
<div id="termsSidebar" style="display:none;position:fixed;top:0;right:0;width:min(420px,100vw);height:100vh;background:#0c1018;border-left:1px solid rgba(255,255,255,0.08);z-index:301;overflow-y:auto;padding:28px 24px;animation:slideIn 0.3s ease">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px">
    <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#4DF0C0">📋 Terms &amp; Conditions</div>
    <button onclick="closeTerms()" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:#8899b4;width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:16px">✕</button>
  </div>
  <div style="font-size:12px;color:#5a6a85;margin-bottom:20px">Last updated: January 2025 · VibeNet, Botswana</div>

  <div class="tc-section">
    <div class="tc-title">1. Acceptance of Terms</div>
    <p class="tc-text">By accessing or using VibeNet, you agree to be bound by these Terms and Conditions. If you do not agree, please do not use the platform. We reserve the right to update these terms at any time.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">2. Eligibility</div>
    <p class="tc-text">You must be at least 18 years old to use VibeNet. By registering, you confirm that the information you provide is accurate and that you are legally permitted to use this service in your jurisdiction.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">3. Content Policy</div>
    <p class="tc-text">You are solely responsible for content you post. You must not post content that is unlawful, harmful, hateful, sexually explicit, or that infringes on the rights of others. VibeNet reserves the right to remove any content and suspend accounts that violate this policy without notice.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">4. Creator Earnings</div>
    <p class="tc-text">Creators earn revenue through video views and ad impressions on their content. Payouts require a minimum of 1,000 followers and 4,000 watch hours. VibeNet processes payouts manually via Orange Money within 24–48 hours of a verified request. Earnings may be withheld if fraudulent activity is suspected.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">5. Advertising</div>
    <p class="tc-text">Ad campaigns submitted on VibeNet are subject to review and approval. VibeNet reserves the right to reject any campaign without providing a reason. Payment for ads is made in advance via Orange Money to the number provided. Approved campaigns will be activated once payment is confirmed.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">6. Account Suspension</div>
    <p class="tc-text">VibeNet may suspend or permanently ban accounts that violate these terms, engage in spam, abuse other users, or attempt to manipulate the platform's earnings system. Banned users forfeit any pending earnings.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">7. Privacy</div>
    <p class="tc-text">We collect only the information necessary to operate the platform (name, email, content you post). We do not sell your personal data to third parties. Media is stored securely on Cloudinary's CDN. By using VibeNet you consent to this data collection.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">8. Intellectual Property</div>
    <p class="tc-text">You retain ownership of the content you post. By posting on VibeNet you grant us a non-exclusive, royalty-free licence to display and distribute your content within the platform. You must not post content you do not own or have rights to.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">9. Limitation of Liability</div>
    <p class="tc-text">VibeNet is provided "as is" without warranties of any kind. We are not liable for any loss of data, earnings, or indirect damages arising from the use of the platform. Service availability is not guaranteed.</p>
  </div>

  <div class="tc-section">
    <div class="tc-title">10. Governing Law</div>
    <p class="tc-text">These terms are governed by the laws of the Republic of Botswana. Any disputes shall be resolved under Botswana jurisdiction.</p>
  </div>

  <div style="margin-top:28px;padding:16px;background:rgba(77,240,192,0.06);border:1px solid rgba(77,240,192,0.15);border-radius:12px;font-size:12px;color:#8899b4;line-height:1.6">
    Questions? Contact us at <span style="color:#4DF0C0">support@vibenet.bw</span>
  </div>
</div>

</div><!-- /mainApp -->

<script>
const API = '/api';
let currentUser = null;

function byId(id){ return document.getElementById(id); }
function escapeHtml(s){ if(!s) return ''; return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }

function showFileName(input){
  const d = byId('fileNameDisplay');
  d.textContent = input.files[0] ? input.files[0].name : '';
}

window.addEventListener('load', async () => {
  try {
    const res = await fetch(API + '/me');
    const j = await res.json();
    if(j.user){ currentUser = j.user; onLogin(); }
  } catch(e) {}
});

async function signup(){
  const name = byId('signupName').value.trim();
  const email = byId('signupEmail').value.trim().toLowerCase();
  const password = byId('signupPassword').value;
  if(!name||!email||!password){ alert('Please fill all required fields.'); return; }

  const pic = byId('signupPic').files[0];

  // Create account immediately — no waiting for pic upload
  const res = await fetch(API + '/signup', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name, email, password, profile_pic: '' })
  });
  const j = await res.json();
  if(!j.user){ alert(j.error || j.message); return; }
  currentUser = j.user;
  onLogin();

  // Upload pic in background after login — user is already in
  if(pic){
    try {
      const url = await uploadFile(pic, 'vibenet/avatars');
      if(url){
        await fetch(API + '/update_profile_pic', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ email, profile_pic: url })
        });
        currentUser.profile_pic = url;
        const av = byId('topAvatar'); if(av){ av.src = url; av.style.display='block'; }
        const ca = byId('composerAvatar'); if(ca){ ca.src = url; }
        const pa = byId('profileAvatar'); if(pa){ pa.src = url; }
      }
    } catch(e){ console.warn('Profile pic upload failed (non-fatal):', e); }
  }
}

async function login(){
  const email = byId('loginEmail').value.trim().toLowerCase();
  const password = byId('loginPassword').value;
  if(!email||!password){ alert('Please fill in your login details.'); return; }
  const res = await fetch(API + '/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email, password})});
  const j = await res.json();
  if(j.user){ currentUser = j.user; onLogin(); } else alert(j.error || 'Invalid credentials');
}

async function logout(){
  await fetch(API + '/logout', {method:'POST'});
  currentUser = null;
  byId('mainApp').style.display = 'none';
  byId('authScreen').style.display = 'flex';
  if(window._vn_poll) clearInterval(window._vn_poll);
}

function onLogin(){
  byId('authScreen').style.display = 'none';
  byId('mainApp').style.display = 'block';

  // Top nav avatar
  const av = byId('topAvatar');
  if(currentUser.profile_pic){ av.src = currentUser.profile_pic; av.style.display = 'block'; }

  // Composer avatar
  const ca = byId('composerAvatar');
  if(currentUser.profile_pic){ ca.src = currentUser.profile_pic; ca.style.display = ''; }

  // Profile tab section
  byId('profileName').textContent = currentUser.name || '—';
  byId('profileEmail').textContent = currentUser.email;
  const pa = byId('profileAvatar');
  if(currentUser.profile_pic){ pa.src = currentUser.profile_pic; }

  refreshAll();
  checkAdmin();
  window._vn_poll = setInterval(()=>{ if(currentUser){ loadNotifications(false); loadMonetization(); loadFeed(); } }, 30000);
}

// Tabs
function showTab(tab){
  const tabs = ['feed','notifications','monet','profile'];
  const navMap = { feed:'navFeed', notifications:'navNotifs', monet:'navMonet', profile:'navProfile' };
  tabs.forEach(t => {
    byId(t).classList.remove('visible');
    byId(t).style.display = 'none';
  });
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
  byId(tab).style.display = 'block';
  byId(tab).classList.add('visible');
  if(navMap[tab]) byId(navMap[tab]).classList.add('active');

  if(tab === 'profile') loadProfilePosts();
  if(tab === 'notifications') loadNotifications(true);
  if(tab === 'monet'){ loadMonetization(); loadAds();  }
}

function showUploadProgress(show, label='Uploading...'){
  const p = byId('uploadProgress');
  const btn = byId('postBtn');
  if(!p) return;
  if(show){
    p.style.display = 'block';
    byId('uploadLabel').textContent = label;
    byId('uploadBar').style.width = '0%';
    if(btn){ btn.disabled = true; btn.style.opacity = '0.5'; }
    // Animate bar to 90% while uploading
    let w = 0;
    p._interval = setInterval(()=>{
      w = Math.min(w + (Math.random() * 4), 88);
      byId('uploadBar').style.width = w + '%';
    }, 300);
  } else {
    clearInterval(p._interval);
    byId('uploadBar').style.width = '100%';
    setTimeout(()=>{ p.style.display='none'; byId('uploadBar').style.width='0%'; }, 600);
    if(btn){ btn.disabled = false; btn.style.opacity = '1'; }
  }
}

async function uploadFile(file, folder='vibenet/posts'){
  const isPost = folder === 'vibenet/posts';
  const isVideo = file.type.startsWith('video/');
  if(isVideo && file.size > 20 * 1024 * 1024){
    alert('Video too large. Max 20MB.');
    return '';
  }
  if(isPost) showUploadProgress(true, `Uploading ${isVideo ? 'video' : 'image'} (${(file.size/1024/1024).toFixed(1)}MB)...`);
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(API + '/upload', {method:'POST', body: fd});
    const j = await res.json();
    if(j.error) throw new Error(j.error);
    if(!j.url) throw new Error('No URL returned');
    if(isPost) showUploadProgress(false);
    return j.url;
  } catch(e){
    if(isPost) showUploadProgress(false);
    alert('Upload failed: ' + e.message);
    return '';
  }
}


function optimizeCldUrl(url, isVideo){
  return url; // media stored as data URLs, no transform needed
}

function isVideoUrl(url){
  if(!url) return false;
  return url.includes('/video/upload/') ||
         url.includes('resource_type=video') ||
         /\.(mp4|webm|mov|avi|mkv|ogv)(\?|$|#)/i.test(url);
}

async function createAd(){
  const title    = byId('adTitle').value.trim();
  const budget   = parseFloat(byId('adBudget').value || 0);
  const whatsapp = byId('adWhatsapp').value.trim().replace(/\D/g,'');
  const msg      = byId('adMsg');
  if(!title || !budget){ alert('Please enter a title and budget.'); return; }
  if(!whatsapp){ alert('Please enter your WhatsApp number.'); return; }
  await fetch(API+'/ads', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title, budget, whatsapp_number: whatsapp, owner: currentUser.email})});
  byId('adTitle').value = ''; byId('adBudget').value = ''; byId('adWhatsapp').value = '';
  msg.style.display = 'block';
  msg.style.color = 'var(--accent)';
  msg.textContent = '✅ Campaign submitted! Please send P' + budget.toFixed(2) + ' via Orange Money to 72927417. Your campaign goes live once we confirm your payment.';
  setTimeout(()=>{ msg.style.display='none'; }, 10000);
  loadAds();
}

async function requestPayout(){
  const omNumber = byId('payoutNumber').value.trim();
  const amount = parseFloat(byId('payoutAmount').value || 0);
  const msg = byId('payoutMsg');
  if(!omNumber){ alert('Please enter your Orange Money number.'); return; }
  if(!amount || amount <= 0){ alert('Please enter a valid amount.'); return; }
  const res = await fetch(API+'/payout', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ email: currentUser.email, om_number: omNumber, amount })
  });
  const j = await res.json();
  msg.style.display = 'block';
  if(j.success){
    byId('payoutNumber').value = ''; byId('payoutAmount').value = '';
    msg.style.color = 'var(--accent)';
    msg.textContent = '✅ ' + j.message;
    await loadMonetization();
  } else {
    msg.style.color = 'var(--danger)';
    msg.textContent = '❌ ' + (j.error || 'Something went wrong.');
  }
  setTimeout(()=>{ msg.style.display='none'; }, 8000);
}

async function addPost(){
  if(!currentUser){ alert('Please login first.'); return; }
  const text = byId('postText').value.trim();
  const fileEl = byId('fileUpload');
  let url = '';
  if(fileEl.files[0]){
    url = await uploadFile(fileEl.files[0]);
    console.log('Upload result URL:', url);
  }
  if(!text && !url) return;
  const res = await fetch(API + '/posts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    author_email: currentUser.email, author_name: currentUser.name, profile_pic: currentUser.profile_pic||'', text, file_url: url
  })});
  const j = await res.json();
  console.log('Post created:', j);
  byId('postText').value=''; fileEl.value=''; byId('fileNameDisplay').textContent='';
  await loadFeed(); await loadProfilePosts(); await loadMonetization();
}

function createPostElement(p){
  const div = document.createElement('div'); div.className='post-card';

  const header = document.createElement('div'); header.className='post-header';
  const authorWrap = document.createElement('div'); authorWrap.className='post-author';
  const img = document.createElement('img'); img.className='post-avatar'; img.src = p.profile_pic || '';
  img.onerror = ()=> { img.style.background='var(--surface)'; img.src=''; };
  const info = document.createElement('div'); info.className='post-author-info';
  const verifiedBadge = p.author_verified ? ' <span class="vbadge" title="VibeNet Verified">✦</span>' : '';
  info.innerHTML = `<strong>${escapeHtml(p.author_name || 'Unknown')}${verifiedBadge}</strong><div class="post-ts">${escapeHtml(p.timestamp)}</div>`;
  authorWrap.append(img, info);
  header.append(authorWrap);

  if(currentUser && currentUser.email === p.author_email){
    // Owner: edit + delete buttons
    const actions = document.createElement('div'); actions.className='post-actions';
    const editBtn = document.createElement('button'); editBtn.className='action-btn edit-btn'; editBtn.title='Edit'; editBtn.textContent='✏️';
    editBtn.onclick = ()=> openEditModal(p.id, p.text);
    const delBtn = document.createElement('button'); delBtn.className='action-btn delete'; delBtn.title='Delete'; delBtn.textContent='🗑';
    delBtn.onclick = async ()=>{
      if(!confirm('Delete this post?')) return;
      const r = await fetch(API+'/posts/'+p.id, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email: currentUser.email})});
      const j = await r.json();
      if(j.success){ div.style.transition='opacity 0.3s,transform 0.3s'; div.style.opacity='0'; div.style.transform='scale(0.97)'; setTimeout(()=>{ div.remove(); loadMonetization(); }, 300); }
    };
    actions.append(editBtn, delBtn);
    header.append(actions);
  } else if(currentUser){
    const fb = document.createElement('button'); fb.className='follow-btn'; fb.textContent='+ Follow';
    fb.onclick = async ()=>{
      const res = await fetch(API+'/follow',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({follower_email:currentUser.email,target_email:p.author_email})});
      const j = await res.json();
      if(j.success){ fb.classList.toggle('active'); fb.textContent=fb.classList.contains('active')?'✓ Following':'+ Follow'; loadMonetization(); }
    };
    (async()=>{
      const r = await fetch(API+`/is_following?f=${encodeURIComponent(currentUser.email)}&t=${encodeURIComponent(p.author_email)}`);
      const jj = await r.json();
      if(jj.following){ fb.classList.add('active'); fb.textContent='✓ Following'; }
    })();
    header.append(fb);
  }

  div.append(header);

  const postTextEl = document.createElement('div');
  if(p.text){ postTextEl.className='post-text'; postTextEl.textContent=p.text; div.append(postTextEl); }
  div._postTextEl = postTextEl;

  if(p.file_url){
    const media = document.createElement('div'); media.className='post-media';
    const isVideo = isVideoUrl(p.file_url);
    if(isVideo){
      const wrap = document.createElement('div'); wrap.className='video-wrap';
      const v = document.createElement('video');
      v.src = optimizeCldUrl(p.file_url, true); v.controls = true; v.muted = true; v.loop = false;
      v.setAttribute('playsinline','');
      const hint = document.createElement('div'); hint.className='play-hint';
      hint.innerHTML='<span>▶</span>';
      v.addEventListener('play', ()=>{ wrap.classList.add('playing'); });
      v.addEventListener('pause', ()=>{ wrap.classList.remove('playing'); });
      v.addEventListener('ended', async()=>{
        wrap.classList.remove('playing');
        await fetch(API+'/watch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer:currentUser?currentUser.email:'',post_id:p.id})});
        await fetch(API+'/ads/impression',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({post_id:p.id,viewer:currentUser?currentUser.email:''})});
        loadMonetization();
      });
      wrap.append(v, hint);
      media.append(wrap);
    } else {
      const im=document.createElement('img'); im.src=optimizeCldUrl(p.file_url, false); media.append(im);
    }
    div.append(media);
  }

  const footer = document.createElement('div'); footer.className='post-footer';
  const bar = document.createElement('div'); bar.className='reaction-bar';
  ['👍','❤️','😂'].forEach(em=>{
    const btn=document.createElement('button'); btn.className='react-btn'; btn.dataset.emoji=em;
    btn.innerHTML=`${em} <span>${p.reactions&&p.reactions[em]?p.reactions[em]:0}</span>`;
    if(p.user_reaction&&currentUser&&p.user_reaction===em) btn.classList.add('active');
    btn.onclick=async(ev)=>{
      ev.stopPropagation();
      if(!currentUser){ alert('Login to react'); return; }
      const res=await fetch(API+'/react',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({post_id:p.id,emoji:em,user_email:currentUser.email})});
      const j=await res.json();
      if(j.success){
        div.querySelectorAll('.react-btn').forEach(rb=>{
          const e=rb.dataset.emoji;
          rb.innerHTML=`${e} <span>${j.reactions&&j.reactions[e]!==undefined?j.reactions[e]:(p.reactions&&p.reactions[e]?p.reactions[e]:0)}</span>`;
          rb.classList.remove('active');
        });
        const clicked=div.querySelector(`.react-btn[data-emoji="${em}"]`);
        if(clicked) clicked.classList.add('active');
      }
    };
    bar.append(btn);
  });

  const cc=document.createElement('div'); cc.className='comment-count'; cc.innerHTML=`💬 ${p.comments_count||0}`;
  footer.append(bar, cc);
  div.append(footer);
  return div;
}

function createAdCard(ad){
  const div = document.createElement('div');
  const waNumber = (ad.whatsapp_number||'').replace(/\D/g,'');
  const waMsg = encodeURIComponent(`Hi! I saw your ad "${ad.title}" on VibeNet and I'd like to know more.`);
  const waLink = waNumber ? `https://wa.me/${waNumber}?text=${waMsg}` : '';
  div.style.cssText = `background:linear-gradient(135deg,rgba(77,240,192,0.06),rgba(0,201,255,0.04));border:1px solid rgba(77,240,192,0.2);border-radius:16px;padding:16px 18px;margin-bottom:12px;${waLink?'cursor:pointer;':''}`;
  if(waLink) div.onclick = ()=> window.open(waLink,'_blank','noopener');
  div.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <span style="background:rgba(77,240,192,0.15);color:#4DF0C0;font-size:10px;font-weight:800;padding:3px 8px;border-radius:100px;letter-spacing:0.8px">SPONSORED</span>
      ${waLink ? '<span style="font-size:11px;color:#25D366;font-weight:600">Tap to chat →</span>' : ''}
    </div>
    <div style="font-size:15px;font-weight:700;color:#e8f0ff;margin-bottom:8px">\${escapeHtml(ad.title||'')}</div>
    ${waLink ? `<div style="display:inline-flex;align-items:center;gap:8px;background:#25D366;color:#fff;font-size:13px;font-weight:700;padding:9px 16px;border-radius:100px;pointer-events:none">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
      Chat on WhatsApp
    </div>` : '<div style="font-size:12px;color:#5a6a85">Promoted on VibeNet</div>'}
  `;
  return div;
}

function observeVideos(){
  if(window._vn_obs) window._vn_obs.disconnect();
  let currentlyPlaying = null;

  const obs = new IntersectionObserver(entries=>{
    entries.forEach(entry=>{
      const v = entry.target;
      const ratio = entry.intersectionRatio;

      if(ratio >= 0.6){
        // Autoplay: pause anything else first
        if(currentlyPlaying && currentlyPlaying !== v){
          currentlyPlaying.pause();
        }
        if(v.paused){
          v.muted = true;
          v.play().then(()=>{ currentlyPlaying = v; }).catch(()=>{});
        }
      } else if(ratio < 0.25){
        if(!v.paused){ v.pause(); }
        if(currentlyPlaying === v) currentlyPlaying = null;
      }
    });
  }, { threshold: [0, 0.25, 0.5, 0.6, 0.75, 1.0] });

  document.querySelectorAll('video').forEach(v=>obs.observe(v));
  window._vn_obs = obs;
}

async function loadNotifications(markSeen=false){
  if(!currentUser) return;
  if(markSeen){
    await fetch(API+'/notifications/mark-seen/'+encodeURIComponent(currentUser.email), {method:'POST'});
  }
  const r=await fetch(API+'/notifications/'+encodeURIComponent(currentUser.email));
  const data=await r.json();
  const list = data.items || [];
  const unseen = data.unseen || 0;
  const el=byId('notifList'); el.innerHTML='';
  const countEl=byId('notifCount');
  if(unseen > 0){ countEl.style.display='inline-block'; countEl.textContent=unseen; } else countEl.style.display='none';
  if(!list.length){
    el.innerHTML='<div class="empty-state" style="padding:32px"><div class="empty-icon">🎉</div><p>All caught up!</p></div>';
    return;
  }
  list.forEach(n=>{
    const d=document.createElement('div'); d.className='notif-item';
    if(!n.seen) d.style.background='rgba(77,240,192,0.04)';
    const icon=n.text.includes('reaction')?'⚡':n.text.includes('follow')?'👋':'🔔';
    d.innerHTML=`<div class="notif-icon">${icon}</div><div><div class="notif-text">${escapeHtml(n.text)}</div><div class="notif-time">${escapeHtml(n.timestamp)}</div></div>`;
    el.appendChild(d);
  });
}

async function loadProfilePosts(){
  if(!currentUser) return;
  const r=await fetch(API+'/profile/'+encodeURIComponent(currentUser.email));
  const j=await r.json();
  byId('profileBio').value=j.bio||'';
  const el=byId('profilePosts'); el.innerHTML='';
  if(!j.posts||!j.posts.length){
    el.innerHTML='<div class="empty-state"><div class="empty-icon">✏️</div><p>No posts yet.</p></div>';
    return;
  }
  j.posts.forEach(p=>{
    const d=document.createElement('div'); d.className='post-card';
    d.innerHTML=`<div class="post-text">${escapeHtml(p.text||'')}</div><div class="post-ts">${escapeHtml(p.timestamp)}</div>`;
    if(p.file_url){
      if(p.file_url.endsWith('.mp4')||p.file_url.endsWith('.webm')){
        d.innerHTML+=`<div class="post-media"><video src="${p.file_url}" controls></video></div>`;
      } else {
        d.innerHTML+=`<div class="post-media"><img src="${p.file_url}"></div>`;
      }
    }
    el.appendChild(d);
  });
}

async function updateBio(){
  if(!currentUser) return;
  const bio = byId('profileBio').value.trim();
  await fetch(API+'/update_bio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:currentUser.email,bio})});
  const saved=document.createElement('span');
  saved.style.cssText='color:var(--accent);font-size:13px;margin-left:10px;';
  saved.textContent='Saved ✓';
  const btn=document.querySelector('[onclick="updateBio()"]');
  btn.parentNode.insertBefore(saved, btn.nextSibling);
  setTimeout(()=>saved.remove(), 2000);
}

async function loadMonetization(){
  if(!currentUser) return;
  const r = await fetch(API+'/monetization/'+encodeURIComponent(currentUser.email));
  const j = await r.json();
  const followers  = j.followers   || 0;
  const watchHours = j.watch_hours || 0;
  const earnings   = j.earnings    || 0;
  const eligible   = j.eligible;

  byId('monFollowers').textContent = followers;
  byId('monWatch').textContent     = watchHours;
  byId('monEarnings').textContent  = earnings.toFixed(2);

  const statusEl = byId('monStatus');
  if(eligible){
    statusEl.innerHTML = '✅ Eligible';
    statusEl.style.color = 'var(--accent)';
  } else {
    // Show what's still needed
    const needFollowers  = Math.max(0, 1000 - followers);
    const needWatchHours = Math.max(0, 4000 - watchHours);
    let msg = '⏳ Growing';
    const parts = [];
    if(needFollowers > 0)  parts.push(`${needFollowers} more followers`);
    if(needWatchHours > 0) parts.push(`${needWatchHours} more watch hours`);
    if(parts.length) msg += ` — need ${parts.join(' & ')}`;
    statusEl.innerHTML = msg;
    statusEl.style.color = 'var(--muted2)';
    statusEl.style.fontSize = '13px';
  }

  // Show/hide payout section based on eligibility
  const payoutSection = byId('payoutSection');
  if(payoutSection){
    if(eligible){
      payoutSection.style.display = 'block';
    } else {
      payoutSection.style.display = 'none';
    }
  }
}

async function createAd(){
  const title=byId('adTitle').value.trim(); const budget=parseFloat(byId('adBudget').value||0);
  if(!title||!budget){ alert('Please enter a title and budget.'); return; }
  await fetch(API+'/ads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,budget,owner:currentUser.email})});
  byId('adTitle').value=''; byId('adBudget').value='';
  loadAds();
}

async function loadAds(){
  const r=await fetch(API+'/ads');
  const list=await r.json();
  const el=byId('adsList'); el.innerHTML='';
  if(!list.length){
    el.innerHTML='<div class="empty-state"><div class="empty-icon">📢</div><p>No campaigns yet. Launch your first one above!</p></div>';
    return;
  }
  list.forEach(a=>{
    const d=document.createElement('div'); d.className='ad-item';
    d.innerHTML=`<div class="ad-item-name">${escapeHtml(a.title)}</div><div class="ad-item-stats"><span class="ad-stat">💰 ${a.budget}</span><span class="ad-stat">👁 ${a.impressions}</span><span class="ad-stat">🖱 ${a.clicks}</span></div>`;
    el.appendChild(d);
  });
}


// Edit modal
let _editPostId = null;
function openEditModal(postId, currentText){
  _editPostId = postId;
  byId('editPostText').value = currentText || '';
  byId('editModal').style.display = 'flex';
  setTimeout(()=>byId('editPostText').focus(), 80);
}
function closeEditModal(){
  byId('editModal').style.display = 'none';
  _editPostId = null;
}
async function saveEditPost(){
  if(!_editPostId || !currentUser) return;
  const text = byId('editPostText').value.trim();
  if(!text){ alert('Post cannot be empty.'); return; }
  const res = await fetch(API+'/posts/'+_editPostId, {
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email: currentUser.email, text})
  });
  const j = await res.json();
  if(j.success){
    closeEditModal();
    // Update in-place in feed
    const cards = document.querySelectorAll('.post-card');
    cards.forEach(card=>{
      if(card._postId == _editPostId && card._postTextEl){
        card._postTextEl.textContent = text;
      }
    });
    await loadFeed();
  } else {
    alert(j.error || 'Edit failed');
  }
}




async function refreshAll(){ await loadFeed(); await loadNotifications(); await loadProfilePosts(); await loadMonetization(); await loadAds(); }

// Terms & Conditions sidebar
function openTerms(){
  byId('termsSidebar').style.display = 'block';
  byId('termsOverlay').style.display = 'block';
  document.body.style.overflow = 'hidden';
}
function closeTerms(){
  byId('termsSidebar').style.display = 'none';
  byId('termsOverlay').style.display = 'none';
  document.body.style.overflow = '';
}

// Admin — only visible to owner
const ADMIN_EMAIL = 'botsile55@gmail.com';
function checkAdmin(){
  if(currentUser && currentUser.email === ADMIN_EMAIL){
    const p = byId('adminPanel');
    if(p) p.style.display = 'block';
  }
}
async function adminWipePosts(){
  if(!confirm('Delete ALL posts? This cannot be undone.')) return;
  const msg = byId('adminMsg');
  const res = await fetch('/api/admin/wipe-posts', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({confirm:'WIPE'})
  });
  const j = await res.json();
  msg.style.display = 'block';
  if(j.success){
    msg.style.color = 'var(--accent)';
    msg.textContent = '✅ All posts wiped.';
    await loadFeed();
  } else {
    msg.style.color = 'var(--danger)';
    msg.textContent = '❌ ' + (j.error || 'Failed');
  }
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

# ---------- API: Auth ----------
@app.route("/api/signup", methods=["POST"])
def api_signup():
    data     = request.get_json() or {}
    name     = data.get("name", "").strip()
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "email + password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists"}), 400
    profile_pic = data.get("profile_pic", "")
    user = User(name=name, email=email, password=password, profile_pic=profile_pic)
    db.session.add(user)
    db.session.commit()
    session["user_email"] = email
    return jsonify({"user": user.to_dict()})


@app.route("/api/login", methods=["POST"])
def api_login():
    data     = request.get_json() or {}
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    user     = User.query.filter_by(email=email, password=password).first()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    if user.banned:
        return jsonify({"error": "Your account has been suspended. Contact support."}), 403
    user.last_active = now_ts()
    db.session.commit()
    session["user_email"] = email
    return jsonify({"user": user.to_dict()})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "logged out"})


@app.route("/api/me")
def api_me():
    email = session.get("user_email")
    if not email:
        return jsonify({"user": None})
    user = User.query.filter_by(email=email).first()
    return jsonify({"user": user.to_dict() if user else None})


# ---------- Upload ----------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename"}), 400
    import base64
    data = f.read()
    if len(data) > 20 * 1024 * 1024:
        return jsonify({"error": "File too large (max 20MB)"}), 400
    mime = f.mimetype or "application/octet-stream"
    b64  = base64.b64encode(data).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"
    return jsonify({"url": data_url})





@app.route("/api/posts/<int:post_id>", methods=["DELETE", "PATCH"])
def api_post_modify(post_id):
    data  = request.get_json() or {}
    email = data.get("email")
    post  = Post.query.get_or_404(post_id)
    if post.author_email != email:
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == "DELETE":
        UserReaction.query.filter_by(post_id=post_id).delete()
        db.session.delete(post)
        db.session.commit()
        return jsonify({"success": True})

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Text required"}), 400
    post.text = text
    db.session.commit()
    return jsonify({"success": True})


# ---------- React ----------
@app.route("/api/react", methods=["POST"])
def api_react_post():
    data       = request.get_json() or {}
    post_id    = data.get("post_id")
    emoji      = data.get("emoji")
    user_email = data.get("user_email")

    post = Post.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found"}), 404

    reactions  = post.reactions()
    prev_react = UserReaction.query.filter_by(user_email=user_email, post_id=post_id).first()
    prev_emoji = prev_react.emoji if prev_react else None

    if prev_emoji == emoji:
        return jsonify({"success": True, "reactions": reactions})

    if prev_react:
        reactions[prev_emoji] = max(0, reactions.get(prev_emoji, 0) - 1)
        db.session.delete(prev_react)

    new_react = UserReaction(user_email=user_email, post_id=post_id, emoji=emoji)
    db.session.add(new_react)
    reactions[emoji] = reactions.get(emoji, 0) + 1
    post.reactions_json = _json.dumps(reactions)

    if post.author_email != user_email:
        notif = Notification(user_email=post.author_email,
                             text=f"{emoji} reaction on your post")
        db.session.add(notif)

    db.session.commit()
    return jsonify({"success": True, "reactions": reactions})


# ---------- Notifications ----------
@app.route("/api/notifications/<email>")
def api_notifications_get(email):
    notifs = Notification.query.filter_by(user_email=email).order_by(Notification.id.desc()).all()
    unseen = sum(1 for n in notifs if not n.seen)
    return jsonify({"items": [n.to_dict() for n in notifs], "unseen": unseen})


@app.route("/api/notifications/mark-seen/<email>", methods=["POST"])
def api_notifications_mark_seen(email):
    Notification.query.filter_by(user_email=email, seen=0).update({"seen": 1})
    db.session.commit()
    return jsonify({"success": True})


# ---------- Monetization / Profile ----------
@app.route("/api/monetization/<email>")
def api_monetization_get(email):
    followers = Follower.query.filter_by(user_email=email).count()
    user      = User.query.filter_by(email=email).first()
    if user:
        eligible = followers >= 1000 and user.watch_hours >= 4000
        return jsonify({
            "followers":   followers,
            "watch_hours": user.watch_hours,
            "earnings":    user.earnings,
            "eligible":    eligible,
        })
    return jsonify({"followers": 0, "watch_hours": 0, "earnings": 0, "eligible": False})


@app.route("/api/profile/<email>")
def api_profile_get(email):
    user  = User.query.filter_by(email=email).first()
    posts = Post.query.filter_by(author_email=email).order_by(Post.id.desc()).all()
    return jsonify({
        "bio":   user.bio if user else "",
        "posts": [p.to_dict() for p in posts],
    })


@app.route("/api/update_bio", methods=["POST"])
def api_update_bio():
    data  = request.get_json() or {}
    user  = User.query.filter_by(email=data.get("email")).first()
    if user:
        user.bio = data.get("bio", "")
        db.session.commit()
    return jsonify({"success": True})


@app.route("/api/update_profile_pic", methods=["POST"])
def api_update_profile_pic():
    data  = request.get_json() or {}
    user  = User.query.filter_by(email=data.get("email")).first()
    if user:
        user.profile_pic = data.get("profile_pic", "")
        db.session.commit()
    return jsonify({"success": True})


# ---------- Following ----------
@app.route("/api/follow", methods=["POST"])
def api_follow():
    data     = request.get_json() or {}
    follower = data.get("follower_email")
    target   = data.get("target_email")

    existing = Follower.query.filter_by(user_email=target, follower_email=follower).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"success": True, "status": "unfollowed"})

    db.session.add(Follower(user_email=target, follower_email=follower))
    db.session.add(Notification(user_email=target, text=f"{follower} followed you"))
    db.session.commit()
    return jsonify({"success": True, "status": "followed"})


@app.route("/api/is_following")
def api_is_following():
    f = request.args.get("f")
    t = request.args.get("t")
    exists = Follower.query.filter_by(user_email=t, follower_email=f).first() is not None
    return jsonify({"following": exists})


# ---------- Watch / Ads ----------
@app.route("/api/watch", methods=["POST"])
def api_watch():
    data    = request.get_json() or {}
    viewer  = data.get("viewer")
    post_id = data.get("post_id")
    post    = Post.query.get(post_id)
    if post and post.author_email != viewer:
        author = User.query.filter_by(email=post.author_email).first()
        if author:
            author.watch_hours += 1
            author.earnings    += 0.1
            db.session.commit()
    return jsonify({"success": True})


@app.route("/api/ads", methods=["GET", "POST"])
def api_ads():
    if request.method == "POST":
        data = request.get_json() or {}
        ad   = Ad(title=data.get("title"), owner_email=data.get("owner"), whatsapp_number=data.get("whatsapp_number",""), budget=data.get("budget", 0), approved=0)
        db.session.add(ad)
        db.session.commit()
        return jsonify({"message": "Ad created"})
    # Only return approved ads to regular users
    ads = Ad.query.filter_by(approved=1).order_by(Ad.id.desc()).all()
    return jsonify([a.to_dict() for a in ads])


@app.route("/api/ads/impression", methods=["POST"])
def api_ads_impression():
    data    = request.get_json() or {}
    post_id = data.get("post_id")
    post    = Post.query.get(post_id)
    if post:
        author = User.query.filter_by(email=post.author_email).first()
        if author:
            author.earnings += 0.05   # P0.05 per ad impression
            db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/wipe-posts", methods=["POST"])
def api_wipe_posts():
    """Delete every post and reaction. One-time cleanup."""
    data = request.get_json() or {}
    if data.get("confirm") != "WIPE":
        return jsonify({"error": "Send confirm=WIPE to proceed"}), 400
    UserReaction.query.delete()
    Post.query.delete()
    db.session.commit()
    return jsonify({"success": True, "message": "All posts and reactions deleted."})


# ---------- Admin Dashboard ----------
ADMIN_EMAIL = "botsile55@gmail.com"
BTN_GREEN   = "background:#4DF0C0;color:#030a0e;padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"
BTN_RED     = "background:rgba(240,106,77,0.15);color:#f06a4d;border:1px solid rgba(240,106,77,0.3);padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"
BTN_GREY    = "background:rgba(255,255,255,0.06);color:#8899b4;border:1px solid rgba(255,255,255,0.1);padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"

def require_admin():
    return session.get("user_email") == ADMIN_EMAIL


@app.route("/admin")
def admin_page():
    if not require_admin():
        return f"""<html><body style="font-family:sans-serif;background:#060910;color:#e8f0ff;padding:40px">
        <h2 style="color:#f06a4d">Not logged in as admin</h2>
        <p>You must be logged in as <strong>{ADMIN_EMAIL}</strong> on the main app first.</p>
        <a href="/" style="color:#4DF0C0">← Go to VibeNet and log in</a>, then return to /admin.
        </body></html>""", 403
    try:
        return _build_admin_page()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        return f"<html><body style='font-family:monospace;background:#060910;color:#f06a4d;padding:40px;white-space:pre-wrap'>Admin error:\n{err}</body></html>", 500


def _build_admin_page():
    total_users     = User.query.count()
    total_posts     = Post.query.count()
    total_ads       = Ad.query.count()
    pending_ads     = Ad.query.filter_by(approved=0).count()
    pending_payouts = PayoutRequest.query.filter_by(status="pending").count()
    total_earnings  = db.session.query(func.sum(User.earnings)).scalar() or 0

    users   = User.query.order_by(User.created_at.desc()).all()
    ads     = Ad.query.order_by(Ad.id.desc()).all()
    payouts = PayoutRequest.query.order_by(PayoutRequest.id.desc()).all()

    def badge(val, labels=("Pending","Approved","Rejected"), colors=("f0c84d","4DF0C0","f06a4d")):
        COLOR_MAP = {"f0c84d":"240,200,77","4DF0C0":"77,240,192","f06a4d":"240,106,77"}
        rgb = COLOR_MAP.get(colors[val], "77,240,192")
        return f'<span style="background:rgba({rgb},0.15);color:#{colors[val]};padding:3px 10px;border-radius:100px;font-size:11px;font-weight:700">{labels[val]}</span>'

    # Build user rows with full insights
    rows_users = ""
    for u in users:
        try:
            posts_count     = Post.query.filter_by(author_email=u.email).count()
            followers_count = Follower.query.filter_by(user_email=u.email).count()
            user_post_ids   = [p.id for p in Post.query.filter_by(author_email=u.email).with_entities(Post.id).all()]
            reactions_total = UserReaction.query.filter(UserReaction.post_id.in_(user_post_ids)).count() if user_post_ids else 0
            last_post       = Post.query.filter_by(author_email=u.email).order_by(Post.id.desc()).first()
            last_post_ts    = last_post.timestamp if last_post else "—"
            status_badge    = '<span style="color:#4DF0C0;font-size:11px;font-weight:700">✦ Verified</span>' if u.verified else ""
            ban_badge       = '<span style="color:#f06a4d;font-size:11px;font-weight:700">⛔ Banned</span>' if u.banned else ""
            rows_users += f"""<tr>
              <td>
                <div style="font-weight:600">{u.name or "—"} {status_badge} {ban_badge}</div>
                <div style="color:#5a6a85;font-size:11px">{u.email}</div>
              </td>
              <td style="text-align:center">{posts_count}</td>
              <td style="text-align:center">{reactions_total}</td>
              <td style="text-align:center">{followers_count}</td>
              <td style="text-align:center">{u.watch_hours}</td>
              <td style="color:#4DF0C0;text-align:center">P{u.earnings:.2f}</td>
              <td style="color:#5a6a85;font-size:11px">{u.last_active or "—"}</td>
              <td style="color:#5a6a85;font-size:11px">{last_post_ts}</td>
              <td>
                <div style="display:flex;gap:5px;flex-wrap:wrap">
                  <button onclick=\'verifyUser("{u.email}", {0 if u.verified else 1})\' style=\'{BTN_GREEN if not u.verified else BTN_GREY}\'>{" Unverify" if u.verified else "✦ Verify"}</button>
                  <button onclick=\'banUser("{u.email}", {0 if u.banned else 1})\' style=\'{BTN_GREY if u.banned else BTN_RED}\'>{" Unban" if u.banned else "⛔ Ban"}</button>
                  <button onclick=\'deleteUser("{u.email}")\' style=\'{BTN_RED}\'>🗑</button>
                </div>
              </td>
            </tr>"""
        except Exception as e:
            rows_users += f'<tr><td colspan="9" style="color:#f06a4d;font-size:12px">Error loading {u.email}: {e}</td></tr>'

    rows_users = rows_users or '<tr><td colspan="9" style="color:#5a6a85;text-align:center;padding:20px">No users</td></tr>'

    rows_ads = "".join(f"""<tr>
      <td>#{a.id}</td><td>{a.title or "—"}</td>
      <td style="color:#8899b4;font-size:12px">{a.owner_email}</td>
      <td>P{a.budget:.2f}</td><td>{a.impressions}</td>
      <td>{badge(a.approved)}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap">
        {"<button onclick=\'approveAd("+str(a.id)+",1)\' style=\'"+BTN_GREEN+"\'>✓ Approve</button>" if a.approved != 1 else ""}
        {"<button onclick=\'approveAd("+str(a.id)+",2)\' style=\'"+BTN_RED+"\'>✗ Reject</button>" if a.approved != 2 else ""}
      </td></tr>""" for a in ads) or '<tr><td colspan="7" style="color:#5a6a85;text-align:center;padding:20px">No campaigns</td></tr>'

    rows_payouts = "".join(f"""<tr>
      <td>#{p.id}</td>
      <td>{p.user_name}<br><span style="color:#5a6a85;font-size:11px">{p.user_email}</span></td>
      <td style="letter-spacing:1px">{p.om_number}</td>
      <td style="color:#4DF0C0;font-weight:700">P{p.amount:.2f}</td>
      <td style="color:#5a6a85;font-size:12px">{p.created_at}</td>
      <td>{"<button onclick=\'markPaid("+str(p.id)+")\' style=\'"+BTN_GREEN+"\'>Mark Paid</button>" if p.status=="pending" else badge(1,("Pending","Paid","Rejected"))}</td>
    </tr>""" for p in payouts) or '<tr><td colspan="6" style="color:#5a6a85;text-align:center;padding:20px">No payout requests</td></tr>'

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VibeNet Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:#060910;color:#e8f0ff;padding:20px;min-height:100vh}}
h1{{color:#4DF0C0;font-size:22px;margin-bottom:4px}}
.sub{{color:#5a6a85;font-size:13px;margin-bottom:28px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:28px}}
.stat{{background:#101520;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px}}
.stat-l{{font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:#5a6a85;margin-bottom:6px}}
.stat-v{{font-size:28px;font-weight:800;color:#4DF0C0}}
.section{{background:#101520;border:1px solid rgba(255,255,255,0.07);border-radius:14px;padding:20px;margin-bottom:24px;overflow-x:auto}}
h2{{font-size:15px;font-weight:700;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.07)}}
table{{width:100%;border-collapse:collapse;font-size:13px;min-width:600px}}
th{{text-align:left;color:#5a6a85;font-weight:600;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);white-space:nowrap}}
td{{padding:10px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
button{{border:none;padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap}}
button:hover{{opacity:0.8}}
a{{color:#4DF0C0;text-decoration:none;font-size:13px}}
</style></head><body>
<h1>⚡ VibeNet Admin</h1>
<div class="sub">Signed in as {ADMIN_EMAIL} · <a href="/">← Back to app</a></div>

<div class="stats">
  <div class="stat"><div class="stat-l">Users</div><div class="stat-v">{total_users}</div></div>
  <div class="stat"><div class="stat-l">Posts</div><div class="stat-v">{total_posts}</div></div>
  <div class="stat"><div class="stat-l">All Ads</div><div class="stat-v">{total_ads}</div></div>
  <div class="stat"><div class="stat-l">Pending Ads</div><div class="stat-v" style="color:#f0c84d">{pending_ads}</div></div>
  <div class="stat"><div class="stat-l">Pending Payouts</div><div class="stat-v" style="color:#f0c84d">{pending_payouts}</div></div>
  <div class="stat"><div class="stat-l">Total Earned</div><div class="stat-v">P{total_earnings:.2f}</div></div>
</div>

<div class="section">
  <h2>👥 Users & Insights</h2>
  <table>
    <tr><th>User</th><th>Posts</th><th>Reactions</th><th>Followers</th><th>Watch Hrs</th><th>Earnings</th><th>Last Active</th><th>Last Post</th><th>Actions</th></tr>
    {rows_users}
  </table>
</div>

<div class="section">
  <h2>📣 Ad Campaigns</h2>
  <table><tr><th>ID</th><th>Title</th><th>Owner</th><th>Budget</th><th>Impressions</th><th>Status</th><th>Actions</th></tr>
  {rows_ads}</table>
</div>

<div class="section">
  <h2>💸 Payout Requests</h2>
  <table><tr><th>ID</th><th>User</th><th>OM Number</th><th>Amount</th><th>Date</th><th>Status</th></tr>
  {rows_payouts}</table>
</div>

<script>
async function approveAd(id, status){{
  const r = await fetch('/api/admin/ads/'+id+'/approve',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{status}})}});
  const j = await r.json();
  if(j.success) location.reload(); else alert(j.error||'Failed');
}}
async function markPaid(id){{
  const r = await fetch('/api/admin/payout/'+id+'/mark-paid',{{method:'POST'}});
  const j = await r.json();
  if(j.success) location.reload(); else alert(j.error||'Failed');
}}
async function banUser(email, val){{
  if(val && !confirm('Ban '+email+'?')) return;
  const r = await fetch('/api/admin/user/ban',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email,val}})}});
  const j = await r.json();
  if(j.success) location.reload(); else alert(j.error||'Failed');
}}
async function verifyUser(email, val){{
  const r = await fetch('/api/admin/user/verify',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email,val}})}});
  const j = await r.json();
  if(j.success) location.reload(); else alert(j.error||'Failed');
}}
async function deleteUser(email){{
  if(!confirm('Permanently delete '+email+' and all their content?')) return;
  const r = await fetch('/api/admin/user/delete',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email}})}});
  const j = await r.json();
  if(j.success) location.reload(); else alert(j.error||'Failed');
}}
</script></body></html>"""


@app.route("/api/admin/ads/<int:ad_id>/approve", methods=["POST"])
def api_admin_approve_ad(ad_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json() or {}
    ad   = Ad.query.get_or_404(ad_id)
    ad.approved = data.get("status", 1)
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/payout/<int:payout_id>/mark-paid", methods=["POST"])
def api_admin_mark_paid(payout_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    pr = PayoutRequest.query.get_or_404(payout_id)
    pr.status = "paid"
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/user/ban", methods=["POST"])
def api_admin_ban_user():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    data  = request.get_json() or {}
    email = data.get("email", "").strip()
    val   = int(data.get("val", 1))
    user  = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user.banned = val
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/user/verify", methods=["POST"])
def api_admin_verify_user():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    data  = request.get_json() or {}
    email = data.get("email", "").strip()
    val   = int(data.get("val", 1))
    user  = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user.verified = val
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/user/delete", methods=["POST"])
def api_admin_delete_user():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    data  = request.get_json() or {}
    email = data.get("email", "").strip()
    if email == ADMIN_EMAIL:
        return jsonify({"error": "Cannot delete admin account"}), 403
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    # Delete all user content
    post_ids = [p.id for p in Post.query.filter_by(author_email=email).all()]
    if post_ids:
        UserReaction.query.filter(UserReaction.post_id.in_(post_ids)).delete(synchronize_session=False)
    Post.query.filter_by(author_email=email).delete()
    Follower.query.filter_by(user_email=email).delete()
    Follower.query.filter_by(follower_email=email).delete()
    Notification.query.filter_by(user_email=email).delete()
    PayoutRequest.query.filter_by(user_email=email).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True})


# ---------- Admin Management (API) ----------
@app.route("/api/admin/stats")
def api_admin_stats():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({
        "users":                  User.query.count(),
        "posts":                  Post.query.count(),
        "pending_payouts":        PayoutRequest.query.filter_by(status="pending").count(),
        "platform_earnings_hold": round(db.session.query(func.sum(User.earnings)).scalar() or 0, 2),
        "pending_ads":            Ad.query.filter_by(approved=0).count(),
    })


@app.route("/api/admin/users")
def api_admin_users():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    users = User.query.order_by(User.id.desc()).all()
    return jsonify([u.to_dict() for u in users])


@app.route("/api/admin/user/<int:user_id>/action", methods=["POST"])
def api_admin_user_action(user_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    data   = request.get_json() or {}
    action = data.get("action")  # verify | unverify | ban | unban
    user   = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if action == "verify":     user.verified = 1
    elif action == "unverify": user.verified = 0
    elif action == "ban":      user.banned = 1
    elif action == "unban":    user.banned = 0
    else: return jsonify({"error": "Unknown action"}), 400
    db.session.commit()
    return jsonify({"success": True, "message": f"User {action}ed successfully"})


# ---------- Payout Requests ----------
@app.route("/api/payout", methods=["POST"])
def api_payout_request():
    data      = request.get_json() or {}
    email     = data.get("email", "").strip()
    om_number = data.get("om_number", "").strip()
    amount    = float(data.get("amount", 0))
    if not email or not om_number or amount <= 0:
        return jsonify({"error": "Missing fields"}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    # Must be eligible: 1K followers + 4K watch hours
    followers = Follower.query.filter_by(user_email=email).count()
    if followers < 1000 or user.watch_hours < 4000:
        return jsonify({"error": f"You need 1,000 followers and 4,000 watch hours to request a payout. You have {followers} followers and {user.watch_hours} watch hours."}), 403
    if user.earnings < amount:
        return jsonify({"error": f"Insufficient balance. Your earnings are P{user.earnings:.2f}"}), 400
    user.earnings -= amount
    pr = PayoutRequest(user_email=email, user_name=user.name or "",
                       om_number=om_number, amount=amount, status="pending")
    db.session.add(pr)
    db.session.commit()
    return jsonify({"success": True, "message": f"Payout of P{amount:.2f} requested. You'll receive it on {om_number} within 24–48hrs."})


@app.route("/api/payout/history/<email>")
def api_payout_history(email):
    items = PayoutRequest.query.filter_by(user_email=email).order_by(PayoutRequest.id.desc()).all()
    return jsonify([r.to_dict() for r in items])




# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=True)
