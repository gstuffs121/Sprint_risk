import os
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash
from config import Config

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    mysql = None
    MySQLError = Exception

DB_DIR = Path(__file__).resolve().parent
SQLITE_DB_PATH = DB_DIR / "sprint_risk.db"

_active_engine = None  # 'mysql' or 'sqlite'


class SQLiteCursorWrapper:
    """Cursor wrapper for SQLite that mimics MySQL dict cursor and translates %s to ?"""
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor

    def execute(self, query, params=None):
        sql = query.replace("%s", "?")
        if params is None:
            return self.raw_cursor.execute(sql)
        if isinstance(params, (list, tuple)):
            return self.raw_cursor.execute(sql, params)
        return self.raw_cursor.execute(sql, (params,))

    def executemany(self, query, seq_of_params):
        sql = query.replace("%s", "?")
        return self.raw_cursor.executemany(sql, seq_of_params)

    def fetchone(self):
        row = self.raw_cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self.raw_cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        return self.raw_cursor.lastrowid

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount

    def close(self):
        self.raw_cursor.close()


class SQLiteConnectionWrapper:
    """Connection wrapper for SQLite to provide uniform interface with MySQL connector."""
    def __init__(self, sqlite_conn):
        self.conn = sqlite_conn
        self.conn.row_factory = sqlite3.Row

    def cursor(self, dictionary=True):
        raw = self.conn.cursor()
        return SQLiteCursorWrapper(raw)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def is_connected(self):
        return True


def get_db_connection():
    """Create a database connection, trying MySQL first and gracefully falling back to SQLite."""
    global _active_engine

    if mysql is not None and Config.MYSQL_HOST:
        try:
            conn = mysql.connector.connect(
                host=Config.MYSQL_HOST,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DATABASE,
                connect_timeout=3
            )
            if conn.is_connected():
                _active_engine = "mysql"
                return conn
        except Exception:
            pass

    _active_engine = "sqlite"
    sqlite_conn = sqlite3.connect(str(SQLITE_DB_PATH), timeout=10)
    sqlite_conn.execute("PRAGMA foreign_keys = ON;")
    return SQLiteConnectionWrapper(sqlite_conn)


def get_dict_cursor(connection):
    """Obtain a cursor yielding dict rows across both MySQL and SQLite."""
    if hasattr(connection, "cursor"):
        if isinstance(connection, SQLiteConnectionWrapper):
            return connection.cursor(dictionary=True)
        return connection.cursor(dictionary=True)
    return connection.cursor()


def get_active_engine():
    """Return 'mysql' or 'sqlite'."""
    global _active_engine
    if _active_engine is None:
        conn = get_db_connection()
        conn.close()
    return _active_engine or "sqlite"


def test_db_connection():
    """Test connection and return active database identifier."""
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        if get_active_engine() == "mysql":
            cur.execute("SELECT DATABASE() AS db_name")
            res = cur.fetchone()
            return res.get("db_name", "sprint_risk_db")
        else:
            return f"sqlite:{SQLITE_DB_PATH.name}"
    finally:
        cur.close()
        conn.close()


def log_audit(action, details, user_id=None, username=None, ip_address=None):
    """Insert an entry into audit_logs safely."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_logs (user_id, username, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, username or "System", action, str(details), ip_address or "127.0.0.1"))
        conn.commit()
    except Exception as e:
        print("Audit Log Warning:", e)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def init_db():
    """Initialize database tables and default configuration settings (without hardcoded credentials)."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        engine = get_active_engine()
        if engine == "mysql":
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(80) NOT NULL UNIQUE,
                    email VARCHAR(120) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(120) DEFAULT '',
                    role VARCHAR(30) NOT NULL DEFAULT 'user',
                    is_active TINYINT(1) NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sprints (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(150) NOT NULL,
                    goal TEXT,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    capacity_hours FLOAT NOT NULL DEFAULT 160.0,
                    status VARCHAR(50) NOT NULL DEFAULT 'planning',
                    created_by INT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    sprint_id INT NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    assignee VARCHAR(100) DEFAULT '',
                    priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
                    complexity INT NOT NULL DEFAULT 3,
                    dependencies INT NOT NULL DEFAULT 0,
                    estimated_hours FLOAT NOT NULL DEFAULT 0.0,
                    actual_hours FLOAT NOT NULL DEFAULT 0.0,
                    status VARCHAR(30) NOT NULL DEFAULT 'todo',
                    is_delayed TINYINT(1) NOT NULL DEFAULT 0,
                    due_date DATE NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_id INT NOT NULL,
                    predicted_hours FLOAT NOT NULL,
                    risk_probability FLOAT NOT NULL,
                    risk_level VARCHAR(20) NOT NULL,
                    explanation TEXT,
                    model_version VARCHAR(50) DEFAULT 'v1-synthetic-demo',
                    created_by INT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NULL,
                    username VARCHAR(80) NULL,
                    action VARCHAR(100) NOT NULL,
                    details TEXT,
                    ip_address VARCHAR(45) NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    key_name VARCHAR(100) NOT NULL UNIQUE,
                    key_value TEXT NOT NULL,
                    description VARCHAR(255) NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    goal TEXT,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    capacity_hours REAL NOT NULL DEFAULT 160.0,
                    status TEXT NOT NULL DEFAULT 'planning',
                    created_by INTEGER NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sprint_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    assignee TEXT DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'Medium',
                    complexity INTEGER NOT NULL DEFAULT 3,
                    dependencies INTEGER NOT NULL DEFAULT 0,
                    estimated_hours REAL NOT NULL DEFAULT 0.0,
                    actual_hours REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'todo',
                    is_delayed INTEGER NOT NULL DEFAULT 0,
                    due_date TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE CASCADE
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    predicted_hours REAL NOT NULL,
                    risk_probability REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    explanation TEXT,
                    model_version TEXT DEFAULT 'v1-synthetic-demo',
                    created_by INTEGER NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NULL,
                    username TEXT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_name TEXT NOT NULL UNIQUE,
                    key_value TEXT NOT NULL,
                    description TEXT NULL
                );
            """)

        conn.commit()

        # SECURE INITIAL ADMIN PROVISIONING:
        # Predictable default administrator credentials (e.g. admin/admin123) are STRICTLY FORBIDDEN.
        # An initial administrator is only created if explicitly configured by the operator via environment variables.
        init_admin_user = os.getenv("INITIAL_ADMIN_USERNAME")
        init_admin_pwd = os.getenv("INITIAL_ADMIN_PASSWORD")
        init_admin_email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@sprintai.internal")

        if init_admin_user and init_admin_pwd and len(init_admin_pwd) >= 8:
            cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (init_admin_user, init_admin_email))
            if not cur.fetchone():
                admin_pwd_hash = generate_password_hash(init_admin_pwd)
                cur.execute("""
                    INSERT INTO users (username, email, password_hash, full_name, role, is_active)
                    VALUES (%s, %s, %s, %s, 'admin', 1)
                """, (init_admin_user, init_admin_email, admin_pwd_hash, "System Administrator"))
                conn.commit()
                log_audit("ADMIN_PROVISIONED_FROM_ENV", f"Admin '{init_admin_user}' provisioned from environment configuration")

        # Seed Sprints & Tasks if table is completely empty (sample non-sensitive project data)
        cur.execute("SELECT COUNT(*) AS total FROM sprints")
        sprint_count_row = cur.fetchone()
        sprint_count = sprint_count_row["total"] if isinstance(sprint_count_row, dict) else sprint_count_row[0]

        if sprint_count == 0:
            cur.execute("""
                INSERT INTO sprints (name, goal, start_date, end_date, capacity_hours, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                "Sprint 14 - AI Engine & Analytics",
                "Deploy machine learning effort estimation and enhance risk analytics dashboard.",
                "2026-10-20",
                "2026-11-05",
                160.0,
                "active"
            ))
            sprint_1_id = cur.lastrowid or 1

            cur.execute("""
                INSERT INTO sprints (name, goal, start_date, end_date, capacity_hours, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                "Sprint 15 - Core Auth & Admin Portal",
                "Implement enterprise role-based authorization, user management, and security audit.",
                "2026-11-06",
                "2026-11-20",
                140.0,
                "planning"
            ))
            sprint_2_id = cur.lastrowid or 2

            cur.execute("""
                INSERT INTO sprints (name, goal, start_date, end_date, capacity_hours, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                "Sprint 13 - Infrastructure & Data Pipeline",
                "Establish baseline dataset generation and initial model training pipeline.",
                "2026-10-05",
                "2026-10-19",
                150.0,
                "completed"
            ))

            # Sample sprint tasks (non-sensitive demo items)
            sample_tasks = [
                (sprint_1_id, "Build Random Forest effort regressor", "Train regression model on historical sprint complexity.", "Alex Rivera", "High", 4, 2, 24.0, 22.0, "completed", 0, "2026-10-25"),
                (sprint_1_id, "Implement delay probability classifier", "Classification pipeline estimating probability of schedule slip.", "Sarah Jenkins", "Critical", 5, 3, 32.0, 18.0, "in_progress", 1, "2026-11-03"),
                (sprint_1_id, "Integrate Chart.js risk distribution donut", "Visualize task status breakdown and risk categories dynamically.", "Dev Team", "Medium", 3, 1, 14.0, 10.0, "in_progress", 0, "2026-11-04"),
                (sprint_1_id, "Create automated audit log tracking", "Capture security and configuration modifications in database.", "Alex Rivera", "Medium", 2, 0, 12.0, 0.0, "todo", 0, "2026-11-05"),
                (sprint_1_id, "Database migration script for foreign keys", "Standardize relational integrity between tasks and predictions.", "Dev Team", "High", 3, 2, 16.0, 4.0, "blocked", 1, "2026-11-02"),
                (sprint_2_id, "Enterprise Role-Based Access Control", "Implement user roles: admin, scrum master, and developer.", "Sarah Jenkins", "High", 4, 1, 20.0, 0.0, "todo", 0, "2026-11-10"),
                (sprint_2_id, "Admin Portal System Health & Metrics", "Unified view of server uptime, active models, and DB status.", "Alex Rivera", "Medium", 3, 1, 15.0, 0.0, "todo", 0, "2026-11-12"),
            ]

            for t in sample_tasks:
                cur.execute("""
                    INSERT INTO tasks (sprint_id, title, description, assignee, priority, complexity, dependencies, estimated_hours, actual_hours, status, is_delayed, due_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, t)

            conn.commit()

            # Seed sample prediction records
            cur.execute("SELECT id FROM tasks LIMIT 2")
            t_rows = cur.fetchall()
            if t_rows:
                cur.execute("""
                    INSERT INTO predictions (task_id, predicted_hours, risk_probability, risk_level, explanation, model_version)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (t_rows[0]["id"] if isinstance(t_rows[0], dict) else t_rows[0][0], 25.5, 32.0, "Medium", "Moderate complexity and reasonable time buffer.", "v1-synthetic-demo"))
                conn.commit()

        # Seed system settings if empty
        cur.execute("SELECT COUNT(*) AS total FROM system_settings")
        settings_count_row = cur.fetchone()
        settings_count = settings_count_row["total"] if isinstance(settings_count_row, dict) else settings_count_row[0]

        if settings_count == 0:
            defaults = [
                ("risk_threshold_low", "25", "Upper probability limit for Low risk (percent)"),
                ("risk_threshold_medium", "50", "Upper probability limit for Medium risk (percent)"),
                ("risk_threshold_high", "75", "Upper probability limit for High risk (percent)"),
                ("default_sprint_capacity", "160", "Default capacity in hours for new sprints"),
                ("maintenance_mode", "false", "System maintenance mode flag")
            ]
            for s in defaults:
                cur.execute("""
                    INSERT INTO system_settings (key_name, key_value, description)
                    VALUES (%s, %s, %s)
                """, s)
            conn.commit()

    except Exception as e:
        print("init_db Error:", e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()
