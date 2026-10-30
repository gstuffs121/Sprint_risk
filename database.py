
import mysql.connector
from mysql.connector import Error
from config import Config


def get_db_connection():
    """Create a new MySQL connection."""
    return mysql.connector.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )


def test_db_connection():
    connection = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE()")
        result = cursor.fetchone()
        cursor.close()

        return result[0]

    except Error:
        raise

    finally:
        if connection and connection.is_connected():
            connection.close()
