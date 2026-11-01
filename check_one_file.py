#!/usr/bin/python3
'''**********************************************************************************
                                                                                    *
Project Name: check_one_file.py                                        *
                                                                                    *
Programming Language: Python 3.11                                                    *
                                                                                    *
Libraries: json sys  os  redis 5.0.1              jsonschema 4.17.3                     *
           requests  2.31.0
                                                                        *
Creater Name: Ziqi Yang                                                             *
                                                                                    *
Published Date: 2/26/2024                                                          *
                                                                                    *
Version: 1.0                                                                        *
                                                                                    *
                                                                                    *
                                                                                    *
                                                                                    *
                                                                                    *
**********************************************************************************'''

####    Scripts start below
import os
import sys
import json
from functions import check_file
from functions import height_check
from functions import Validate_json, checkLine
from functions import new_type
from functions import decode_tx



file_path = os.getenv('FILE_PATH')
file_name = os.getenv('FILE_NAME')

result = check_file(file_path, file_name)
height = height_check(result, file_name)

# Check if this file passes JSON Schema test. 1 is the specific case that passes.
if Validate_json(result, file_name) == 1:

    # Count numbers of transactions in this block
    count = len(result["block"]["data"]["txs"])

    # If there is no transaction in this block, end this progress
    if count == 0:
        sys.exit(10)
    else:
        sys.exit(0)
else:
    # The file is valid JSON but does not match the block schema. Report it and
    # leave the file untouched: an indexer should never rewrite its input. (The
    # previous code called checkLine with the wrong number of arguments, so it
    # crashed with a TypeError before it could exit with code 8.)
    print(f"{file_name} does not match the block schema; see the validation error above.", file=sys.stderr)
    sys.exit(8)
