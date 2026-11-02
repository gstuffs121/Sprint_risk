import os
import sys
import time
from datetime import datetime
from pathlib import Path
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify
)
from werkzeug.security import generate_password_hash
from database import (
    get_db_connection,
    get_dict_cursor,
    get_active_engine,
    test_db_connection,
    log_audit
)
from routes.auth import admin_required, get_current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@admin_required
def before_request():
    """Ensure every route in admin blueprint requires admin role."""
    pass


# -------------------------------------------------------------
# 1. ADMIN DASHBOARD
# -------------------------------------------------------------
@admin_bp.route("/")
def index():
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        # Users
        cur.execute("SELECT COUNT(*) AS total FROM users")
        total_users = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM users WHERE is_active = 1")
        active_users = cur.fetchone()["total"]

        # Sprints
        cur.execute("SELECT COUNT(*) AS total FROM sprints")
        total_sprints = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM sprints WHERE status = 'active'")
        active_sprints = cur.fetchone()["total"]

        # Tasks
        cur.execute("SELECT COUNT(*) AS total FROM tasks")
        total_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status = 'completed'")
        completed_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status != 'completed'")
        pending_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE is_delayed = 1")
        delayed_tasks = cur.fetchone()["total"]

        # AI Predictions
        cur.execute("SELECT COUNT(*) AS total, AVG(risk_probability) AS avg_risk FROM predictions")
        pred_stats = cur.fetchone()
        total_predictions = pred_stats["total"]
        avg_risk = round(pred_stats["avg_risk"] or 0, 1)

        # Recent Audit Logs
        cur.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 8")
        recent_logs = cur.fetchall()

        # Users overview by role
        cur.execute("SELECT role, COUNT(*) AS count FROM users GROUP BY role")
        role_breakdown = cur.fetchall()

        # Model file statuses
        root_dir = Path(__file__).resolve().parents[1]
        effort_model_path = root_dir / "models" / "effort_model.joblib"
        risk_model_path = root_dir / "models" / "risk_model.joblib"
        dataset_path = root_dir / "dataset" / "sprint_tasks.csv"

        model_status = {
            "effort_model": effort_model_path.exists(),
            "effort_size_kb": round(effort_model_path.stat().st_size / 1024, 1) if effort_model_path.exists() else 0,
            "risk_model": risk_model_path.exists(),
            "risk_size_kb": round(risk_model_path.stat().st_size / 1024, 1) if risk_model_path.exists() else 0,
            "dataset_rows": 0
        }
        if dataset_path.exists():
            with open(dataset_path, "r", encoding="utf-8") as f:
                model_status["dataset_rows"] = sum(1 for _ in f) - 1

        db_engine = get_active_engine()

        return render_template(
            "admin/dashboard.html",
            user=user,
            total_users=total_users,
            active_users=active_users,
            total_sprints=total_sprints,
            active_sprints=active_sprints,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
            delayed_tasks=delayed_tasks,
            total_predictions=total_predictions,
            avg_risk=avg_risk,
            recent_logs=recent_logs,
            role_breakdown=role_breakdown,
            model_status=model_status,
            db_engine=db_engine
        )

    except Exception as e:
        flash("Error loading admin overview: " + str(e), "danger")
        return render_template(
            "admin/dashboard.html",
            user=user,
            total_users=0,
            active_users=0,
            total_sprints=0,
            active_sprints=0,
            total_tasks=0,
            completed_tasks=0,
            pending_tasks=0,
            delayed_tasks=0,
            total_predictions=0,
            avg_risk=0,
            recent_logs=[],
            role_breakdown=[],
            model_status={},
            db_engine="Unknown"
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# -------------------------------------------------------------
# 2. USER MANAGEMENT
# -------------------------------------------------------------
@admin_bp.route("/users")
def users():
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        search_q = request.args.get("q", "").strip()
        role_f = request.args.get("role", "").strip()
        status_f = request.args.get("status", "").strip()

        query = "SELECT * FROM users WHERE 1=1"
        params = []

        if search_q:
            query += " AND (username LIKE %s OR email LIKE %s OR full_name LIKE %s)"
            params.extend([f"%{search_q}%", f"%{search_q}%", f"%{search_q}%"])

        if role_f:
            query += " AND role = %s"
            params.append(role_f)

        if status_f in ["0", "1"]:
            query += " AND is_active = %s"
            params.append(int(status_f))

        query += " ORDER BY created_at DESC"
        cur.execute(query, tuple(params))
        user_list = cur.fetchall()

        return render_template(
            "admin/users.html",
            user=user,
            users=user_list,
            search_q=search_q,
            selected_role=role_f,
            selected_status=status_f
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@admin_bp.route("/users/create", methods=["POST"])
def create_user():
    user = get_current_user()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "user")
    password = request.form.get("password", "")

    if not username or not email or not password:
        flash("Username, email and password are required.", "danger")
        return redirect(url_for("admin.users"))

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
        if cur.fetchone():
            flash("Username or email already exists.", "danger")
            return redirect(url_for("admin.users"))

        pwd_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users (username, email, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (username, email, pwd_hash, full_name or username, role))
        conn.commit()

        log_audit(
            "ADMIN_CREATED_USER",
            f"Admin {user['username']} created user account '{username}' with role '{role}'",
            user_id=user["id"],
            username=user["username"]
        )
        flash(f"User '{username}' created successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash("Failed to create user: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle-status", methods=["POST"])
def toggle_user_status(user_id):
    user = get_current_user()
    if user_id == user["id"]:
        flash("You cannot deactivate your own administrative account.", "danger")
        return redirect(url_for("admin.users"))

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT is_active, username FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if target:
            new_status = 0 if target["is_active"] else 1
            cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (new_status, user_id))
            conn.commit()
            action_desc = "activated" if new_status else "deactivated"
            log_audit(
                "ADMIN_USER_STATUS_CHANGE",
                f"Admin {user['username']} {action_desc} user '{target['username']}'",
                user_id=user["id"],
                username=user["username"]
            )
            flash(f"User '{target['username']}' {action_desc}.", "info")
    except Exception as e:
        conn.rollback()
        flash("Error changing user status: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit-role", methods=["POST"])
def edit_user_role(user_id):
    user = get_current_user()
    new_role = request.form.get("role", "user")

    if new_role not in ["admin", "scrum_master", "user"]:
        flash("Invalid role specified.", "danger")
        return redirect(url_for("admin.users"))

    if user_id == user["id"] and new_role != "admin":
        flash("You cannot demote your own admin account.", "danger")
        return redirect(url_for("admin.users"))

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if target:
            cur.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
            conn.commit()
            log_audit(
                "ADMIN_ROLE_CHANGE",
                f"Admin {user['username']} changed role of '{target['username']}' to '{new_role}'",
                user_id=user["id"],
                username=user["username"]
            )
            flash(f"Updated role for '{target['username']}' to {new_role}.", "success")
    except Exception as e:
        conn.rollback()
        flash("Error updating role: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    user = get_current_user()
    if user_id == user["id"]:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for("admin.users"))

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if target:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            log_audit(
                "ADMIN_DELETE_USER",
                f"Admin {user['username']} deleted user '{target['username']}'",
                user_id=user["id"],
                username=user["username"]
            )
            flash(f"User '{target['username']}' deleted.", "info")
    except Exception as e:
        conn.rollback()
        flash("Failed to delete user: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin.users"))


# -------------------------------------------------------------
# 3. SPRINT MONITORING
# -------------------------------------------------------------
@admin_bp.route("/sprints")
def sprints():
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("""
            SELECT s.*, u.username AS creator_username,
                   COUNT(t.id) AS task_count,
                   COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                   COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_count,
                   COALESCE(SUM(t.estimated_hours), 0) AS total_est_hours
            FROM sprints s
            LEFT JOIN users u ON s.created_by = u.id
            LEFT JOIN tasks t ON s.id = t.sprint_id
            GROUP BY s.id, s.name, s.goal, s.start_date, s.end_date, s.capacity_hours, s.status, s.created_by, s.created_at, u.username
            ORDER BY s.created_at DESC
        """)
        sprint_list = cur.fetchall()

        for s in sprint_list:
            cnt = s.get("task_count", 0)
            cmp = s.get("completed_count", 0)
            s["progress"] = round((cmp / cnt * 100), 1) if cnt > 0 else 0

        return render_template("admin/sprints.html", user=user, sprints=sprint_list)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------
# 4. TASK MONITORING
# -------------------------------------------------------------
@admin_bp.route("/tasks")
def tasks():
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("""
            SELECT t.*, s.name AS sprint_name,
                   p.risk_probability, p.risk_level, p.predicted_hours
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            LEFT JOIN (
                SELECT task_id, risk_probability, risk_level, predicted_hours
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
            ORDER BY t.created_at DESC
        """)
        task_list = cur.fetchall()
        return render_template("admin/tasks.html", user=user, tasks=task_list)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------
# 5. AI MONITORING & RETRAINING
# -------------------------------------------------------------
@admin_bp.route("/ai")
def ai_monitoring():
    user = get_current_user()
    root_dir = Path(__file__).resolve().parents[1]
    effort_model_path = root_dir / "models" / "effort_model.joblib"
    risk_model_path = root_dir / "models" / "risk_model.joblib"
    data_path = root_dir / "dataset" / "sprint_tasks.csv"

    # Dataset stats
    dataset_rows = 0
    if data_path.exists():
        with open(data_path, "r", encoding="utf-8") as f:
            dataset_rows = max(0, sum(1 for _ in f) - 1)

    # Prediction counts
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("""
            SELECT COUNT(*) AS total,
                   AVG(risk_probability) AS avg_risk,
                   AVG(predicted_hours) AS avg_hours,
                   COALESCE(SUM(CASE WHEN risk_level = 'Critical' THEN 1 ELSE 0 END), 0) AS critical_count,
                   COALESCE(SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END), 0) AS high_count,
                   COALESCE(SUM(CASE WHEN risk_level = 'Medium' THEN 1 ELSE 0 END), 0) AS medium_count,
                   COALESCE(SUM(CASE WHEN risk_level = 'Low' THEN 1 ELSE 0 END), 0) AS low_count
            FROM predictions
        """)
        stats = cur.fetchone()

        cur.execute("""
            SELECT p.*, t.title AS task_title
            FROM predictions p
            JOIN tasks t ON p.task_id = t.id
            ORDER BY p.created_at DESC
            LIMIT 15
        """)
        recent_preds = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    model_info = {
        "effort_model": {
            "exists": effort_model_path.exists(),
            "algorithm": "RandomForestRegressor (scikit-learn)",
            "features": "Complexity, Priority, Dependencies, Days Remaining, Team Workload",
            "modified": datetime.fromtimestamp(effort_model_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if effort_model_path.exists() else "Not trained",
            "size_kb": round(effort_model_path.stat().st_size / 1024, 1) if effort_model_path.exists() else 0
        },
        "risk_model": {
            "exists": risk_model_path.exists(),
            "algorithm": "RandomForestClassifier (scikit-learn)",
            "target": "Binary Delay Probability [0 = On-Time, 1 = Delayed]",
            "modified": datetime.fromtimestamp(risk_model_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if risk_model_path.exists() else "Not trained",
            "size_kb": round(risk_model_path.stat().st_size / 1024, 1) if risk_model_path.exists() else 0
        },
        "dataset_rows": dataset_rows
    }

    return render_template(
        "admin/ai.html",
        user=user,
        model_info=model_info,
        stats=stats,
        recent_preds=recent_preds
    )


@admin_bp.route("/ai/retrain", methods=["POST"])
def retrain_models():
    user = get_current_user()
    try:
        from ai.train_models import create_sample_dataset, train_models
        # Safely trigger retraining
        start_time = time.time()
        df = create_sample_dataset()
        train_models(df)
        elapsed = round(time.time() - start_time, 2)

        log_audit(
            "AI_MODELS_RETRAINED",
            f"Admin {user['username']} retrained Random Forest models in {elapsed}s on {len(df)} samples",
            user_id=user["id"],
            username=user["username"]
        )
        flash(f"AI Models retrained successfully in {elapsed} seconds! Updated joblib artifacts.", "success")
    except Exception as e:
        print("Retrain Error:", e)
        flash("Failed to retrain models: " + str(e), "danger")

    return redirect(url_for("admin.ai_monitoring"))


# -------------------------------------------------------------
# 6. AUDIT LOGS
# -------------------------------------------------------------
@admin_bp.route("/logs")
def logs():
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        search_q = request.args.get("q", "").strip()
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        if search_q:
            query += " AND (action LIKE %s OR details LIKE %s OR username LIKE %s)"
            params.extend([f"%{search_q}%", f"%{search_q}%", f"%{search_q}%"])
        query += " ORDER BY created_at DESC LIMIT 100"
        cur.execute(query, tuple(params))
        log_list = cur.fetchall()
        return render_template("admin/logs.html", user=user, logs=log_list, search_q=search_q)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------
# 7. SYSTEM HEALTH
# -------------------------------------------------------------
@admin_bp.route("/health")
def system_health():
    user = get_current_user()
    root_dir = Path(__file__).resolve().parents[1]

    # Model file availability
    effort_exists = (root_dir / "models" / "effort_model.joblib").exists()
    risk_exists = (root_dir / "models" / "risk_model.joblib").exists()
    dataset_exists = (root_dir / "dataset" / "sprint_tasks.csv").exists()

    # DB connectivity test
    db_status = "Connected"
    active_db = "Unknown"
    table_counts = {}
    try:
        active_db = test_db_connection()
        conn = get_db_connection()
        cur = get_dict_cursor(conn)
        ALLOWED_TABLES = {"users", "sprints", "tasks", "predictions", "audit_logs", "system_settings"}
        for tbl in ["users", "sprints", "tasks", "predictions", "audit_logs", "system_settings"]:
            if tbl in ALLOWED_TABLES:
                cur.execute(f"SELECT COUNT(*) AS total FROM {tbl}")
            table_counts[tbl] = cur.fetchone()["total"]
        cur.close()
        conn.close()
    except Exception as e:
        db_status = f"Error: {str(e)}"

    health_info = {
        "flask_status": "Operational",
        "python_version": sys.version.split()[0],
        "database_status": db_status,
        "database_backend": get_active_engine().upper(),
        "database_identifier": active_db,
        "table_counts": table_counts,
        "effort_model": "Ready" if effort_exists else "Missing",
        "risk_model": "Ready" if risk_exists else "Missing",
        "dataset_file": "Available" if dataset_exists else "Missing",
        "system_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return render_template("admin/health.html", user=user, health=health_info)


# -------------------------------------------------------------
# 8. SYSTEM SETTINGS
# -------------------------------------------------------------
@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)

    if request.method == "POST":
        try:
            for key, val in request.form.items():
                if key.startswith("setting_"):
                    setting_name = key.replace("setting_", "")
                    cur.execute("""
                        UPDATE system_settings
                        SET key_value = %s
                        WHERE key_name = %s
                    """, (val.strip(), setting_name))
            conn.commit()

            log_audit(
                "SYSTEM_SETTINGS_UPDATED",
                f"Admin {user['username']} updated system configuration settings",
                user_id=user["id"],
                username=user["username"]
            )
            flash("System settings saved successfully!", "success")
        except Exception as e:
            conn.rollback()
            flash("Failed to update settings: " + str(e), "danger")

    try:
        cur.execute("SELECT * FROM system_settings ORDER BY key_name")
        settings_list = cur.fetchall()
        settings_dict = {s["key_name"]: s["key_value"] for s in settings_list}
        return render_template("admin/settings.html", user=user, settings=settings_dict, raw_settings=settings_list)
    finally:
        cur.close()
        conn.close()
