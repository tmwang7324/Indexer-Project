# !/usr/bin/python3
'''**********************************************************************************
                                                                                    *
Project Name: functions.py                                                          *
                                                                                    *
Programming Language: Python 3.11                                                   *
                                                                                    *
Libraries: json  os    sys     requests  2.31.0      jsonschema   4.21.1           *
            time               psycopg2   2.9.9       hashlib         base64        *
            binascii                                                                *
Creater Name: Ziqi Yang                                                             *
                                                                                    *
Published Date: 4/15/2024                                                           *
                                                                                    *
Version: 1.0                                                                        *
                                                                                    *
Version: 1.1                                                                        *
Function 'hash_to_hex' has been added to convert transaction string to hex hash     *
Function 'block_hash_base64_to_hex' has been added to convert base 64 block hash    *
to hex hash                                                                         *
hashlib, base64, and binascii, these three packages have been added                 *
All of them are included in original Python                                         *
                                                                                    *  
Version: 1.2                                                                        *
Function 'decode_tx' has been updated. The old url had been changed to new url      *
'https://terra-rest.publicnode.com/cosmos/tx/v1beta1/decode'                        *
                                                                                    *
Version: 1.3                                                                        *
Function 'new_type' has been created to store new message type if there is          *
**********************************************************************************'''

#    Functions start below
import json
import os
from jsonschema import validate
from jsonschema.exceptions import ValidationError
import sys
import requests
import time
import psycopg2
from psycopg2 import OperationalError
import hashlib
import base64
import binascii
from datetime import datetime, timezone
import traceback
#//from terra_sdk.client.lcd import LCDClient
#from terra_sdk.core.tx import Tx #?/ trmintimport

def check_file(file_path,file_name):

    # Check if the file exists in the directory
    if os.path.isfile(file_path):
        pass
        # print(f'{file_name} does exist in {path_name}')
    else:
        print(f'{file_name} does exist in {file_path}, or {file_name} is not a file', file=sys.stderr)
        sys.exit(1)



        # Check if the file name is composed entirely of digits
    if file_name.isdigit():
        pass
            #print('This file is named by numbers')
    else:
        print(f"The file name {file_name} is not composed entirely of digits.", file=sys.stderr)
        sys.exit(2)



    # Check if it is a JSON file
    try:
        with open(file_path, 'r') as file:
            # print(f"{file_name} is a JSON file.")
            content = json.load(file)

    except json.JSONDecodeError:
        print(f"{file_name} is not a JSON file.", file=sys.stderr)
        file = open(file_path, "r")
        print(file)
        checkLine(file_path, file_name,len(file.readlines()) - 1)
        file.close()
        sys.exit(3)

    except ValueError as e:
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
        sys.exit(4)

    return content


def height_check(content,file_name):
    try:

        # Check if the file name equals the height
        height = content['block']['header']['height']
    except KeyError:
        print("There is not such key in the file", file=sys.stderr)
        sys.exit(5)
    except TypeError:
        print("The Type of value is not correct", file=sys.stderr)
        sys.exit(6)

    if height == file_name:
        # print(f'{file_name} is same as height.')
        pass
    else:
        print(f'Error: {file_name} does not same as height.', file=sys.stderr)
        sys.exit(7)

    # print(f'{file_name} is a valid JSON file and the name is same as the BLOCK HEIGHT'
    return height


def Validate_json(content, file_name):
    schema = {
            "type": "object",
            "properties":{
                "block_id": {
                    "type": "object",
                    "properties": {
                        "hash": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9+/=]+$",
                            "minLength": 44,
                            "maxLength": 44
                        },
                        "part_set_header": {
                            "type": "object",
                            "properties": {
                                "total": {
                                "type": "integer"
                                },
                                "hash": {
                                    "type": "string",
                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                    "minLength": 44,
                                    "maxLength": 44
                                },
                            },
                            "required": ["total","hash"]
                        },
                    },
                    "required": ["hash","part_set_header"]

                },
                "block": {
                    "type": "object",
                    "properties": {
                        "header": {
                            "type": "object",
                            "properties": {
                                "version": {
                                    "type": "object",
                                    "properties": {
                                        "block":{
                                            "type": "string",
                                            "pattern": r"^\d+$"
                                        },
                                        "app": {
                                            "type": "string",
                                            "pattern": r"^\d+$"
                                        },
                                    },
                                    "required": ["block","app"]
                                },
                                "chain_id": {
                                    "type": "string"
                                },
                                "height": {
                                    "type": "string",
                                    "pattern": r"^\d+$"
                                },
                                "time": {
                                    "type": "string",
                                    "format": "date-time"
                                },
                                "last_block_id": {
                                    "type": "object",
                                    "properties": {
                                        "hash": {
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9+/=]+$",
                                            "minLength": 44,
                                            "maxLength": 44
                                        },
                                        "part_set_header": {
                                            "type": "object",
                                            "properties": {
                                                "total": {
                                                  "type": "integer"
                                                },
                                                "hash": {
                                                   "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                                    "minLength": 44,
                                                    "maxLength": 44
                                                },
                                            },
                                            "required": ["total","hash"]
                                        },
                                    },
                                    "required": ["hash","part_set_header"]
                                },
                                "last_commit_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "data_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "validators_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "next_validators_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "consensus_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "app_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "last_results_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "evidence_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "proposer_address": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 28,
                                        "maxLength": 28
                                },
                            },
                            "required": ["version","chain_id","height", "time","last_block_id","last_commit_hash","data_hash","validators_hash","next_validators_hash","consensus_hash","app_hash","last_results_hash","evidence_hash","proposer_address"]
                        },
                        "data":{
                            "type": "object",
                            "properties": {
                                "txs": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                },
                            },
                            "required": ["txs"]
                        },
                        "evidence":{
                            "type": "object",
                            "properties": {
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                },
                            },
                            "required": ["evidence"]
                        },
                        "last_commit":{
                            "type": "object",
                            "properties": {
                                "height": {
                                    "type": "string",
                                    "pattern": r"^\d+$"
                                },
                                "round": {
                                    "type": "integer",
                                    "min": 0
                                },
                                "block_id":{
                                    "type": "object",
                                    "properties": {
                                        "hash":{
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9+/=]+$",
                                            "minLength": 44,
                                            "maxLength": 44
                                        },
                                        "part_set_header": {
                                            "type": "object",
                                            "properties": {
                                                "total": {
                                                    "type": "integer",
                                                    "min": 0
                                                },
                                                "hash":{
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                                    "minLength": 44,
                                                    "maxLength": 44
                                                }
                                            },
                                            "required": ["total","hash"]
                                        }
                                    },
                                    "required":["hash","part_set_header"]
                                },

                                "signatures": {
                                    "type": "array",
                                    "items": {
                                        "if" :{
                                            "properties": {
                                                "block_id_flag": {
                                                    "type": "string",
                                                    "pattern": "BLOCK_ID_FLAG_COMMIT"
                                                },
                                            },
                                        "then":{
                                                "properties": {
                                                 "block_id_flag": {
                                                       "type": "string"
                                                 },
                                                 "validator_address": {
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$"
                                                 },
                                                "timestamp": {
                                                    "type": "string",
                                                    "format": "date-time"
                                                },
                                                "signature": {
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                                    "minLength": 88,
                                                    "maxLength": 88
                                                }
                                            },
                                        },
                                        "else":{
                                            "properties": {
                                                 "block_id_flag": {
                                                       "type": "string"
                                                 },
                                                 "validator_address": {
                                                    "type": "string",
                                                    "pattern": "null"
                                                 },
                                                "timestamp": {
                                                    "type": "string",
                                                    "pattern": "0001-01-01T00:00:00Z"
                                                },
                                                "signature": {
                                                    "type": "string",
                                                    "pattern": "null"
                                                },
                                            },
                                        },
                                        "required": ["block_id_flag", "validator_address", "timestamp", "signature"]
                                        },
                                    }
                                }
                            },
                            "required": ["height","round","block_id","signatures"]
                        },
                    },
                    "required": ["header","data","evidence","last_commit"]
                },
                "sdk_block":{
                    "type": "object",
                    "properties": {
                        "header": {
                            "type": "object",
                            "properties": {
                                "version": {
                                    "type": "object",
                                    "properties": {
                                        "block":{
                                            "type": "string",
                                            "pattern": r"^\d+$"
                                        },
                                        "app": {
                                            "type": "string",
                                            "pattern": r"^\d+$"
                                        },
                                    },
                                    "required": ["block","app"]
                                },
                                "chain_id": {
                                    "type": "string"
                                },
                                "height": {
                                    "type": "string",
                                    "pattern": r"^\d+$"
                                },
                                "time": {
                                    "type": "string",
                                    "format": "date-time"
                                },
                                "last_block_id": {
                                    "type": "object",
                                    "properties": {
                                        "hash": {
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9+/=]+$",
                                            "minLength": 44,
                                            "maxLength": 44
                                        },
                                        "part_set_header": {
                                            "type": "object",
                                            "properties": {
                                                "total": {
                                                  "type": "integer"
                                                },
                                                "hash": {
                                                   "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                                    "minLength": 44,
                                                    "maxLength": 44
                                                },
                                            },
                                            "required": ["total","hash"]
                                        },
                                    },
                                    "required": ["hash","part_set_header"]
                                },
                                "last_commit_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "data_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "validators_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "next_validators_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "consensus_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "app_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "last_results_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "evidence_hash": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 44,
                                        "maxLength": 44
                                },
                                "proposer_address": {
                                        "type": "string",
                                        "pattern": "^[A-Za-z0-9+/=]+$",
                                        "minLength": 53,
                                        "maxLength": 53
                                },
                            },
                            "required": ["version","chain_id","height", "time","last_block_id","last_commit_hash","data_hash","validators_hash","next_validators_hash","consensus_hash","app_hash","last_results_hash","evidence_hash","proposer_address"]
                        },
                        "data":{
                            "type": "object",
                            "properties": {
                                "txs": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                },
                            },
                            "required": ["txs"]
                        },
                        "evidence":{
                            "type": "object",
                            "properties": {
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                },
                            },
                            "required": ["evidence"]
                        },
                        "last_commit":{
                            "type": "object",
                            "properties": {
                                "height": {
                                    "type": "string",
                                    "pattern": r"^\d+$"
                                },
                                "round": {
                                    "type": "integer",
                                    "min": 0
                                },
                                "block_id":{
                                    "type": "object",
                                    "properties": {
                                        "hash":{
                                            "type": "string",
                                            "pattern": "^[A-Za-z0-9+/=]+$"
                                        },
                                        "part_set_header": {
                                            "type": "object",
                                            "properties": {
                                                "total": {
                                                    "type": "integer",
                                                    "min": 0
                                                },
                                                "hash":{
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$"
                                                }
                                            },
                                            "required": ["total","hash"]
                                        }
                                    },
                                    "required":["hash","part_set_header"]
                                },

                                "signatures": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "if" :{
                                            "properties": {
                                                "block_id_flag": {
                                                    "type": "string",
                                                    "pattern": "BLOCK_ID_FLAG_COMMIT"
                                                },
                                            },
                                        "then":{
                                                "properties": {
                                                 "block_id_flag": {
                                                       "type": "string"
                                                 },
                                                 "validator_address": {
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$"
                                                 },
                                                "timestamp": {
                                                    "type": "string",
                                                    "format": "date-time"
                                                },
                                                "signature": {
                                                    "type": "string",
                                                    "pattern": "^[A-Za-z0-9+/=]+$",
                                                    "minLength": 88,
                                                    "maxLength": 88
                                                }
                                            },
                                        },
                                        "else":{
                                            "properties": {
                                                 "block_id_flag": {
                                                       "type": "string"
                                                 },
                                                 "validator_address": {
                                                    "type": "string",
                                                    "pattern": "null"
                                                 },
                                                "timestamp": {
                                                    "type": "string",
                                                    "pattern": "0001-01-01T00:00:00Z"
                                                },
                                                "signature": {
                                                    "type": "string",
                                                    "pattern": "null"
                                                },
                                            },
                                        },
                                        "required": ["block_id_flag", "validator_address", "timestamp", "signature"]
                                        },
                                    }

                                }
                            },
                            "required": ["height","round","block_id","signatures"]
                        },
                    },
                    "required": ["header","data","evidence","last_commit"]
                }
            },
            "required": ["block_id","block","sdk_block"]
    }

    try:
        validate(instance=content, schema=schema)
        #print(f'Content in {file_name} has been validated')
        return 1
    except ValidationError as ve:
        print(f"JSON data of {file_name} is invalid.", file=sys.stderr)
        print(ve, file=sys.stderr)
        print(traceback.format_exc())

def new_type(message, file_path, height, transaction_num, message_num):

        path = f'{file_path}/new_type.txt'

        # Check if the file exist
        if not os.path.isfile(path):
            print(f"File does not exist. Creating '{path}'...")
            try:
                # Use 'x' mode to create the file
                with open(path, 'x') as file:
                    print(f"File '{path}' created successfully.")
            except FileExistsError:
                pass

        # If and only if the type is unique, it will be stored.
        with open(path, 'a') as file:  # Use 'a' mode to append the content
            file.write(f"The message is the No. {message_num} message in No. {transaction_num} transaction  from block {height} \n")
            file.write(message + '\n' + '\n')


def decode_tx(tx, max_retries=10, retry_delay=2):
    """
    Decodes a transaction using an external API.

    Args:
        tx: The transaction to decode.
        max_retries: Maximum number of retries for the request.
        retry_delay: Time to wait between retries (in seconds).

    Returns:
        Decoded transaction if successful, None otherwise.
    """
    url_array = ["https://terra-rest.publicnode.com", "https://api-terra-01.stakeflow.io", "https://terra-api.polkachu.com"]
    headers = {'Content-Type': 'application/json'}
    data = json.dumps({"tx_bytes": tx})
    retries = 0

    while retries < max_retries:
        # Cycle through the endpoints so retries past the end of the list wrap
        # around instead of raising IndexError, and join the path with exactly
        # one '/' whether or not the base URL ends with one.
        base_url = url_array[retries % len(url_array)].rstrip('/')
        full_url = base_url + "/cosmos/tx/v1beta1/decode"
        try:
            response = requests.post(full_url, headers=headers, data=data, timeout=5)  # Adding a 5-second timeout
            if response.status_code == 200:
                print(f"Successfully decoded transaction")
                return response.json()
            else:
                print(f"Error: Unable to decode transaction, server returned status code {response.status_code} using {full_url}", file=sys.stderr)
                if response.status_code in [400, 429, 500, 502, 503, 504]:  # Retry on certain status codes
                    time.sleep(retry_delay)
                    retries += 1
                else:
                    break  # Do not retry on other errors
        except requests.exceptions.RequestException as e:
            print(f"Network request error: {e} using {full_url}", file=sys.stderr)
            time.sleep(retry_delay)
            retries += 1

    return None


def create_connection(db_name, db_user, db_password, db_host, db_port):
    connection = None
    try:
        connection = psycopg2.connect(
            database=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
        )
        #print("Connection to PostgreSQL DB successful")#
    except OperationalError as e:
        print(f"The error '{e}' occurred")
    return connection

def hash_to_hex(data: str) -> str:
    try:
        # Convert data from base64 to bytes
        data_bytes = base64.b64decode(data)
        # Calculate SHA-256 hash
        sha256_hash = hashlib.sha256(data_bytes).hexdigest()
        # Convert hash to uppercase
        return sha256_hash.upper()
    except Exception as e:
        print(f"Error while hashing: {e}")
        return None

def block_hash_base64_to_hex(hash: str) -> str:
    try:
        # Convert data from base64 to bytes
        data_bytes = base64.b64decode(hash)
        # Convert SHA-256 hash
        hex_str = binascii.hexlify(data_bytes).decode('utf-8')
        # Convert hash to uppercase
        return hex_str.upper()
    except Exception as e:
        print(f"Error while hashing: {e}")
        return None
def checkLine(file_path, file_name, N):
       try:
            print("ran", file=sys.stderr)
            with open(file_path, 'r') as fr:
                # reading line by line
                lines = fr.readlines()
                if(N >= len(lines) or N == 0):
                    print(f"Error: Line number does not exist", file=sys.stderr)
                else:
                    if lines[N - 1].strip() != '':
                        foundError = N
                    else:
                        foundError = -1
                    # pointer for position
                    ptr = 1
                
                    # opening in writing mode
                    if foundError != -1:
                        with open(file_path, 'w') as fw:
                            for line in lines:
                            
                                # we want to remove 5th line
                                if ptr != foundError:
                                    fw.write(line)
                                ptr += 1
                        print(foundError, sys.stderr)
            print("Deleted", file=sys.stderr)
            
            check_file(file_path, file_name)
       except:
            print("Oops! something error", sys.stderr)
            print(traceback.format_exc())


def time_parse(time_string):
    timestamp_truncated = time_string[:19] # ignore the milliseconds
    created_time = (
        datetime.strptime(timestamp_truncated, "%Y-%m-%dT%H:%M:%S")
        .replace(tzinfo=timezone.utc)
        .replace(microsecond=0)
    )
    return created_time


def time_parse_old(time_string):
    time_list = list(time_string)
    #print(time_string)
    if len(time_string) == 30:
        milisecond_str = ""
        microsecond_str = ""
        for item in time_list[20: 26]:
            milisecond_str = milisecond_str + item
            for item in time_list[26:-2]:
                microsecond_str = microsecond_str + item
        rounded_mili = milisecond_str + "." + microsecond_str
        #print(rounded_mili)
        rounded_mili = round(float(rounded_mili))
        rounded_mili = str(rounded_mili).zfill(len(milisecond_str))
                    
                    
                    
        time_list = "".join(time_list[:20])
        time_list = time_list + rounded_mili
                    
                
        dt = datetime.strptime(time_list, "%Y-%m-%dT%H:%M:%S.%f")                
        formatted_dt =  dt.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00"
    else:
        parsed_time_string = time_string.replace("Z", "")
        dt = datetime.strptime(parsed_time_string, "%Y-%m-%dT%H:%M:%S.%f")
        formatted_dt =  dt.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00"

    return formatted_dt      
