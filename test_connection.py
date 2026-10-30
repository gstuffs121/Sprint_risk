
from database import test_db_connection

try:
    database_name = test_db_connection()
    print("MySQL connection successful!")
    print("Connected database:", database_name)

except Exception as error:
    print("MySQL connection failed!")
    print(error)
