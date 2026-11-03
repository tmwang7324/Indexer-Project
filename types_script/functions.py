# !/usr/bin/python3
'''**********************************************************************************
                                                                                    *
Project Name: functions.py                                                          *
                                                                                    *
Programming Language: Python 3.11                                                   *
                                                                                    *
Libraries:               psycopg2   2.9.9                                           *
                                                                                    *
Creater Name: Ziqi Yang                                                             *
                                                                                    *
Published Date: 4/15/2024                                                           *
                                                                                    *
Version: 1.0                                                                        *
                                                                                    *
                                                                                    *
                                                                                    *
                                                                                    *
                                                                                    *
**********************************************************************************'''

#    Functions start below
import json
import os
import re
import psycopg2
from psycopg2 import OperationalError


def db_schema():
    """Same rule as the root functions.py: INDEXER_DB_SCHEMA, else "db_schema" in info.json, else None."""
    schema = os.environ.get("INDEXER_DB_SCHEMA")
    if schema is None:
        try:
            with open("info.json", "r") as f:
                schema = json.load(f).get("psql", {}).get("db_schema")
        except (OSError, ValueError):
            schema = None
    if schema and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"db_schema {schema!r} is not a plain schema name")
    return schema or None


def create_connection(db_name, db_user, db_password, db_host, db_port):
    env = os.environ
    db_name = env.get("INDEXER_DB_NAME", db_name)
    db_user = env.get("INDEXER_DB_USER", db_user)
    db_password = env.get("INDEXER_DB_PASSWORD", db_password)
    db_host = env.get("INDEXER_DB_HOST", db_host)
    db_port = env.get("INDEXER_DB_PORT", db_port)
    schema = db_schema()
    connection = None
    try:
        connection = psycopg2.connect(
            database=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            options=f"-c search_path={schema}" if schema else None,
        )
        print("Connection to PostgreSQL DB successful")
    except OperationalError as e:
        print(f"The error '{e}' occurred")
    return connection