# app.py - VibeNet  (SQLAlchemy ORM  |  SQLite locally  |  PostgreSQL on Render  |  Supabase Storage)
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
    "pool_size": 5,
    "max_overflow": 10,
    "pool_recycle": 300,  # Recycle connections every 5 minutes
    "pool_pre_ping": True,  # Test connection before using
    "connect_args": {
        "connect_timeout": 30,
        "application_name": "vibenet_app",
    } if not DATABASE_URL.startswith("sqlite") else {},
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
    file_mime      = db.Column(db.Text, default="")
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
            "timestamp": self.timestamp, "reactions": self.reactions(),
            "comments_count": self.comments_count,
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
    impressions      = db.Column(db.Integer, default=0)
    clicks           = db.Column(db.Integer, default=0)
    approved         = db.Column(db.Integer, default=0)  # 0=pending, 1=approved, 2=rejected
    expiry_date      = db.Column(db.Text, default="")
    created_at       = db.Column(db.Text, default=lambda: now_ts())

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "owner_email": self.owner_email,
            "whatsapp_number": self.whatsapp_number or "",
            "budget": self.budget, "impressions": self.impressions, "clicks": self.clicks,
            "approved": self.approved, "expiry_date": self.expiry_date or "",
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
    target_type  = db.Column(db.Text, nullable=False)  # 'post' | 'comment' | 'user'
    target_id    = db.Column(db.Integer, nullable=False)
    reason       = db.Column(db.Text, nullable=False)
    status       = db.Column(db.Text, default="pending")  # pending | reviewed | dismissed
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
    status     = db.Column(db.Text, default="pending")  # pending | approved | rejected
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
        "ALTER TABLE payout_requests ADD COLUMN user_email TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN user_name TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN om_number TEXT DEFAULT ''",
        "ALTER TABLE payout_requests ADD COLUMN amount FLOAT DEFAULT 0",
        "ALTER TABLE payout_requests ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE payout_requests ADD COLUMN created_at TEXT DEFAULT ''",
        "ALTER TABLE posts ADD COLUMN file_mime TEXT DEFAULT ''",
        "ALTER TABLE posts ADD COLUMN comments_count INTEGER DEFAULT 0",
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

PRIVACY_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — VibeNet</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#060910;color:#c8d8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7;padding:0}
  .container{max-width:720px;margin:0 auto;padding:40px 24px 80px}
  .back{display:inline-flex;align-items:center;gap:6px;color:#4DF0C0;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:32px}
  .back:hover{opacity:0.8}
  .logo{font-size:22px;font-weight:900;color:#4DF0C0;margin-bottom:8px}
  h1{font-size:28px;font-weight:800;color:#e8f0ff;margin-bottom:6px}
  .subtitle{font-size:14px;color:#5a6a85;margin-bottom:40px}
  h2{font-size:17px;font-weight:700;color:#4DF0C0;margin:32px 0 10px;padding-top:8px;border-top:1px solid rgba(77,240,192,0.1)}
  p{font-size:14px;color:#9aacc8;margin-bottom:12px}
  ul{padding-left:20px;margin-bottom:12px}
  li{font-size:14px;color:#9aacc8;margin-bottom:6px}
  .footer{margin-top:48px;padding-top:24px;border-top:1px solid rgba(255,255,255,0.07);font-size:13px;color:#5a6a85;text-align:center}
  a{color:#4DF0C0}
</style>
</head>
<body>
<div class="container">
  <a href="/" class="back">← Back to VibeNet</a>
  <div class="logo">⚡ VibeNet</div>
  <h1>Privacy Policy</h1>
  <div class="subtitle">Last updated: January 2025 · Effective immediately</div>

  <h2>1. Who We Are</h2>
  <p>VibeNet is a social media and creator monetisation platform operated in Botswana. We are committed to protecting your personal information in accordance with the <strong>Botswana Data Protection Act, 2018</strong>.</p>
  <p>For privacy questions, contact us at: <a href="mailto:botsile55@gmail.com">botsile55@gmail.com</a></p>

  <h2>2. Information We Collect</h2>
  <p>When you use VibeNet, we collect:</p>
  <ul>
    <li><strong>Account information</strong> — your name, email address, and password (stored encrypted)</li>
    <li><strong>Profile content</strong> — profile picture, bio, posts, videos, and images you upload</li>
    <li><strong>Activity data</strong> — posts, reactions, comments, follows, and watch history</li>
    <li><strong>Financial information</strong> — Orange Money number and payout amounts when you request earnings</li>
    <li><strong>Usage data</strong> — last active time, watch hours, and engagement metrics</li>
  </ul>
  <p>We do <strong>not</strong> collect payment card details, government IDs, or sensitive personal data beyond what is listed above.</p>

  <h2>3. How We Use Your Information</h2>
  <ul>
    <li>To operate your account and provide platform features</li>
    <li>To calculate and process creator earnings and payouts</li>
    <li>To display your content and profile to other users</li>
    <li>To send you platform notifications (reactions, follows, comments)</li>
    <li>To review reports and moderate content for safety</li>
    <li>To improve the platform and fix issues</li>
  </ul>

  <h2>4. How We Store Your Data</h2>
  <p>Your data is stored securely on cloud servers (Render.com) with PostgreSQL databases. Media files including profile pictures, images, and videos are stored directly in our database. We do not share your data with third-party advertisers.</p>
  <p>Passwords are stored using one-way hashing. We recommend using a unique password for VibeNet.</p>

  <h2>5. Who Can See Your Information</h2>
  <ul>
    <li><strong>Your posts and profile</strong> — visible to all VibeNet users</li>
    <li><strong>Your email address</strong> — only visible to VibeNet admins, never shown publicly</li>
    <li><strong>Your Orange Money number</strong> — only used for processing your payout, visible only to admins</li>
    <li><strong>Your earnings</strong> — only visible to you and admins</li>
  </ul>

  <h2>6. Advertiser Data</h2>
  <p>If you run an ad campaign on VibeNet, your campaign title, WhatsApp number, and budget are stored. Your WhatsApp number is shown to users who click your ad so they can contact you directly. This is a feature you opt into by creating a campaign.</p>

  <h2>7. Your Rights</h2>
  <p>Under the Botswana Data Protection Act 2018, you have the right to:</p>
  <ul>
    <li>Access the personal data we hold about you</li>
    <li>Request correction of inaccurate data</li>
    <li>Request deletion of your account and associated data</li>
    <li>Object to how we process your data</li>
  </ul>
  <p>To exercise any of these rights, email us at <a href="mailto:botsile55@gmail.com">botsile55@gmail.com</a>. We will respond within 14 days.</p>

  <h2>8. Data Retention</h2>
  <p>We retain your data for as long as your account is active. If you request account deletion, we will remove your personal data within 30 days, except where we are required by law to retain certain records.</p>

  <h2>9. Children's Privacy</h2>
  <p>VibeNet is not intended for users under the age of 13. We do not knowingly collect data from children. If you believe a child has created an account, please contact us immediately.</p>

  <h2>10. Changes to This Policy</h2>
  <p>We may update this Privacy Policy from time to time. We will notify users of significant changes via the platform. Continued use of VibeNet after changes constitutes acceptance of the updated policy.</p>

  <div class="footer">
    VibeNet · Botswana · <a href="/terms">Terms &amp; Conditions</a> · <a href="/">Back to App</a>
  </div>
</div>
</body>
</html>
"""

TERMS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms &amp; Conditions — VibeNet</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#060910;color:#c8d8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7;padding:0}
  .container{max-width:720px;margin:0 auto;padding:40px 24px 80px}
  .back{display:inline-flex;align-items:center;gap:6px;color:#4DF0C0;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:32px}
  .back:hover{opacity:0.8}
  .logo{font-size:22px;font-weight:900;color:#4DF0C0;margin-bottom:8px}
  h1{font-size:28px;font-weight:800;color:#e8f0ff;margin-bottom:6px}
  .subtitle{font-size:14px;color:#5a6a85;margin-bottom:40px}
  h2{font-size:17px;font-weight:700;color:#4DF0C0;margin:32px 0 10px;padding-top:8px;border-top:1px solid rgba(77,240,192,0.1)}
  p{font-size:14px;color:#9aacc8;margin-bottom:12px}
  ul{padding-left:20px;margin-bottom:12px}
  li{font-size:14px;color:#9aacc8;margin-bottom:6px}
  .highlight{background:rgba(77,240,192,0.06);border-left:3px solid #4DF0C0;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:16px}
  .footer{margin-top:48px;padding-top:24px;border-top:1px solid rgba(255,255,255,0.07);font-size:13px;color:#5a6a85;text-align:center}
  a{color:#4DF0C0}
</style>
</head>
<body>
<div class="container">
  <a href="/" class="back">← Back to VibeNet</a>
  <div class="logo">⚡ VibeNet</div>
  <h1>Terms &amp; Conditions</h1>
  <div class="subtitle">Last updated: January 2025 · By using VibeNet you agree to these terms</div>

  <div class="highlight">
    <strong style="color:#e8f0ff">Summary:</strong> Be respectful, post original content, don't scam people, and follow Botswana law. We reserve the right to remove content and ban accounts that violate these terms.
  </div>

  <h2>1. Acceptance of Terms</h2>
  <p>By creating an account or using VibeNet, you agree to be bound by these Terms and Conditions and our <a href="/privacy">Privacy Policy</a>. If you do not agree, do not use the platform.</p>

  <h2>2. Eligibility</h2>
  <ul>
    <li>You must be at least 13 years old to use VibeNet</li>
    <li>You must provide accurate information when creating your account</li>
    <li>You are responsible for maintaining the security of your account and password</li>
    <li>One account per person — creating multiple accounts to abuse the system is prohibited</li>
  </ul>

  <h2>3. Content Rules</h2>
  <p>You are solely responsible for content you post on VibeNet. The following content is <strong style="color:#f06a4d">strictly prohibited</strong>:</p>
  <ul>
    <li>Nudity, pornography, or sexually explicit material</li>
    <li>Hate speech, tribalism, racism, or content that incites violence</li>
    <li>Harassment, bullying, or threats targeting individuals</li>
    <li>Spam, scams, pyramid schemes, or fraudulent content</li>
    <li>Content that infringes on copyright or intellectual property</li>
    <li>Misinformation that could cause public harm</li>
    <li>Content that violates Botswana law, including the Cybercrime and Computer Related Crimes Act</li>
    <li>Personal information of others posted without their consent</li>
  </ul>
  <p>We reserve the right to remove any content that violates these rules without notice.</p>

  <h2>4. Creator Monetisation</h2>
  <p>VibeNet offers a creator earnings programme subject to the following conditions:</p>
  <ul>
    <li>You must reach <strong>1,000 followers</strong> and <strong>4,000 watch hours</strong> to be eligible for payouts</li>
    <li>Earnings are calculated at <strong>P0.10 per watch hour</strong> based on actual video watch time</li>
    <li>Minimum payout threshold applies — you must have sufficient balance before requesting</li>
    <li>Payouts are processed manually via Orange Money within <strong>24–48 hours</strong> of approval</li>
    <li>VibeNet reserves the right to adjust earning rates with notice to creators</li>
    <li>Artificially inflating watch hours or followers through bots or fake accounts will result in permanent ban and forfeiture of earnings</li>
  </ul>

  <h2>5. Advertising</h2>
  <ul>
    <li>Ad campaigns require a minimum budget of <strong>P150</strong> (15 days at P10/day)</li>
    <li>Payment must be sent via Orange Money before your campaign goes live</li>
    <li>VibeNet does not guarantee specific impressions or clicks</li>
    <li>Ads must comply with Botswana advertising standards and must not contain prohibited content</li>
    <li>Refunds are not available once a campaign has been approved and activated</li>
  </ul>

  <h2>6. Verified Badge</h2>
  <ul>
    <li>The VibeNet Verified badge costs a one-time fee of <strong>P50</strong></li>
    <li>Payment must be sent via Orange Money before your request is reviewed</li>
    <li>Approval is at VibeNet's sole discretion</li>
    <li>The badge can be revoked if you violate these Terms</li>
    <li>The P50 fee is non-refundable</li>
  </ul>

  <h2>7. Intellectual Property</h2>
  <p>You retain ownership of content you post on VibeNet. By posting, you grant VibeNet a non-exclusive licence to display and distribute your content on the platform. You confirm that you own or have the right to post all content you upload.</p>
  <p>VibeNet's name, logo, and branding are our intellectual property and may not be used without permission.</p>

  <h2>8. Account Suspension and Termination</h2>
  <p>VibeNet may suspend or permanently ban accounts that:</p>
  <ul>
    <li>Repeatedly violate content rules</li>
    <li>Engage in fraud or attempt to manipulate the earnings system</li>
    <li>Receive multiple verified reports from other users</li>
    <li>Are found to be impersonating another person or organisation</li>
  </ul>
  <p>Banned accounts forfeit any pending earnings or payout requests.</p>

  <h2>9. Limitation of Liability</h2>
  <p>VibeNet is provided "as is". We do not guarantee uninterrupted service and are not liable for any loss of data, lost earnings due to downtime, or damages resulting from use of the platform. Our maximum liability to you shall not exceed the total amount paid by you to VibeNet in the 12 months preceding the claim.</p>

  <h2>10. Governing Law</h2>
  <p>These Terms are governed by the laws of the <strong>Republic of Botswana</strong>. Any disputes shall be subject to the jurisdiction of the courts of Botswana.</p>

  <h2>11. Changes to Terms</h2>
  <p>We may update these Terms from time to time. Continued use of VibeNet after changes constitutes acceptance. We will notify users of significant changes via the platform.</p>

  <h2>12. Contact</h2>
  <p>For any questions about these Terms, contact us at <a href="mailto:botsile55@gmail.com">botsile55@gmail.com</a>.</p>

  <div class="footer">
    VibeNet · Botswana · <a href="/privacy">Privacy Policy</a> · <a href="/">Back to App</a>
  </div>
</div>
</body>
</html>
"""

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
  align-items: flex-start;
  justify-content: center;
  z-index: 100;
  background: var(--bg);
  padding: 20px;
  overflow-y: auto;
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
<script async src="https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.6/dist/ffmpeg.min.js"></script>
</head>
<body>

<!-- ===== AUTH SCREEN ===== -->
<div id="authScreen">
  <div class="auth-wrap" style="grid-template-columns:1fr;max-width:440px;border-radius:24px">
    <div class="auth-brand" style="padding:32px 32px 24px;text-align:center">
      <div class="brand-logo" style="font-size:30px">⚡ VibeNet</div>
      <div class="brand-tag" style="font-size:13px;max-width:100%">Share moments, grow your audience, and earn from your content.</div>
    </div>

    <div class="auth-forms" style="padding:0 24px 32px">
      <!-- Auth Tabs -->
      <div style="display:flex;background:rgba(255,255,255,0.04);border-radius:12px;padding:4px;margin-bottom:20px">
        <button id="tabSignup" onclick="switchAuthTab('signup')" style="flex:1;padding:10px;border:none;border-radius:9px;font-size:14px;font-weight:700;cursor:pointer;background:var(--accent);color:#060910;transition:all 0.2s">Create Account</button>
        <button id="tabLogin" onclick="switchAuthTab('login')" style="flex:1;padding:10px;border:none;border-radius:9px;font-size:14px;font-weight:600;cursor:pointer;background:transparent;color:var(--muted2);transition:all 0.2s">Sign In</button>
      </div>

      <!-- Signup Form -->
      <div id="authSignup">
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
          <div class="field-label">Date of Birth</div>
          <input id="signupDob" type="date" style="color-scheme:dark" />
          <div style="font-size:11px;color:#5a6a85;margin-top:4px">You must be at least 13 years old to join VibeNet.</div>
        </div>
        <div class="field">
          <div class="field-label">Profile photo (optional)</div>
          <input id="signupPic" type="file" accept="image/*" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--muted2);width:100%;font-size:13px;" />
        </div>
        <button class="btn-primary" onclick="signup()" style="width:100%;margin-top:4px;">Create Account →</button>
        <div style="text-align:center;margin-top:14px;font-size:12px;color:#5a6a85">Already have an account? <span onclick="switchAuthTab('login')" style="color:var(--accent);cursor:pointer;font-weight:600">Sign In</span></div>
      </div>

      <!-- Login Form -->
      <div id="authLogin" style="display:none">
        <div class="field">
          <div class="field-label">Email</div>
          <input id="loginEmail" type="email" placeholder="you@email.com" />
        </div>
        <div class="field">
          <div class="field-label">Password</div>
          <input id="loginPassword" type="password" placeholder="••••••••" />
        </div>
        <button class="btn-primary" onclick="login()" style="width:100%;">Sign In →</button>
        <div style="text-align:center;margin-top:14px;font-size:12px;color:#5a6a85">Don't have an account? <span onclick="switchAuthTab('signup')" style="color:var(--accent);cursor:pointer;font-weight:600">Create one</span></div>
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
            <button class="btn-primary" id="postBtn" onclick="addPost()">Post →</button>
          </div>
          <div id="uploadProgress" style="display:none;margin-top:10px">
            <div id="uploadLabel" style="font-size:12px;color:var(--muted2,#5a6a85);margin-bottom:6px">Uploading...</div>
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
              <input id="adBudget" class="form-input" type="number" min="150" placeholder="150 = 15 days" style="width:100%" />
            </div>
            <div style="flex:1;min-width:160px">
              <div class="form-label" style="margin-bottom:6px">WhatsApp Number</div>
              <input id="adWhatsapp" class="form-input" placeholder="e.g. 26772927417" style="width:100%" />
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
      </div><!-- /monet tab -->

      <!-- Profile Tab -->
      <div id="profile" class="tab">
        <div class="section-header">
          <h2>My Profile</h2>
          <p>Manage your identity and content</p>
        </div>

        <div class="profile-header">
          <div class="profile-avatar-wrap" style="position:relative">
            <img class="profile-avatar" id="profileAvatar" src="" onerror="this.style.background='var(--surface)'" />
            <label style="position:absolute;bottom:0;right:0;background:var(--accent);color:#060910;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:13px" title="Change photo">
              📷
              <input type="file" accept="image/*" style="display:none" onchange="changeProfilePic(this)" />
            </label>
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

        <div class="monet-section-title" style="margin-top:24px">✦ Verified Badge</div>
        <div style="background:rgba(77,240,192,0.04);border:1px solid rgba(77,240,192,0.15);border-radius:14px;padding:18px;margin-bottom:16px">
          <div id="verifiedStatus" style="font-size:13px;color:#8899b4;margin-bottom:12px">Loading...</div>
          <div style="font-size:13px;color:#c8d8f0;margin-bottom:14px">Get the <strong style="color:#4DF0C0">✦ VibeNet Verified</strong> badge on your profile and posts. One-time fee of <strong>P50</strong> via Orange Money.</div>
          <button id="verifiedBtn" onclick="requestVerified()" class="btn-primary" style="width:100%">✦ Apply for Verified Badge — P50</button>
          <div id="verifiedMsg" style="display:none;margin-top:10px;font-size:13px;line-height:1.6"></div>
        </div>
      </div>

    </div><!-- /main-col -->


  </div><!-- /app-layout -->

<!-- Report Modal -->
<div id="reportModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeReportModal()">
  <div class="modal-box">
    <div class="modal-title">⚑ Report Content</div>
    <div style="font-size:13px;color:#8899b4;margin-bottom:14px">Select a reason for your report:</div>
    <div id="reportReasons" style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Spam"> Spam</label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Nudity or sexual content"> Nudity or sexual content</label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Hate speech or harassment"> Hate speech or harassment</label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Violence or dangerous content"> Violence or dangerous content</label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Misinformation"> Misinformation</label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#c8d8f0"><input type="radio" name="reportReason" value="Other"> Other</label>
    </div>
    <div class="modal-footer">
      <button class="btn-ghost" onclick="closeReportModal()">Cancel</button>
      <button class="btn-primary" onclick="submitReport()" style="background:#f06a4d">Submit Report</button>
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

function switchAuthTab(tab){
  const isSignup = tab === 'signup';
  byId('authSignup').style.display = isSignup ? 'block' : 'none';
  byId('authLogin').style.display  = isSignup ? 'none'  : 'block';
  byId('tabSignup').style.background = isSignup ? 'var(--accent)' : 'transparent';
  byId('tabSignup').style.color      = isSignup ? '#060910' : 'var(--muted2)';
  byId('tabSignup').style.fontWeight = isSignup ? '700' : '600';
  byId('tabLogin').style.background  = isSignup ? 'transparent' : 'var(--accent)';
  byId('tabLogin').style.color       = isSignup ? 'var(--muted2)' : '#060910';
  byId('tabLogin').style.fontWeight  = isSignup ? '600' : '700';
}

async function signup(){
  const name = byId('signupName').value.trim();
  const email = byId('signupEmail').value.trim().toLowerCase();
  const password = byId('signupPassword').value;
  const dob = byId('signupDob').value;
  if(!name||!email||!password){ alert('Please fill all required fields.'); return; }
  if(!dob){ alert('Please enter your date of birth.'); return; }

  // Age check — must be 13+
  const birthDate = new Date(dob);
  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const m = today.getMonth() - birthDate.getMonth();
  if(m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) age--;
  if(age < 13){
    alert('❌ You must be at least 13 years old to create a VibeNet account.');
    return;
  }

  let profilePicUrl = '';
  const pic = byId('signupPic').files[0];
  if(pic){
    try { profilePicUrl = await uploadFile(pic, 'vibenet/avatars'); }
    catch(e) { console.warn('Profile pic upload failed:', e); }
  }

  const res = await fetch(API + '/signup', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name, email, password, profile_pic: profilePicUrl })
  });
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
  window._vn_poll = setInterval(()=>{ if(currentUser){ loadNotifications(false); loadMonetization(); } }, 5000);
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

  if(tab === 'profile'){ loadProfilePosts(); loadVerifiedStatus(); }
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
    let w = 0;
    p._interval = setInterval(()=>{
      w = Math.min(w + (Math.random() * 3), 88);
      byId('uploadBar').style.width = w + '%';
    }, 400);
  } else {
    clearInterval(p._interval);
    byId('uploadBar').style.width = '100%';
    setTimeout(()=>{ p.style.display='none'; byId('uploadBar').style.width='0%'; }, 700);
    if(btn){ btn.disabled = false; btn.style.opacity = '1'; }
  }
}

async function uploadFile(file, folder='vibenet/posts'){
  const isVideo = file.type.startsWith('video/');
  let fileToUpload = file;
  let thumbnailBlob = null;
  
  // Compress video if larger than 10MB
  if(isVideo && file.size > 10 * 1024 * 1024){
    showUploadProgress(true, `Compressing video (${(file.size/1024/1024).toFixed(1)}MB)...`);
    try {
      fileToUpload = await compressVideo(file);
      showUploadProgress(true, `Extracting thumbnail...`);
      thumbnailBlob = await extractVideoThumbnail(fileToUpload);
      showUploadProgress(true, `Uploading compressed video (${(fileToUpload.size/1024/1024).toFixed(1)}MB)...`);
    } catch(e) {
      console.warn('Compression/thumbnail failed, uploading original:', e);
      showUploadProgress(true, `Uploading video (${(file.size/1024/1024).toFixed(1)}MB)...`);
    }
  } else if(isVideo) {
    showUploadProgress(true, `Extracting thumbnail...`);
    try {
      thumbnailBlob = await extractVideoThumbnail(file);
    } catch(e) {
      console.warn('Thumbnail extraction failed:', e);
    }
    showUploadProgress(true, `Uploading video (${(fileToUpload.size/1024/1024).toFixed(1)}MB)...`);
  } else {
    showUploadProgress(true, `Uploading image (${(fileToUpload.size/1024/1024).toFixed(1)}MB)...`);
  }
  
  try {
    const fd = new FormData();
    fd.append('file', fileToUpload);
    if(thumbnailBlob) fd.append('thumbnail', thumbnailBlob, 'thumb.jpg');
    const res = await fetch(API + '/upload', {method:'POST', body: fd});
    const j = await res.json();
    showUploadProgress(false);
    if(j.error) throw new Error(j.error);
    return {url: j.url || '', thumbnail: j.thumbnail || ''};
  } catch(e) {
    showUploadProgress(false);
    console.error('Upload failed:', e.message);
    alert('Upload failed: ' + e.message);
    return {url: '', thumbnail: ''};
  }
}

async function extractVideoThumbnail(file){
  return new Promise((resolve) => {
    const video = document.createElement('video');
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    
    video.onloadedmetadata = () => {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      video.currentTime = Math.min(1, video.duration * 0.1);
    };
    
    video.onseeked = () => {
      ctx.drawImage(video, 0, 0);
      canvas.toBlob(resolve, 'image/jpeg', 0.8);
    };
    
    video.onerror = () => resolve(null);
    video.src = URL.createObjectURL(file);
  });
}

async function compressVideo(file){
  const { FFmpeg, toBlobURL } = FFmpeg;
  const ffmpeg = new FFmpeg.FFmpeg();
  const coreURL = await toBlobURL(`https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/ffmpeg-core.js`, 'text/javascript');
  const wasmURL = await toBlobURL(`https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/ffmpeg-core.wasm`, 'application/wasm');
  
  await ffmpeg.load({ coreURL, wasmURL });
  
  const inputName = 'input.' + file.name.split('.').pop();
  const outputName = 'output.mp4';
  
  const buffer = await file.arrayBuffer();
  ffmpeg.FS('writeFile', inputName, new Uint8Array(buffer));
  
  await ffmpeg.run('-i', inputName, '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24', '-vf', 'scale=1280:-1', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', outputName);
  
  const data = ffmpeg.FS('readFile', outputName);
  ffmpeg.FS('unlink', inputName);
  ffmpeg.FS('unlink', outputName);
  
  return new File([data.buffer], file.name.replace(/\.[^/.]+$/, '.mp4'), { type: 'video/mp4' });
}

function optimizeCldUrl(url, isVideo){
  if(!url || !url.includes('cloudinary.com')) return url;
  return url.replace('/upload/', '/upload/q_auto,f_auto/');
}

async function createAd(){
  const title = byId('adTitle').value.trim();
  const budget = parseFloat(byId('adBudget').value || 0);
  const msg = byId('adMsg');
  if(!title || !budget){ alert('Please enter a title and budget.'); return; }
  await fetch(API+'/ads', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title, budget, owner: currentUser.email})});
  byId('adTitle').value = ''; byId('adBudget').value = '';
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
  let url = '', mime = '', thumbnail = '';
  if(fileEl.files[0]){
    mime = fileEl.files[0].type;
    const result = await uploadFile(fileEl.files[0]);
    url = result.url;
    thumbnail = result.thumbnail;
  }
  if(!text && !url) return;
  await fetch(API + '/posts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    author_email: currentUser.email, author_name: currentUser.name,
    profile_pic: currentUser.profile_pic||'', text, file_url: url, file_mime: mime, thumbnail_url: thumbnail
  })});
  byId('postText').value=''; fileEl.value=''; byId('fileNameDisplay').textContent='';
  await loadFeed(true); await loadProfilePosts(); await loadMonetization();
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
    // Report button
    const rpBtn = document.createElement('button');
    rpBtn.style.cssText = 'background:none;border:none;color:#5a6a85;font-size:13px;cursor:pointer;padding:4px 6px;margin-left:4px';
    rpBtn.title = 'Report post';
    rpBtn.textContent = '⚑';
    rpBtn.onclick = ()=> openReportModal('post', p.id);
    header.append(fb, rpBtn);
  }

  div.append(header);

  const postTextEl = document.createElement('div');
  if(p.text){ postTextEl.className='post-text'; postTextEl.textContent=p.text; div.append(postTextEl); }
  div._postTextEl = postTextEl;

  if(p.file_url){
    const media = document.createElement('div'); media.className='post-media';
    const isVideo = (p.file_mime && p.file_mime.startsWith('video/')) ||
                    p.file_url.startsWith('data:video/') ||
                    /\.(mp4|webm|mov|avi|mkv)(\?|$)/i.test(p.file_url);
    if(isVideo){
      const wrap = document.createElement('div'); wrap.className='video-wrap';
      const v = document.createElement('video');
      v.dataset.src = optimizeCldUrl(p.file_url, true);
      v.controls = true; v.muted = true; v.loop = false;
      v.setAttribute('playsinline','');
      v.setAttribute('preload', 'metadata');
      v.style.background = '#0d1117';
      if(p.thumbnail_url) v.poster = p.thumbnail_url;

      // Lazy load: set src when near viewport
      const vObs = new IntersectionObserver(entries => {
        entries.forEach(e => {
          if(e.isIntersecting && v.dataset.src){
            v.src = v.dataset.src;
            delete v.dataset.src;
            vObs.disconnect();
            // Thumbnail after src loads
            v.addEventListener('loadedmetadata', ()=>{ v.currentTime = 0.05; });
            v.addEventListener('seeked', ()=>{
              if(v.dataset.thumbDone) return;
              v.dataset.thumbDone = '1';
              try {
                const canvas = document.createElement('canvas');
                canvas.width = v.videoWidth || 640;
                canvas.height = v.videoHeight || 360;
                canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
                v.poster = canvas.toDataURL('image/jpeg', 0.7);
              } catch(e){}
            }, { once: true });
          }
        });
      }, { rootMargin: '300px' });
      vObs.observe(v);

      const hint = document.createElement('div'); hint.className='play-hint';
      hint.innerHTML='<span>▶</span>';
      v.addEventListener('play', ()=>{ wrap.classList.add('playing'); });
      v.addEventListener('pause', ()=>{ wrap.classList.remove('playing'); });
      v.addEventListener('ended', async()=>{
        wrap.classList.remove('playing');
        const seconds = v.duration && isFinite(v.duration) ? Math.min(Math.round(v.duration), 300) : 0;
        await fetch(API+'/watch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer:currentUser?currentUser.email:'',post_id:p.id,seconds})});
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
  cc.style.cursor='pointer';
  cc.onclick=()=>toggleComments(p.id, div);
  footer.append(bar, cc);
  div.append(footer);

  // Comments section (hidden by default)
  const commentsSection = document.createElement('div');
  commentsSection.id = `comments-${p.id}`;
  commentsSection.style.cssText = 'display:none;border-top:1px solid rgba(255,255,255,0.06);padding:12px 0 4px';
  commentsSection.innerHTML = `
    <div id="comment-list-${p.id}" style="margin-bottom:10px"></div>
    <div style="display:flex;gap:8px;align-items:center">
      <img src="${currentUser?currentUser.profile_pic||'':''}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;background:var(--surface)" onerror="this.src=''">
      <input id="comment-input-${p.id}" type="text" placeholder="Add a comment..." style="flex:1;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:8px 14px;color:#e8f0ff;font-size:13px;outline:none"
        onkeydown="if(event.key==='Enter')postComment(${p.id})">
      <button onclick="postComment(${p.id})" style="background:var(--accent);color:#060910;border:none;border-radius:20px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer">Send</button>
    </div>`;
  div.append(commentsSection);
  return div;
}

let _feedPage = 1;
let _feedHasMore = false;
let _feedAds = [];
let _feedAdIndex = 0;
let _feedLoading = false;

async function loadFeed(reset=true){
  if(_feedLoading) return;
  _feedLoading = true;

  if(reset){
    _feedPage = 1;
    _feedAdIndex = 0;
    const feed = byId('feedList');
    feed.innerHTML = '<div style="text-align:center;padding:32px;color:#5a6a85;font-size:13px">⏳ Loading...</div>';
    const adsRes = await fetch(API+'/ads');
    _feedAds = await adsRes.json();
  }

  const postsRes = await fetch(API+`/posts?page=${_feedPage}&limit=10`);
  const data = await postsRes.json();
  const list = data.posts || [];
  _feedHasMore = data.has_more || false;

  const feed = byId('feedList');
  if(reset) feed.innerHTML = '';

  const oldBtn = byId('loadMoreBtn');
  if(oldBtn) oldBtn.remove();

  if(!list.length && _feedPage === 1){
    feed.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><p>No posts yet. Be the first to share something!</p></div>';
    _feedLoading = false;
    return;
  }

  list.forEach((p, i) => {
    feed.appendChild(createPostElement(p));
    if(_feedAds.length && (i+1) % 5 === 0){
      feed.appendChild(createAdCard(_feedAds[_feedAdIndex++ % _feedAds.length]));
    }
  });

  // Lazy load videos — only load src when near viewport
  feed.querySelectorAll('video[data-src]').forEach(v => {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if(e.isIntersecting){ v.src = v.dataset.src; delete v.dataset.src; obs.disconnect(); }
      });
    }, { rootMargin: '200px' });
    obs.observe(v);
  });

  if(_feedHasMore){
    const btn = document.createElement('button');
    btn.id = 'loadMoreBtn';
    btn.textContent = 'Load more posts';
    btn.style.cssText = 'display:block;width:100%;padding:14px;margin:12px 0 24px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:12px;color:#8899b4;font-size:14px;font-weight:600;cursor:pointer';
    btn.onclick = async () => {
      _feedPage++;
      btn.textContent = '⏳ Loading...';
      btn.disabled = true;
      await loadFeed(false);
    };
    feed.appendChild(btn);
  }

  _feedLoading = false;
}


function createAdCard(ad){
  const waNumber = (ad.whatsapp_number||'').replace(/\D/g,'');
  const waMsg = encodeURIComponent('Hi! I saw your ad "' + (ad.title||'') + '" on VibeNet and I\'d like to know more.');
  const waLink = waNumber ? 'https://wa.me/' + waNumber + '?text=' + waMsg : '';
  const div = document.createElement('div');
  div.style.cssText = 'background:linear-gradient(135deg,rgba(77,240,192,0.06),rgba(0,201,255,0.04));border:1px solid rgba(77,240,192,0.2);border-radius:16px;padding:16px 18px;margin-bottom:12px;cursor:' + (waLink?'pointer':'default');
  div.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><span style="background:rgba(77,240,192,0.15);color:#4DF0C0;font-size:10px;font-weight:800;padding:3px 8px;border-radius:100px;letter-spacing:0.8px">SPONSORED</span>' + (waLink ? '<span style="font-size:11px;color:#25D366;font-weight:600">Tap to chat →</span>' : '') + '</div><div style="font-size:15px;font-weight:700;color:#e8f0ff;margin-bottom:12px">' + escapeHtml(ad.title||'') + '</div>';
  if(waLink){
    const btn = document.createElement('a');
    btn.href = waLink;
    btn.target = '_blank';
    btn.rel = 'noopener noreferrer';
    btn.style.cssText = 'display:inline-flex;align-items:center;gap:8px;background:#25D366;color:#fff;font-size:13px;font-weight:700;padding:10px 18px;border-radius:100px;text-decoration:none;';
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg> Chat on WhatsApp';
    div.appendChild(btn);
  }
  return div;
}

function observeVideos(){
  // Autoplay disabled — users press play manually
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

async function changeProfilePic(input){
  if(!currentUser || !input.files[0]) return;
  const file = input.files[0];
  const fd = new FormData();
  fd.append('file', file);
  fd.append('email', currentUser.email);
  const btn = input.closest('label');
  if(btn) btn.textContent = '⏳';
  try {
    const res = await fetch(API + '/update_profile_pic', {method:'POST', body: fd});
    const j = await res.json();
    if(j.success){
      currentUser.profile_pic = j.profile_pic;
      byId('profileAvatar').src = j.profile_pic;
      byId('composerAvatar').src = j.profile_pic;
    } else {
      alert(j.error || 'Upload failed');
    }
  } catch(e) {
    alert('Upload failed: ' + e.message);
  }
  if(btn){ btn.innerHTML = '📷<input type="file" accept="image/*" style="display:none" onchange="changeProfilePic(this)" />'; }
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
  const title    = byId('adTitle').value.trim();
  const budget   = parseFloat(byId('adBudget').value||0);
  const whatsapp = byId('adWhatsapp').value.trim();
  const msg      = byId('adMsg');
  if(!title){ alert('Please enter a campaign title.'); return; }
  if(!whatsapp){ alert('Please enter your WhatsApp number.'); return; }
  if(budget < 150){ alert('Minimum budget is P150 (15 days). P10 per day.'); return; }
  const days = Math.floor(budget / 10);
  await fetch(API+'/ads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title, budget, whatsapp_number: whatsapp, owner: currentUser.email})});
  byId('adTitle').value=''; byId('adBudget').value=''; byId('adWhatsapp').value='';
  msg.style.display = 'block';
  msg.style.color = 'var(--accent)';
  msg.textContent = `✅ Campaign submitted for ${days} days! Please send P${budget.toFixed(2)} via Orange Money to 72927417. Your campaign goes live once we confirm your payment.`;
  setTimeout(()=>{ msg.style.display='none'; }, 12000);
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


// Report modal
let _reportTarget = null;
function openReportModal(type, id){
  _reportTarget = {type, id};
  document.querySelectorAll('input[name="reportReason"]').forEach(r=>r.checked=false);
  byId('reportModal').style.display = 'flex';
}
function closeReportModal(){
  byId('reportModal').style.display = 'none';
  _reportTarget = null;
}
async function submitReport(){
  if(!currentUser || !_reportTarget) return;
  const reason = document.querySelector('input[name="reportReason"]:checked');
  if(!reason){ alert('Please select a reason.'); return; }
  const res = await fetch(API+'/report', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      reporter_email: currentUser.email,
      target_type: _reportTarget.type,
      target_id: _reportTarget.id,
      reason: reason.value
    })
  });
  const j = await res.json();
  closeReportModal();
  if(j.success) alert('✅ ' + j.message);
  else alert('❌ ' + (j.error || 'Failed to submit report'));
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




async function requestVerified(){
  if(!currentUser) return;
  const btn = byId('verifiedBtn');
  const msg = byId('verifiedMsg');
  btn.disabled = true; btn.textContent = '⏳ Submitting...';
  const res = await fetch(API+'/verified-request', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email: currentUser.email})
  });
  const j = await res.json();
  msg.style.display = 'block';
  if(j.success){
    msg.style.color = 'var(--accent)';
    msg.textContent = '✅ ' + j.message;
    btn.style.display = 'none';
    byId('verifiedStatus').textContent = '⏳ Pending review';
  } else {
    msg.style.color = 'var(--danger)';
    msg.textContent = '❌ ' + (j.error || 'Something went wrong');
    btn.disabled = false; btn.textContent = '✦ Apply for Verified Badge — P50';
  }
  setTimeout(()=>{ msg.style.display='none'; }, 10000);
}

async function loadVerifiedStatus(){
  if(!currentUser) return;
  const statusEl = byId('verifiedStatus');
  const btn = byId('verifiedBtn');
  if(!statusEl) return;
  if(currentUser.verified){
    statusEl.innerHTML = '✦ You are <strong style="color:#4DF0C0">VibeNet Verified</strong> 🎉';
    if(btn) btn.style.display = 'none';
    return;
  }
  const res = await fetch(API+'/verified-request/status/'+encodeURIComponent(currentUser.email));
  const j = await res.json();
  if(j.status === 'pending'){
    statusEl.textContent = '⏳ Your request is under review';
    if(btn) btn.style.display = 'none';
  } else if(j.status === 'rejected'){
    statusEl.textContent = '❌ Previous request was rejected. You may apply again.';
  } else {
    statusEl.textContent = 'Not verified yet. Apply below.';
  }
}

async function toggleComments(postId, postDiv){
  const section = byId(`comments-${postId}`);
  if(!section) return;
  if(section.style.display === 'none'){
    section.style.display = 'block';
    await loadComments(postId);
  } else {
    section.style.display = 'none';
  }
}

async function loadComments(postId){
  const list = byId(`comment-list-${postId}`);
  if(!list) return;
  const res = await fetch(API+`/posts/${postId}/comments`);
  const comments = await res.json();
  list.innerHTML = '';
  if(!comments.length){
    list.innerHTML = '<div style="font-size:12px;color:#5a6a85;padding:4px 0">No comments yet. Be first!</div>';
    return;
  }
  comments.forEach(c => {
    const d = document.createElement('div');
    d.style.cssText = 'display:flex;gap:8px;margin-bottom:10px;align-items:flex-start';
    const isOwn = currentUser && currentUser.email === c.author_email;
    d.innerHTML = `
      <img src="${c.profile_pic||''}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;background:var(--surface);flex-shrink:0" onerror="this.src=''">
      <div style="flex:1;background:rgba(255,255,255,0.04);border-radius:12px;padding:8px 12px">
        <div style="font-size:12px;font-weight:700;color:#4DF0C0;margin-bottom:2px">${escapeHtml(c.author_name||'User')}</div>
        <div style="font-size:13px;color:#c8d8f0">${escapeHtml(c.text)}</div>
        <div style="font-size:11px;color:#5a6a85;margin-top:4px">${escapeHtml(c.timestamp)}</div>
      </div>
      ${isOwn ? `<button onclick="deleteComment(${c.id},${postId})" style="background:none;border:none;color:#5a6a85;font-size:14px;cursor:pointer;padding:4px">🗑</button>` : ''}`;
    list.appendChild(d);
  });
}

async function postComment(postId){
  if(!currentUser){ alert('Please login to comment'); return; }
  const input = byId(`comment-input-${postId}`);
  const text = input.value.trim();
  if(!text) return;
  input.value = '';
  await fetch(API+`/posts/${postId}/comments`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      author_email: currentUser.email, author_name: currentUser.name,
      profile_pic: currentUser.profile_pic||'', text
    })
  });
  await loadComments(postId);
  // Update comment count display
  const cc = document.querySelector(`#comments-${postId}`)?.previousElementSibling?.querySelector('.comment-count');
  if(cc) cc.innerHTML = `💬 ${parseInt(cc.textContent.replace('💬','').trim()||0)+1}`;
}

async function deleteComment(commentId, postId){
  if(!currentUser) return;
  if(!confirm('Delete this comment?')) return;
  await fetch(API+`/comments/${commentId}`, {
    method:'DELETE', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email: currentUser.email})
  });
  await loadComments(postId);
}

async function refreshAll(){ await loadFeed(true); await loadNotifications(); await loadProfilePosts(); await loadMonetization(); await loadAds(); }
</script>

<div style="text-align:center;padding:32px 16px 48px;border-top:1px solid rgba(255,255,255,0.05);margin-top:24px">
  <div style="font-size:18px;font-weight:900;color:#4DF0C0;margin-bottom:8px">⚡ VibeNet</div>
  <div style="font-size:12px;color:#3a4a60;margin-bottom:10px">Botswana's Creator Platform</div>
  <div style="display:flex;justify-content:center;gap:20px;font-size:12px">
    <a href="/privacy" target="_blank" style="color:#5a6a85;text-decoration:none">Privacy Policy</a>
    <a href="/terms" target="_blank" style="color:#5a6a85;text-decoration:none">Terms &amp; Conditions</a>
  </div>
  <div style="font-size:11px;color:#2a3a50;margin-top:10px">© 2025 VibeNet. All rights reserved.</div>
</div>

</body>
</html>
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


# ---------- Upload ----------
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
        
        # Optional thumbnail
        thumbnail_data = None
        thumbnail_url = ""
        if "thumbnail" in request.files:
            thumb = request.files["thumbnail"]
            thumbnail_data = thumb.read()

        # Try Supabase Storage first (preferred)
        if _supabase_ok():
            try:
                file_id = uuid.uuid4().hex
                file_ext = os.path.splitext(f.filename)[1] or ".bin"
                file_path = f"posts/{file_id}{file_ext}"
                
                # Upload main file to Supabase Storage
                headers = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": mime,
                }
                url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{file_path}"
                
                response = requests.post(url, data=data, headers=headers, timeout=300)
                
                if response.status_code in (200, 201):
                    # Return public URL
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{file_path}"
                    
                    # Upload thumbnail if provided
                    if thumbnail_data:
                        try:
                            thumb_id = uuid.uuid4().hex
                            thumb_path = f"posts/{thumb_id}_thumb.jpg"
                            thumb_headers = {
                                "Authorization": f"Bearer {SUPABASE_KEY}",
                                "Content-Type": "image/jpeg",
                            }
                            thumb_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{thumb_path}"
                            thumb_resp = requests.post(thumb_url, data=thumbnail_data, headers=thumb_headers, timeout=60)
                            if thumb_resp.status_code in (200, 201):
                                thumbnail_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{thumb_path}"
                        except Exception as e:
                            print(f"Thumbnail upload failed: {e}")
                    
                    return jsonify({"url": public_url, "thumbnail": thumbnail_url})
                else:
                    print(f"Supabase upload failed: {response.status_code} - {response.text}")
                    # Fall back to DB for small files only
                    if len(data) > 10 * 1024 * 1024:
                        return jsonify({"error": f"Upload failed: {response.text[:80]}"}), 503
                    print("Falling back to DB storage")
            except Exception as e:
                print(f"Supabase upload error: {e}")
                if len(data) > 10 * 1024 * 1024:
                    return jsonify({"error": f"Supabase upload failed: {str(e)[:80]}"}), 503

        # Fallback: store as base64 in DB (only for small files)
        if len(data) <= 10 * 1024 * 1024:
            try:
                import base64
                b64      = base64.b64encode(data).decode("utf-8")
                media_id = uuid.uuid4().hex
                mf = MediaFile(id=media_id, mime=mime, data=b64)
                db.session.add(mf)
                db.session.commit()
                return jsonify({"url": f"/media/{media_id}", "thumbnail": thumbnail_url})
            except Exception as db_err:
                print(f"DB fallback failed: {db_err}")
                db.session.rollback()
                return jsonify({"error": f"Upload service temporarily unavailable. ({str(db_err)[:80]}...)"}), 503
        else:
            return jsonify({"error": "File too large and Supabase not available. Configure Supabase or use smaller files."}), 503

    except Exception as e:
        print(f"Upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)[:150]}), 500


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
        # Build a verified lookup map
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
    post = Post(
        author_email=data.get("author_email"),
        author_name=data.get("author_name"),
        profile_pic=data.get("profile_pic", ""),
        text=data.get("text", ""),
        file_url=data.get("file_url", ""),
        file_mime=data.get("file_mime", ""),
        thumbnail_url=data.get("thumbnail_url", ""),
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

    # Try Cloudinary first
    if _cloudinary_ok():
        try:
            import io
            result = cloudinary.uploader.upload(
                io.BytesIO(data),
                folder        = "vibenet/avatars",
                resource_type = "image",
                quality       = "auto",
                fetch_format  = "auto",
            )
            url = result.get("secure_url", "")
            user.profile_pic = url
            db.session.commit()
            return jsonify({"success": True, "profile_pic": url})
        except Exception as e:
            print(f"Cloudinary avatar upload failed: {e}, falling back to DB")

    # Fallback: store as base64 in DB
    import base64
    b64      = base64.b64encode(data).decode("utf-8")
    media_id = uuid.uuid4().hex
    mf = MediaFile(id=media_id, mime=mime, data=b64)
    db.session.add(mf)
    user.profile_pic = f"/media/{media_id}"
    db.session.commit()
    return jsonify({"success": True, "profile_pic": user.profile_pic})


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
    seconds  = float(data.get("seconds", 0))  # actual seconds watched
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
            approved        = 0,
            expiry_date     = expiry,
        )
        db.session.add(ad)
        db.session.commit()
        return jsonify({"message": f"Ad created. Runs for {days} days until {expiry}."})
    # Only return approved, non-expired ads
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
    # Prevent duplicate reports
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
            </tr>"""
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
        # Get context snippet
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
      {ad_rows}</table></div></div>

    <div class="card"><div class="section-title">💸 Payout Requests</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Email</th><th style="{TH}">OM Number</th>
      <th style="{TH}">Amount</th><th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></tr>
      {payout_rows}</table></div></div>

    <div class="card"><div class="section-title">✦ Verified Badge Requests</div><div class="overflow"><table style="{TABLE}">
      <tr><th style="{TH}">ID</th><th style="{TH}">Name</th><th style="{TH}">Email</th>
      <th style="{TH}">Status</th><th style="{TH}">Date</th><th style="{TH}">Action</th></tr>
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
