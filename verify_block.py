####    Scripts start below
import os
import sys
import json
from functions import check_file
from functions import create_connection
from functions import block_hash_base64_to_hex, time_parse
from psycopg2 import errors
from datetime import datetime, timedelta, timezone



with open("info.json", "r") as f:
    info = json.load(f)

db_name = info["psql"]["db_name"]
db_user = info["psql"]["db_user"]
db_password = info["psql"]["db_password"]
db_host = info["psql"]["db_host"]
db_port = info["psql"]["db_port"]

connection = create_connection(db_name, db_user, db_password, db_host, db_port)

file_path = os.getenv("FILE_PATH")
file_name = os.getenv("FILE_NAME")

# json file content
content = check_file(file_path, file_name)
block_hash = content["block_id"]["hash"]
block_hash_hex = block_hash_base64_to_hex(block_hash)
chain_id = content["block"]["header"]["chain_id"]
height = content["block"]["header"]["height"]
tx_num = str(len(content["block"]["data"]["txs"]))
created_time = content["block"]["header"]["time"]

cursor = connection.cursor()

# check block information was inserted into database correctly
# get the block hash, chain id, height, tx number, and created time from database
query = """
SELECT block_hash, chain_id, height, tx_num, created_at FROM blocks WHERE block_hash = %s;
"""

values = (block_hash_hex,)

try:
    cursor.execute(query, values)
    result = cursor.fetchall()
    # check there should only be one row
    if result is None or len(result) != 1:
        # print to stderr
        print("There should be only one row", file=sys.stderr)
        sys.exit(1)
    result = result[0]

    # check the block information is correct
    if result[1] != chain_id or result[2] != height or result[3] != tx_num:
        if result[1] != chain_id:
            print(
                "Chain id is not correct, found",
                result[1],
                "expected",
                chain_id,
                file=sys.stderr,
            )
        if result[2] != height:
            print(
                "Height is not correct, found",
                result[2],
                "expected",
                height,
                file=sys.stderr,
            )
        if result[3] != tx_num:
            print(
                "Tx number is not correct, found",
                result[3],
                "expected",
                tx_num,
                file=sys.stderr,
            )
        sys.exit(1)
    
    if len(created_time) == 30:
        timestamp_truncated = created_time[:26] + "Z"
        # set time zone to -5
        created_time = datetime.strptime(timestamp_truncated, "%Y-%m-%dT%H:%M:%S.%fZ")
        created_time = created_time.replace(tzinfo=timezone.utc).astimezone(
            timezone(timedelta(hours=-5))
        )
    else:
        created_time = datetime.strptime(created_time, "%Y-%m-%dT%H:%M:%S.%fZ")
        created_time = created_time.replace(tzinfo=timezone.utc).astimezone(
            timezone(timedelta(hours=-5))
        )
    print(created_time, file=sys.stderr)
    # check that the created time is correct to the second, ignore the milliseconds
    if result[4].replace(microsecond=0) != created_time.replace(microsecond=0):
        print(
            "Created time is not correct, found",
            result[4],
            "expected",
            created_time,
            file=sys.stderr,
        )
        print(result[4])
        print(type(result[4]), file=sys.stderr)
        sys.exit(1)

except errors.UniqueViolation as e:
    pass
cursor.close()
 #//#/home/tw2623/Indexer-Project/test_blocks/srv/2024/06/01