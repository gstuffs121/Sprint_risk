from datetime import date, datetime
from flask import (
    Blueprint,
    render_template,
    jsonify,
    session,
    flash
)
from database import get_db_connection, get_dict_cursor
from routes.auth import get_current_user

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        # 1. Sprint metrics
        cur.execute("SELECT COUNT(*) AS total FROM sprints")
        total_sprints = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM sprints WHERE status = 'active'")
        active_sprints = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM sprints WHERE status = 'completed'")
        completed_sprints = cur.fetchone()["total"]

        # 2. Task metrics
        cur.execute("SELECT COUNT(*) AS total FROM tasks")
        total_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status = 'completed'")
        completed_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status = 'in_progress'")
        in_progress_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status = 'blocked'")
        blocked_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE status = 'todo'")
        todo_tasks = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM tasks WHERE is_delayed = 1")
        delayed_tasks = cur.fetchone()["total"]

        # 3. Overdue tasks
        today_str = date.today().isoformat()
        cur.execute("""
            SELECT COUNT(*) AS total FROM tasks
            WHERE due_date IS NOT NULL AND due_date < %s AND status != 'completed'
        """, (today_str,))
        overdue_tasks = cur.fetchone()["total"]

        # 4. Effort metrics
        cur.execute("SELECT COALESCE(SUM(estimated_hours), 0) AS total FROM tasks")
        estimated_hours = round(cur.fetchone()["total"], 1)

        cur.execute("SELECT COALESCE(SUM(actual_hours), 0) AS total FROM tasks")
        actual_hours = round(cur.fetchone()["total"], 1)

        # 5. AI predictions summary
        cur.execute("SELECT COUNT(*) AS total, COALESCE(AVG(risk_probability), 0) AS avg_risk FROM predictions")
        pred_stats = cur.fetchone()
        total_predictions = pred_stats["total"]
        avg_risk = round(pred_stats["avg_risk"], 1)

        # 6. Active / Recent Sprints with calculated progress
        cur.execute("""
            SELECT s.*,
                COUNT(t.id) AS task_count,
                COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_task_count,
                COALESCE(SUM(t.estimated_hours), 0) AS allocated_hours
            FROM sprints s
            LEFT JOIN tasks t ON s.id = t.sprint_id
            GROUP BY s.id, s.name, s.goal, s.start_date, s.end_date, s.capacity_hours, s.status, s.created_by, s.created_at
            ORDER BY s.created_at DESC
            LIMIT 5
        """)
        recent_sprints = cur.fetchall()

        for s in recent_sprints:
            cnt = s.get("task_count", 0)
            comp = s.get("completed_task_count", 0)
            s["progress"] = round((comp / cnt * 100), 1) if cnt > 0 else 0
            cap = s.get("capacity_hours", 160) or 160
            alloc = s.get("allocated_hours", 0) or 0
            s["capacity_percent"] = min(100, round((alloc / cap * 100), 1)) if cap > 0 else 0

        # 7. Recent Tasks with Sprint name and latest prediction
        cur.execute("""
            SELECT t.*, s.name AS sprint_name,
                p.predicted_hours, p.risk_probability, p.risk_level
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            LEFT JOIN (
                SELECT task_id, predicted_hours, risk_probability, risk_level
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
            ORDER BY t.created_at DESC
            LIMIT 6
        """)
        recent_tasks = cur.fetchall()

        # 8. High-Risk Tasks Alert List (AI detected critical / high risk or flagged delayed)
        cur.execute("""
            SELECT t.*, s.name AS sprint_name, p.risk_probability, p.risk_level, p.predicted_hours
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            LEFT JOIN (
                SELECT task_id, risk_probability, risk_level, predicted_hours
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            ) p ON t.id = p.task_id
            WHERE t.status != 'completed' AND (t.is_delayed = 1 OR p.risk_level IN ('High', 'Critical') OR p.risk_probability >= 50)
            ORDER BY COALESCE(p.risk_probability, 50) DESC
            LIMIT 4
        """)
        risk_alerts = cur.fetchall()

        # 9. Recent Activity / Audit Log Preview
        cur.execute("""
            SELECT * FROM audit_logs
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_activity = cur.fetchall()

        return render_template(
            "dashboard.html",
            user=user,
            total_sprints=total_sprints,
            active_sprints=active_sprints,
            completed_sprints=completed_sprints,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            in_progress_tasks=in_progress_tasks,
            blocked_tasks=blocked_tasks,
            todo_tasks=todo_tasks,
            delayed_tasks=delayed_tasks,
            overdue_tasks=overdue_tasks,
            estimated_hours=estimated_hours,
            actual_hours=actual_hours,
            total_predictions=total_predictions,
            avg_risk=avg_risk,
            recent_sprints=recent_sprints,
            recent_tasks=recent_tasks,
            risk_alerts=risk_alerts,
            recent_activity=recent_activity
        )

    except Exception as e:
        print("Dashboard Error:", e)
        flash("Unable to load complete dashboard: " + str(e), "danger")
        return render_template(
            "dashboard.html",
            user=user,
            total_sprints=0,
            active_sprints=0,
            completed_sprints=0,
            total_tasks=0,
            completed_tasks=0,
            in_progress_tasks=0,
            blocked_tasks=0,
            todo_tasks=0,
            delayed_tasks=0,
            overdue_tasks=0,
            estimated_hours=0,
            actual_hours=0,
            total_predictions=0,
            avg_risk=0,
            recent_sprints=[],
            recent_tasks=[],
            risk_alerts=[],
            recent_activity=[]
        )

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@dashboard_bp.route("/api/chart-data")
def chart_data():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        # Task status distribution
        cur.execute("""
            SELECT status, COUNT(*) AS total
            FROM tasks
            GROUP BY status
        """)
        status_results = cur.fetchall()

        # Standard status order
        status_map = {"todo": 0, "in_progress": 0, "blocked": 0, "completed": 0}
        for r in status_results:
            key = r["status"].lower().replace(" ", "_").replace("-", "_")
            if key in status_map:
                status_map[key] += r["total"]
            else:
                status_map[key] = r["total"]

        # Risk level distribution from predictions
        cur.execute("""
            SELECT risk_level, COUNT(*) AS total
            FROM (
                SELECT task_id, risk_level
                FROM predictions
                WHERE id IN (SELECT MAX(id) FROM predictions GROUP BY task_id)
            )
            GROUP BY risk_level
        """)
        risk_results = cur.fetchall()
        risk_map = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        for r in risk_results:
            if r["risk_level"] in risk_map:
                risk_map[r["risk_level"]] = r["total"]

        # Sprint capacity vs allocated
        cur.execute("""
            SELECT s.name, s.capacity_hours, COALESCE(SUM(t.estimated_hours), 0) AS allocated_hours
            FROM sprints s
            LEFT JOIN tasks t ON s.id = t.sprint_id
            GROUP BY s.id, s.name, s.capacity_hours
            ORDER BY s.created_at DESC
            LIMIT 5
        """)
        sprint_capacities = cur.fetchall()

        return jsonify({
            "status": "success",
            "task_distribution": {
                "labels": ["To Do", "In Progress", "Blocked", "Completed"],
                "values": [
                    status_map.get("todo", 0),
                    status_map.get("in_progress", 0),
                    status_map.get("blocked", 0),
                    status_map.get("completed", 0)
                ]
            },
            "risk_distribution": {
                "labels": ["Low Risk (<25%)", "Medium Risk (25-50%)", "High Risk (50-75%)", "Critical Risk (>75%)"],
                "values": [
                    risk_map["Low"],
                    risk_map["Medium"],
                    risk_map["High"],
                    risk_map["Critical"]
                ]
            },
            "sprint_workload": {
                "labels": [s["name"][:18] + ("..." if len(s["name"]) > 18 else "") for s in sprint_capacities],
                "capacities": [s["capacity_hours"] for s in sprint_capacities],
                "allocated": [s["allocated_hours"] for s in sprint_capacities]
            }
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "task_distribution": {"labels": [], "values": []},
            "risk_distribution": {"labels": [], "values": []}
        }), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
