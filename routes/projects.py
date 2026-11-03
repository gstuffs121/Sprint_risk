import re
from datetime import datetime
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
from database import get_db_connection, get_dict_cursor, log_audit
from routes.auth import get_current_user

projects_bp = Blueprint("projects", __name__)


@projects_bp.route("/projects", methods=["GET", "POST"])
def index():
    user = get_current_user()
    conn = None
    cur = None

    # Handle Create Project
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        key_code = request.form.get("key_code", "").strip().upper()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "active").lower()

        if not name or not key_code:
            flash("Please enter both a project name and a project key (e.g. SPAI).", "danger")
            return redirect(url_for("projects.index"))

        # Clean key_code (alphanumeric, 2-10 chars)
        clean_key = re.sub(r"[^A-Z0-9_-]", "", key_code)
        if len(clean_key) < 2 or len(clean_key) > 10:
            flash("Project key must be between 2 and 10 alphanumeric characters.", "danger")
            return redirect(url_for("projects.index"))

        try:
            conn = get_db_connection()
            cur = get_dict_cursor(conn)

            # Check key uniqueness
            cur.execute("SELECT id FROM projects WHERE key_code = %s", (clean_key,))
            if cur.fetchone():
                flash(f"A project with key '{clean_key}' already exists. Please choose another key.", "danger")
                return redirect(url_for("projects.index"))

            cur.execute("""
                INSERT INTO projects (name, key_code, description, status, owner_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                name,
                clean_key,
                description,
                status,
                user["id"] if user else None
            ))
            conn.commit()
            new_id = cur.lastrowid

            log_audit(
                "PROJECT_CREATED",
                f"Created project '{name}' [{clean_key}]",
                user_id=user["id"] if user else None,
                username=user["username"] if user else "Anonymous"
            )

            flash(f"Project '{name}' [{clean_key}] created successfully!", "success")
            return redirect(url_for("projects.detail", project_id=new_id))

        except Exception as e:
            if conn:
                conn.rollback()
            flash("Failed to create project: " + str(e), "danger")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        return redirect(url_for("projects.index"))

    # GET Projects List
    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        status_filter = request.args.get("status", "").strip().lower()
        search_query = request.args.get("q", "").strip()

        query = """
            SELECT p.*,
                   u.username AS owner_username,
                   COUNT(DISTINCT s.id) AS sprint_count,
                   COUNT(DISTINCT CASE WHEN s.status = 'active' THEN s.id ELSE NULL END) AS active_sprint_count,
                   COUNT(t.id) AS task_count,
                   COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_task_count,
                   COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_task_count,
                   COALESCE(SUM(t.estimated_hours), 0) AS total_estimated_hours,
                   COALESCE(SUM(t.actual_hours), 0) AS total_actual_hours
            FROM projects p
            LEFT JOIN users u ON p.owner_id = u.id
            LEFT JOIN sprints s ON p.id = s.project_id
            LEFT JOIN tasks t ON s.id = t.sprint_id
        """
        where_clauses = []
        params = []

        if status_filter in ["active", "archived", "completed"]:
            where_clauses.append("p.status = %s")
            params.append(status_filter)

        if search_query:
            where_clauses.append("(p.name LIKE %s OR p.key_code LIKE %s OR p.description LIKE %s)")
            params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += """
            GROUP BY p.id, p.name, p.key_code, p.description, p.status, p.owner_id, p.created_at, u.username
            ORDER BY p.created_at DESC
        """

        cur.execute(query, tuple(params) if params else None)
        project_list = cur.fetchall()

        # Compute completion percentages
        for p in project_list:
            total_t = p.get("task_count", 0)
            comp_t = p.get("completed_task_count", 0)
            p["progress"] = round((comp_t / total_t * 100), 1) if total_t > 0 else 0

        # Overall summary KPIs
        cur.execute("SELECT COUNT(*) AS total FROM projects")
        total_projects = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM projects WHERE status = 'active'")
        active_projects = cur.fetchone()["total"]

        return render_template(
            "projects.html",
            user=user,
            projects=project_list,
            total_projects=total_projects,
            active_projects=active_projects,
            selected_status=status_filter,
            search_query=search_query
        )

    except Exception as e:
        print("Projects List Error:", e)
        flash("Failed to load projects: " + str(e), "danger")
        return render_template(
            "projects.html",
            user=user,
            projects=[],
            total_projects=0,
            active_projects=0,
            selected_status="",
            search_query=""
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@projects_bp.route("/projects/<int:project_id>")
def detail(project_id):
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        # 1. Project details
        cur.execute("""
            SELECT p.*, u.username AS owner_username, u.full_name AS owner_fullname
            FROM projects p
            LEFT JOIN users u ON p.owner_id = u.id
            WHERE p.id = %s
        """, (project_id,))
        project = cur.fetchone()

        if not project:
            flash(f"Project #{project_id} not found.", "warning")
            return redirect(url_for("projects.index"))

        # 2. Associated sprints
        cur.execute("""
            SELECT s.*,
                   COUNT(t.id) AS task_count,
                   COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_tasks,
                   COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_tasks,
                   COALESCE(SUM(t.estimated_hours), 0) AS allocated_hours,
                   COALESCE(SUM(t.actual_hours), 0) AS actual_hours
            FROM sprints s
            LEFT JOIN tasks t ON s.id = t.sprint_id
            WHERE s.project_id = %s
            GROUP BY s.id, s.project_id, s.name, s.goal, s.start_date, s.end_date, s.capacity_hours, s.status, s.created_by, s.created_at
            ORDER BY s.created_at DESC
        """, (project_id,))
        sprints = cur.fetchall()

        for s in sprints:
            cnt = s.get("task_count", 0)
            cmp = s.get("completed_tasks", 0)
            s["progress"] = round((cmp / cnt * 100), 1) if cnt > 0 else 0
            cap = s.get("capacity_hours", 160) or 160
            alloc = s.get("allocated_hours", 0) or 0
            s["utilization"] = round((alloc / cap * 100), 1) if cap > 0 else 0

        # 3. Tasks belonging to this project (via sprints)
        cur.execute("""
            SELECT t.*, s.name AS sprint_name,
                   p.predicted_hours, p.risk_probability, p.risk_level
            FROM tasks t
            JOIN sprints s ON t.sprint_id = s.id
            LEFT JOIN (
                SELECT task_id, predicted_hours, risk_probability, risk_level
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
            WHERE s.project_id = %s
            ORDER BY t.created_at DESC
            LIMIT 30
        """, (project_id,))
        project_tasks = cur.fetchall()

        # 4. Aggregated Project KPIs
        total_tasks = len(project_tasks)
        completed_tasks = sum(1 for t in project_tasks if t["status"] == "completed")
        in_progress_tasks = sum(1 for t in project_tasks if t["status"] == "in_progress")
        blocked_tasks = sum(1 for t in project_tasks if t["status"] == "blocked")
        delayed_tasks = sum(1 for t in project_tasks if t.get("is_delayed"))
        total_estimated = round(sum(t.get("estimated_hours", 0) or 0 for t in project_tasks), 1)
        total_actual = round(sum(t.get("actual_hours", 0) or 0 for t in project_tasks), 1)
        overall_progress = round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0

        # Distinct assignees
        team_members = sorted(list({t["assignee"] for t in project_tasks if t.get("assignee")}))

        return render_template(
            "project_detail.html",
            user=user,
            project=project,
            sprints=sprints,
            tasks=project_tasks,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            in_progress_tasks=in_progress_tasks,
            blocked_tasks=blocked_tasks,
            delayed_tasks=delayed_tasks,
            total_estimated=total_estimated,
            total_actual=total_actual,
            overall_progress=overall_progress,
            team_members=team_members
        )

    except Exception as e:
        print("Project Detail Error:", e)
        flash("Failed to load project details: " + str(e), "danger")
        return redirect(url_for("projects.index"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@projects_bp.route("/projects/<int:project_id>/edit", methods=["POST"])
def edit(project_id):
    user = get_current_user()
    name = request.form.get("name", "").strip()
    key_code = request.form.get("key_code", "").strip().upper()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "active").lower()

    if not name or not key_code:
        flash("Project name and key are required.", "danger")
        return redirect(url_for("projects.detail", project_id=project_id))

    clean_key = re.sub(r"[^A-Z0-9_-]", "", key_code)

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        # Check uniqueness against other projects
        cur.execute("SELECT id FROM projects WHERE key_code = %s AND id != %s", (clean_key, project_id))
        if cur.fetchone():
            flash(f"Key '{clean_key}' is already in use by another project.", "danger")
            return redirect(url_for("projects.detail", project_id=project_id))

        cur.execute("""
            UPDATE projects
            SET name = %s, key_code = %s, description = %s, status = %s
            WHERE id = %s
        """, (name, clean_key, description, status, project_id))
        conn.commit()

        log_audit(
            "PROJECT_UPDATED",
            f"Updated project #{project_id} '{name}' [{clean_key}]",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )
        flash(f"Project '{name}' updated successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash("Failed to update project: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("projects.detail", project_id=project_id))


@projects_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
def delete(project_id):
    user = get_current_user()
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT name, key_code FROM projects WHERE id = %s", (project_id,))
        proj = cur.fetchone()
        if proj:
            # Unlink sprints first
            cur.execute("UPDATE sprints SET project_id = NULL WHERE project_id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()

            log_audit(
                "PROJECT_DELETED",
                f"Deleted project #{project_id} '{proj['name']}' [{proj['key_code']}]",
                user_id=user["id"] if user else None,
                username=user["username"] if user else "Anonymous"
            )
            flash(f"Project '{proj['name']}' deleted.", "info")
    except Exception as e:
        conn.rollback()
        flash("Failed to delete project: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("projects.index"))


@projects_bp.route("/api/projects")
def api_projects():
    """Return JSON list of projects for dynamic select dropdowns."""
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT id, name, key_code, status FROM projects ORDER BY name ASC")
        return jsonify({"status": "success", "projects": cur.fetchall()})
    finally:
        cur.close()
        conn.close()
