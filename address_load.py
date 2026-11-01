#!/usr/bin/python3
'''**********************************************************************************
                                                                                    *
Project Name: address_load.py                                                         *
                                                                                    *
Programming Language: Python 3.11                                                   *
                                                                                    *
Libraries: json                                                                     *
                                                                                    *
Creater Name: Ziqi Yang                                                             *
                                                                                    *
Published Date: 4/15/2024                                                           *
                                                                                    *
Version: 1.0                                                                        *
                                                                                    *
Version: 1.1
Now 'address_load' only needs one input. Also, the info of 'address_type' has
changed to only three condition, 'user', 'validator', and 'contract'.               *
                                                                                    *
**********************************************************************************'''

#    Scripts start below
from functions import create_connection
from datetime import datetime
import json
import os
from psycopg2 import errors
import sys


def classify_address(address, file_name=None):
    """Return 'blank', 'validator', 'user', 'contract' or 'Unknown' for a bech32 address."""
    # Find the bech32 separator: the last '1' in the string. The data part
    # after it can never contain '1', but the prefix in front of it can.
    index_of_1 = address.rfind('1')
    # Count the length after 1
    substring_after_1 = address[index_of_1 + 1:]
    length_after_1 = len(substring_after_1)
    # If the string contains 'valoper' string, this is a validator address
    validator = 'valoper'
    if len(address) == 0:
        return 'blank'
    if validator in address:
        return 'validator'
    # If the length after 1 equals 38, this is a user address.
    # (Checked before the contract case: '>= 38' used to come first, so this
    # branch was unreachable and every user address was labelled 'contract'.)
    if length_after_1 == 38:
        return 'user'
    # If the length after 1 is larger than 38, this is a contract address
    if length_after_1 > 38:
        return 'contract'
    # If the address does not belong to three types above, it will be an unknown type
    print(f"The type of address could not be detected, check address {address} in block {file_name}", file=sys.stderr)
    return 'Unknown'


def main(address):
    #print(address, sys.stderr)
    

    with open('info.json', 'r') as f:
        info = json.load(f)

    db_name = info['psql']['db_name']
    db_user = info['psql']['db_user']
    db_password = info['psql']['db_password']
    db_host = info['psql']['db_host']
    db_port = info['psql']['db_port']

    connection = create_connection(db_name, db_user, db_password, db_host, db_port)
    cursor = connection.cursor()

    file_name = os.getenv('FILE_NAME')
    # Define the values
    comment = ''
    created_time = datetime.now()
    updated_time = created_time

    address_type = classify_address(address, file_name)

    query = """
    INSERT INTO address (address_type, addresses, comment, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)
    RETURNING address_id;
    
    """


    # Load the values
    values = (address_type, address, comment, created_time, updated_time)
    try:
        cursor.execute(query, values)
        address_id = cursor.fetchone()[0]

    except errors.UniqueViolation as e:
        connection.rollback()
        search_query = "SELECT address_id FROM address WHERE addresses = %s"
        cursor.execute(search_query, (address,))
        address_id = cursor.fetchone()[0]

    connection.commit()
    connection.close()
    return address_id

if __name__ == '__main__':
    main(address)
