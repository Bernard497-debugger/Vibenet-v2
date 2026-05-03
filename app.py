# app.py - VibeNet (SQLAlchemy ORM | SQLite locally | PostgreSQL on Render | psycopg3)
import os
import uuid
import datetime
import json as _json
from flask import Flask, request, jsonify, send_from_directory, session, render_template_string, redirect

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import requests

# ---------- Supabase Storage Config ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "vibenet")

def _supabase_ok():
    return bool(SUPABASE_URL and SUPABASE_KEY)

# ---------- Config ----------
APP_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["PORT"] = int(os.environ.get("PORT", 5000))
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")

# SQLAlchemy: fix DATABASE_URL for psycopg3
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Convert legacy Render URL to psycopg3 format
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql+psycopg://"):
        pass  # Already correct
    else:
        DATABASE_URL = f"postgresql+psycopg://{DATABASE_URL.replace('postgresql://', '')}"

app.config["SQLALCHEMY_DATABASE_URI"] = (
    DATABASE_URL if DATABASE_URL
    else f"sqlite:///{os.path.join(APP_DIR, 'data', 'vibenet.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Connection pool settings - works with both SQLite and PostgreSQL
if DATABASE_URL and "sqlite" not in DATABASE_URL:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "connect_args": {
            "connect_timeout": 30,
            "application_name": "vibenet_app",
        }
    }
else:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)

db = SQLAlchemy(app)

# ---------- Global Error Handler ----------
@app.errorhandler(Exception)
def handle_error(error):
    """Catch all unhandled exceptions and return JSON"""
    import traceback
    print(f"Unhandled error: {error}")
    traceback.print_exc()
    return jsonify({"error": str(error), "type": type(error).__name__}), 500

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
    verified          = db.Column(db.Integer, default=0)
    banned            = db.Column(db.Integer, default=0)
    last_active       = db.Column(db.Text, default="")
    created_at        = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "profile_pic": self.profile_pic, "bio": self.bio,
            "watch_hours": self.watch_hours, "earnings": self.earnings,
            "verified": bool(self.verified),
            "banned": bool(self.banned),
            "last_active": self.last_active or "",
        }


class Follower(db.Model):
    __tablename__ = "followers"
    id             = db.Column(db.Integer, primary_key=True)
    user_email     = db.Column(db.Text, nullable=False)
    follower_email = db.Column(db.Text, nullable=False)
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
    file_mime      = db.Column(db.Text, default="")
    thumbnail_url  = db.Column(db.Text, default="")
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
            "text": self.text, "file_url": self.file_url, "file_mime": self.file_mime or "",
            "thumbnail_url": self.thumbnail_url or "", "timestamp": self.timestamp,
            "reactions": self.reactions(), "comments_count": self.comments_count,
            "user_reaction": user_reaction, "author_verified": author_verified,
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
    image_url        = db.Column(db.Text, default="")
    impressions      = db.Column(db.Integer, default=0)
    clicks           = db.Column(db.Integer, default=0)
    approved         = db.Column(db.Integer, default=0)
    expiry_date      = db.Column(db.Text, default="")
    created_at       = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "owner_email": self.owner_email,
            "whatsapp_number": self.whatsapp_number or "",
            "budget": self.budget, "image_url": self.image_url or "", "impressions": self.impressions, "clicks": self.clicks,
            "approved": self.approved, "expiry_date": self.expiry_date or "",
        }


class PayoutRequest(db.Model):
    __tablename__ = "payout_requests"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    user_name  = db.Column(db.Text, default="")
    om_number  = db.Column(db.Text, nullable=False)
    amount     = db.Column(db.Float, nullable=False)
    status     = db.Column(db.Text, default="pending")
    created_at = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "user_email": self.user_email, "user_name": self.user_name,
            "om_number": self.om_number, "amount": self.amount,
            "status": self.status, "created_at": self.created_at,
        }


class MediaFile(db.Model):
    __tablename__ = "media_files"
    id   = db.Column(db.String(32), primary_key=True)
    mime = db.Column(db.Text, default="application/octet-stream")
    data = db.Column(db.Text, nullable=False)


class Comment(db.Model):
    __tablename__ = "comments"
    id           = db.Column(db.Integer, primary_key=True)
    post_id      = db.Column(db.Integer, nullable=False)
    author_email = db.Column(db.Text, nullable=False)
    author_name  = db.Column(db.Text, default="")
    profile_pic  = db.Column(db.Text, default="")
    text         = db.Column(db.Text, nullable=False)
    timestamp    = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "post_id": self.post_id,
            "author_email": self.author_email, "author_name": self.author_name,
            "profile_pic": self.profile_pic, "text": self.text,
            "timestamp": self.timestamp,
        }


class Report(db.Model):
    __tablename__ = "reports"
    id           = db.Column(db.Integer, primary_key=True)
    reporter_email = db.Column(db.Text, nullable=False)
    target_type  = db.Column(db.Text, nullable=False)
    target_id    = db.Column(db.Integer, nullable=False)
    reason       = db.Column(db.Text, nullable=False)
    status       = db.Column(db.Text, default="pending")
    created_at   = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "reporter_email": self.reporter_email,
            "target_type": self.target_type, "target_id": self.target_id,
            "reason": self.reason, "status": self.status, "created_at": self.created_at,
        }


class VerifiedRequest(db.Model):
    __tablename__ = "verified_requests"
    id         = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.Text, nullable=False)
    user_name  = db.Column(db.Text, default="")
    status     = db.Column(db.Text, default="pending")
    created_at = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "user_email": self.user_email, "user_name": self.user_name,
            "status": self.status, "created_at": self.created_at,
        }


# ---------- Create tables ----------
with app.app_context():
    try:
        db.create_all()
        print("✅ Database tables created/verified OK", flush=True)
    except Exception as e:
        print(f"⚠️  DB init warning (non-fatal): {e}", flush=True)
    
    # Run migrations for new columns
    migrations = [
        "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_active TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN approved INTEGER DEFAULT 0",
        "ALTER TABLE ads ADD COLUMN whatsapp_number TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN expiry_date TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN image_url TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN user_email TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN user_name TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN om_number TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN amount FLOAT DEFAULT 0",
        "ALTER TABLE payout_requests ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE payout_requests ADD COLUMN created_at TEXT DEFAULT ''",
        "ALTER TABLE posts ADD COLUMN file_mime TEXT DEFAULT ''",
        "ALTER TABLE posts ADD COLUMN comments_count INTEGER DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN thumbnail_url TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

# ---------- Health check ----------
@app.route("/health")
def health():
    return "OK", 200


# ---------- Static uploads ----------
@app.route("/media/<media_id>")
def serve_media(media_id):
    from flask import Response
    import base64
    mf = MediaFile.query.get(media_id)
    if not mf: return "Not found", 404
    return Response(base64.b64decode(mf.data), mimetype=mf.mime)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- Frontend ----------
# [INSERT YOUR HTML TEMPLATES HERE - PRIVACY_HTML, TERMS_HTML, HTML]
# (Keep them exactly as in your original file)

PRIVACY_HTML = r"""<!doctype html>
... [keep your existing HTML templates] ...
"""

TERMS_HTML = r"""<!doctype html>
... [keep your existing HTML templates] ...
"""

HTML = r"""
... [keep your existing HTML, it's unchanged] ...
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/privacy")
def privacy_page():
    return render_template_string(PRIVACY_HTML)

@app.route("/terms")
def terms_page():
    return render_template_string(TERMS_HTML)

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


# ---------- Upload (unchanged) ----------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "No filename"}), 400
        data = f.read()
        if len(data) > 100 * 1024 * 1024:
            return jsonify({"error": "File too large (max 100MB)"}), 400
        mime = f.mimetype or "application/octet-stream"
        
        print(f"📥 Upload: {f.filename} ({len(data)} bytes, mime: {mime})", flush=True)
        
        is_video = mime.startswith('video/') or f.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
        
        # Save thumbnail if provided
        thumbnail_url = ""
        if "thumbnail" in request.files:
            try:
                thumb = request.files["thumbnail"]
                thumb_data = thumb.read()
                thumb_id = uuid.uuid4().hex
                thumb_path = f"posts/{thumb_id}.jpg"
                
                headers = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "image/jpeg",
                }
                thumb_url_upload = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{thumb_path}"
                
                print(f"📸 Uploading thumbnail...", flush=True)
                thumb_resp = requests.post(thumb_url_upload, data=thumb_data, headers=headers, timeout=30)
                print(f"📸 Thumbnail response: {thumb_resp.status_code}", flush=True)
                
                if thumb_resp.status_code in (200, 201):
                    thumbnail_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{thumb_path}"
                    print(f"✅ Thumbnail saved: {thumbnail_url}", flush=True)
            except Exception as e:
                print(f"⚠️ Thumbnail failed (continuing): {e}", flush=True)

        # Upload to Supabase
        try:
            file_id = uuid.uuid4().hex
            file_ext = os.path.splitext(f.filename)[1] or ".bin"
            
            if is_video and file_ext.lower() not in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                file_ext = '.mp4'
            
            file_path = f"posts/{file_id}{file_ext}"
            
            headers = {
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": mime,
            }
            upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{file_path}"
            
            print(f"📤 Uploading to Supabase: {file_path}", flush=True)
            print(f"📤 Upload URL: {upload_url}", flush=True)
            
            response = requests.post(upload_url, data=data, headers=headers, timeout=120)
            
            print(f"📡 Response: {response.status_code}", flush=True)
            if response.status_code not in (200, 201):
                print(f"❌ Supabase error: {response.text[:200]}", flush=True)
            
            if response.status_code in (200, 201):
                public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{file_path}"
                print(f"✅ Upload OK: {public_url}", flush=True)
                return jsonify({"url": public_url, "thumbnail": thumbnail_url})
            else:
                return jsonify({"error": f"Supabase: {response.status_code}"}), 503
                
        except Exception as e:
            print(f"❌ Upload error: {e}", flush=True)
            return jsonify({"error": str(e)[:100]}), 500

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        return jsonify({"error": str(e)[:100]}), 500


@app.route("/api/test-supabase", methods=["GET"])
def api_test_supabase():
    """Quick diagnostic for Supabase Storage config."""
    return jsonify({
        "supabase_ok": _supabase_ok(),
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_key_set": bool(SUPABASE_KEY),
        "bucket": SUPABASE_BUCKET,
    })


# ---------- Posts ----------
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    if request.method == "GET":
        page  = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
        offset = (page - 1) * limit
        total = Post.query.count()
        posts = Post.query.order_by(Post.id.desc()).offset(offset).limit(limit).all()
        emails = list({p.author_email for p in posts})
        verified_map = {}
        if emails:
            users = User.query.filter(User.email.in_(emails)).all()
            verified_map = {u.email: bool(u.verified) for u in users}
        return jsonify({
            "posts": [p.to_dict(author_verified=verified_map.get(p.author_email, False)) for p in posts],
            "page": page,
            "has_more": (offset + limit) < total
        })

    data = request.get_json() or {}
    
    author_email = data.get("author_email", "").strip().lower()
    if not author_email:
        return jsonify({"error": "author_email required"}), 400
    
    user = User.query.filter_by(email=author_email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    if user.banned:
        return jsonify({"error": "Account banned"}), 403
    
    text = data.get("text", "").strip()
    file_url = data.get("file_url", "").strip()
    
    if not text and not file_url:
        return jsonify({"error": "Post must have text or file"}), 400
    
    post = Post(
        author_email=author_email,
        author_name=data.get("author_name", user.name),
        profile_pic=data.get("profile_pic", user.profile_pic),
        text=text,
        file_url=file_url,
        file_mime=data.get("file_mime", ""),
        thumbnail_url=data.get("thumbnail_url", ""),
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict()), 201


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
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f     = request.files["file"]
    email = request.form.get("email", "")
    user  = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    data = f.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({"error": "Image too large (max 5MB)"}), 400
    mime = f.mimetype or "image/jpeg"

    if _supabase_ok():
        try:
            file_id = uuid.uuid4().hex
            file_path = f"avatars/{file_id}.jpg"
            
            headers = {
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": mime,
            }
            url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{file_path}"
            
            response = requests.post(url, data=data, headers=headers, timeout=60)
            
            if response.status_code in (200, 201):
                public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{file_path}"
                user.profile_pic = public_url
                db.session.commit()
                return jsonify({"success": True, "profile_pic": public_url})
        except Exception as e:
            print(f"Supabase avatar upload failed: {e}, falling back to base64")

    try:
        import base64
        b64      = base64.b64encode(data).decode("utf-8")
        media_id = uuid.uuid4().hex
        mf = MediaFile(id=media_id, mime=mime, data=b64)
        db.session.add(mf)
        user.profile_pic = f"/media/{media_id}"
        db.session.commit()
        return jsonify({"success": True, "profile_pic": user.profile_pic})
    except Exception as e:
        print(f"Base64 fallback failed: {e}")
        return jsonify({"error": "Upload failed"}), 500


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
    data     = request.get_json() or {}
    viewer   = data.get("viewer")
    post_id  = data.get("post_id")
    seconds  = float(data.get("seconds", 0))
    post     = Post.query.get(post_id)
    if post and post.author_email != viewer and seconds > 0:
        author = User.query.filter_by(email=post.author_email).first()
        if author:
            hours_watched = seconds / 3600.0
            author.watch_hours = round(author.watch_hours + hours_watched, 4)
            author.earnings    = round(author.earnings + (hours_watched * 0.10), 4)
            db.session.commit()
    return jsonify({"success": True})


@app.route("/api/ads", methods=["GET", "POST"])
def api_ads():
    if request.method == "POST":
        data   = request.get_json() or {}
        budget = float(data.get("budget", 0))
        if budget < 150:
            return jsonify({"error": "Minimum budget is P150 (15 days)"}), 400
        days = int(budget // 10)
        import datetime as dt
        expiry = (dt.datetime.utcnow() + dt.timedelta(days=days)).strftime("%Y-%m-%d")
        ad = Ad(
            title           = data.get("title"),
            owner_email     = data.get("owner"),
            whatsapp_number = data.get("whatsapp_number", ""),
            budget          = budget,
            image_url       = data.get("image_url", ""),
            approved        = 0,
            expiry_date     = expiry,
        )
        db.session.add(ad)
        db.session.commit()
        return jsonify({"message": f"Ad created. Runs for {days} days until {expiry}."})
    import datetime as dt
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    ads = Ad.query.filter_by(approved=1).filter(
        (Ad.expiry_date == None) | (Ad.expiry_date >= today)
    ).order_by(Ad.id.desc()).all()
    return jsonify([a.to_dict() for a in ads])


@app.route("/api/ads/impression", methods=["POST"])
def api_ads_impression():
    data    = request.get_json() or {}
    post_id = data.get("post_id")
    post    = Post.query.get(post_id)
    if post:
        author = User.query.filter_by(email=post.author_email).first()
        if author:
            author.earnings += 0.05
            db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/wipe-posts", methods=["POST"])
def api_wipe_posts():
    data = request.get_json() or {}
    if data.get("confirm") != "WIPE":
        return jsonify({"error": "Send confirm=WIPE to proceed"}), 400
    UserReaction.query.delete()
    Post.query.delete()
    db.session.commit()
    return jsonify({"success": True, "message": "All posts and reactions deleted."})


# ---------- Comments ----------
@app.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
def api_comments(post_id):
    if request.method == "GET":
        comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.id.asc()).all()
        return jsonify([c.to_dict() for c in comments])
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Comment cannot be empty"}), 400
    c = Comment(
        post_id      = post_id,
        author_email = data.get("author_email", ""),
        author_name  = data.get("author_name", ""),
        profile_pic  = data.get("profile_pic", ""),
        text         = text,
    )
    db.session.add(c)
    post = Post.query.get(post_id)
    if post:
        post.comments_count = (post.comments_count or 0) + 1
        if post.author_email != c.author_email:
            db.session.add(Notification(
                user_email=post.author_email,
                text=f"{c.author_name or c.author_email} commented on your post"
            ))
    db.session.commit()
    return jsonify(c.to_dict())


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
def api_delete_comment(comment_id):
    data = request.get_json() or {}
    c    = Comment.query.get_or_404(comment_id)
    if c.author_email != data.get("email"):
        return jsonify({"error": "Unauthorized"}), 403
    post = Post.query.get(c.post_id)
    if post:
        post.comments_count = max(0, (post.comments_count or 1) - 1)
    db.session.delete(c)
    db.session.commit()
    return jsonify({"success": True})


# ---------- Verified Badge Requests ----------
@app.route("/api/verified-request", methods=["POST"])
def api_verified_request():
    data  = request.get_json() or {}
    email = data.get("email", "").strip()
    user  = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.verified:
        return jsonify({"error": "Already verified"}), 400
    existing = VerifiedRequest.query.filter_by(user_email=email, status="pending").first()
    if existing:
        return jsonify({"error": "You already have a pending request"}), 400
    vr = VerifiedRequest(user_email=email, user_name=user.name or "")
    db.session.add(vr)
    db.session.commit()
    return jsonify({"success": True, "message": "Request submitted! Pay P50 via Orange Money to 72927417 with reference 'VERIFY'. We'll review within 24hrs."})


@app.route("/api/verified-request/status/<email>")
def api_verified_request_status(email):
    vr = VerifiedRequest.query.filter_by(user_email=email).order_by(VerifiedRequest.id.desc()).first()
    if not vr:
        return jsonify({"status": None})
    return jsonify({"status": vr.status, "created_at": vr.created_at})


# ---------- Reports ----------
@app.route("/api/report", methods=["POST"])
def api_report():
    data   = request.get_json() or {}
    email  = data.get("reporter_email", "")
    ttype  = data.get("target_type", "")
    tid    = data.get("target_id")
    reason = data.get("reason", "").strip()
    if not email or not ttype or not tid or not reason:
        return jsonify({"error": "Missing fields"}), 400
    existing = Report.query.filter_by(reporter_email=email, target_type=ttype, target_id=tid).first()
    if existing:
        return jsonify({"error": "You already reported this"}), 400
    r = Report(reporter_email=email, target_type=ttype, target_id=tid, reason=reason)
    db.session.add(r)
    db.session.commit()
    return jsonify({"success": True, "message": "Report submitted. Our team will review it."})


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


# ---------- Admin ----------
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
BTN_GREEN = "background:#4DF0C0;color:#060910;border:none;padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"
BTN_RED   = "background:#f06a4d;color:#fff;border:none;padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"
BTN_GREY  = "background:rgba(255,255,255,0.06);color:#8899b4;border:1px solid rgba(255,255,255,0.1);padding:6px 12px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer"

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
    pending_reports = Report.query.filter_by(status="pending").count()
    total_earnings  = db.session.query(func.sum(User.earnings)).scalar() or 0

    users = User.query.order_by(User.id.desc()).all()
    user_rows = ""
    for u in users:
        try:
            post_count    = Post.query.filter_by(author_email=u.email).count()
            follower_count= Follower.query.filter_by(user_email=u.email).count()
            post_ids      = [p.id for p in Post.query.filter_by(author_email=u.email).with_entities(Post.id).all()]
            reactions     = UserReaction.query.filter(UserReaction.post_id.in_(post_ids)).count() if post_ids else 0
            verified_badge= '<span style="color:#4DF0C0;font-weight:700">✦ Verified</span>' if u.verified else ''
            banned_badge  = '<span style="color:#f06a4d;font-weight:700">⛔ Banned</span>' if u.banned else ''
            user_rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
              <td style="padding:10px 8px">{u.id}</td>
              <td style="padding:10px 8px">{u.name or '—'} {verified_badge} {banned_badge}</td>
              <td style="padding:10px 8px">{u.email}</td>
              <td style="padding:10px 8px">{post_count}</td>
              <td style="padding:10px 8px">{reactions}</td>
              <td style="padding:10px 8px">{follower_count}</td>
              <td style="padding:10px 8px">{u.watch_hours or 0}h</td>
              <td style="padding:10px 8px">P{u.earnings:.2f}</td>
              <td style="padding:10px 8px">{u.last_active or '—'}</td>
              <td style="padding:10px 8px;display:flex;gap:6px;flex-wrap:wrap">
                <form method="post" action="/api/admin/user/verify" style="display:inline">
                  <input type="hidden" name="email" value="{u.email}">
                  <button style="{BTN_GREEN if not u.verified else BTN_GREY}">{'Unverify' if u.verified else '✦ Verify'}</button>
                </form>
                <form method="post" action="/api/admin/user/ban" style="display:inline">
                  <input type="hidden" name="email" value="{u.email}">
                  <button style="{BTN_GREY if not u.banned else BTN_RED}">{'Unban' if u.banned else '⛔ Ban'}</button>
                </form>
                {'' if u.email == ADMIN_EMAIL else f'''<form method="post" action="/api/admin/user/delete" style="display:inline" onsubmit="return confirm('Delete {u.name}?')">
                  <input type="hidden" name="email" value="{u.email}">
                  <button style="{BTN_RED}">🗑 Delete</button>
                </form>'''}
              </td>
            <table>"""
        except Exception:
            continue

    ads = Ad.query.order_by(Ad.id.desc()).all()
    ad_rows = ""
    for a in ads:
        status = {0:"⏳ Pending", 1:"✅ Approved", 2:"❌ Rejected"}.get(a.approved,"?")
        ad_rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
          <td style="padding:10px 8px">{a.id}</td>
          <td style="padding:10px 8px">{a.title}</td>
          <td style="padding:10px 8px">{a.owner_email}</td>
          <td style="padding:10px 8px">P{a.budget:.2f}</td>
          <td style="padding:10px 8px">{a.whatsapp_number or '—'}</td>
          <td style="padding:10px 8px">{a.expiry_date or '—'}</td>
          <td style="padding:10px 8px">{status}</td>
          <td style="padding:10px 8px;display:flex;gap:6px">
            <form method="post" action="/api/admin/ads/{a.id}/approve" style="display:inline">
              <input type="hidden" name="action" value="approve">
              <button style="{BTN_GREEN}">✓ Approve</button>
            </form>
            <form method="post" action="/api/admin/ads/{a.id}/approve" style="display:inline">
              <input type="hidden" name="action" value="reject">
              <button style="{BTN_RED}">✕ Reject</button>
            </form>
          </td>
        </tr>"""

    payouts = PayoutRequest.query.order_by(PayoutRequest.id.desc()).all()
    payout_rows = ""
    for p in payouts:
        payout_rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
          <td style="padding:10px 8px">{p.id}</td>
          <td style="padding:10px 8px">{p.user_email}</td>
          <td style="padding:10px 8px">{p.om_number}</td>
          <td style="padding:10px 8px">P{p.amount:.2f}</td>
          <td style="padding:10px 8px">{p.status}</td>
          <td style="padding:10px 8px">{p.created_at or '—'}</td>
          <td style="padding:10px 8px">
            {'<form method="post" action="/api/admin/payout/'+str(p.id)+'/mark-paid" style="display:inline"><button style="'+BTN_GREEN+'">✓ Mark Paid</button></form>' if p.status=='pending' else '—'}
          </td>
        </tr>"""

    vreqs = VerifiedRequest.query.order_by(VerifiedRequest.id.desc()).all()
    vreq_rows = ""
    for v in vreqs:
        vreq_rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
          <td style="padding:10px 8px">{v.id}</td>
          <td style="padding:10px 8px">{v.user_name or '—'}</td>
          <td style="padding:10px 8px">{v.user_email}</td>
          <td style="padding:10px 8px">{v.status}</td>
          <td style="padding:10px 8px">{v.created_at or '—'}</td>
          <td style="padding:10px 8px;display:flex;gap:6px">
            {'<form method="post" action="/api/admin/verified/'+str(v.id)+'/approve" style="display:inline"><input type="hidden" name="action" value="approve"><button style="'+BTN_GREEN+'">✦ Approve</button></form><form method="post" action="/api/admin/verified/'+str(v.id)+'/approve" style="display:inline"><input type="hidden" name="action" value="reject"><button style="'+BTN_RED+'">✕ Reject</button></form>' if v.status=='pending' else v.status}
          </td>
        </tr>"""

    reports = Report.query.order_by(Report.id.desc()).all()
    report_rows = ""
    for r in reports:
        context = "—"
        try:
            if r.target_type == "post":
                p = Post.query.get(r.target_id)
                context = (p.text or "")[:40] + "..." if p and p.text else "Media post"
            elif r.target_type == "comment":
                c = Comment.query.get(r.target_id)
                context = (c.text or "")[:40] + "..." if c else "Deleted"
            elif r.target_type == "user":
                u = User.query.get(r.target_id)
                context = u.email if u else "Deleted"
        except Exception:
            pass
        report_rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
          <td style="padding:10px 8px">{r.id}</td>
          <td style="padding:10px 8px">{r.reporter_email}</td>
          <td style="padding:10px 8px">{r.target_type} #{r.target_id}</td>
          <td style="padding:10px 8px;max-width:200px;overflow:hidden;text-overflow:ellipsis">{context}</td>
          <td style="padding:10px 8px">{r.reason}</td>
          <td style="padding:10px 8px">{r.created_at or '—'}</td>
          <td style="padding:10px 8px">{r.status}</td>
          <td style="padding:10px 8px;display:flex;gap:6px">
            <form method="post" action="/api/admin/report/{r.id}/action" style="display:inline">
              <input type="hidden" name="action" value="dismiss">
              <button style="{BTN_GREY}">Dismiss</button>
            </form>
            {'<form method="post" action="/api/admin/report/'+str(r.id)+'/action" style="display:inline"><input type="hidden" name="action" value="remove"><button style="'+BTN_RED+'">🗑 Remove</button></form>' if r.target_type in ['post','comment'] else ''}
          </td>
        </tr>"""

    TH = "padding:10px 8px;text-align:left;color:#4DF0C0;font-size:12px;border-bottom:1px solid rgba(77,240,192,0.2)"
    TABLE = "width:100%;border-collapse:collapse;font-size:13px;color:#c8d8f0"

    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>VibeNet Admin</title>
    <style>body{{background:#060910;color:#e8f0ff;font-family:sans-serif;padding:24px;margin:0}}
    h1{{color:#4DF0C0;margin-bottom:4px}}h2{{color:#8899b4;font-size:14px;font-weight:400;margin-bottom:24px}}
    .card{{background:#0d1117;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:20px;margin-bottom:24px}}
    .stats{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
    .stat{{background:#0d1117;border:1px solid rgba(77,240,192,0.15);border-radius:10px;padding:16px 20px;min-width:120px}}
    .stat-val{{font-size:28px;font-weight:800;color:#4DF0C0}}.stat-label{{font-size:12px;color:#5a6a85;margin-top:4px}}
    .section-title{{font-size:16px;font-weight:700;color:#e8f0ff;margin-bottom:16px}}
    .overflow{{overflow-x:auto}}</style></head><body>
    <h1>⚡ VibeNet Admin</h1>
    <h2>Signed in as {ADMIN_EMAIL} · <a href="/" style="color:#4DF0C0">← Back to app</a></h2>

    <div class="stats">
      <div class="stat"><div class="stat-val">{total_users}</div><div class="stat-label">Users</div></div>
      <div class="stat"><div class="stat-val">{total_posts}</div><div class="stat-label">Posts</div></div>
      <div class="stat"><div class="stat-val">{pending_ads}</div><div class="stat-label">Pending Ads</div></div>
      <div class="stat"><div class="stat-val">{pending_payouts}</div><div class="stat-label">Pending Payouts</div></div>
      <div class="stat"><div class="stat-val" style="color:{'#f06a4d' if pending_reports > 0 else '#4DF0C0'}">{pending_reports}</div><div class="stat-label">Pending Reports</div></div>
      <div class="stat"><div class="stat-val">P{total_earnings:.2f}</div><div class="stat-label">Total Earnings</div></div>
    </div>

    <div class="card"><div class="section-title">👥 Users</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Name</th><th style="{TH}">Email</th><th style="{TH}">Posts</th>
      <th style="{TH}">Reactions</th><th style="{TH}">Followers</th><th style="{TH}">Watch Hrs</th>
      <th style="{TH}">Earnings</th><th style="{TH}">Last Active</th><th style="{TH}">Actions</th></tr>
      {user_rows}</table></div></div>

    <div class="card"><div class="section-title">📢 Ad Campaigns</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Title</th><th style="{TH}">Owner</th>
      <th style="{TH}">Budget</th><th style="{TH}">WhatsApp</th><th style="{TH}">Expires</th><th style="{TH}">Status</th><th style="{TH}">Actions</th></tr>
      {ad_rows}<table></div></div>

    <div class="card"><div class="section-title">💸 Payout Requests</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Email</th><th style="{TH}">OM Number</th>
      <th style="{TH}">Amount</th><th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></tr>
      {payout_rows}</table></div></div>

    <div class="card"><div class="section-title">✦ Verified Badge Requests</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Name</th><th style="{TH}">Email</th>
      <th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></table>
      {vreq_rows}</table></div></div>

    <div class="card"><div class="section-title">⚑ Content Moderation Queue</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Reporter</th><th style="{TH}">Target</th>
      <th style="{TH}">Content</th><th style="{TH}">Reason</th><th style="{TH}">Date</th>
      <th style="{TH}">Status</th><th style="{TH}">Actions</th></tr>
      {report_rows}</table></div></div>
    </body></html>"""

@app.route("/api/admin/user/ban", methods=["POST"])
def api_admin_ban():
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    email = request.form.get("email") or (request.get_json() or {}).get("email","")
    user = User.query.filter_by(email=email).first()
    if not user: return jsonify({"error":"Not found"}), 404
    user.banned = 0 if user.banned else 1
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/user/verify", methods=["POST"])
def api_admin_verify():
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    email = request.form.get("email") or (request.get_json() or {}).get("email","")
    user = User.query.filter_by(email=email).first()
    if not user: return jsonify({"error":"Not found"}), 404
    user.verified = 0 if user.verified else 1
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/user/delete", methods=["POST"])
def api_admin_delete_user():
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    email = request.form.get("email") or (request.get_json() or {}).get("email","")
    if email == ADMIN_EMAIL: return jsonify({"error":"Cannot delete admin"}), 403
    user = User.query.filter_by(email=email).first()
    if not user: return jsonify({"error":"Not found"}), 404
    post_ids = [p.id for p in Post.query.filter_by(author_email=email).with_entities(Post.id).all()]
    if post_ids:
        UserReaction.query.filter(UserReaction.post_id.in_(post_ids)).delete(synchronize_session=False)
    Post.query.filter_by(author_email=email).delete()
    Follower.query.filter_by(user_email=email).delete()
    Follower.query.filter_by(follower_email=email).delete()
    Notification.query.filter_by(user_email=email).delete()
    PayoutRequest.query.filter_by(user_email=email).delete()
    db.session.delete(user)
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/ads/<int:ad_id>/approve", methods=["POST"])
def api_admin_approve_ad(ad_id):
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    action = request.form.get("action") or (request.get_json() or {}).get("action","approve")
    ad = Ad.query.get(ad_id)
    if not ad: return jsonify({"error":"Not found"}), 404
    ad.approved = 1 if action == "approve" else 2
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/payout/<int:payout_id>/mark-paid", methods=["POST"])
def api_admin_mark_paid(payout_id):
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    p = PayoutRequest.query.get(payout_id)
    if not p: return jsonify({"error":"Not found"}), 404
    p.status = "paid"
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/report/<int:report_id>/action", methods=["POST"])
def api_admin_report_action(report_id):
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    action = request.form.get("action") or (request.get_json() or {}).get("action","dismiss")
    r = Report.query.get(report_id)
    if not r: return jsonify({"error":"Not found"}), 404
    if action == "dismiss":
        r.status = "dismissed"
        db.session.commit()
    elif action == "remove":
        r.status = "reviewed"
        if r.target_type == "post":
            post = Post.query.get(r.target_id)
            if post:
                UserReaction.query.filter_by(post_id=r.target_id).delete()
                Comment.query.filter_by(post_id=r.target_id).delete()
                db.session.delete(post)
        elif r.target_type == "comment":
            c = Comment.query.get(r.target_id)
            if c:
                post = Post.query.get(c.post_id)
                if post: post.comments_count = max(0, (post.comments_count or 1) - 1)
                db.session.delete(c)
        db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/verified/<int:vreq_id>/approve", methods=["POST"])
def api_admin_approve_verified(vreq_id):
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    action = request.form.get("action") or (request.get_json() or {}).get("action","approve")
    vr = VerifiedRequest.query.get(vreq_id)
    if not vr: return jsonify({"error":"Not found"}), 404
    vr.status = "approved" if action == "approve" else "rejected"
    if action == "approve":
        user = User.query.filter_by(email=vr.user_email).first()
        if user:
            user.verified = 1
            db.session.add(Notification(user_email=vr.user_email, text="✦ Your verified badge has been approved! You are now VibeNet Verified."))
    db.session.commit()
    return redirect("/admin") if request.form else jsonify({"success":True})

@app.route("/api/admin/wipe-posts", methods=["POST"])
def api_admin_wipe_posts():
    if not require_admin(): return jsonify({"error":"Unauthorized"}), 403
    data = request.get_json() or {}
    if data.get("confirm") != "WIPE": return jsonify({"error":"Send confirm=WIPE"}), 400
    UserReaction.query.delete()
    Post.query.delete()
    db.session.commit()
    return jsonify({"success":True})

# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=True)
