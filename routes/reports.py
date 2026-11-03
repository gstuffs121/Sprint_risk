import csv
import io
from flask import (
    Blueprint,
    render_template,
    flash,
    Response
)
from database import get_db_connection, get_dict_cursor
from routes.auth import get_current_user

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
def index():
    user = get_current_user()
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        # 0. Projects Summary
        cur.execute("SELECT COUNT(*) AS total FROM projects")
        total_projects = cur.fetchone()["total"]

        # 1. Overall Task Statistics
        cur.execute("""
            SELECT
                COUNT(*) AS total_tasks,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_tasks,
                COALESCE(SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress_tasks,
                COALESCE(SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END), 0) AS blocked_tasks,
                COALESCE(SUM(CASE WHEN is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_tasks,
                AVG(estimated_hours) AS average_estimated_hours,
                AVG(actual_hours) AS average_actual_hours,
                COALESCE(SUM(estimated_hours), 0) AS total_estimated_hours,
                COALESCE(SUM(actual_hours), 0) AS total_actual_hours
            FROM tasks
        """)
        task_stats = cur.fetchone()

        # Calculate completion rate & variance
        total = task_stats["total_tasks"] or 0
        comp = task_stats["completed_tasks"] or 0
        task_stats["completion_rate"] = round((comp / total * 100), 1) if total > 0 else 0

        avg_est = task_stats.get("average_estimated_hours") or 0
        avg_act = task_stats.get("average_actual_hours") or 0
        task_stats["variance_hours"] = round(avg_act - avg_est, 1)

        # 2. AI Prediction Statistics
        cur.execute("""
            SELECT
                COUNT(*) AS total_predictions,
                AVG(risk_probability) AS average_risk,
                AVG(predicted_hours) AS average_predicted_hours,
                COALESCE(SUM(CASE WHEN risk_level = 'Critical' THEN 1 ELSE 0 END), 0) AS critical_count,
                COALESCE(SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END), 0) AS high_count,
                COALESCE(SUM(CASE WHEN risk_level = 'Medium' THEN 1 ELSE 0 END), 0) AS medium_count,
                COALESCE(SUM(CASE WHEN risk_level = 'Low' THEN 1 ELSE 0 END), 0) AS low_count
            FROM predictions
        """)
        prediction_stats = cur.fetchone()

        # 3. Sprint Performance breakdown
        cur.execute("""
            SELECT
                s.id,
                s.name,
                s.status,
                s.start_date,
                s.end_date,
                s.capacity_hours,
                s.created_at,
                p_proj.key_code AS project_key,
                COUNT(t.id) AS task_count,
                COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_count,
                COALESCE(SUM(t.estimated_hours), 0) AS total_est_hours,
                COALESCE(SUM(t.actual_hours), 0) AS total_act_hours
            FROM sprints s
            LEFT JOIN projects p_proj ON s.project_id = p_proj.id
            LEFT JOIN tasks t ON s.id = t.sprint_id
            GROUP BY s.id, s.project_id, s.name, s.status, s.start_date, s.end_date, s.capacity_hours, s.created_at, p_proj.key_code
            ORDER BY s.created_at DESC
        """)
        sprint_stats = cur.fetchall()

        for s in sprint_stats:
            cnt = s.get("task_count", 0)
            cmp = s.get("completed_count", 0)
            s["progress"] = round((cmp / cnt * 100), 1) if cnt > 0 else 0
            cap = s.get("capacity_hours", 160) or 160
            est = s.get("total_est_hours", 0) or 0
            s["capacity_utilization"] = round((est / cap * 100), 1) if cap > 0 else 0

        # 4. Priority Risk Breakdown
        cur.execute("""
            SELECT
                priority,
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_count
            FROM tasks
            GROUP BY priority
        """)
        priority_breakdown = cur.fetchall()
        for p in priority_breakdown:
            tot = p.get("total", 0)
            dl = p.get("delayed_count", 0)
            p["delay_rate"] = round((dl / tot * 100), 1) if tot > 0 else 0

        # 5. Complexity Breakdown
        cur.execute("""
            SELECT
                complexity,
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_count
            FROM tasks
            GROUP BY complexity
            ORDER BY complexity ASC
        """)
        complexity_breakdown = cur.fetchall()
        for c in complexity_breakdown:
            tot = c.get("total", 0)
            dl = c.get("delayed_count", 0)
            c["delay_rate"] = round((dl / tot * 100), 1) if tot > 0 else 0

        return render_template(
            "reports.html",
            user=user,
            total_projects=total_projects,
            task_stats=task_stats,
            prediction_stats=prediction_stats,
            sprint_stats=sprint_stats,
            priority_breakdown=priority_breakdown,
            complexity_breakdown=complexity_breakdown
        )

    except Exception as e:
        print("Reports Error:", e)
        flash("Failed to generate analytics report: " + str(e), "danger")
        return render_template(
            "reports.html",
            user=user,
            total_projects=0,
            task_stats={
                "total_tasks": 0,
                "completed_tasks": 0,
                "in_progress_tasks": 0,
                "blocked_tasks": 0,
                "delayed_tasks": 0,
                "completion_rate": 0,
                "total_estimated_hours": 0,
                "total_actual_hours": 0,
                "variance_hours": 0
            },
            prediction_stats={"total_predictions": 0, "average_risk": 0, "average_predicted_hours": 0},
            sprint_stats=[],
            priority_breakdown=[],
            complexity_breakdown=[]
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@reports_bp.route("/reports/export")
@reports_bp.route("/reports/export-sprints")
def export_sprints_csv():
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("""
            SELECT s.name, s.status, s.start_date, s.end_date, s.capacity_hours,
                   COUNT(t.id) AS task_count,
                   COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                   COALESCE(SUM(CASE WHEN t.is_delayed = 1 THEN 1 ELSE 0 END), 0) AS delayed_count,
                   COALESCE(SUM(t.estimated_hours), 0) AS est_hours,
                   COALESCE(SUM(t.actual_hours), 0) AS act_hours
            FROM sprints s
            LEFT JOIN tasks t ON s.id = t.sprint_id
            GROUP BY s.id, s.name, s.status, s.start_date, s.end_date, s.capacity_hours
            ORDER BY s.created_at DESC
        """)
        records = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Sprint Name", "Status", "Start Date", "End Date", "Capacity (hrs)", "Total Tasks", "Completed", "Delayed", "Estimated Hours", "Actual Hours"])

        for r in records:
            writer.writerow([
                r["name"],
                r["status"],
                r["start_date"],
                r["end_date"],
                r["capacity_hours"],
                r["task_count"],
                r["completed_count"],
                r["delayed_count"],
                r["est_hours"],
                r["act_hours"]
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=sprintai_sprints_report.csv"}
        )
    finally:
        cur.close()
        conn.close()
