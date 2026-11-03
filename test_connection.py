from database import test_db_connection, get_active_engine, get_db_connection, get_dict_cursor

try:
    database_name = test_db_connection()
    engine = get_active_engine()
    print(f"SprintAI Database Engine: {engine.upper()}")
    print(f"Connected database identifier: {database_name}")

    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    for tbl in ["projects", "sprints", "tasks", "predictions", "users"]:
        cur.execute(f"SELECT COUNT(*) AS total FROM {tbl}")
        count = cur.fetchone()["total"]
        print(f"  - Table '{tbl}': {count} records")
    cur.close()
    conn.close()
    print("Connection check completed successfully.")

except Exception as error:
    print("Database connection test encountered an error:")
    print(error)
