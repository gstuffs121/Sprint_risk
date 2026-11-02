from datetime import date, datetime
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

sprints_bp = Blueprint("sprints", __name__)


@sprints_bp.route("/sprints", methods=["GET", "POST"])
def index():
    user = get_current_user()
    conn = None
    cur = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        goal = request.form.get("goal", "").strip()
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        capacity_hours = request.form.get("capacity_hours", "160")
        status = request.form.get("status", "planning").lower()

        if not name or not start_date or not end_date:
            flash("Please provide sprint name, start date, and end date.", "danger")
            return redirect(url_for("sprints.index"))

        try:
            capacity_hours = float(capacity_hours)
            if capacity_hours <= 0:
                flash("Capacity hours must be greater than zero.", "danger")
                return redirect(url_for("sprints.index"))

            s_date = date.fromisoformat(start_date)
            e_date = date.fromisoformat(end_date)
            if e_date < s_date:
                flash("Sprint end date cannot be earlier than start date.", "danger")
                return redirect(url_for("sprints.index"))

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO sprints (name, goal, start_date, end_date, capacity_hours, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                name,
                goal,
                start_date,
                end_date,
                capacity_hours,
                status,
                user["id"] if user else None
            ))
            conn.commit()
            new_id = cur.lastrowid

            log_audit(
                "SPRINT_CREATED",
                f"Created sprint '{name}' with {capacity_hours}h capacity",
                user_id=user["id"] if user else None,
                username=user["username"] if user else "Anonymous"
            )

            flash(f"Sprint '{name}' created successfully!", "success")
            return redirect(url_for("sprints.detail", sprint_id=new_id))

        except Exception as e:
            if conn:
                conn.rollback()
            flash("Failed to create sprint: " + str(e), "danger")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        return redirect(url_for("sprints.index"))

    # GET Sprints
    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        status_filter = request.args.get("status", "").strip().lower()
        search_query = request.args.get("q", "").strip()

        base_query = """
            SELECT s.*,
                COUNT(t.id) AS task_count,
                COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_tasks,
                COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_tasks,
                COALESCE(SUM(t.estimated_hours), 0) AS allocated_hours,
                COALESCE(SUM(t.actual_hours), 0) AS actual_hours
            FROM sprints s
            LEFT JOIN tasks t ON s.id = t.sprint_id
        """
        params = []
        where_clauses = []

        if status_filter and status_filter in ["planning", "active", "completed"]:
            where_clauses.append("s.status = %s")
            params.append(status_filter)

        if search_query:
            where_clauses.append("(s.name LIKE %s OR s.goal LIKE %s)")
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += """
            GROUP BY s.id, s.name, s.goal, s.start_date, s.end_date, s.capacity_hours, s.status, s.created_by, s.created_at
            ORDER BY s.created_at DESC
        """

        cur.execute(base_query, tuple(params))
        sprint_list = cur.fetchall()

        # Compute percentage stats
        for s in sprint_list:
            cnt = s.get("task_count", 0)
            comp = s.get("completed_tasks", 0)
            s["progress"] = round((comp / cnt * 100), 1) if cnt > 0 else 0
            cap = s.get("capacity_hours", 160) or 160
            alloc = s.get("allocated_hours", 0) or 0
            s["capacity_percent"] = round((alloc / cap * 100), 1) if cap > 0 else 0

        # Summary KPIs
        total_sprints = len(sprint_list)
        active_count = sum(1 for s in sprint_list if s["status"] == "active")
        total_capacity = sum(s.get("capacity_hours", 0) for s in sprint_list)

        return render_template(
            "sprints.html",
            user=user,
            sprints=sprint_list,
            sprint_list=sprint_list,
            total_sprints=total_sprints,
            active_count=active_count,
            total_capacity=round(total_capacity, 1),
            selected_status=status_filter,
            search_query=search_query
        )

    except Exception as e:
        print("Sprints Loading Error:", e)
        flash("Unable to load sprints: " + str(e), "danger")
        return render_template(
            "sprints.html",
            user=user,
            sprints=[],
            sprint_list=[],
            total_sprints=0,
            active_count=0,
            total_capacity=0,
            selected_status="",
            search_query=""
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@sprints_bp.route("/sprints/<int:sprint_id>")
def detail(sprint_id):
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        cur.execute("SELECT * FROM sprints WHERE id = %s", (sprint_id,))
        sprint = cur.fetchone()

        if not sprint:
            flash("Sprint not found.", "danger")
            return redirect(url_for("sprints.index"))

        # Associated tasks with predictions
        cur.execute("""
            SELECT t.*, p.predicted_hours, p.risk_probability, p.risk_level
            FROM tasks t
            LEFT JOIN (
                SELECT task_id, predicted_hours, risk_probability, risk_level
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
            WHERE t.sprint_id = %s
            ORDER BY t.created_at DESC
        """, (sprint_id,))
        tasks = cur.fetchall()

        # Metrics for this sprint
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t["status"] == "completed")
        in_progress_tasks = sum(1 for t in tasks if t["status"] == "in_progress")
        delayed_tasks = sum(1 for t in tasks if t["is_delayed"] == 1)
        progress = round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0

        total_est = sum(t.get("estimated_hours", 0) or 0 for t in tasks)
        total_act = sum(t.get("actual_hours", 0) or 0 for t in tasks)
        capacity = sprint.get("capacity_hours", 160) or 160
        capacity_usage = round((total_est / capacity * 100), 1) if capacity > 0 else 0

        # Remaining days
        try:
            e_date = sprint["end_date"]
            if isinstance(e_date, str):
                e_date = date.fromisoformat(e_date)
            elif isinstance(e_date, datetime):
                e_date = e_date.date()
            days_remaining = (e_date - date.today()).days
        except Exception:
            days_remaining = 0

        return render_template(
            "sprint_detail.html",
            user=user,
            sprint=sprint,
            tasks=tasks,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            in_progress_tasks=in_progress_tasks,
            delayed_tasks=delayed_tasks,
            progress=progress,
            total_est=round(total_est, 1),
            total_act=round(total_act, 1),
            capacity=capacity,
            capacity_usage=capacity_usage,
            days_remaining=days_remaining
        )

    except Exception as e:
        flash("Error loading sprint details: " + str(e), "danger")
        return redirect(url_for("sprints.index"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@sprints_bp.route("/sprints/<int:sprint_id>/edit", methods=["POST"])
def edit(sprint_id):
    user = get_current_user()
    name = request.form.get("name", "").strip()
    goal = request.form.get("goal", "").strip()
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    capacity_hours = request.form.get("capacity_hours", "160")
    status = request.form.get("status", "planning").lower()

    if not name or not start_date or not end_date:
        flash("Missing required fields for sprint update.", "danger")
        return redirect(url_for("sprints.detail", sprint_id=sprint_id))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE sprints
            SET name = %s, goal = %s, start_date = %s, end_date = %s, capacity_hours = %s, status = %s
            WHERE id = %s
        """, (name, goal, start_date, end_date, float(capacity_hours), status, sprint_id))
        conn.commit()

        log_audit(
            "SPRINT_UPDATED",
            f"Updated sprint #{sprint_id} ({name})",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )
        flash("Sprint updated successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash("Failed to update sprint: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("sprints.detail", sprint_id=sprint_id))


@sprints_bp.route("/sprints/<int:sprint_id>/delete", methods=["POST"])
def delete(sprint_id):
    user = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sprints WHERE id = %s", (sprint_id,))
        conn.commit()
        log_audit(
            "SPRINT_DELETED",
            f"Deleted sprint #{sprint_id}",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )
        flash("Sprint deleted successfully.", "info")
    except Exception as e:
        conn.rollback()
        flash("Unable to delete sprint: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("sprints.index"))
