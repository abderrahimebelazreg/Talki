from __future__ import annotations

import os
import random
import smtplib
import sqlite3
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

logging.basicConfig(filename='talki.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app.secret_key = os.environ.get("TALKI_SECRET_KEY", "dev-secret-change-me")
DATABASE_PATH = os.environ.get("TALKI_DB_PATH", "talki.db")
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
AVATAR_FOLDER = os.path.join(UPLOAD_FOLDER, "avatars")
POSTS_FOLDER = os.path.join(UPLOAD_FOLDER, "posts")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_MEDIA_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"}
CODE_COOLDOWN_SECONDS = 60
BANNED_WORDS = {"hate", "kill", "die", "stupid", "idiot", "kys", "nigger", "faggot"} # Basic list, should be expanded

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

def check_content(text: str) -> bool:
    """Returns True if content is clean, False if it contains banned words."""
    if not text:
        return True
    text_lower = text.lower()
    for word in BANNED_WORDS:
        # Simple containment check; for production use regex with word boundaries
        if word in text_lower:
            return False
    return True

@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf_token")
        if not token or token != request.form.get("_csrf_token"):
            return "CSRF token missing or invalid", 400

def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = uuid.uuid4().hex
    return session["_csrf_token"]

app.jinja_env.globals["csrf_token"] = generate_csrf_token

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                handle TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                avatar_path TEXT,
                bio TEXT,
                hobbies TEXT,
                share_link TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT 'signup',
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                media_path TEXT,
                media_type TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS followers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                follower_id INTEGER NOT NULL,
                following_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (follower_id) REFERENCES users (id),
                FOREIGN KEY (following_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, post_id),
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (post_id) REFERENCES posts (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (post_id) REFERENCES posts (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY (reporter_id) REFERENCES users (id),
                FOREIGN KEY (post_id) REFERENCES posts (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (actor_id) REFERENCES users (id),
                FOREIGN KEY (post_id) REFERENCES posts (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_reads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                last_read_message_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(conversation_id, user_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                last_message_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(conversation_id, user_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id),
                FOREIGN KEY (sender_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                UNIQUE(requester_id, recipient_id),
                FOREIGN KEY (requester_id) REFERENCES users (id),
                FOREIGN KEY (recipient_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "users", "avatar_path", "avatar_path TEXT")
        ensure_column(conn, "users", "bio", "bio TEXT")
        ensure_column(conn, "users", "hobbies", "hobbies TEXT")
        ensure_column(conn, "users", "share_link", "share_link TEXT")
        ensure_column(conn, "users", "last_active_at", "last_active_at TEXT")
        ensure_column(conn, "users", "last_chat_active_at", "last_chat_active_at TEXT")
        ensure_column(
            conn,
            "users",
            "last_active_conversation_id",
            "last_active_conversation_id INTEGER",
        )
        ensure_column(conn, "posts", "media_path", "media_path TEXT")
        ensure_column(conn, "posts", "media_type", "media_type TEXT")
        ensure_column(conn, "posts", "is_hidden", "is_hidden INTEGER DEFAULT 0")
        ensure_column(
            conn,
            "verification_codes",
            "purpose",
            "purpose TEXT NOT NULL DEFAULT 'signup'",
        )

        admin_count = conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()[
            "count"
        ]
        if admin_count == 0:
            conn.execute(
                """
                INSERT INTO admin_users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                ("admin", generate_password_hash("admin"), datetime.utcnow().isoformat()),
            )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return user


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def is_admin(user) -> bool:
    if not user:
        return False
    admin_email = os.environ.get("TALKI_ADMIN_EMAIL")
    if admin_email:
        return user["email"].lower() == admin_email.lower()
    return user["id"] == 1


def create_notification(
    user_id: int,
    actor_id: int,
    post_id: int,
    notif_type: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    if user_id == actor_id:
        return
    if conn is None:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO notifications (user_id, actor_id, post_id, type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, actor_id, post_id, notif_type, datetime.now(timezone.utc).isoformat()),
            )
    else:
        conn.execute(
            """
            INSERT INTO notifications (user_id, actor_id, post_id, type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, actor_id, post_id, notif_type, datetime.now(timezone.utc).isoformat()),
        )


def nav_items(active: str) -> list[dict]:
    items = [
        {"label": "Posts", "href": url_for("posts")},
        {"label": "Chat", "href": url_for("chat")},
        {"label": "Profile", "href": url_for("profile")},
        {"label": "Settings", "href": url_for("settings")},
    ]
    for item in items:
        item["active"] = item["label"].lower() == active
    return items


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapper


@app.before_request
def redirect_logged_in_from_auth_pages():
    if request.endpoint in {"login", "signup", "forgot_password", "reset_password"} and current_user():
        return redirect(url_for("posts"))


@app.before_request
def touch_last_active():
    user_id = session.get("user_id")
    if not user_id:
        return
    if request.endpoint == "static" or request.endpoint is None:
        return
    active_chat_endpoints = {"chat", "chat_messages", "chat_send"}
    if request.endpoint not in active_chat_endpoints:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE users
                SET last_chat_active_at = NULL,
                    last_active_conversation_id = NULL
                WHERE id = ?
                """,
                (user_id,),
            )
    now_ts = time.time()
    last_ping = session.get("last_active_ping", 0)
    if now_ts - last_ping < 30:
        return
    session["last_active_ping"] = now_ts
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_active_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), user_id),
        )


@app.route("/")
def index():
    if current_user():
        return redirect(url_for("posts"))
    return redirect(url_for("login"))


def send_verification_email(to_email: str, code: str) -> None:
    smtp_email = os.environ.get("TALKI_SMTP_EMAIL")
    smtp_password = os.environ.get("TALKI_SMTP_PASSWORD")
    if not smtp_email or not smtp_password:
        raise RuntimeError(
            "Email sending is not configured. Set TALKI_SMTP_EMAIL and TALKI_SMTP_PASSWORD."
        )

    message = EmailMessage()
    message["Subject"] = "Your Talki verification code"
    message["From"] = smtp_email
    message["To"] = to_email
    message.set_content(
        f"Your Talki verification code is {code}. It expires in 10 minutes."
    )
    message.add_alternative(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>Talki Verification</title>
          </head>
          <body style="margin:0;background:#0b1120;color:#e2e8f0;font-family:Arial,Helvetica,sans-serif;">
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#0b1120;padding:24px 12px;">
              <tr>
                <td align="center">
                  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px;background:#111827;border-radius:20px;overflow:hidden;border:1px solid rgba(255,255,255,0.08);">
                    <tr>
                      <td style="padding:24px 28px;background:linear-gradient(135deg,#0ea5a4 0%,#fb7185 100%);">
                        <p style="margin:0;font-size:14px;letter-spacing:3px;text-transform:uppercase;color:#ffffff;">Talki</p>
                        <h1 style="margin:8px 0 0;font-size:22px;color:#ffffff;">Confirm your email</h1>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:24px 28px;">
                        <p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:#cbd5f5;">
                          Use the verification code below to finish signing in. This code expires in 10 minutes.
                        </p>
                        <div style="margin:20px 0;padding:16px 20px;border-radius:14px;background:rgba(15,23,42,0.8);border:1px solid rgba(255,255,255,0.14);text-align:center;box-shadow:0 16px 30px rgba(0,0,0,0.25);">
                          <span style="font-size:28px;letter-spacing:6px;font-weight:700;color:#ffffff;" class="code-text">{code}</span>
                        </div>
                        <p style="margin:0;font-size:12px;line-height:1.6;color:#94a3b8;">
                          If you did not request this code, you can safely ignore this email.
                        </p>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:18px 28px;background:#0b1120;border-top:1px solid rgba(255,255,255,0.06);">
                        <p style="margin:0;font-size:11px;color:#64748b;">Talki Team</p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_email, smtp_password)
        server.send_message(message)


def allowed_file(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def normalize_handle(value: str) -> str:
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    return value


def get_conversation_between(conn: sqlite3.Connection, user_id: int, other_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT c.id
        FROM conversations c
        JOIN conversation_participants cp1
          ON cp1.conversation_id = c.id AND cp1.user_id = ?
        JOIN conversation_participants cp2
          ON cp2.conversation_id = c.id AND cp2.user_id = ?
        LIMIT 1
        """,
        (user_id, other_id),
    ).fetchone()
    return row["id"] if row else None


def get_or_create_conversation(
    conn: sqlite3.Connection, user_id: int, other_id: int
) -> int:
    existing = get_conversation_between(conn, user_id, other_id)
    if existing:
        return existing
    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        """
        INSERT INTO conversations (created_at, last_message_at)
        VALUES (?, ?)
        """,
        (now, None),
    )
    conversation_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO conversation_participants (conversation_id, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (conversation_id, user_id, now),
    )
    conn.execute(
        """
        INSERT INTO conversation_participants (conversation_id, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (conversation_id, other_id, now),
    )
    return conversation_id


def store_verification_code(email: str, code: str, purpose: str) -> None:
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    code_hash = generate_password_hash(code)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO verification_codes (email, code_hash, purpose, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (email, code_hash, purpose, expires_at, datetime.utcnow().isoformat()),
        )


def latest_code_record(email: str, purpose: str):
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM verification_codes
            WHERE email = ? AND purpose = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (email, purpose),
        ).fetchone()


def cooldown_remaining_seconds(email: str, purpose: str) -> int:
    record = latest_code_record(email, purpose)
    if not record:
        return 0
    created_at = datetime.fromisoformat(record["created_at"])
    elapsed = (datetime.utcnow() - created_at).total_seconds()
    remaining = CODE_COOLDOWN_SECONDS - int(elapsed)
    return max(0, remaining)


def verify_code(email: str, code: str, purpose: str) -> bool:
    record = latest_code_record(email, purpose)
    if not record:
        return False
    if datetime.fromisoformat(record["expires_at"]) < datetime.utcnow():
        return False
    return check_password_hash(record["code_hash"], code)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    notice = None
    code_status = None
    cooldown_seconds = 0
    form_data = {
        "name": "",
        "email": "",
        "handle": "",
    }

    if request.method == "POST":
        action = request.form.get("action")
        form_data["name"] = request.form.get("name", "").strip()
        form_data["email"] = request.form.get("email", "").strip().lower()
        form_data["handle"] = normalize_handle(request.form.get("handle", ""))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        code = request.form.get("code", "").strip()

        if action == "send_code":
            if not form_data["email"]:
                error = "Please enter an email to receive a code."
            else:
                with get_db() as conn:
                    existing = conn.execute(
                        "SELECT id FROM users WHERE email = ?",
                        (form_data["email"],),
                    ).fetchone()
                if existing:
                    error = "Email already registered. Try logging in."
                else:
                    cooldown_seconds = cooldown_remaining_seconds(form_data["email"], "signup")
                    if cooldown_seconds > 0:
                        error = (
                            f"Please wait {cooldown_seconds} seconds before resending."
                        )
                    else:
                        code_value = f"{random.randint(0, 999999):06d}"
                        try:
                            store_verification_code(form_data["email"], code_value, "signup")
                            send_verification_email(form_data["email"], code_value)
                            notice = "Verification code sent. Check your inbox."
                            cooldown_seconds = CODE_COOLDOWN_SECONDS
                        except RuntimeError as exc:
                            error = str(exc)
                        except Exception:
                            error = "Unable to send email right now. Try again later."

        if action == "create_account":
            if not all([form_data["name"], form_data["email"], form_data["handle"], password]):
                error = "Please complete all fields before creating your account."
            elif not code:
                error = "Enter the 6-digit verification code."
            else:
                if not verify_code(form_data["email"], code, "signup"):
                    code_status = "bad"
                    error = "Verification code is incorrect or expired."
                elif password != confirm_password:
                    code_status = "ok"
                    error = "Passwords do not match."
                else:
                    code_status = "ok"
                    with get_db() as conn:
                        try:
                            conn.execute(
                                """
                                INSERT INTO users (email, name, handle, password_hash, verified, created_at)
                                VALUES (?, ?, ?, ?, 1, ?)
                                """,
                                (
                                    form_data["email"],
                                    form_data["name"],
                                    form_data["handle"],
                                    generate_password_hash(password),
                                    datetime.utcnow().isoformat(),
                                ),
                            )
                            session.pop("user_id", None)
                            session["signup_notice"] = "Account created. Please sign in."
                            code_status = "ok"
                            return redirect(url_for("login"))
                        except sqlite3.IntegrityError:
                            error = "Email or handle already exists. Try logging in."

    if form_data["email"] and not cooldown_seconds:
        cooldown_seconds = cooldown_remaining_seconds(form_data["email"], "signup")

    return render_template(
        "signup.html",
        nav=[],
        year=datetime.now().year,
        error=error,
        notice=notice,
        code_status=code_status,
        cooldown_seconds=cooldown_seconds,
        form_data=form_data,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    email_or_handle = ""
    notice = session.pop("signup_notice", None)

    if request.method == "POST":
        email_or_handle = request.form.get("email_or_handle", "").strip().lower()
        if email_or_handle.startswith("@"):
            email_or_handle = email_or_handle[1:]
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                """
                SELECT * FROM users
                WHERE email = ? OR LOWER(handle) = ?
                """,
                (email_or_handle, email_or_handle),
            ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Invalid credentials."
        else:
            session["user_id"] = user["id"]
            return redirect(url_for("posts"))

    return render_template(
        "login.html",
        nav=[],
        year=datetime.now().year,
        error=error,
        notice=notice,
        email_or_handle=email_or_handle,
    )


@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    error = None
    notice = None
    identifier = ""
    cooldown_seconds = 0
    email = None

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        if not identifier:
            error = "Enter your email or handle."
        else:
            with get_db() as conn:
                user = conn.execute(
                    """
                    SELECT * FROM users
                    WHERE email = ? OR LOWER(handle) = ?
                    """,
                    (identifier, identifier),
                ).fetchone()
            if not user:
                error = "Account not found."
            else:
                email = user["email"]
                cooldown_seconds = cooldown_remaining_seconds(email, "reset")
                if cooldown_seconds > 0:
                    error = f"Please wait {cooldown_seconds} seconds before resending."
                else:
                    code_value = f"{random.randint(0, 999999):06d}"
                    try:
                        store_verification_code(email, code_value, "reset")
                        send_verification_email(email, code_value)
                        notice = "Verification code sent. Check your inbox."
                        cooldown_seconds = CODE_COOLDOWN_SECONDS
                        session["reset_email"] = email
                        session["reset_notice"] = notice
                        return redirect(url_for("reset_password"))
                    except RuntimeError as exc:
                        error = str(exc)
                    except Exception:
                        error = "Unable to send email right now. Try again later."

    if not email and identifier:
        with get_db() as conn:
            user = conn.execute(
                """
                SELECT * FROM users
                WHERE email = ? OR LOWER(handle) = ?
                """,
                (identifier, identifier),
            ).fetchone()
        if user:
            email = user["email"]

    if email and not cooldown_seconds:
        cooldown_seconds = cooldown_remaining_seconds(email, "reset")

    return render_template(
        "forgot_password.html",
        nav=[],
        year=datetime.now().year,
        error=error,
        notice=notice,
        identifier=identifier,
        cooldown_seconds=cooldown_seconds,
    )


@app.route("/reset", methods=["GET", "POST"])
def reset_password():
    error = None
    notice = session.pop("reset_notice", None)
    code_status = None
    cooldown_seconds = 0
    email = session.get("reset_email")

    if not email:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        action = request.form.get("action")
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if action == "send_code":
            cooldown_seconds = cooldown_remaining_seconds(email, "reset")
            if cooldown_seconds > 0:
                error = f"Please wait {cooldown_seconds} seconds before resending."
            else:
                code_value = f"{random.randint(0, 999999):06d}"
                try:
                    store_verification_code(email, code_value, "reset")
                    send_verification_email(email, code_value)
                    notice = "Verification code sent. Check your inbox."
                    cooldown_seconds = CODE_COOLDOWN_SECONDS
                except RuntimeError as exc:
                    error = str(exc)
                except Exception:
                    error = "Unable to send email right now. Try again later."

        if action == "reset_password":
            if not code:
                error = "Enter the 6-digit verification code."
            elif not verify_code(email, code, "reset"):
                code_status = "bad"
                error = "Verification code is incorrect or expired."
            elif not password:
                code_status = "ok"
                error = "Enter a new password."
            elif password != confirm_password:
                code_status = "ok"
                error = "Passwords do not match."
            else:
                code_status = "ok"
                with get_db() as conn:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE email = ?",
                        (generate_password_hash(password), email),
                    )
                    user_id = conn.execute(
                        "SELECT id FROM users WHERE email = ?",
                        (email,),
                    ).fetchone()["id"]
                session["user_id"] = user_id
                session.pop("reset_email", None)
                return redirect(url_for("posts"))

    if not cooldown_seconds:
        cooldown_seconds = cooldown_remaining_seconds(email, "reset")

    return render_template(
        "reset_password.html",
        nav=[],
        year=datetime.now().year,
        error=error,
        notice=notice,
        code_status=code_status,
        cooldown_seconds=cooldown_seconds,
        email=email,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/posts", methods=["GET", "POST"])
@login_required
def posts():
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        media = request.files.get("media")
        media_path = None
        media_type = None
        if media and media.filename:
            if not allowed_file(media.filename, ALLOWED_MEDIA_EXTENSIONS):
                session["posts_error"] = "Only images or videos are allowed."
                return redirect(url_for("posts"))
            os.makedirs(POSTS_FOLDER, exist_ok=True)
            extension = media.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{uuid.uuid4().hex}.{extension}")
            save_path = os.path.join(POSTS_FOLDER, filename)
            media.save(save_path)
            media_path = f"uploads/posts/{filename}"
            media_type = "video" if extension in {"mp4", "webm", "mov"} else "image"

        if content or media_path:
            if not check_content(content):
                session["posts_error"] = "Your post contains inappropriate language."
                # Clean up uploaded file if rejected
                if media_path:
                    try:
                        os.remove(os.path.join(app.root_path, "static", media_path))
                    except OSError:
                        pass
                return redirect(url_for("posts"))

            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO posts (user_id, content, media_path, media_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session.get("user_id"),
                        content if content else "",
                        media_path,
                        media_type,
                        datetime.utcnow().isoformat(),
                    ),
                )
        return redirect(url_for("posts"))

    with get_db() as conn:
        post_rows = conn.execute(
            """
            SELECT posts.id,
                   posts.content,
                   posts.created_at,
                   posts.media_path,
                   posts.media_type,
                   users.id AS author_id,
                   users.name,
                   users.handle,
                   users.avatar_path,
                   (SELECT COUNT(*) FROM likes WHERE post_id = posts.id) AS like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id = posts.id) AS comment_count,
                   (SELECT COUNT(*) FROM followers WHERE follower_id = ? AND following_id = users.id) AS is_following,
                   (SELECT COUNT(*) FROM likes WHERE post_id = posts.id AND user_id = ?) AS liked_by_me
            FROM posts
            JOIN users ON users.id = posts.user_id
            WHERE posts.is_hidden = 0
            ORDER BY posts.created_at DESC
            """
        , (session.get("user_id"), session.get("user_id"))).fetchall()
        suggested_rows = conn.execute(
            """
            SELECT id, name, handle, avatar_path
            FROM users
            WHERE id != ?
              AND id NOT IN (
                SELECT following_id
                FROM followers
                WHERE follower_id = ?
              )
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (session.get("user_id"), session.get("user_id")),
        ).fetchall()
        posts_error = session.pop("posts_error", None)

    def time_ago(ts: str) -> str:
        created = datetime.fromisoformat(ts)
        delta = datetime.utcnow() - created
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"

    feed = [
        {
            "id": row["id"],
            "author_id": row["author_id"],
            "name": row["name"],
            "handle": f"@{row['handle']}",
            "time": time_ago(row["created_at"]),
            "text": row["content"],
            "avatar_path": row["avatar_path"],
            "media_path": row["media_path"],
            "media_type": row["media_type"],
            "like_count": row["like_count"],
            "comment_count": row["comment_count"],
            "is_following": row["is_following"] > 0,
            "liked_by_me": row["liked_by_me"] > 0,
            "is_owner": row["author_id"] == session.get("user_id"),
        }
        for row in post_rows
    ]
    comments_by_post = {}
    post_ids = [row["id"] for row in post_rows]
    if post_ids:
        placeholders = ",".join(["?"] * len(post_ids))
        with get_db() as conn:
            comment_rows = conn.execute(
                f"""
                SELECT comments.id,
                       comments.post_id,
                       comments.user_id,
                       comments.content,
                       comments.created_at,
                       users.name,
                       users.handle
                FROM comments
                JOIN users ON users.id = comments.user_id
                WHERE comments.post_id IN ({placeholders})
                ORDER BY comments.created_at ASC
                """,
                post_ids,
            ).fetchall()
        for row in comment_rows:
            comments_by_post.setdefault(row["post_id"], []).append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "name": row["name"],
                    "handle": f"@{row['handle']}",
                    "content": row["content"],
                    "created_at": row["created_at"],
                }
            )
    return render_template(
        "posts.html",
        nav=nav_items("posts"),
        posts=feed,
        comments_by_post=comments_by_post,
        suggested=suggested_rows,
        posts_error=posts_error,
        year=datetime.now().year,
    )


@app.route("/chat")
@app.route("/chat/<int:conversation_id>")
@login_required
def chat(conversation_id: int | None = None):
    user_id = session.get("user_id")
    chat_notice = session.pop("chat_notice", None)
    search_query = request.args.get("q", "").strip()
    open_new_modal = request.args.get("new") == "1" or bool(search_query)

    def time_ago(ts: str | None) -> str:
        if not ts:
            return ""
        created = datetime.fromisoformat(ts)
        delta = datetime.utcnow() - created
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"

    def format_time(ts: str | None) -> str:
        if not ts:
            return ""
        try:
            return datetime.fromisoformat(ts).strftime("%H:%M")
        except ValueError:
            return ts

    conversations = []
    active_user = None
    active_user_online = False
    active_user_status = ""
    other_last_read_id = 0
    last_outgoing_id = 0
    last_outgoing_status = ""
    last_outgoing_time = ""
    messages = []
    search_results = []

    with get_db() as conn:
        convo_rows = conn.execute(
            """
            SELECT c.id,
                   c.created_at,
                   c.last_message_at,
                   u.id AS other_id,
                   u.name,
                   u.handle,
                   u.avatar_path,
                   (
                       SELECT body
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.created_at DESC
                       LIMIT 1
                   ) AS last_message
            FROM conversations c
            JOIN conversation_participants cps
              ON cps.conversation_id = c.id AND cps.user_id = ?
            JOIN conversation_participants cpo
              ON cpo.conversation_id = c.id AND cpo.user_id != ?
            JOIN users u ON u.id = cpo.user_id
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
            """,
            (user_id, user_id),
        ).fetchall()

        if conversation_id is None and convo_rows:
            conversation_id = convo_rows[0]["id"]

        for row in convo_rows:
            last_ts = row["last_message_at"] or row["created_at"]
            conversations.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "handle": row["handle"],
                    "avatar_path": row["avatar_path"],
                    "last": row["last_message"] or "No messages yet.",
                    "time": time_ago(last_ts),
                    "active": conversation_id == row["id"],
                }
            )

        if conversation_id is not None:
            is_member = conn.execute(
                """
                SELECT 1
                FROM conversation_participants
                WHERE conversation_id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
            if is_member:
                conn.execute(
                    """
                    UPDATE users
                    SET last_chat_active_at = ?, last_active_conversation_id = ?
                    WHERE id = ?
                    """,
                    (datetime.utcnow().isoformat(), conversation_id, user_id),
                )
                active_user = conn.execute(
                    """
                    SELECT users.id,
                           users.name,
                           users.handle,
                           users.avatar_path,
                           users.last_active_at,
                           users.last_chat_active_at,
                           users.last_active_conversation_id
                    FROM conversation_participants cp
                    JOIN users ON users.id = cp.user_id
                    WHERE cp.conversation_id = ? AND users.id != ?
                    LIMIT 1
                    """,
                    (conversation_id, user_id),
                ).fetchone()
                message_rows = conn.execute(
                    """
                    SELECT messages.id,
                           messages.sender_id,
                           messages.body,
                           messages.created_at
                    FROM messages
                    WHERE messages.conversation_id = ?
                    ORDER BY messages.created_at ASC
                    """,
                    (conversation_id,),
                ).fetchall()
                if message_rows:
                    last_message_id = message_rows[-1]["id"]
                    conn.execute(
                        """
                        INSERT INTO conversation_reads
                          (conversation_id, user_id, last_read_message_id, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(conversation_id, user_id)
                        DO UPDATE SET last_read_message_id = excluded.last_read_message_id,
                                      updated_at = excluded.updated_at
                        """,
                        (conversation_id, user_id, last_message_id, datetime.utcnow().isoformat()),
                    )
                if active_user:
                    read_row = conn.execute(
                        """
                        SELECT last_read_message_id
                        FROM conversation_reads
                        WHERE conversation_id = ? AND user_id = ?
                        """,
                        (conversation_id, active_user["id"]),
                    ).fetchone()
                    if read_row:
                        other_last_read_id = read_row["last_read_message_id"]
                    now_chat = datetime.utcnow()
                    in_chat = False
                    if (
                        active_user["last_active_conversation_id"] == conversation_id
                        and active_user["last_chat_active_at"]
                    ):
                        try:
                            chat_delta = now_chat - datetime.fromisoformat(
                                active_user["last_chat_active_at"]
                            )
                            in_chat = chat_delta.total_seconds() <= 90
                        except ValueError:
                            in_chat = False
                    if active_user["last_active_at"]:
                        try:
                            active_delta = datetime.utcnow() - datetime.fromisoformat(
                                active_user["last_active_at"]
                            )
                            active_user_online = active_delta.total_seconds() <= 120
                            active_user_status = (
                                "Online" if active_user_online else f"Last seen {time_ago(active_user['last_active_at'])}"
                            )
                        except ValueError:
                            active_user_status = "Offline"
                    else:
                        active_user_status = "Offline"

                for row in message_rows:
                    if row["sender_id"] == user_id:
                        last_outgoing_id = row["id"]

                if last_outgoing_id:
                    last_outgoing_row = next(
                        (row for row in reversed(message_rows) if row["id"] == last_outgoing_id),
                        None,
                    )
                    if last_outgoing_row:
                        last_outgoing_time = format_time(last_outgoing_row["created_at"])
                        if other_last_read_id >= last_outgoing_id or in_chat:
                            last_outgoing_status = "Seen"
                        else:
                            last_outgoing_status = "Sent"
                messages = [
                    {
                        "id": row["id"],
                        "from_me": row["sender_id"] == user_id,
                        "text": row["body"],
                        "created_at": row["created_at"],
                        "time": format_time(row["created_at"]),
                        "show_meta": row["id"] == last_outgoing_id,
                        "status": last_outgoing_status if row["id"] == last_outgoing_id else "",
                    }
                    for row in message_rows
                ]
            else:
                conversation_id = None

        if search_query:
            normalized = normalize_handle(search_query)
            search_like = f"%{normalized.lower()}%"
            search_results = conn.execute(
                """
                SELECT id, name, handle, email, avatar_path
                FROM users
                WHERE id != ?
                  AND (
                    LOWER(handle) LIKE ?
                    OR LOWER(email) LIKE ?
                    OR LOWER(name) LIKE ?
                  )
                ORDER BY created_at DESC
                LIMIT 8
                """,
                (user_id, search_like, search_like, search_like),
            ).fetchall()

    return render_template(
        "chat.html",
        nav=nav_items("chat"),
        conversations=conversations,
        messages=messages,
        active_user=active_user,
        active_user_online=active_user_online,
        active_user_status=active_user_status,
        active_conversation_id=conversation_id,
        last_outgoing_id=last_outgoing_id,
        last_outgoing_status=last_outgoing_status,
        last_outgoing_time=last_outgoing_time,
        chat_notice=chat_notice,
        search_query=search_query,
        search_results=search_results,
        open_new_modal=open_new_modal,
        full_bleed=True,
        hide_nav_on_mobile=True,
        year=datetime.now().year,
    )


@app.route("/chat/<int:conversation_id>/messages")
@login_required
def chat_messages(conversation_id: int):
    user_id = session.get("user_id")
    after_id = request.args.get("after_id", type=int) or 0
    with get_db() as conn:
        is_member = conn.execute(
            """
            SELECT 1
            FROM conversation_participants
            WHERE conversation_id = ? AND user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
        if not is_member:
            return {"messages": []}
        conn.execute(
            """
            UPDATE users
            SET last_chat_active_at = ?, last_active_conversation_id = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), conversation_id, user_id),
        )
        rows = conn.execute(
            """
            SELECT id, sender_id, body, created_at
            FROM messages
            WHERE conversation_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (conversation_id, after_id),
        ).fetchall()
        other_user = conn.execute(
            """
            SELECT users.id,
                   users.last_active_at,
                   users.last_chat_active_at,
                   users.last_active_conversation_id
            FROM conversation_participants cp
            JOIN users ON users.id = cp.user_id
            WHERE cp.conversation_id = ? AND users.id != ?
            LIMIT 1
            """,
            (conversation_id, user_id),
        ).fetchone()
        other_last_read_id = 0
        if other_user:
            read_row = conn.execute(
                """
                SELECT last_read_message_id
                FROM conversation_reads
                WHERE conversation_id = ? AND user_id = ?
                """,
                (conversation_id, other_user["id"]),
            ).fetchone()
            if read_row:
                other_last_read_id = read_row["last_read_message_id"]
        last_outgoing_row = conn.execute(
            """
            SELECT id, created_at
            FROM messages
            WHERE conversation_id = ? AND sender_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, user_id),
        ).fetchone()
        last_outgoing_id = last_outgoing_row["id"] if last_outgoing_row else 0
        last_outgoing_time = (
            datetime.fromisoformat(last_outgoing_row["created_at"]).strftime("%H:%M")
            if last_outgoing_row
            else ""
        )
        active_user_online = False
        active_user_status = "Offline"
        in_chat = False
        if other_user and other_user["last_active_at"]:
            try:
                active_delta = datetime.utcnow() - datetime.fromisoformat(
                    other_user["last_active_at"]
                )
                active_user_online = active_delta.total_seconds() <= 120
                active_user_status = (
                    "Online"
                    if active_user_online
                    else f"Last seen {max(1, int(active_delta.total_seconds() // 60))}m"
                )
            except ValueError:
                active_user_status = "Offline"
        if (
            other_user
            and other_user["last_active_conversation_id"] == conversation_id
            and other_user["last_chat_active_at"]
        ):
            try:
                chat_delta = datetime.utcnow() - datetime.fromisoformat(
                    other_user["last_chat_active_at"]
                )
                in_chat = chat_delta.total_seconds() <= 90
            except ValueError:
                in_chat = False
        if last_outgoing_id:
            if other_last_read_id >= last_outgoing_id or in_chat:
                last_outgoing_status = "Seen"
            else:
                last_outgoing_status = "Sent"
        else:
            last_outgoing_status = ""
        messages = [
            {
                "id": row["id"],
                "from_me": row["sender_id"] == user_id,
                "text": row["body"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        if rows:
            last_message_id = rows[-1]["id"]
            conn.execute(
                """
                INSERT INTO conversation_reads
                  (conversation_id, user_id, last_read_message_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id, user_id)
                DO UPDATE SET last_read_message_id = excluded.last_read_message_id,
                              updated_at = excluded.updated_at
                """,
                (conversation_id, user_id, last_message_id, datetime.utcnow().isoformat()),
            )
    return {
        "messages": messages,
        "other_online": active_user_online,
        "other_status": active_user_status,
        "other_last_read_id": other_last_read_id,
        "last_outgoing_id": last_outgoing_id,
        "last_outgoing_status": last_outgoing_status,
        "last_outgoing_time": last_outgoing_time,
    }


@app.route("/chat/<int:conversation_id>/send", methods=["POST"])
@login_required
def chat_send(conversation_id: int):
    message_body = request.form.get("message", "").strip()
    if not message_body:
        return redirect(url_for("chat", conversation_id=conversation_id))
    
    if not check_content(message_body):
        session["chat_notice"] = "Message not sent: Contains inappropriate language."
        return redirect(url_for("chat", conversation_id=conversation_id))
        
    user_id = session.get("user_id")
    with get_db() as conn:
        is_member = conn.execute(
            """
            SELECT 1
            FROM conversation_participants
            WHERE conversation_id = ? AND user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
        if not is_member:
            return redirect(url_for("chat"))
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE users
            SET last_chat_active_at = ?, last_active_conversation_id = ?
            WHERE id = ?
            """,
            (now, conversation_id, user_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, user_id, message_body, now),
        )
        message_id = cursor.lastrowid
        conn.execute(
            """
            UPDATE conversations
            SET last_message_at = ?
            WHERE id = ?
            """,
            (now, conversation_id),
        )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return {
            "id": message_id,
            "from_me": True,
            "text": message_body,
            "created_at": now,
        }
    return redirect(url_for("chat", conversation_id=conversation_id))


@app.route("/chat/request", methods=["POST"])
@login_required
def chat_request():
    recipient_id = request.form.get("recipient_id", type=int)
    if not recipient_id or recipient_id == session.get("user_id"):
        return redirect(url_for("chat"))
    with get_db() as conn:
        recipient = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (recipient_id,),
        ).fetchone()
        if not recipient:
            return redirect(url_for("chat"))
        conversation_id = get_or_create_conversation(
            conn, session.get("user_id"), recipient_id
        )
        try:
            conn.execute(
                """
                INSERT INTO chat_requests (requester_id, recipient_id, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (session.get("user_id"), recipient_id, datetime.utcnow().isoformat()),
            )
        except sqlite3.IntegrityError:
            pass
    session["chat_notice"] = "Chat request sent."
    return redirect(url_for("chat", conversation_id=conversation_id))


@app.route("/chat/start/<int:user_id>")
@login_required
def chat_start(user_id: int):
    if user_id == session.get("user_id"):
        return redirect(url_for("profile"))
    with get_db() as conn:
        other = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not other:
            return redirect(url_for("chat"))
        conversation_id = get_or_create_conversation(conn, session.get("user_id"), user_id)
    return redirect(url_for("chat", conversation_id=conversation_id))


@app.route("/profile")
@login_required
def profile():
    user = current_user()
    profile_error = session.pop("profile_error", None)
    profile_notice = session.pop("profile_notice", None)
    joined_date = None
    if user and user["created_at"]:
        try:
            joined_date = datetime.fromisoformat(user["created_at"]).strftime("%d/%m/%Y")
        except ValueError:
            joined_date = user["created_at"]
    share_url = None
    if user and user["share_link"]:
        if user["share_link"].startswith("http://") or user["share_link"].startswith("https://"):
            share_url = user["share_link"]
        else:
            share_url = f"https://{user['share_link']}"

    with get_db() as conn:
        followers_count = conn.execute(
            "SELECT COUNT(*) AS count FROM followers WHERE following_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        following_count = conn.execute(
            "SELECT COUNT(*) AS count FROM followers WHERE follower_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        posts_count = conn.execute(
            "SELECT COUNT(*) AS count FROM posts WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        following_list = conn.execute(
            """
            SELECT users.id, users.name, users.handle, users.avatar_path
            FROM followers
            JOIN users ON users.id = followers.following_id
            WHERE followers.follower_id = ?
            ORDER BY followers.created_at DESC
            LIMIT 12
            """,
            (user["id"],),
        ).fetchall()
        media_rows = conn.execute(
            """
            SELECT media_path, media_type
            FROM posts
            WHERE user_id = ? AND media_path IS NOT NULL
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
        recent_rows = conn.execute(
            """
            SELECT content, created_at
            FROM posts
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (user["id"],),
        ).fetchall()
        recent_posts = [
            {
                "content": row["content"],
                "created_at": datetime.fromisoformat(row["created_at"]).strftime("%d/%m/%Y %H:%M"),
            }
            for row in recent_rows
        ]
    return render_template(
        "profile.html",
        nav=nav_items("profile"),
        year=datetime.now().year,
        user=user,
        joined_date=joined_date,
        share_url=share_url,
        followers_count=followers_count,
        following_count=following_count,
        posts_count=posts_count,
        following_list=following_list,
        media_posts=media_rows,
        recent_posts=recent_posts,
        profile_error=profile_error,
        profile_notice=profile_notice,
    )


@app.route("/profile/upload", methods=["POST"])
@login_required
def profile_upload():
    file = request.files.get("avatar")
    if not file or file.filename == "":
        session["profile_error"] = "Please choose an image to upload."
        return redirect(url_for("profile"))
    if not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        session["profile_error"] = "Only PNG, JPG, JPEG, GIF, or WEBP files are allowed."
        return redirect(url_for("profile"))

    os.makedirs(AVATAR_FOLDER, exist_ok=True)
    extension = file.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(f"{uuid.uuid4().hex}.{extension}")
    save_path = os.path.join(AVATAR_FOLDER, filename)
    file.save(save_path)

    relative_path = f"uploads/avatars/{filename}"
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET avatar_path = ? WHERE id = ?",
            (relative_path, session.get("user_id")),
        )
    session["profile_notice"] = "Profile image updated."
    return redirect(url_for("profile"))


@app.route("/profile/update", methods=["POST"])
@login_required
def profile_update():
    name = request.form.get("name", "").strip()
    handle = normalize_handle(request.form.get("handle", ""))
    bio = request.form.get("bio", "").strip()
    hobbies = request.form.get("hobbies", "").strip()
    share_link = request.form.get("share_link", "").strip()
    if not name or not handle:
        session["profile_error"] = "Name and handle are required."
        return redirect(url_for("profile"))
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE handle = ? AND id != ?",
            (handle, session.get("user_id")),
        ).fetchone()
        if existing:
            session["profile_error"] = "Handle already taken."
            return redirect(url_for("profile"))
        conn.execute(
            """
            UPDATE users
            SET name = ?, handle = ?, bio = ?, hobbies = ?, share_link = ?
            WHERE id = ?
            """,
            (name, handle, bio, hobbies, share_link, session.get("user_id")),
        )
    session["profile_notice"] = "Profile updated."
    return redirect(url_for("profile"))


@app.route("/u/<handle>")
def public_profile(handle: str):
    handle = normalize_handle(handle)
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE handle = ?",
            (handle,),
        ).fetchone()
        if not user:
            return redirect(url_for("login"))

        followers_count = conn.execute(
            "SELECT COUNT(*) AS count FROM followers WHERE following_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        following_count = conn.execute(
            "SELECT COUNT(*) AS count FROM followers WHERE follower_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        posts_count = conn.execute(
            "SELECT COUNT(*) AS count FROM posts WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["count"]
        followers_list = conn.execute(
            """
            SELECT users.id, users.name, users.handle, users.avatar_path
            FROM followers
            JOIN users ON users.id = followers.follower_id
            WHERE followers.following_id = ?
            ORDER BY followers.created_at DESC
            LIMIT 12
            """,
            (user["id"],),
        ).fetchall()
        following_list = conn.execute(
            """
            SELECT users.id, users.name, users.handle, users.avatar_path
            FROM followers
            JOIN users ON users.id = followers.following_id
            WHERE followers.follower_id = ?
            ORDER BY followers.created_at DESC
            LIMIT 12
            """,
            (user["id"],),
        ).fetchall()
        media_rows = conn.execute(
            """
            SELECT media_path, media_type
            FROM posts
            WHERE user_id = ? AND media_path IS NOT NULL
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
        post_rows = conn.execute(
            """
            SELECT content, created_at
            FROM posts
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
        recent_rows = conn.execute(
            """
            SELECT content, created_at
            FROM posts
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (user["id"],),
        ).fetchall()

    joined_date = None
    if user and user["created_at"]:
        try:
            joined_date = datetime.fromisoformat(user["created_at"]).strftime("%d/%m/%Y")
        except ValueError:
            joined_date = user["created_at"]

    share_url = None
    if user and user["share_link"]:
        if user["share_link"].startswith("http://") or user["share_link"].startswith("https://"):
            share_url = user["share_link"]
        else:
            share_url = f"https://{user['share_link']}"

    viewer = current_user()
    is_self = viewer and viewer["id"] == user["id"]
    is_following = False
    if viewer and not is_self:
        with get_db() as conn:
            is_following = (
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM followers
                    WHERE follower_id = ? AND following_id = ?
                    """,
                    (viewer["id"], user["id"]),
                ).fetchone()["count"]
                > 0
            )

    recent_posts = [
        {
            "content": row["content"],
            "created_at": datetime.fromisoformat(row["created_at"]).strftime("%d/%m/%Y %H:%M"),
        }
        for row in recent_rows
    ]
    all_posts = [
        {
            "content": row["content"],
            "created_at": datetime.fromisoformat(row["created_at"]).strftime("%d/%m/%Y %H:%M"),
        }
        for row in post_rows
    ]

    return render_template(
        "public_profile.html",
        nav=nav_items("profile") if viewer else [],
        year=datetime.now().year,
        user=user,
        joined_date=joined_date,
        share_url=share_url,
        followers_count=followers_count,
        following_count=following_count,
        posts_count=posts_count,
        followers_list=followers_list,
        following_list=following_list,
        media_posts=media_rows,
        recent_posts=recent_posts,
        all_posts=all_posts,
        is_self=is_self,
        is_following=is_following,
    )


@app.route("/follow/<int:user_id>", methods=["POST"])
@login_required
def follow(user_id: int):
    if user_id == session.get("user_id"):
        return redirect(url_for("posts"))
    with get_db() as conn:
        exists = conn.execute(
            """
            SELECT id FROM followers
            WHERE follower_id = ? AND following_id = ?
            """,
            (session.get("user_id"), user_id),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO followers (follower_id, following_id, created_at)
                VALUES (?, ?, ?)
                """,
                (session.get("user_id"), user_id, datetime.utcnow().isoformat()),
            )
    return redirect(url_for("posts"))


@app.route("/unfollow/<int:user_id>", methods=["POST"])
@login_required
def unfollow(user_id: int):
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM followers
            WHERE follower_id = ? AND following_id = ?
            """,
            (session.get("user_id"), user_id),
        )
    return redirect(url_for("posts"))


@app.route("/posts/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id: int):
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO likes (user_id, post_id, created_at) VALUES (?, ?, ?)",
                (session.get("user_id"), post_id, datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError:
            pass
        post = conn.execute(
            "SELECT user_id FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if post:
            create_notification(
                post["user_id"],
                session.get("user_id"),
                post_id,
                "like",
                conn=conn,
            )
    return redirect(request.referrer or url_for("posts"))


@app.route("/posts/<int:post_id>/unlike", methods=["POST"])
@login_required
def unlike_post(post_id: int):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM likes WHERE user_id = ? AND post_id = ?",
            (session.get("user_id"), post_id),
        )
    return redirect(request.referrer or url_for("posts"))


@app.route("/posts/<int:post_id>/like-toggle", methods=["POST"])
@login_required
def like_toggle(post_id: int):
    liked = False
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM likes WHERE user_id = ? AND post_id = ?",
            (session.get("user_id"), post_id),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM likes WHERE user_id = ? AND post_id = ?",
                (session.get("user_id"), post_id),
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO likes (user_id, post_id, created_at) VALUES (?, ?, ?)",
                (session.get("user_id"), post_id, datetime.now(timezone.utc).isoformat()),
            )
            post = conn.execute(
                "SELECT user_id FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if post:
                create_notification(
                    post["user_id"],
                    session.get("user_id"),
                    post_id,
                    "like",
                    conn=conn,
                )
            liked = True
        like_count = conn.execute(
            "SELECT COUNT(*) AS count FROM likes WHERE post_id = ?",
            (post_id,),
        ).fetchone()["count"]
    return {
        "liked": liked,
        "like_count": like_count,
    }


@app.route("/posts/<int:post_id>/comment", methods=["POST"])
@login_required
def comment_post(post_id: int):
    content = request.form.get("comment", "").strip()
    if content:
        if not check_content(content):
            session["posts_error"] = "Your comment contains inappropriate language."
            return redirect(request.referrer or url_for("posts"))
        with get_db() as conn:
            conn.execute(
                "INSERT INTO comments (user_id, post_id, content, created_at) VALUES (?, ?, ?, ?)",
                (session.get("user_id"), post_id, content, datetime.now(timezone.utc).isoformat()),
            )
            post = conn.execute(
                "SELECT user_id FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if post:
                create_notification(
                    post["user_id"],
                    session.get("user_id"),
                    post_id,
                    "comment",
                    conn=conn,
                )
    return redirect(request.referrer or url_for("posts"))


@app.route("/comments/<int:comment_id>/edit", methods=["POST"])
@login_required
def edit_comment(comment_id: int):
    content = request.form.get("content", "").strip()
    with get_db() as conn:
        comment = conn.execute(
            "SELECT user_id FROM comments WHERE id = ?",
            (comment_id,),
        ).fetchone()
        if comment and comment["user_id"] == session.get("user_id"):
            conn.execute(
                "UPDATE comments SET content = ? WHERE id = ?",
                (content, comment_id),
            )
    return redirect(request.referrer or url_for("posts"))


@app.route("/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id: int):
    try:
        with get_db() as conn:
            comment = conn.execute(
                "SELECT user_id FROM comments WHERE id = ?",
                (comment_id,),
            ).fetchone()
            if comment and comment["user_id"] == session.get("user_id"):
                conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    except Exception:
        pass  # Silently fail if there's any issue
    referrer = request.referrer or url_for("posts")
    return redirect(referrer)


@app.route("/posts/<int:post_id>/edit", methods=["POST"])
@login_required
def edit_post(post_id: int):
    content = request.form.get("content", "").strip()
    with get_db() as conn:
        post = conn.execute(
            "SELECT user_id FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if post and post["user_id"] == session.get("user_id"):
            conn.execute(
                "UPDATE posts SET content = ? WHERE id = ?",
                (content, post_id),
            )
    return redirect(request.referrer or url_for("posts"))


@app.route("/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id: int):
    try:
        with get_db() as conn:
            post = conn.execute(
                "SELECT id, user_id, media_path FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if post and post["user_id"] == session.get("user_id"):
                # Delete associated media file from filesystem
                if post["media_path"]:
                    try:
                        media_full_path = os.path.join(app.root_path, "static", post["media_path"])
                        if os.path.exists(media_full_path):
                            os.remove(media_full_path)
                    except OSError:
                        pass  # Ignore file deletion errors
                
                # Delete from database
                conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                conn.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
                conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
                conn.execute("DELETE FROM reports WHERE post_id = ?", (post_id,))
    except Exception:
        pass  # Silently fail if there's any issue
    referrer = request.referrer or url_for("posts")
    return redirect(referrer)


@app.route("/posts/<int:post_id>/report", methods=["POST"])
@login_required
def report_post(post_id: int):
    reason = request.form.get("reason", "").strip()
    details = request.form.get("details", "").strip()
    if not reason:
        session["posts_error"] = "Please select a report reason."
        return redirect(url_for("posts"))
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO reports (reporter_id, post_id, reason, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session.get("user_id"), post_id, reason, details, datetime.utcnow().isoformat()),
        )
        count = conn.execute("SELECT COUNT(*) as c FROM reports WHERE post_id = ?", (post_id,)).fetchone()["c"]
        if count >= 3:
             conn.execute("UPDATE posts SET is_hidden = 1 WHERE id = ?", (post_id,))
    session["posts_error"] = "Report submitted."
    return redirect(request.referrer or url_for("posts"))


@app.route("/posts/<int:post_id>")
@login_required
def post_detail(post_id: int):
    with get_db() as conn:
        post = conn.execute(
            """
            SELECT posts.id,
                   posts.content,
                   posts.created_at,
                   posts.media_path,
                   posts.media_type,
                   users.id AS author_id,
                   users.name,
                   users.handle,
                   users.avatar_path,
                   (SELECT COUNT(*) FROM likes WHERE post_id = posts.id) AS like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id = posts.id) AS comment_count,
                   (SELECT COUNT(*) FROM followers WHERE follower_id = ? AND following_id = users.id) AS is_following,
                   (SELECT COUNT(*) FROM likes WHERE post_id = posts.id AND user_id = ?) AS liked_by_me
            FROM posts
            JOIN users ON users.id = posts.user_id
            WHERE posts.id = ?
            """,
            (session.get("user_id"), session.get("user_id"), post_id),
        ).fetchone()
        if not post:
            return redirect(url_for("posts"))
        comment_rows = conn.execute(
            """
            SELECT comments.id,
                   comments.user_id,
                   comments.content,
                   comments.created_at,
                   users.name,
                   users.handle
            FROM comments
            JOIN users ON users.id = comments.user_id
            WHERE comments.post_id = ?
            ORDER BY comments.created_at ASC
            """,
            (post_id,),
        ).fetchall()

    def time_ago(ts: str) -> str:
        created = datetime.fromisoformat(ts)
        delta = datetime.utcnow() - created
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"

    post_view = {
        "id": post["id"],
        "author_id": post["author_id"],
        "name": post["name"],
        "handle": f"@{post['handle']}",
        "time": time_ago(post["created_at"]),
        "text": post["content"],
        "avatar_path": post["avatar_path"],
        "media_path": post["media_path"],
        "media_type": post["media_type"],
        "like_count": post["like_count"],
        "comment_count": post["comment_count"],
        "is_following": post["is_following"] > 0,
        "liked_by_me": post["liked_by_me"] > 0,
        "is_owner": post["author_id"] == session.get("user_id"),
    }

    comments = [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "handle": f"@{row['handle']}",
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in comment_rows
    ]
    return render_template(
        "post_detail.html",
        nav=nav_items("posts"),
        year=datetime.now().year,
        post=post_view,
        comments=comments,
    )


@app.route("/notifications")
@login_required
def notifications():
    with get_db() as conn:
        notif_rows = conn.execute(
            """
            SELECT notifications.id,
                   notifications.type,
                   notifications.created_at,
                   posts.id AS post_id,
                   actor.name AS actor_name,
                   actor.handle AS actor_handle
            FROM notifications
            JOIN users AS actor ON actor.id = notifications.actor_id
            JOIN posts ON posts.id = notifications.post_id
            WHERE notifications.user_id = ?
            ORDER BY notifications.created_at DESC
            """,
            (session.get("user_id"),),
        ).fetchall()
        conn.execute(
            "UPDATE notifications SET read = 1 WHERE user_id = ?",
            (session.get("user_id"),),
        )
    notifications_list = [
        {
            "id": row["id"],
            "type": row["type"],
            "created_at": row["created_at"],
            "post_id": row["post_id"],
            "actor_name": row["actor_name"],
            "actor_handle": f"@{row['actor_handle']}",
        }
        for row in notif_rows
    ]
    return render_template(
        "notifications.html",
        nav=nav_items("notifications"),
        year=datetime.now().year,
        notifications=notifications_list,
    )


@app.route("/admin")
def admin():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("admin_login"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    error = None
    notice = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_admin":
            current_password = request.form.get("current_password", "")
            new_username = request.form.get("new_username", "").strip()
            new_password = request.form.get("new_password", "")
            with get_db() as conn:
                admin_user = conn.execute(
                    "SELECT * FROM admin_users WHERE id = ?",
                    (session.get("admin_id"),),
                ).fetchone()
                if not admin_user or not check_password_hash(admin_user["password_hash"], current_password):
                    error = "Current password is incorrect."
                else:
                    if new_username:
                        conn.execute(
                            "UPDATE admin_users SET username = ? WHERE id = ?",
                            (new_username, admin_user["id"]),
                        )
                    if new_password:
                        conn.execute(
                            "UPDATE admin_users SET password_hash = ? WHERE id = ?",
                            (generate_password_hash(new_password), admin_user["id"]),
                        )
                    notice = "Admin account updated."
        if action == "add_admin":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                error = "Username and password are required."
            else:
                with get_db() as conn:
                    try:
                        conn.execute(
                            """
                            INSERT INTO admin_users (username, password_hash, created_at)
                            VALUES (?, ?, ?)
                            """,
                            (username, generate_password_hash(password), datetime.utcnow().isoformat()),
                        )
                        notice = "New admin added."
                    except sqlite3.IntegrityError:
                        error = "That admin username already exists."
    return render_template(
        "admin_settings.html",
        nav=[],
        year=datetime.now().year,
        error=error,
        notice=notice,
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    error = None
    notice = None
    code_status = None
    cooldown_seconds = 0
    email_input = session.get("pending_email") or user["email"]

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_profile":
            display_name = request.form.get("display_name", "").strip()
            bio = request.form.get("bio", "").strip()
            if not display_name:
                error = "Display name is required."
            else:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE users SET name = ?, bio = ? WHERE id = ?",
                        (display_name, bio, user["id"]),
                    )
                notice = "Profile settings updated."

        if action == "send_email_code":
            new_email = request.form.get("new_email", "").strip().lower()
            email_input = new_email
            if not new_email:
                error = "Enter the new email address."
            elif new_email == user["email"]:
                error = "That is already your current email."
            else:
                with get_db() as conn:
                    existing = conn.execute(
                        "SELECT id FROM users WHERE email = ?",
                        (new_email,),
                    ).fetchone()
                if existing:
                    error = "That email is already in use."
                else:
                    cooldown_seconds = cooldown_remaining_seconds(new_email, "change_email")
                    if cooldown_seconds > 0:
                        error = f"Please wait {cooldown_seconds} seconds before resending."
                    else:
                        code_value = f"{random.randint(0, 999999):06d}"
                        try:
                            store_verification_code(new_email, code_value, "change_email")
                            send_verification_email(new_email, code_value)
                            session["pending_email"] = new_email
                            notice = "Verification code sent to the new email."
                            cooldown_seconds = CODE_COOLDOWN_SECONDS
                        except RuntimeError as exc:
                            error = str(exc)
                        except Exception:
                            error = "Unable to send email right now. Try again later."

        if action == "change_email":
            new_email = session.get("pending_email") or request.form.get("new_email", "").strip().lower()
            code = request.form.get("email_code", "").strip()
            email_input = new_email or email_input
            if not new_email:
                error = "Send a verification code first."
            elif not code:
                error = "Enter the 6-digit code."
            elif not verify_code(new_email, code, "change_email"):
                code_status = "bad"
                error = "Verification code is incorrect or expired."
            else:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE users SET email = ? WHERE id = ?",
                        (new_email, user["id"]),
                    )
                session.pop("pending_email", None)
                code_status = "ok"
                notice = "Email updated successfully."

    if session.get("pending_email") and not cooldown_seconds:
        cooldown_seconds = cooldown_remaining_seconds(session["pending_email"], "change_email")

    return render_template(
        "settings.html",
        nav=nav_items("settings"),
        year=datetime.now().year,
        user=current_user(),
        error=error,
        notice=notice,
        code_status=code_status,
        cooldown_seconds=cooldown_seconds,
        email_input=email_input,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        with get_db() as conn:
            admin = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
            if admin and check_password_hash(admin["password_hash"], password):
                session["admin_id"] = admin["id"]
                # Enforce 2FA here in production (e.g. redirect to OTP page)
                # For this refactor, we'll log the action
                logging.info(f"Admin login: {username}")
                return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Invalid credentials")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    with get_db() as conn:
        counts = {
            "users": conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"],
            "posts": conn.execute("SELECT COUNT(*) as c FROM posts").fetchone()["c"],
            "reports": conn.execute("SELECT COUNT(*) as c FROM reports WHERE status='open'").fetchone()["c"],
        }
    return render_template("admin_dashboard.html", counts=counts)

@app.route("/admin/reports")
@admin_required
def admin_reports():
    with get_db() as conn:
        reports = conn.execute("""
            SELECT r.*, p.content as post_content, u.handle as reporter_handle 
            FROM reports r 
            JOIN posts p ON p.id = r.post_id 
            JOIN users u ON u.id = r.reporter_id 
            WHERE r.status = 'open'
        """).fetchall()
    return render_template("admin_reports.html", reports=reports)

@app.route("/admin/reports/<int:report_id>/dismiss", methods=["POST"])
@admin_required
def admin_dismiss_report(report_id: int):
    with get_db() as conn:
        conn.execute("UPDATE reports SET status = 'dismissed' WHERE id = ?", (report_id,))
    return redirect(url_for("admin_reports"))

@app.route("/admin/posts/<int:post_id>/delete", methods=["POST"])
@admin_required
def admin_delete_post(post_id: int):
    try:
        with get_db() as conn:
            post = conn.execute(
                "SELECT id, media_path FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            # Delete associated media file from filesystem
            if post and post["media_path"]:
                try:
                    media_full_path = os.path.join(app.root_path, "static", post["media_path"])
                    if os.path.exists(media_full_path):
                        os.remove(media_full_path)
                except OSError:
                    pass  # Ignore file deletion errors
            
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    except Exception:
        pass  # Silently fail if there's any issue
    referrer = request.referrer or url_for("admin_dashboard")
    return redirect(referrer)

init_db()


if __name__ == "__main__":
    app.run(debug=True)
