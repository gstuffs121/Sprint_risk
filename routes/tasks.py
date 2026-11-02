from datetime import date
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

tasks_bp = Blueprint("tasks", __name__)


@tasks_bp.route("/tasks", methods=["GET", "POST"])
def index():
    user = get_current_user()
    conn = None
    cur = None

    if request.method == "POST":
        sprint_id = request.form.get("sprint_id")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        assignee = request.form.get("assignee", "").strip()
        priority = request.form.get("priority", "Medium").title()
        complexity = request.form.get("complexity", "3")
        dependencies = request.form.get("dependencies", "0")
        estimated_hours = request.form.get("estimated_hours", "0")
        actual_hours = request.form.get("actual_hours", "0")
        status = request.form.get("status", "todo").lower().replace(" ", "_")
        is_delayed = 1 if request.form.get("is_delayed") else 0
        due_date = request.form.get("due_date")

        if not sprint_id or not title:
            flash("Please choose a sprint and enter a task title.", "danger")
            return redirect(url_for("tasks.index"))

        try:
            complexity = max(1, min(5, int(complexity)))
            dependencies = max(0, min(5, int(dependencies)))
            estimated_hours = max(0.0, float(estimated_hours or 0))
            actual_hours = max(0.0, float(actual_hours or 0))

            if priority not in ["Low", "Medium", "High", "Critical"]:
                priority = "Medium"

            if status not in ["todo", "in_progress", "blocked", "completed"]:
                status = "todo"

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO tasks (
                    sprint_id, title, description, assignee, priority, complexity,
                    dependencies, estimated_hours, actual_hours, status, is_delayed, due_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                sprint_id,
                title,
                description,
                assignee,
                priority,
                complexity,
                dependencies,
                estimated_hours,
                actual_hours,
                status,
                is_delayed,
                due_date if due_date else None
            ))
            conn.commit()
            new_id = cur.lastrowid

            log_audit(
                "TASK_CREATED",
                f"Created task #{new_id} '{title}' in sprint #{sprint_id}",
                user_id=user["id"] if user else None,
                username=user["username"] if user else "Anonymous"
            )

            flash(f"Task '{title}' created successfully!", "success")

            # Check if redirect to specific sprint was requested
            next_sprint = request.form.get("return_sprint")
            if next_sprint:
                return redirect(url_for("sprints.detail", sprint_id=next_sprint))

        except Exception as e:
            if conn:
                conn.rollback()
            print("Task Create Error:", e)
            flash("Failed to create task: " + str(e), "danger")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        return redirect(url_for("tasks.index"))

    # GET Tasks
    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        view_mode = request.args.get("view", "board")  # 'board' or 'table'
        sprint_filter = request.args.get("sprint_id", "")
        status_filter = request.args.get("status", "")
        priority_filter = request.args.get("priority", "")
        search_query = request.args.get("q", "").strip()

        # Load available sprints for dropdowns
        cur.execute("SELECT id, name, status FROM sprints ORDER BY created_at DESC")
        sprint_list = cur.fetchall()

        # Build query for tasks
        base_query = """
            SELECT t.*, s.name AS sprint_name,
                p.predicted_hours, p.risk_probability, p.risk_level
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            LEFT JOIN (
                SELECT task_id, predicted_hours, risk_probability, risk_level
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
        """
        where_clauses = []
        params = []

        if sprint_filter and sprint_filter.isdigit():
            where_clauses.append("t.sprint_id = %s")
            params.append(int(sprint_filter))

        if status_filter:
            where_clauses.append("t.status = %s")
            params.append(status_filter)

        if priority_filter:
            where_clauses.append("t.priority = %s")
            params.append(priority_filter)

        if search_query:
            where_clauses.append("(t.title LIKE %s OR t.assignee LIKE %s OR t.description LIKE %s)")
            params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += " ORDER BY t.created_at DESC"

        cur.execute(base_query, tuple(params))
        task_list = cur.fetchall()

        # Group tasks for Kanban columns
        kanban = {
            "todo": [],
            "in_progress": [],
            "blocked": [],
            "completed": []
        }
        for task in task_list:
            st = task.get("status", "todo").lower().replace(" ", "_").replace("-", "_")
            if st in kanban:
                kanban[st].append(task)
            else:
                kanban["todo"].append(task)

        # Overview counts
        total_tasks = len(task_list)
        completed_count = sum(1 for t in task_list if t["status"] == "completed")
        in_progress_count = sum(1 for t in task_list if t["status"] == "in_progress")
        blocked_count = sum(1 for t in task_list if t["status"] == "blocked")
        delayed_count = sum(1 for t in task_list if t["is_delayed"] == 1)
        total_estimated = sum(t.get("estimated_hours", 0) or 0 for t in task_list)
        total_actual = sum(t.get("actual_hours", 0) or 0 for t in task_list)

        return render_template(
            "tasks.html",
            user=user,
            tasks=task_list,
            task_list=task_list,
            sprints=sprint_list,
            kanban=kanban,
            view_mode=view_mode,
            total_tasks=total_tasks,
            completed_count=completed_count,
            in_progress_count=in_progress_count,
            blocked_count=blocked_count,
            delayed_count=delayed_count,
            total_estimated=round(total_estimated, 1),
            total_actual=round(total_actual, 1),
            selected_sprint=sprint_filter,
            selected_status=status_filter,
            selected_priority=priority_filter,
            search_query=search_query
        )

    except Exception as e:
        print("Tasks Loading Error:", e)
        flash("Unable to load tasks: " + str(e), "danger")
        return render_template(
            "tasks.html",
            user=user,
            tasks=[],
            task_list=[],
            sprints=[],
            kanban={"todo": [], "in_progress": [], "blocked": [], "completed": []},
            view_mode="board",
            total_tasks=0,
            completed_count=0,
            in_progress_count=0,
            blocked_count=0,
            delayed_count=0,
            total_estimated=0,
            total_actual=0,
            selected_sprint="",
            selected_status="",
            selected_priority="",
            search_query=""
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@tasks_bp.route("/tasks/<int:task_id>/update-status", methods=["POST"])
def update_status(task_id):
    user = get_current_user()
    new_status = request.form.get("status") or (request.json.get("status") if request.is_json else None)

    if not new_status or new_status not in ["todo", "in_progress", "blocked", "completed"]:
        if request.is_json:
            return jsonify({"status": "error", "message": "Invalid status"}), 400
        flash("Invalid task status specified.", "danger")
        return redirect(url_for("tasks.index"))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # If moving to completed, is_delayed is resolved
        if new_status == "completed":
            cur.execute("UPDATE tasks SET status = %s, is_delayed = 0 WHERE id = %s", (new_status, task_id))
        else:
            cur.execute("UPDATE tasks SET status = %s WHERE id = %s", (new_status, task_id))
        conn.commit()

        log_audit(
            "TASK_STATUS_UPDATED",
            f"Updated task #{task_id} status to '{new_status}'",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )

        if request.is_json:
            return jsonify({"status": "success", "task_id": task_id, "new_status": new_status})

        flash(f"Task status updated to {new_status.replace('_', ' ').title()}.", "success")
    except Exception as e:
        conn.rollback()
        if request.is_json:
            return jsonify({"status": "error", "message": str(e)}), 500
        flash("Failed to update task status: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(request.referrer or url_for("tasks.index"))


@tasks_bp.route("/tasks/<int:task_id>/edit", methods=["POST"])
def edit(task_id):
    user = get_current_user()
    title = request.form.get("title", "").strip()
    sprint_id = request.form.get("sprint_id")
    assignee = request.form.get("assignee", "").strip()
    priority = request.form.get("priority", "Medium")
    complexity = request.form.get("complexity", "3")
    dependencies = request.form.get("dependencies", "0")
    estimated_hours = request.form.get("estimated_hours", "0")
    actual_hours = request.form.get("actual_hours", "0")
    status = request.form.get("status", "todo")
    is_delayed = 1 if request.form.get("is_delayed") else 0
    due_date = request.form.get("due_date")

    if not title or not sprint_id:
        flash("Task title and sprint are required.", "danger")
        return redirect(url_for("tasks.index"))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE tasks
            SET title = %s, sprint_id = %s, assignee = %s, priority = %s,
                complexity = %s, dependencies = %s, estimated_hours = %s,
                actual_hours = %s, status = %s, is_delayed = %s,
                due_date = %s
            WHERE id = %s
        """, (
            title,
            sprint_id,
            assignee,
            priority,
            int(complexity),
            int(dependencies),
            float(estimated_hours or 0),
            float(actual_hours or 0),
            status,
            is_delayed,
            due_date if due_date else None,
            task_id
        ))
        conn.commit()
        log_audit(
            "TASK_UPDATED",
            f"Updated task #{task_id} ({title})",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )
        flash(f"Task '{title}' updated successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash("Error updating task: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(request.referrer or url_for("tasks.index"))


@tasks_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete(task_id):
    user = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        log_audit(
            "TASK_DELETED",
            f"Deleted task #{task_id}",
            user_id=user["id"] if user else None,
            username=user["username"] if user else "Anonymous"
        )
        flash("Task deleted successfully.", "info")
    except Exception as e:
        conn.rollback()
        flash("Failed to delete task: " + str(e), "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(request.referrer or url_for("tasks.index"))
