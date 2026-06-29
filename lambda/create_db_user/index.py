import json
import os
import boto3
import pymysql


def handler(event, context):
    if event["RequestType"] == "Delete":
        return

    secrets_manager = boto3.client("secretsmanager")

    master_user = json.loads(
        secrets_manager.get_secret_value(SecretId=os.environ["MASTER_SECRET_ARN"])[
            "SecretString"
        ]
    )
    app_user = json.loads(
        secrets_manager.get_secret_value(SecretId=os.environ["APP_SECRET_ARN"])[
            "SecretString"
        ]
    )

    conn = pymysql.connect(
        host=os.environ["DB_ENDPOINT"],
        user=master_user["username"],
        password=master_user["password"],
        database=os.environ["DB_NAME"],
        connect_timeout=10,
    )

    try:
        with conn.cursor() as cursor:
            app_username = app_user["username"]
            app_password = app_user["password"]
            db_name = os.environ["DB_NAME"]

            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{app_username}'@'%' IDENTIFIED BY '{app_password}'"
            )

            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{db_name}`.* TO '{app_username}'@'%'"
            )

            conn.commit()
    finally:
        conn.close()
