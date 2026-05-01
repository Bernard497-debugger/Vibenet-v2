# VibeNet - Supabase Version
import os
from datetime import datetime
from flask import Flask, request, jsonify, session
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vibenet_secret_dev")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# Supabase Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "vibenet-media")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Helper function to get current user
def get_current_user():
    email = session.get("user_email")
    if not email:
        return None
    
    response = supabase.table("users").select("*").eq("email", email).execute()
    if response.data:
        return response.data[0]
    return None

def now_ts():
    return datetime.utcnow().isoformat()

# Initialize Supabase tables (run once)
def init_supabase():
    """Create tables if they don't exist using raw SQL"""
    
    # Users table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            profile_pic VARCHAR(500),
            bio TEXT,
            watch_hours FLOAT DEFAULT 0,
            earnings FLOAT DEFAULT 0,
            verified BOOLEAN DEFAULT FALSE,
            banned BOOLEAN DEFAULT FALSE,
            last_active TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    # Posts table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            author_email VARCHAR(255) REFERENCES users(email),
            author_name VARCHAR(255),
            text TEXT,
            file_url VARCHAR(500),
            file_type VARCHAR(50),
            timestamp TIMESTAMP DEFAULT NOW(),
            verified BOOLEAN DEFAULT FALSE,
            comments_count INT DEFAULT 0
        );
    """).execute()
    
    # Comments table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_id INT REFERENCES posts(id) ON DELETE CASCADE,
            author_email VARCHAR(255) REFERENCES users(email),
            author_name VARCHAR(255),
            text TEXT,
            timestamp TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    # Reactions table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS reactions (
            user_email VARCHAR(255) REFERENCES users(email),
            post_id INT REFERENCES posts(id) ON DELETE CASCADE,
            emoji VARCHAR(10),
            PRIMARY KEY (user_email, post_id)
        );
    """).execute()
    
    # Followers table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS followers (
            user_email VARCHAR(255) REFERENCES users(email),
            follower_email VARCHAR(255) REFERENCES users(email),
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_email, follower_email)
        );
    """).execute()
    
    # Notifications table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_email VARCHAR(255) REFERENCES users(email),
            type VARCHAR(50),
            content TEXT,
            seen BOOLEAN DEFAULT FALSE,
            timestamp TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    # Verified requests table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS verified_requests (
            id SERIAL PRIMARY KEY,
            user_email VARCHAR(255) REFERENCES users(email),
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    # Payouts table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS payouts (
            id SERIAL PRIMARY KEY,
            user_email VARCHAR(255) REFERENCES users(email),
            amount FLOAT,
            status VARCHAR(20) DEFAULT 'pending',
            payment_method VARCHAR(50),
            payment_details VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    # Campaigns table
    supabase.sql("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id SERIAL PRIMARY KEY,
            advertiser_email VARCHAR(255) REFERENCES users(email),
            title VARCHAR(255),
            budget FLOAT,
            impressions INT DEFAULT 0,
            clicks INT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        );
    """).execute()
    
    print("Supabase tables initialized successfully")

def upload_file_to_supabase(file_data, filename):
    """Upload a file to Supabase Storage"""
    try:
        # Generate unique filename
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
        unique_name = f"{uuid.uuid4()}.{ext}"
        
        # Upload to bucket
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            unique_name,
            file_data,
            {"content-type": f"image/{ext}" if ext in ['jpg', 'png', 'gif', 'webp'] else "video/mp4"}
        )
        
        # Get public URL
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(unique_name)
        return public_url
    except Exception as e:
        print(f"Upload error: {e}")
        return None

# ========== AUTH ==========
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    # Check if user exists
    existing = supabase.table("users").select("*").eq("email", email).execute()
    if existing.data:
        return jsonify({"error": "User already exists"}), 400
    
    # Create user
    password_hash = generate_password_hash(password)
    new_user = {
        "name": name,
        "email": email,
        "password_hash": password_hash,
        "created_at": now_ts()
    }
    
    response = supabase.table("users").insert(new_user).execute()
    
    if response.data:
        session["user_email"] = email
        user_data = response.data[0]
        user_data.pop("password_hash", None)  # Remove sensitive data
        return jsonify({"success": True, "user": user_data}), 201
    
    return jsonify({"error": "Signup failed"}), 500

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    response = supabase.table("users").select("*").eq("email", email).execute()
    
    if not response.data:
        return jsonify({"error": "Invalid credentials"}), 401
    
    user = response.data[0]
    
    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    if user.get("banned"):
        return jsonify({"error": "Account banned"}), 403
    
    # Update last_active
    supabase.table("users").update({"last_active": now_ts()}).eq("email", email).execute()
    
    session["user_email"] = email
    user.pop("password_hash", None)
    return jsonify({"user": user})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "logged out"})

@app.route("/api/me")
def api_me():
    user = get_current_user()
    if not user:
        return jsonify({"user": None})
    user.pop("password_hash", None)
    return jsonify({"user": user})

# ========== POSTS ==========
@app.route("/api/posts", methods=["GET", "POST"])
def api_posts():
    if request.method == "GET":
        response = supabase.table("posts").select("*").order("timestamp", desc=True).execute()
        return jsonify(response.data)
    
    # POST - Create new post
    data = request.form if request.files else request.get_json() or {}
    
    if request.files:
        # Handle file upload
        file = request.files.get("file")
        author_email = request.form.get("author_email")
        author_name = request.form.get("author_name")
        text = request.form.get("text", "")
        
        file_url = None
        file_type = None
        
        if file:
            file_data = file.read()
            file_url = upload_file_to_supabase(file_data, file.filename)
            file_type = "image" if file.content_type.startswith("image/") else "video"
    else:
        author_email = data.get("author_email")
        author_name = data.get("author_name")
        text = data.get("text", "")
        file_url = data.get("file_url", "")
        file_type = data.get("file_type", "")
    
    if not author_email:
        return jsonify({"error": "Not logged in"}), 401
    
    # Get user's verified status
    user = get_current_user()
    verified = user.get("verified", False) if user else False
    
    post = {
        "author_email": author_email,
        "author_name": author_name,
        "text": text,
        "file_url": file_url,
        "file_type": file_type,
        "verified": verified,
        "timestamp": now_ts()
    }
    
    response = supabase.table("posts").insert(post).execute()
    
    if response.data:
        return jsonify(response.data[0]), 201
    
    return jsonify({"error": "Failed to create post"}), 500

@app.route("/api/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    # Check if user owns the post
    post = supabase.table("posts").select("*").eq("id", post_id).execute()
    if not post.data or post.data[0]["author_email"] != user["email"]:
        return jsonify({"error": "Unauthorized"}), 403
    
    supabase.table("posts").delete().eq("id", post_id).execute()
    return jsonify({"success": True})

# ========== COMMENTS ==========
@app.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
def api_comments(post_id):
    if request.method == "GET":
        response = supabase.table("comments").select("*").eq("post_id", post_id).order("timestamp", desc=True).execute()
        return jsonify(response.data)
    
    data = request.get_json() or {}
    author_email = data.get("author_email")
    author_name = data.get("author_name")
    text = data.get("text", "")
    
    if not author_email:
        return jsonify({"error": "Not logged in"}), 401
    
    comment = {
        "post_id": post_id,
        "author_email": author_email,
        "author_name": author_name,
        "text": text,
        "timestamp": now_ts()
    }
    
    response = supabase.table("comments").insert(comment).execute()
    
    # Update comments count on post
    supabase.sql("""
        UPDATE posts 
        SET comments_count = comments_count + 1 
        WHERE id = {}
    """.format(post_id)).execute()
    
    if response.data:
        return jsonify(response.data[0]), 201
    
    return jsonify({"error": "Failed to add comment"}), 500

# ========== REACTIONS ==========
@app.route("/api/react", methods=["POST"])
def api_react():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    emoji = data.get("emoji")
    user_email = data.get("user_email")
    
    # Check existing reaction
    existing = supabase.table("reactions").select("*").eq("user_email", user_email).eq("post_id", post_id).execute()
    
    if existing.data:
        # Update reaction
        supabase.table("reactions").update({"emoji": emoji}).eq("user_email", user_email).eq("post_id", post_id).execute()
    else:
        # Insert new reaction
        supabase.table("reactions").insert({
            "user_email": user_email,
            "post_id": post_id,
            "emoji": emoji
        }).execute()
    
    # Get updated reaction counts
    reaction_counts = supabase.sql("""
        SELECT emoji, COUNT(*) as count 
        FROM reactions 
        WHERE post_id = {}
        GROUP BY emoji
    """.format(post_id)).execute()
    
    reactions = {r[0]: r[1] for r in reaction_counts.data} if reaction_counts.data else {}
    
    return jsonify({"success": True, "reactions": reactions})

# ========== FOLLOW ==========
@app.route("/api/follow", methods=["POST"])
def api_follow():
    data = request.get_json() or {}
    user_email = data.get("user_email")
    follower_email = data.get("follower_email")
    
    # Check if following
    existing = supabase.table("followers").select("*").eq("user_email", user_email).eq("follower_email", follower_email).execute()
    
    if existing.data:
        # Unfollow
        supabase.table("followers").delete().eq("user_email", user_email).eq("follower_email", follower_email).execute()
        return jsonify({"status": "unfollowed"})
    else:
        # Follow
        supabase.table("followers").insert({
            "user_email": user_email,
            "follower_email": follower_email
        }).execute()
        return jsonify({"status": "followed"})

@app.route("/api/is_following")
def is_following():
    user = request.args.get("user")
    follower = request.args.get("follower")
    
    response = supabase.table("followers").select("*").eq("user_email", user).eq("follower_email", follower).execute()
    return jsonify({"following": len(response.data) > 0})

# ========== PROFILE ==========
@app.route("/api/profile/<email>")
def profile(email):
    response = supabase.table("users").select("*").eq("email", email).execute()
    if not response.data:
        return jsonify({"error": "User not found"}), 404
    
    user = response.data[0]
    user.pop("password_hash", None)
    return jsonify(user)

@app.route("/api/update_bio", methods=["POST"])
def update_bio():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    bio = data.get("bio", "")
    
    supabase.table("users").update({"bio": bio}).eq("email", user["email"]).execute()
    
    user["bio"] = bio
    user.pop("password_hash", None)
    return jsonify({"success": True, "user": user})

@app.route("/api/update_profile_pic", methods=["POST"])
def update_profile_pic():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["file"]
    file_url = upload_file_to_supabase(file.read(), file.filename)
    
    if file_url:
        supabase.table("users").update({"profile_pic": file_url}).eq("email", user["email"]).execute()
        return jsonify({"success": True, "profile_pic": file_url})
    
    return jsonify({"error": "Upload failed"}), 500

# ========== NOTIFICATIONS ==========
@app.route("/api/notifications/<email>")
def get_notifications(email):
    user = get_current_user()
    if not user or user["email"] != email:
        return jsonify({"error": "Unauthorized"}), 403
    
    response = supabase.table("notifications").select("*").eq("user_email", email).order("timestamp", desc=True).execute()
    return jsonify(response.data)

@app.route("/api/notifications/<int:notif_id>/mark_seen", methods=["POST"])
def mark_seen(notif_id):
    supabase.table("notifications").update({"seen": True}).eq("id", notif_id).execute()
    return jsonify({"success": True})

# ========== MONETIZATION ==========
@app.route("/api/watch", methods=["POST"])
def watch_video():
    data = request.get_json() or {}
    author_email = data.get("author_email")
    watch_seconds = data.get("watch_seconds", 0)
    
    if author_email:
        watch_hours = watch_seconds / 3600
        earnings_added = watch_hours * 0.10
        
        # Update user stats
        response = supabase.table("users").select("watch_hours, earnings").eq("email", author_email).execute()
        if response.data:
            user = response.data[0]
            new_watch_hours = user.get("watch_hours", 0) + watch_hours
            new_earnings = user.get("earnings", 0) + earnings_added
            
            supabase.table("users").update({
                "watch_hours": new_watch_hours,
                "earnings": new_earnings
            }).eq("email", author_email).execute()
            
            return jsonify({"success": True, "earnings": new_earnings})
    
    return jsonify({"error": "User not found"}), 404

@app.route("/api/earnings/<email>")
def get_earnings(email):
    user = get_current_user()
    if not user or user["email"] != email:
        return jsonify({"error": "Unauthorized"}), 403
    
    response = supabase.table("users").select("watch_hours, earnings, verified").eq("email", email).execute()
    if response.data:
        return jsonify(response.data[0])
    
    return jsonify({"error": "User not found"}), 404

# ========== VERIFIED BADGES ==========
@app.route("/api/verified-badge/request", methods=["POST"])
def request_verified():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    if user.get("verified"):
        return jsonify({"error": "Already verified"}), 400
    
    # Check for existing request
    existing = supabase.table("verified_requests").select("*").eq("user_email", user["email"]).eq("status", "pending").execute()
    if existing.data:
        return jsonify({"error": "Already requested"}), 400
    
    supabase.table("verified_requests").insert({
        "user_email": user["email"],
        "status": "pending"
    }).execute()
    
    return jsonify({"success": True, "message": "Verified badge request submitted"})

@app.route("/api/verified-status")
def verified_status():
    user = get_current_user()
    if not user:
        return jsonify({"verified": False})
    
    return jsonify({"verified": user.get("verified", False)})

# ========== PAYOUTS ==========
@app.route("/api/payout-request", methods=["POST"])
def payout_request():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    amount = data.get("amount")
    orange_money = data.get("orange_money", "")
    
    if not amount or amount < 10:
        return jsonify({"error": "Minimum payout is P10"}), 400
    
    if user["earnings"] < amount:
        return jsonify({"error": "Insufficient earnings"}), 400
    
    supabase.table("payouts").insert({
        "user_email": user["email"],
        "amount": amount,
        "status": "pending",
        "payment_method": "orange_money",
        "payment_details": orange_money
    }).execute()
    
    return jsonify({"success": True, "message": "Payout request submitted"})

@app.route("/api/payout-history")
def payout_history():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    response = supabase.table("payouts").select("*").eq("user_email", user["email"]).order("created_at", desc=True).execute()
    return jsonify(response.data)

# ========== CAMPAIGNS/ADS ==========
@app.route("/api/campaigns", methods=["GET", "POST"])
def api_campaigns():
    if request.method == "GET":
        response = supabase.table("campaigns").select("*").eq("status", "active").execute()
        return jsonify(response.data)
    
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json() or {}
    campaign = {
        "advertiser_email": user["email"],
        "title": data.get("title", ""),
        "budget": data.get("budget", 0),
        "status": "active"
    }
    
    response = supabase.table("campaigns").insert(campaign).execute()
    
    if response.data:
        return jsonify(response.data[0]), 201
    
    return jsonify({"error": "Failed to create campaign"}), 500

@app.route("/api/campaigns/<int:campaign_id>/impression", methods=["POST"])
def campaign_impression(campaign_id):
    supabase.sql("""
        UPDATE campaigns 
        SET impressions = impressions + 1 
        WHERE id = {}
    """.format(campaign_id)).execute()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:campaign_id>/click", methods=["POST"])
def campaign_click(campaign_id):
    supabase.sql("""
        UPDATE campaigns 
        SET clicks = clicks + 1 
        WHERE id = {}
    """.format(campaign_id)).execute()
    return jsonify({"success": True})

# ========== ADMIN ==========
@app.route("/admin")
def admin_dashboard():
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    user = get_current_user()
    
    if not user or user["email"] != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Get stats
    total_users = supabase.table("users").select("count", count="exact").execute()
    total_posts = supabase.table("posts").select("count", count="exact").execute()
    total_earnings = supabase.table("users").select("earnings").execute()
    
    pending_verified = supabase.table("verified_requests").select("*").eq("status", "pending").execute()
    pending_payouts = supabase.table("payouts").select("*").eq("status", "pending").execute()
    
    return jsonify({
        "stats": {
            "total_users": total_users.count,
            "total_posts": total_posts.count,
            "total_earnings": sum(u["earnings"] for u in total_earnings.data)
        },
        "pending": {
            "verified": pending_verified.data,
            "payouts": pending_payouts.data
        }
    })

@app.route("/api/admin/verified/<int:req_id>/approve", methods=["POST"])
def approve_verified(req_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    user = get_current_user()
    
    if not user or user["email"] != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Get the request
    req = supabase.table("verified_requests").select("*").eq("id", req_id).execute()
    if req.data:
        user_email = req.data[0]["user_email"]
        # Update user verified status
        supabase.table("users").update({"verified": True}).eq("email", user_email).execute()
        # Update request status
        supabase.table("verified_requests").update({"status": "approved"}).eq("id", req_id).execute()
        return jsonify({"success": True})
    
    return jsonify({"error": "Not found"}), 404

@app.route("/api/admin/payout/<int:payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    admin_email = os.environ.get("ADMIN_EMAIL", "botsile55@gmail.com")
    user = get_current_user()
    
    if not user or user["email"] != admin_email:
        return jsonify({"error": "Unauthorized"}), 403
    
    supabase.table("payouts").update({"status": "approved"}).eq("id", payout_id).execute()
    return jsonify({"success": True})

# ========== INITIALIZATION ==========
@app.route("/")
def index():
    # Simple HTML landing page (same as before)
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>VibeNet</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #0d1117;
                color: #c8d8f0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .container {
                text-align: center;
                padding: 40px;
            }
            h1 {
                color: #4DF0C0;
                font-size: 48px;
                margin-bottom: 20px;
            }
            .buttons {
                display: flex;
                gap: 20px;
                justify-content: center;
                margin-top: 30px;
            }
            .btn {
                padding: 12px 24px;
                background: #4DF0C0;
                color: #0d1117;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 VibeNet</h1>
            <p>Your community platform powered by Supabase</p>
            <div class="buttons">
                <a href="/dashboard" class="btn">Go to Dashboard</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.route("/dashboard")
def dashboard():
    user = get_current_user()
    if not user:
        return """
        <script>
            window.location.href = '/';
        </script>
        """
    
    # Get posts
    posts = supabase.table("posts").select("*").order("timestamp", desc=True).execute()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>VibeNet Dashboard</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #0d1117;
                color: #c8d8f0;
                padding: 20px;
            }}
            .header {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .user-info h2 {{ color: #4DF0C0; margin-bottom: 5px; }}
            .user-info p {{ font-size: 12px; color: #8899b4; }}
            .btn {{
                padding: 10px 20px;
                background: #4DF0C0;
                color: #0d1117;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
            }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .post {{
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 15px;
            }}
            .post-author {{ font-weight: 600; color: #4DF0C0; }}
            .post-text {{ margin: 10px 0; }}
            .post-time {{ font-size: 11px; color: #8899b4; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="user-info">
                <h2>{user["name"]} {user.get('verified', False) and '✓' or ''}</h2>
                <p>💰 P{round(user.get("earnings", 0), 2)} | ⏱️ {round(user.get("watch_hours", 0), 2)}h</p>
            </div>
            <button class="btn" onclick="logout()">Logout</button>
        </div>
        
        <div class="container" id="posts-container">
            {''.join(f'''
            <div class="post">
                <div class="post-author">{p["author_name"]} {p.get('verified', False) and '✦' or ''}</div>
                <div class="post-text">{p["text"]}</div>
                <div class="post-time">{p["timestamp"]}</div>
            </div>
            ''' for p in posts.data)}
        </div>

        <script>
        async function logout() {{
            await fetch('/api/logout', {{method: 'POST'}});
            window.location.href = '/';
        }}
        </script>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    # Initialize Supabase tables on startup
    try:
        init_supabase()
        print("✅ Supabase initialized successfully")
    except Exception as e:
        print(f"⚠️  Supabase init warning: {e}")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
