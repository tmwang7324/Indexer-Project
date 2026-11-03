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
import traceback
from functions import check_file
from functions import height_check
from functions import Validate_json, checkLine
from functions import new_type
from functions import decode_tx



file_path = os.getenv('FILE_PATH')
file_name = os.getenv('FILE_NAME')

# Line removed from a block that fails the schema check (see the block fixer below)
MALFORMED_LINE = 5
# The field on that line: its schema error path must be this for the fixer to act
MALFORMED_FIELD = 'block_id.part_set_header.total'

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
    # Block fixer: some malformed blocks had a bad 5th line, so remove line 5
    # from the file and exit 8. The run stops; re-running picks up the fixed file.
    #
    # The previous version called checkLine(file_name, 1), which takes three
    # arguments, so it raised a TypeError and exited 1 instead of 8. The shell
    # only stops on 8, so it went on to load the schema-invalid block. It also
    # opened file_name (relative to the working directory) instead of file_path.
    foundError = MALFORMED_LINE
    # Only the known defect is repaired. A block that fails the schema for any other reason is reported and left
    # exactly as it is, so repeated runs no longer eat a line each time (D11).
    if Validate_json.last_error_path != MALFORMED_FIELD:
        print(f"{file_name} fails the schema at {Validate_json.last_error_path!r}, not at {MALFORMED_FIELD!r}; "
              f"the file is left unchanged", file=sys.stderr)
        sys.exit(8)
    try:
        with open(file_path, 'r') as fr:
            # reading line by line
            lines = fr.readlines()

        if foundError <= len(lines) and lines[foundError - 1].strip() != '':
            removed = lines[foundError - 1]
            # opening in writing mode
            with open(file_path, 'w') as fw:
                for ptr, line in enumerate(lines, start=1):
                    # we want to remove 5th line
                    if ptr != foundError:
                        fw.write(line)
            # Log the exact text removed so the original block can be restored
            print(f"Deleted line {foundError} of {file_name}: {removed.strip()}", file=sys.stderr)
        else:
            print(f"{file_name} has no non-blank line {foundError}; nothing deleted", file=sys.stderr)
    except OSError:
        print(f"Could not rewrite {file_path}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
    sys.exit(8)
