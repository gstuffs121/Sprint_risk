"""
Secure Administrator Provisioning CLI Tool for SprintAI.
Run via:
    python -m utils.create_admin
or:
    python utils/create_admin.py --username admin --email admin@example.com
"""

import argparse
import getpass
import sys
from werkzeug.security import generate_password_hash
from database import get_db_connection, get_dict_cursor, init_db, log_audit


def provision_admin(username, email, password, full_name="System Administrator"):
    """Provision a new administrator account with validation and audit logging."""
    username = (username or "").strip()
    email = (email or "").strip().lower()
    full_name = (full_name or "").strip() or username

    if not username or len(username) < 3:
        raise ValueError("Administrator username must be at least 3 characters.")

    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")

    if not password or len(password) < 8:
        raise ValueError("Administrator password must be at least 8 characters for security compliance.")

    # Ensure tables exist
    init_db()

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"An account with username '{username}' or email '{email}' already exists.")

        pwd_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users (username, email, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, 'admin', 1)
        """, (username, email, pwd_hash, full_name))
        conn.commit()

        new_id = cur.lastrowid
        log_audit(
            "ADMIN_PROVISIONED_SECURELY",
            f"Administrator account '{username}' provisioned via CLI tool",
            user_id=new_id,
            username=username,
            ip_address="127.0.0.1"
        )
        return new_id
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Secure Administrator Provisioning for SprintAI")
    parser.add_argument("--username", "-u", help="Administrator username")
    parser.add_argument("--email", "-e", help="Administrator email address")
    parser.add_argument("--fullname", "-n", help="Administrator display name", default="System Administrator")
    parser.add_argument("--password", "-p", help="Administrator password (optional; prompted securely if omitted)")

    args = parser.parse_args()

    username = args.username
    if not username:
        username = input("Enter administrator username: ").strip()

    email = args.email
    if not email:
        email = input("Enter administrator email: ").strip()

    fullname = args.fullname or "System Administrator"

    password = args.password
    if not password:
        password = getpass.getpass("Enter administrator password (min 8 chars): ")
        confirm = getpass.getpass("Confirm administrator password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    try:
        admin_id = provision_admin(username, email, password, fullname)
        print(f"Success: Administrator '{username}' provisioned successfully (User ID: #{admin_id}).")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
