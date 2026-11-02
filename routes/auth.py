from functools import wraps
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    g
)
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, get_dict_cursor, log_audit

auth_bp = Blueprint("auth", __name__)


def get_current_user():
    """Retrieve currently authenticated user dict from session or None."""
    if "user_id" not in session:
        return None
    return {
        "id": session.get("user_id"),
        "username": session.get("username"),
        "email": session.get("email"),
        "full_name": session.get("full_name") or session.get("username"),
        "role": session.get("role", "user"),
        "is_authenticated": True
    }


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access SprintAI workspace.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access the Admin Portal.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") != "admin":
            flash("Administrative privileges are required for this section.", "danger")
            log_audit(
                "UNAUTHORIZED_ADMIN_ACCESS_ATTEMPT",
                f"User {session.get('username')} attempted accessing {request.path}",
                user_id=session.get("user_id"),
                username=session.get("username"),
                ip_address=request.remote_addr
            )
            return redirect(url_for("dashboard.index"))
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    error = None

    if request.method == "POST":
        login_input = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not login_input or not password:
            error = "Please enter both username/email and password."
            return render_template("login.html", error=error)

        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        try:
            cur.execute("""
                SELECT * FROM users
                WHERE (username = %s OR email = %s)
                LIMIT 1
            """, (login_input, login_input))
            user = cur.fetchone()

            if user:
                if not user.get("is_active", 1):
                    error = "This account is deactivated. Contact your system administrator."
                elif check_password_hash(user["password_hash"], password):
                    # Set session
                    session.clear()
                    session["user_id"] = user["id"]
                    session["username"] = user["username"]
                    session["email"] = user["email"]
                    session["full_name"] = user["full_name"] or user["username"]
                    session["role"] = user["role"]

                    log_audit(
                        "USER_LOGIN",
                        f"User logged in: {user['username']} ({user['role']})",
                        user_id=user["id"],
                        username=user["username"],
                        ip_address=request.remote_addr
                    )

                    flash(f"Welcome back, {user['full_name'] or user['username']}!", "success")
                    next_url = request.args.get("next")
                    if next_url and next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
                        return redirect(next_url)
                    if user["role"] == "admin":
                        return redirect(url_for("admin.index"))
                    return redirect(url_for("dashboard.index"))
                else:
                    error = "Invalid username/email or password."
            else:
                error = "Invalid username/email or password."

        except Exception as e:
            error = f"Authentication error: {str(e)}"
        finally:
            cur.close()
            conn.close()

    return render_template("login.html", error=error)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # CRITICAL SECURITY RULE: Public registration CANNOT assign admin or privileged roles.
        # Role is unconditionally enforced as standard 'user' on the server.
        enforced_role = "user"

        if not username or not email or not password:
            error = "Please provide username, email, and password."
        elif len(username) < 3:
            error = "Username must be at least 3 characters long."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            conn = get_db_connection()
            cur = get_dict_cursor(conn)
            try:
                cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
                if cur.fetchone():
                    error = "Username or email is already registered."
                else:
                    pwd_hash = generate_password_hash(password)
                    cur.execute("""
                        INSERT INTO users (username, email, password_hash, full_name, role, is_active)
                        VALUES (%s, %s, %s, %s, %s, 1)
                    """, (username, email, pwd_hash, full_name or username, enforced_role))
                    conn.commit()

                    new_id = cur.lastrowid
                    log_audit(
                        "USER_REGISTERED",
                        f"New user registered: {username} ({enforced_role})",
                        user_id=new_id,
                        username=username,
                        ip_address=request.remote_addr
                    )

                    flash("Account created successfully! You can now sign in.", "success")
                    return redirect(url_for("auth.login"))
            except Exception as e:
                conn.rollback()
                error = f"Registration error: {str(e)}"
            finally:
                cur.close()
                conn.close()

    return render_template("register.html", error=error)


@auth_bp.route("/logout")
def logout():
    uid = session.get("user_id")
    uname = session.get("username")
    if uname:
        log_audit(
            "USER_LOGOUT",
            f"User logged out: {uname}",
            user_id=uid,
            username=uname,
            ip_address=request.remote_addr
        )
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    error = None
    success = None

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        try:
            if not email:
                error = "Email address cannot be empty."
            elif new_password and len(new_password) < 6:
                error = "New password must be at least 6 characters."
            elif new_password and new_password != confirm_password:
                error = "New passwords do not match."
            else:
                if new_password:
                    cur.execute("""
                        UPDATE users
                        SET full_name = %s, email = %s, password_hash = %s
                        WHERE id = %s
                    """, (full_name, email, generate_password_hash(new_password), user["id"]))
                else:
                    cur.execute("""
                        UPDATE users
                        SET full_name = %s, email = %s
                        WHERE id = %s
                    """, (full_name, email, user["id"]))
                conn.commit()

                session["full_name"] = full_name
                session["email"] = email
                success = "Profile updated successfully!"
                log_audit("PROFILE_UPDATE", f"User {user['username']} updated profile", user_id=user["id"], username=user["username"])
        except Exception as e:
            conn.rollback()
            error = f"Error updating profile: {str(e)}"

    cur.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
    db_user = cur.fetchone() or user
    cur.close()
    conn.close()

    return render_template("profile.html", user=db_user, error=error, success=success)
