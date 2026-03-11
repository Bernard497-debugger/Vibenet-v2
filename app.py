# app.py - VibeNet  (SQLAlchemy ORM  |  SQLite locally  |  PostgreSQL on Render)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, session, render_template_string

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

import base64
import requests as _requests

# ---------- Config ----------
APP_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["PORT"] = int(os.environ.get("PORT", 5000))
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")

# Orange Money Web Payment
OM_ENVIRONMENT  = os.environ.get("OM_ENVIRONMENT", "sandbox")   # "sandbox" or "production"
OM_CLIENT_ID    = os.environ.get("OM_CLIENT_ID", "")
OM_CLIENT_SECRET= os.environ.get("OM_CLIENT_SECRET", "")
OM_COUNTRY_CODE = os.environ.get("OM_COUNTRY_CODE", "BW")       # BW = Botswana
OM_CURRENCY     = os.environ.get("OM_CURRENCY", "BWP")          # Botswana Pula
# Merchant's own Orange Money account number (required by the API)
OM_MERCHANT_KEY = os.environ.get("OM_MERCHANT_KEY", "")         # notifyUrl secret key

OM_BASE_URL = (
    "https://api.orange.com/orange-money-webpay/dev/v1"
    if OM_ENVIRONMENT != "production"
    else "https://api.orange.com/orange-money-webpay/v1"
)
OM_TOKEN_URL = "https://api.orange.com/oauth/v3/token"

_om_token_cache = {"token": None, "expires_at": 0}

def _om_ok():
    return bool(OM_CLIENT_ID) and bool(OM_CLIENT_SECRET)

def _om_get_token():
    """Fetch (or return cached) OAuth2 Bearer token."""
    import time
    now = time.time()
    if _om_token_cache["token"] and now < _om_token_cache["expires_at"] - 30:
        return _om_token_cache["token"]
    creds   = base64.b64encode(f"{OM_CLIENT_ID}:{OM_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    r = _requests.post(OM_TOKEN_URL, headers=headers,
                       data="grant_type=client_credentials", timeout=15)
    j = r.json()
    token = j.get("access_token")
    expires_in = int(j.get("expires_in", 3600))
    _om_token_cache["token"]      = token
    _om_token_cache["expires_at"] = now + expires_in
    return token

def om_post(path: str, data: dict):
    token   = _om_get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    r = _requests.post(OM_BASE_URL + path, headers=headers,
                       json=data, timeout=15)
    return r.json(), r.status_code

def om_get(path: str):
    token   = _om_get_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = _requests.get(OM_BASE_URL + path, headers=headers, timeout=15)
    return r.json(), r.status_code

# Pricing (USD)
PRICE_VERIFIED_USD = 9.99   # $9.99 / month — VibeNet Verified badge
PRICE_AD_CPM_USD   = 5.00   # $5.00 per 1,000 impressions
PRICE_TIP_MIN_USD  = 1.00   # $1.00 minimum tip

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
    "pool_recycle": 280,   # keep Render/Postgres connections alive
    "pool_pre_ping": True,
}

os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)

db = SQLAlchemy(app)

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
    yc_customer       = db.Column(db.Text, default="")     # Yellow Card customer ref
    created_at        = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "profile_pic": self.profile_pic, "bio": self.bio,
            "watch_hours": self.watch_hours, "earnings": self.earnings,
            "verified": bool(self.verified),
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
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.Text)
    owner_email = db.Column(db.Text)
    budget      = db.Column(db.Float, default=0.0)
    impressions = db.Column(db.Integer, default=0)
    clicks      = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "owner_email": self.owner_email,
            "budget": self.budget, "impressions": self.impressions, "clicks": self.clicks,
        }


class Payment(db.Model):
    __tablename__ = "payments"
    id              = db.Column(db.Integer, primary_key=True)
    payer_email     = db.Column(db.Text, nullable=False)
    recipient_email = db.Column(db.Text, default="")   # empty = platform (verified/ads)
    amount_cents    = db.Column(db.Integer, nullable=False)
    currency        = db.Column(db.Text, default="usd")
    payment_type    = db.Column(db.Text, nullable=False)  # tip | ad | verified
    om_order_id     = db.Column(db.Text, default="")   # Orange Money order ID
    om_reference    = db.Column(db.Text, default="")   # Orange Money transaction reference
    status          = db.Column(db.Text, default="pending")  # pending | paid | failed
    metadata_json   = db.Column(db.Text, default="{}")
    created_at      = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "payer_email": self.payer_email,
            "recipient_email": self.recipient_email,
            "amount_cents": self.amount_cents,
            "payment_type": self.payment_type,
            "status": self.status,
            "created_at": self.created_at,
        }


# ---------- Utilities ----------
def now_ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# ---------- Create tables ----------
with app.app_context():
    db.create_all()

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

.pay-sections {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 8px;
}

.pay-section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 22px;
  display: flex;
  gap: 18px;
  align-items: flex-start;
  transition: border-color 0.2s;
}
.pay-section:hover { border-color: rgba(255,255,255,0.1); }

.verified-section {
  border-color: rgba(77,240,192,0.2);
  background: linear-gradient(135deg, rgba(77,240,192,0.04) 0%, var(--card) 60%);
}
.verified-section:hover { border-color: rgba(77,240,192,0.4); }

.pay-section-icon {
  font-size: 28px;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  background: var(--surface);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pay-section-body { flex: 1; min-width: 0; }

.pay-section-title {
  font-family: 'Syne', sans-serif;
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 4px;
}

.pay-section-desc {
  font-size: 13px;
  color: var(--muted2);
  line-height: 1.55;
  margin-bottom: 14px;
}

.pay-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.pay-amount-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.pay-currency {
  position: absolute;
  left: 10px;
  color: var(--muted2);
  font-size: 14px;
  pointer-events: none;
}
.pay-amount { padding-left: 22px !important; }

.pay-note {
  font-size: 12px;
  color: var(--muted2);
  margin-top: 6px;
}
.pay-note.success { color: var(--accent); }
.pay-note.error   { color: var(--danger); }

/* Orange Money uses inline form — no channel picker needed */

.pay-history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 8px;
  font-size: 13px;
}
.pay-history-type {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.pay-history-meta { color: var(--muted2); font-size: 12px; }
.pay-status-paid   { color: var(--accent); font-weight: 600; }
.pay-status-pending{ color: #f5c542; font-weight: 600; }
.pay-status-failed { color: var(--danger); font-weight: 600; }

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
            <button class="btn-primary" onclick="addPost()">Post →</button>
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

        <!-- Payment sections -->
        <div class="pay-sections">

          <!-- ① Tip a Creator -->
          <div class="pay-section">
            <div class="pay-section-icon">💸</div>
            <div class="pay-section-body">
              <div class="pay-section-title">Tip a Creator</div>
              <div class="pay-section-desc">Send a direct payment to any creator via PayPal or card. 90% goes directly to them.</div>
              <div class="pay-row" style="margin-bottom:10px">
                <input id="tipEmail" class="form-input" placeholder="Creator email" style="flex:1" />
                <div class="pay-amount-wrap">
                  <span class="pay-currency">$</span>
                  <input id="tipAmount" class="form-input pay-amount" type="number" min="1" placeholder="5" style="width:80px" />
                </div>
                <button class="btn-primary" onclick="openPayModal('tip')">Send Tip →</button>
              </div>
            </div>
          </div>

          <!-- ② Advertise -->
          <div class="pay-section">
            <div class="pay-section-icon">📣</div>
            <div class="pay-section-body">
              <div class="pay-section-title">Advertise on VibeNet</div>
              <div class="pay-section-desc">Place your campaign in front of thousands. Priced at $5 per 1,000 impressions.</div>
              <div class="pay-row" style="margin-bottom:10px">
                <input id="adPayTitle" class="form-input" placeholder="Campaign name" style="flex:1" />
                <div class="pay-amount-wrap">
                  <span class="pay-currency">$</span>
                  <input id="adPayBudget" class="form-input pay-amount" type="number" min="5" placeholder="50" style="width:80px" />
                </div>
                <button class="btn-primary" onclick="openPayModal('ad')">Launch Ad →</button>
              </div>
              <div id="adImpressionsPreview" class="pay-note"></div>
            </div>
          </div>

          <!-- ③ VibeNet Verified -->
          <div class="pay-section verified-section">
            <div class="pay-section-icon">✦</div>
            <div class="pay-section-body">
              <div class="pay-section-title">VibeNet Verified <span class="vbadge" style="width:20px;height:20px;font-size:12px">✦</span></div>
              <div class="pay-section-desc">Get the official verified badge on your profile and all posts. $9.99 / month, cancel anytime.</div>
              <div id="verifiedStatus" class="pay-note" style="margin-bottom:10px"></div>
              <button class="btn-primary" id="verifiedBtn" onclick="openPayModal('verified')">Get Verified — $9.99/mo →</button>
            </div>
          </div>

        </div>

        <!-- Payment history -->
        <div class="monet-section-title" style="margin-top:28px">Payment History</div>
        <div id="paymentHistory"></div>

        <!-- Legacy ad campaigns (free) -->
        <div class="monet-section-title" style="margin-top:20px">Active Campaigns</div>
        <div id="adsList"></div>
      </div>

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

<!-- Orange Money Payment Modal -->
<div id="payModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closePayModal()">
  <div class="modal-box" style="max-width:460px">
    <div class="modal-title" id="payModalTitle">Pay with Orange Money</div>
    <div id="payModalSummary" style="font-size:13px;color:var(--muted2);margin-bottom:16px;line-height:1.5"></div>

    <!-- Orange Money form -->
    <div id="om-step-form">
      <div style="background:var(--surface);border:1px solid rgba(255,140,0,0.25);border-radius:12px;padding:16px;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
          <span style="font-size:26px">🟠</span>
          <div>
            <div style="font-weight:700;font-size:14px">Orange Money — Botswana</div>
            <div style="font-size:12px;color:var(--muted2)">Pay via your Orange Money wallet using USSD OTP</div>
          </div>
        </div>
        <div class="form-label" style="margin-bottom:6px">Your Orange Money Number</div>
        <input id="om-phone" class="form-input" placeholder="+267XXXXXXXX" style="width:100%;margin-bottom:10px" />
        <div id="om-otp-row" style="display:none">
          <div style="background:rgba(255,140,0,0.08);border:1px solid rgba(255,140,0,0.3);border-radius:8px;padding:12px;font-size:13px;color:var(--text);margin-bottom:10px;line-height:1.5">
            📱 <strong>Dial <code>*144#</code> on your Orange phone</strong>, select <em>Generate OTP</em>, then enter the code below.
          </div>
          <div class="form-label" style="margin-bottom:6px">OTP Code</div>
          <input id="om-otp" class="form-input" placeholder="Enter OTP from USSD" style="width:100%;letter-spacing:3px;font-size:16px" maxlength="6" />
        </div>
      </div>
    </div>

    <!-- Not configured fallback -->
    <div id="om-not-configured" style="display:none;text-align:center;padding:24px;background:var(--surface);border-radius:12px;border:1px solid var(--border)">
      <div style="font-size:28px;margin-bottom:10px">🔧</div>
      <div style="font-weight:600;margin-bottom:6px">Orange Money not configured</div>
      <div style="font-size:13px;color:var(--muted2)">Set <code style="background:var(--card);padding:2px 6px;border-radius:4px">OM_CLIENT_ID</code> and <code style="background:var(--card);padding:2px 6px;border-radius:4px">OM_CLIENT_SECRET</code> environment variables.</div>
    </div>

    <div id="payModalError" class="pay-note error" style="margin-top:10px"></div>
    <div class="modal-footer">
      <button class="btn-ghost" onclick="closePayModal()">Cancel</button>
      <button class="btn-primary" id="paySubmitBtn" onclick="submitPayment()">Request OTP →</button>
    </div>
  </div>
</div>

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
  const fd = new FormData();
  fd.append('name', name); fd.append('email', email); fd.append('password', password);
  if(pic) fd.append('file', pic);
  const res = await fetch(API + '/signup', { method:'POST', body: fd });
  const j = await res.json();
  if(j.user){ currentUser = j.user; onLogin(); } else alert(j.error || j.message);
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
  window._vn_poll = setInterval(()=>{ if(currentUser){ loadNotifications(); loadMonetization(); } }, 5000);
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
  if(tab === 'notifications') loadNotifications();
  if(tab === 'monet'){ loadMonetization(); loadAds(); loadPaymentHistory(); checkVerifiedStatus(); }
}

async function uploadFile(file){
  const fd = new FormData(); fd.append('file', file);
  const res = await fetch(API + '/upload', {method:'POST', body: fd});
  const j = await res.json();
  return j.url || '';
}

async function addPost(){
  if(!currentUser){ alert('Please login first.'); return; }
  const text = byId('postText').value.trim();
  const fileEl = byId('fileUpload');
  let url = '';
  if(fileEl.files[0]) url = await uploadFile(fileEl.files[0]);
  if(!text && !url) return;
  await fetch(API + '/posts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    author_email: currentUser.email, author_name: currentUser.name, profile_pic: currentUser.profile_pic||'', text, file_url: url
  })});
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
    if(p.file_url.endsWith('.mp4')||p.file_url.endsWith('.webm')||p.file_url.includes('video')){
      const wrap = document.createElement('div'); wrap.className='video-wrap';
      const v = document.createElement('video');
      v.src = p.file_url; v.controls = true; v.muted = true; v.loop = false;
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
      const im=document.createElement('img'); im.src=p.file_url; media.append(im);
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

async function loadFeed(){
  const res = await fetch(API+'/posts');
  const list = await res.json();
  const feed = byId('feedList'); feed.innerHTML='';
  if(!list.length){
    feed.innerHTML='<div class="empty-state"><div class="empty-icon">📭</div><p>No posts yet. Be the first to share something!</p></div>';
    return;
  }
  list.forEach(p=>feed.appendChild(createPostElement(p)));
  observeVideos();
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

async function loadNotifications(){
  if(!currentUser) return;
  const r=await fetch(API+'/notifications/'+encodeURIComponent(currentUser.email));
  const list=await r.json();
  const el=byId('notifList'); el.innerHTML='';
  const countEl=byId('notifCount');
  if(list.length){ countEl.style.display='inline-block'; countEl.textContent=list.length; } else countEl.style.display='none';
  if(!list.length){
    el.innerHTML='<div class="empty-state" style="padding:32px"><div class="empty-icon">🎉</div><p>All caught up!</p></div>';
    return;
  }
  list.forEach(n=>{
    const d=document.createElement('div'); d.className='notif-item';
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
  const r=await fetch(API+'/monetization/'+encodeURIComponent(currentUser.email));
  const j=await r.json();
  byId('monFollowers').textContent=j.followers;
  byId('monWatch').textContent=j.watch_hours;
  byId('monEarnings').textContent=(j.earnings||0).toFixed(2);
  byId('monStatus').textContent=j.followers>=1000&&j.watch_hours>=4000?'✅ Eligible':'⏳ Growing';
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


// ── Orange Money Payment helpers ─────────────────────────────────────────
let _payModalType  = null;
let _omOrderId     = null;   // Order ID from step 1 — needed for OTP confirmation
let _omOtpPending  = false;  // true after order created, waiting for OTP

async function openPayModal(type){
  if(!currentUser){ alert('Login first'); return; }
  _payModalType = type;
  _omOrderId    = null;
  _omOtpPending = false;

  const titles = { tip:'Tip a Creator', ad:'Launch Ad Campaign', verified:'Get VibeNet Verified' };
  const summaries = {
    tip:      () => { const e=byId('tipEmail').value.trim(); const a=byId('tipAmount').value||'?'; return `Sending BWP equivalent of $${a} to <strong>${escapeHtml(e||'enter email above')}</strong>. 90% goes to the creator.`; },
    ad:       () => { const t=byId('adPayTitle').value.trim(); const b=byId('adPayBudget').value||'?'; const i=Math.floor((parseFloat(b)||0)/5*1000); return `Campaign: <strong>${escapeHtml(t||'enter name above')}</strong> · $${b} · ~${i.toLocaleString()} impressions`; },
    verified: () => '<strong>VibeNet Verified badge</strong> — BWP 109/month (~$9.99). Cancel anytime.',
  };

  byId('payModalTitle').textContent = titles[type] || 'Pay with Orange Money';
  byId('payModalSummary').innerHTML = summaries[type] ? summaries[type]() : '';
  byId('payModalError').textContent = '';
  byId('om-otp-row').style.display  = 'none';
  byId('om-phone').value            = '';
  byId('payModal').style.display    = 'flex';
  byId('om-step-form').style.display      = 'block';
  byId('om-not-configured').style.display = 'none';
  byId('paySubmitBtn').textContent  = 'Request OTP →';
  byId('paySubmitBtn').style.display = 'inline-flex';

  // Quick check if configured
  const r = await fetch(API+'/pay/status');
  const j = await r.json();
  if(!j.configured){
    byId('om-step-form').style.display      = 'none';
    byId('om-not-configured').style.display = 'block';
    byId('paySubmitBtn').style.display      = 'none';
  }
}

async function submitPayment(){
  const errEl     = byId('payModalError');
  const submitBtn = byId('paySubmitBtn');
  errEl.textContent = '';

  const phone = byId('om-phone').value.trim();
  if(!phone){ errEl.textContent='Enter your Orange Money number (+267XXXXXXXX)'; return; }

  if(!_omOtpPending){
    // ── Step 1: Create payment order → triggers USSD OTP on user's phone ──
    submitBtn.textContent = 'Sending OTP...';
    submitBtn.disabled    = true;

    let body = { payer: currentUser.email, phone };
    if(_payModalType === 'tip'){
      const email  = byId('tipEmail').value.trim();
      const amount = parseFloat(byId('tipAmount').value || 0);
      if(!email || amount < 1){ errEl.textContent='Enter creator email and amount ($1 min)'; submitBtn.textContent='Request OTP →'; submitBtn.disabled=false; return; }
      body = { ...body, recipient: email, amount_usd: amount };
    } else if(_payModalType === 'ad'){
      const title  = byId('adPayTitle').value.trim();
      const budget = parseFloat(byId('adPayBudget').value || 0);
      if(!title || budget < 5){ errEl.textContent='Enter campaign name and budget ($5 min)'; submitBtn.textContent='Request OTP →'; submitBtn.disabled=false; return; }
      body = { ...body, title, budget_usd: budget };
    }

    const initRoute = { tip:'/pay/tip', ad:'/pay/ad', verified:'/pay/verified' }[_payModalType];
    const res = await fetch(API+initRoute, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const j   = await res.json();

    submitBtn.textContent = 'Request OTP →';
    submitBtn.disabled    = false;

    if(j.already_verified){ closePayModal(); alert('You are already verified!'); return; }

    if(j.order_id || j.id){
      _omOrderId    = j.order_id || j.id;
      _omOtpPending = true;
      byId('om-otp-row').style.display  = 'block';
      byId('om-phone').disabled         = true;
      submitBtn.textContent = 'Confirm Payment →';
      errEl.style.color = 'var(--accent)';
      errEl.textContent = '✓ OTP sent! Dial *144# → Generate OTP, then enter code above.';
    } else {
      errEl.style.color = 'var(--danger)';
      errEl.textContent = j.error || 'Could not initiate payment.';
    }

  } else {
    // ── Step 2: Confirm OTP ────────────────────────────────────────────────
    const otp = byId('om-otp').value.trim();
    if(!otp){ errEl.textContent='Enter the OTP from your phone'; return; }
    submitBtn.textContent = 'Confirming...';
    submitBtn.disabled    = true;

    const res = await fetch(API+'/pay/confirm', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ order_id: _omOrderId, otp, payer: currentUser.email })
    });
    const j = await res.json();
    submitBtn.textContent = 'Confirm Payment →';
    submitBtn.disabled    = false;

    if(j.success){
      closePayModal();
      await loadPaymentHistory();
      await loadMonetization();
      if(_payModalType === 'verified'){ currentUser.verified = true; checkVerifiedStatus(); }
      const msgs = {
        tip:      'Tip sent! The creator has been notified.',
        ad:       `Ad campaign is live! (~${j.impressions||0} impressions)`,
        verified: 'You are now VibeNet Verified! ✦',
      };
      alert(msgs[_payModalType] || 'Payment successful!');
    } else {
      errEl.style.color = 'var(--danger)';
      errEl.textContent = j.error || 'OTP confirmation failed. Please try again.';
    }
  }
}

function closePayModal(){
  byId('payModal').style.display = 'none';
  _payModalType  = null;
  _omOrderId     = null;
  _omOtpPending  = false;
  byId('om-phone').disabled = false;
}

async function loadPaymentHistory(){
  if(!currentUser) return;
  const r = await fetch(API+'/pay/history?email='+encodeURIComponent(currentUser.email));
  const list = await r.json();
  const el = byId('paymentHistory'); el.innerHTML = '';
  if(!list.length){
    el.innerHTML = '<div class="empty-state" style="padding:24px"><div class="empty-icon">🧾</div><p>No payments yet.</p></div>';
    return;
  }
  const icons = { tip:'💸', ad:'📣', verified:'✦' };
  const labels = { tip:'Tip sent', ad:'Ad campaign', verified:'Verified badge' };
  list.forEach(p=>{
    const d = document.createElement('div'); d.className='pay-history-item';
    const statusCls = p.status==='paid'?'pay-status-paid': p.status==='pending'?'pay-status-pending':'pay-status-failed';
    d.innerHTML = `
      <div>
        <div class="pay-history-type">${icons[p.payment_type]||'💳'} ${labels[p.payment_type]||p.payment_type}
          ${p.recipient_email ? '<span style="color:var(--muted2);font-weight:400"> → '+escapeHtml(p.recipient_email)+'</span>' : ''}
        </div>
        <div class="pay-history-meta">${escapeHtml(p.created_at)}</div>
      </div>
      <div style="text-align:right">
        <div style="font-weight:700">$${(p.amount_cents/100).toFixed(2)}</div>
        <div class="${statusCls}">${p.status}</div>
      </div>`;
    el.appendChild(d);
  });
}

// Show impressions preview when typing ad budget
document.addEventListener('DOMContentLoaded', ()=>{
  const adBudgetEl = document.getElementById('adPayBudget');
  const previewEl  = document.getElementById('adImpressionsPreview');
  if(adBudgetEl && previewEl){
    adBudgetEl.addEventListener('input', ()=>{
      const v = parseFloat(adBudgetEl.value||0);
      if(v >= 5){
        const imps = Math.floor((v / 5) * 1000);
        previewEl.textContent = `Est. ${imps.toLocaleString()} impressions`;
        previewEl.className = 'pay-note success';
      } else {
        previewEl.textContent = '$5 minimum';
        previewEl.className = 'pay-note error';
      }
    });
  }
});

// Update verified button state
async function checkVerifiedStatus(){
  if(!currentUser) return;
  const statusEl = byId('verifiedStatus');
  const btn      = byId('verifiedBtn');
  if(!statusEl || !btn) return;
  if(currentUser.verified){
    statusEl.textContent = 'You are verified ✦';
    statusEl.className   = 'pay-note success';
    btn.textContent      = 'Already Verified';
    btn.disabled         = true;
    btn.style.opacity    = '0.5';
  }
}

async function refreshAll(){ await loadFeed(); await loadNotifications(); await loadProfilePosts(); await loadMonetization(); await loadAds(); await loadPaymentHistory(); await checkVerifiedStatus(); }
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
    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        return jsonify({"error": "email + password required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists"}), 400

    profile_pic = ""
    if "file" in request.files:
        f = request.files["file"]
        if f and f.filename:
            fn = f"{uuid.uuid4().hex}_{f.filename}"
            f.save(os.path.join(UPLOAD_DIR, fn))
            profile_pic = f"/uploads/{fn}"

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
    fn = f"{uuid.uuid4().hex}_{f.filename}"
    f.save(os.path.join(UPLOAD_DIR, fn))
    return jsonify({"url": f"/uploads/{fn}"})


# ---------- Posts ----------
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    if request.method == "GET":
        posts = Post.query.order_by(Post.id.desc()).all()
        # Build a verified lookup map
        emails = list({p.author_email for p in posts})
        verified_map = {}
        if emails:
            users = User.query.filter(User.email.in_(emails)).all()
            verified_map = {u.email: bool(u.verified) for u in users}
        return jsonify([p.to_dict(author_verified=verified_map.get(p.author_email, False)) for p in posts])

    data = request.get_json() or {}
    post = Post(
        author_email=data.get("author_email"),
        author_name=data.get("author_name"),
        profile_pic=data.get("profile_pic", ""),
        text=data.get("text", ""),
        file_url=data.get("file_url", ""),
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict())


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
    return jsonify([n.to_dict() for n in notifs])


# ---------- Monetization / Profile ----------
@app.route("/api/monetization/<email>")
def api_monetization_get(email):
    followers = Follower.query.filter_by(user_email=email).count()
    user      = User.query.filter_by(email=email).first()
    if user:
        return jsonify({"followers": followers, "watch_hours": user.watch_hours, "earnings": user.earnings})
    return jsonify({"followers": 0, "watch_hours": 0, "earnings": 0})


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
        ad   = Ad(title=data.get("title"), owner_email=data.get("owner"), budget=data.get("budget", 0))
        db.session.add(ad)
        db.session.commit()
        return jsonify({"message": "Ad created"})
    ads = Ad.query.order_by(Ad.id.desc()).all()
    return jsonify([a.to_dict() for a in ads])


@app.route("/api/ads/impression", methods=["POST"])
def api_ads_impression():
    return jsonify({"success": True})




# ══════════════════════════════════════════════════════════════════════════
# PAYMENT GATEWAY  (Yellow Card — Africa fiat on/off ramps)
# ══════════════════════════════════════════════════════════════════════════

def _apply_side_effects(payment):
    """Run post-payment actions once a payment is confirmed."""
    pay_type = payment.payment_type
    if pay_type == "tip":
        recipient = User.query.filter_by(email=payment.recipient_email).first()
        if recipient:
            recipient.earnings += round(payment.amount_cents * 0.9 / 100, 2)
            db.session.add(Notification(user_email=recipient.email,
                text=f"You received a ${payment.amount_cents/100:.2f} tip!"))
            db.session.commit()
    elif pay_type == "ad":
        meta  = _json.loads(payment.metadata_json or "{}")
        title = meta.get("title", "Ad campaign")
        imps  = meta.get("impressions", 0)
        db.session.add(Ad(title=title, owner_email=payment.payer_email,
                          budget=payment.amount_cents / 100))
        db.session.add(Notification(user_email=payment.payer_email,
            text=f"Ad '{title}' is live! (~{imps:,} impressions)"))
        db.session.commit()
    elif pay_type == "verified":
        user = User.query.filter_by(email=payment.payer_email).first()
        if user:
            user.verified = 1
            db.session.add(Notification(user_email=payment.payer_email,
                text="Your VibeNet Verified badge is now active! ✦"))
            db.session.commit()


# ── Gateway status check ─────────────────────────────────────────────────
@app.route("/api/pay/status")
def api_pay_status():
    return jsonify({"configured": _om_ok(),
                    "environment": OM_ENVIRONMENT,
                    "country": OM_COUNTRY_CODE,
                    "currency": OM_CURRENCY})


def _om_create_order(amount_usd, phone, reference, description):
    """Create an Orange Money payment order. Returns (order_id, error_msg)."""
    # Orange Money uses local currency — convert USD → BWP at a fixed rate
    # In production you should use a live FX rate. 1 USD ≈ 13.5 BWP (2025)
    BWP_RATE   = float(os.environ.get("BWP_RATE", "13.5"))
    amount_bwp = round(amount_usd * BWP_RATE, 2)
    notify_url = os.environ.get("OM_NOTIFY_URL",
                                "https://yourdomain.com/api/pay/webhook")
    payload = {
        "merchant_key":  OM_MERCHANT_KEY or OM_CLIENT_ID,
        "currency":      OM_CURRENCY,
        "order_id":      reference,
        "amount":        str(amount_bwp),
        "return_url":    notify_url,
        "cancel_url":    notify_url,
        "notif_url":     notify_url,
        "lang":          "en",
        "reference":     description,
        "msisdn":        phone,
    }
    result, status = om_post("/webpayment", payload)
    if status in (200, 201):
        order_id  = result.get("pay_token") or result.get("order_id") or result.get("id", "")
        return order_id, None
    return None, result.get("message", result.get("error", "Could not create order"))


# ── Tip a creator ─────────────────────────────────────────────────────────
@app.route("/api/pay/tip", methods=["POST"])
def api_pay_tip():
    if not _om_ok():
        return jsonify({"error": "Orange Money not configured. Set OM_CLIENT_ID and OM_CLIENT_SECRET."}), 503
    data       = request.get_json() or {}
    payer      = data.get("payer", "")
    recipient  = data.get("recipient", "").strip().lower()
    amount_usd = float(data.get("amount_usd", 0))
    phone      = data.get("phone", "")
    if amount_usd < PRICE_TIP_MIN_USD:
        return jsonify({"error": f"Minimum tip is ${PRICE_TIP_MIN_USD:.2f}"}), 400
    if not phone:
        return jsonify({"error": "Orange Money phone number required"}), 400
    recipient_user = User.query.filter_by(email=recipient).first()
    if not recipient_user:
        return jsonify({"error": "Creator not found"}), 404
    amount_cents = int(round(amount_usd * 100))
    payment = Payment(payer_email=payer, recipient_email=recipient,
        amount_cents=amount_cents, payment_type="tip",
        metadata_json=_json.dumps({"recipient_name": recipient_user.name or recipient,
                                    "phone": phone}))
    db.session.add(payment); db.session.commit()
    order_id, err = _om_create_order(amount_usd, phone,
        f"tip-{payment.id}", f"VibeNet tip to {recipient_user.name or recipient}")
    if err:
        payment.status = "failed"; db.session.commit()
        return jsonify({"error": err}), 402
    payment.om_order_id = order_id; db.session.commit()
    return jsonify({"order_id": order_id, "id": order_id})


# ── Advertise ─────────────────────────────────────────────────────────────
@app.route("/api/pay/ad", methods=["POST"])
def api_pay_ad():
    if not _om_ok():
        return jsonify({"error": "Orange Money not configured."}), 503
    data       = request.get_json() or {}
    payer      = data.get("payer", "")
    title      = data.get("title", "").strip()
    budget_usd = float(data.get("budget_usd", 0))
    phone      = data.get("phone", "")
    if budget_usd < PRICE_AD_CPM_USD:
        return jsonify({"error": f"Minimum ad budget is ${PRICE_AD_CPM_USD:.2f}"}), 400
    if not title:
        return jsonify({"error": "Campaign title required"}), 400
    if not phone:
        return jsonify({"error": "Orange Money phone number required"}), 400
    amount_cents    = int(round(budget_usd * 100))
    est_impressions = int((budget_usd / PRICE_AD_CPM_USD) * 1000)
    payment = Payment(payer_email=payer, recipient_email="",
        amount_cents=amount_cents, payment_type="ad",
        metadata_json=_json.dumps({"title": title, "impressions": est_impressions,
                                    "phone": phone}))
    db.session.add(payment); db.session.commit()
    order_id, err = _om_create_order(budget_usd, phone,
        f"ad-{payment.id}", f"VibeNet Ad: {title}")
    if err:
        payment.status = "failed"; db.session.commit()
        return jsonify({"error": err}), 402
    payment.om_order_id = order_id; db.session.commit()
    return jsonify({"order_id": order_id, "id": order_id, "impressions": est_impressions})


# ── VibeNet Verified ──────────────────────────────────────────────────────
@app.route("/api/pay/verified", methods=["POST"])
def api_pay_verified():
    if not _om_ok():
        return jsonify({"error": "Orange Money not configured."}), 503
    data  = request.get_json() or {}
    payer = data.get("payer", "")
    phone = data.get("phone", "")
    user  = User.query.filter_by(email=payer).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.verified:
        return jsonify({"already_verified": True})
    if not phone:
        return jsonify({"error": "Orange Money phone number required"}), 400
    payment = Payment(payer_email=payer, recipient_email="",
        amount_cents=int(PRICE_VERIFIED_USD * 100), payment_type="verified",
        metadata_json=_json.dumps({"phone": phone}))
    db.session.add(payment); db.session.commit()
    order_id, err = _om_create_order(PRICE_VERIFIED_USD, phone,
        f"verified-{payment.id}", "VibeNet Verified Badge")
    if err:
        payment.status = "failed"; db.session.commit()
        return jsonify({"error": err}), 402
    payment.om_order_id = order_id; db.session.commit()
    return jsonify({"order_id": order_id, "id": order_id})


# ── OTP Confirmation ──────────────────────────────────────────────────────
@app.route("/api/pay/confirm", methods=["POST"])
def api_pay_confirm():
    """Submit the OTP the user got via USSD to finalise the payment."""
    if not _om_ok():
        return jsonify({"error": "Orange Money not configured."}), 503
    data     = request.get_json() or {}
    order_id = data.get("order_id", "")
    otp      = data.get("otp", "").strip()
    payer    = data.get("payer", "")
    if not order_id or not otp:
        return jsonify({"error": "order_id and otp are required"}), 400
    payment = Payment.query.filter_by(om_order_id=order_id, payer_email=payer).first()
    if not payment:
        return jsonify({"error": "Payment not found"}), 404
    # Send OTP to Orange Money to complete the transaction
    result, status = om_post("/webpayment", {
        "pay_token":     order_id,
        "otp_code":      otp,
        "merchant_key":  OM_MERCHANT_KEY or OM_CLIENT_ID,
    })
    if status in (200, 201) and result.get("status") in ("SUCCESS", "SUCCESSFULL", "success", "200"):
        payment.status       = "paid"
        payment.om_reference = result.get("txn_id", result.get("reference", ""))
        db.session.commit()
        _apply_side_effects(payment)
        meta = _json.loads(payment.metadata_json or "{}")
        return jsonify({"success": True,
                        "impressions": meta.get("impressions", 0),
                        "reference": payment.om_reference})
    else:
        msg = result.get("message", result.get("error", "OTP confirmation failed"))
        return jsonify({"error": msg}), 402


# ── Webhook (Orange Money notif_url callback) ─────────────────────────────
@app.route("/api/pay/webhook", methods=["POST"])
def api_pay_webhook():
    payload  = request.get_json(force=True) or {}
    status   = (payload.get("status") or payload.get("txn_status") or "").upper()
    order_id = payload.get("order_id") or payload.get("pay_token", "")
    if order_id:
        payment = Payment.query.filter_by(om_order_id=order_id).first()
        if payment:
            if status in ("SUCCESS", "SUCCESSFULL"):
                payment.status       = "paid"
                payment.om_reference = payload.get("txn_id", "")
                db.session.commit()
                _apply_side_effects(payment)
            elif status in ("FAILED", "CANCELLED", "EXPIRED"):
                payment.status = "failed"
                db.session.commit()
    return jsonify({"received": True})


# ── Payment history ───────────────────────────────────────────────────────
@app.route("/api/pay/history")
def api_pay_history():
    email    = request.args.get("email", "")
    payments = Payment.query.filter_by(payer_email=email).order_by(Payment.id.desc()).limit(50).all()
    return jsonify([p.to_dict() for p in payments])


# ---------- Payment result pages ----------
@app.route("/payment/success")
def payment_success():
    ptype = request.args.get("type", "payment")
    msgs  = {
        "tip":      "Your tip was sent successfully!",
        "ad":       "Your ad campaign is now live!",
        "verified": "You are now VibeNet Verified! ✦",
    }
    msg = msgs.get(ptype, "Payment successful!")
    return render_template_string("""
<!doctype html><html><head><meta charset=utf-8>
<title>Payment Success</title>
<style>
  body{background:#060910;color:#E8F0FF;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
  .box{text-align:center;padding:48px;background:#101520;border-radius:20px;border:1px solid rgba(77,240,192,0.3)}
  h1{color:#4DF0C0;font-size:2rem;margin-bottom:12px}
  p{color:#8899B4;margin-bottom:24px}
  a{color:#4DF0C0;text-decoration:none;font-weight:600}
</style></head><body>
<div class="box"><h1>✦ {{ msg }}</h1><p>Your payment has been processed.</p><a href="/">← Back to VibeNet</a></div>
</body></html>""", msg=msg)


@app.route("/payment/cancel")
def payment_cancel():
    return render_template_string("""
<!doctype html><html><head><meta charset=utf-8>
<title>Payment Cancelled</title>
<style>
  body{background:#060910;color:#E8F0FF;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
  .box{text-align:center;padding:48px;background:#101520;border-radius:20px;border:1px solid rgba(240,106,77,0.3)}
  h1{color:#F06A4D;font-size:2rem;margin-bottom:12px}
  p{color:#8899B4;margin-bottom:24px}
  a{color:#4DF0C0;text-decoration:none;font-weight:600}
</style></head><body>
<div class="box"><h1>Payment Cancelled</h1><p>No charge was made.</p><a href="/">← Back to VibeNet</a></div>
</body></html>""")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=True)
