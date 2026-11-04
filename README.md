# Indexer Project

## Intro
Indexer Project achieves Extract, Translate, Loading (ETL) progress by using Python and Shell script, allowing users to load different information from files to database. The blocks in blockchains are the primary information to be loaded. 

## Requirement
**Python3**, **PostgreSQL**, **JQ**, and **Shell** are required to run the project. To run the project, installation of all three softwares is required, including the Python liabraries that the Project applies. 
### Python:
#### Version: 3.10 or above 
### PostgreSQL:
#### Version: 16.2
### JQ:
#### Version: 1.7.1

## Installation
*Note: If using python3 command, replace all instances of pip with pip3.*

Before installing the dependencies, please type command:
```
pip install --upgrade pip
```

```
pip freeze
```

To install all required libraries for Python, run the following command
```
pip install -r requirements.txt
```

## Database setup
The indexer needs a running PostgreSQL 16 server with an empty database. `load_transactions.sh` creates all of the tables itself (it runs `Txs.sql` on every start), so you only create the database.

### 1. Install the client tools
`load_transactions.sh` calls the `psql` client and `jq` directly, so both must be installed on your machine even if the server runs in Docker.

macOS (Homebrew):
```
brew install libpq jq
brew link --force libpq
```
Ubuntu/Debian (on Windows, use WSL):
```
sudo apt install postgresql-client jq
```
Check that both work with `psql --version` and `jq --version`.

### 2. Start the server
#### Option A: Docker (recommended)
Keeps PostgreSQL isolated from the rest of your machine and easy to reset. This creates the user `indexer` with password `indexer` and the database `indexer`, and keeps the data in a Docker volume so it survives restarts:
```
docker run -d --name indexer-db \
  -e POSTGRES_USER=indexer -e POSTGRES_PASSWORD=indexer -e POSTGRES_DB=indexer \
  -p 5432:5432 -v indexer-pgdata:/var/lib/postgresql/data \
  postgres:16
```
If something on your machine already uses port 5432, publish another port instead (for example `-p 5433:5432`) and use it as `db_port` in `info.json`.

Day-to-day commands:
```
docker stop indexer-db        # stop the server (data is kept)
docker start indexer-db       # start it again
docker exec -it indexer-db psql -U indexer -d indexer    # open a SQL shell
```
To delete everything and start over:
```
docker rm -f indexer-db
docker volume rm indexer-pgdata
```

#### Option B: Native install
macOS:
```
brew install postgresql@16
brew services start postgresql@16
```
Ubuntu/Debian:
```
sudo apt install postgresql
```
Then create a user and database (on Linux, run these as the `postgres` user, e.g. `sudo -u postgres createuser ...`):
```
createuser --pwprompt indexer
createdb --owner indexer indexer
```

### 3. Point the indexer at the database
Copy `info.json.template` to `info.json` and fill it in. With either option above, using the example user and password:
```json
{
    "psql": {
        "db_name": "indexer",
        "db_user": "indexer",
        "db_password": "indexer",
        "db_host": "localhost",
        "db_port": "5432"
    }
}
```
`info.json` is listed in `.gitignore`, so your credentials are never committed.

Check the connection:
```
PGPASSWORD=indexer psql -h localhost -p 5432 -U indexer -d indexer -c "select version();"
```

## Usage
To run the whole project, run the command git clone
```
git clone https://github.com/Shikhar-G/Indexer-Project.git
```
**Please open 'info.json.template', copy this file to a new file called 'info.json', and input the postgreSQL login information (see [Database setup](#database-setup)). Do not input any personal information into info.json.template.**

*For the `db_name` field, ensure this database already exists.*

**This script requires a folder containing decrypted blocks to be parsed.**

Then, from the root directory of the repository, run following command:
```
./load_transactions.sh -b <block folder location>
```
or if using the `python3` command, run:
```
./load_transactions.sh -b <block folder location> -t
```
if the command above does not work, run the following:
```
bash load_transactions.sh -b <block folder location>
```
or 
```
bash load_transactions.sh -b <block folder location> -t
```
### The old pipeline is a performance baseline
`load_transactions.sh` is kept so the new indexer can be compared with it. **Run it on its own, never at the same time
as the indexer**: two writers on one machine skew each other's timings, and the comparison (below) exists to be fair.
To keep its tables apart from the indexer's, give it a schema: `"db_schema": "legacy"` under `psql` in `info.json`, or
`INDEXER_DB_SCHEMA=legacy` in the environment (the script creates the schema and applies it as the connection's
`search_path`; with neither set it uses the database default, exactly as before). `INDEXER_DB_NAME`, `_USER`,
`_PASSWORD`, `_HOST` and `_PORT` override the values in `info.json` when set. `LEGACY_DECODE_URLS` (comma-separated
base URLs) replaces the public decode endpoints, for example with a local fake. The validator accepts Terra blocks, and
the line-5 fixer only deletes a line when the schema error is about `block_id.part_set_header.total`; any other
failure exits 8 and leaves the file as it is.

## Running the tests
From the root directory of the repository:
```
python3 -m unittest discover -s tests
```
The tests that need PostgreSQL are skipped unless `INDEXER_TEST_DB_NAME` is set. **They drop and recreate the `public` schema of that database, so use a throwaway database.** Connection settings come from `INDEXER_TEST_DB_NAME`, `INDEXER_TEST_DB_USER`, `INDEXER_TEST_DB_PASSWORD`, `INDEXER_TEST_DB_HOST` and `INDEXER_TEST_DB_PORT`:
Create the test database once. With the Docker setup:
```
docker exec indexer-db createdb -U indexer indexer_test
```
or with a native install:
```
createdb --owner indexer indexer_test
```
Then run the tests against it:
```
INDEXER_TEST_DB_NAME=indexer_test INDEXER_TEST_DB_USER=indexer INDEXER_TEST_DB_PASSWORD=indexer python3 -m unittest discover -s tests
```
Transactions are decoded from saved fixtures in `tests/fixtures/decoded`, so the tests need no network access.

# The new indexer (`indexer/`, `api/`)

The revamp described in [REVAMP.md](REVAMP.md) lives next to the old pipeline, which stays as it is (D8). It is built
ticket by ticket from [docs/tickets/](docs/tickets/README.md).

```
 files / replay cache / live nodes ──> parse ──> handlers ──> writer ──> PostgreSQL (schema `indexer`) ──> GraphQL API
```

## Setup
```
pip install -r requirements-dev.txt
docker compose up -d postgres-test        # PostgreSQL 16 on 127.0.0.1:5433, thrown away when stopped
```
Settings come from environment variables; the defaults match the Compose test database:
`INDEXER_DB_HOST`, `INDEXER_DB_PORT`, `INDEXER_DB_NAME`, `INDEXER_DB_USER`, `INDEXER_DB_PASSWORD`.
Create the schema with `alembic upgrade head` (migrations are hand-written SQL in `migrations/versions/`).

## Running
```
python -m indexer run --source files:test_blocks                 # Migaloo block files that have a decoded fixture
python -m indexer run --source replay:tests/indexer/data/terra   # Terra blocks from a replay cache
python -m indexer run --source rest [--from-height N] [--to-height M] [--no-follow] [--workers W] [--record DIR]
python -m indexer verify --sample 50 --source replay:DIR [--seed S]   # compare stored blocks with the source
python -m api                                                    # GraphQL at http://127.0.0.1:8000/graphql
python -m indexer bench --heights A:B --prepare                  # fetch the benchmark inputs (needs the network)
python -m indexer bench --heights A:B [--workers W] [--decode local|live] [--live] [--only old,baseline,new]
```
**Where a live run starts:** one above the checkpoint if there is one, otherwise `--from-height`, otherwise 25,000
blocks below the head. **Where it ends:** with `--to-height` or `--no-follow` at that height or the head found at start;
otherwise it catches up, then keeps polling the head and indexes each new block (stop it with SIGTERM or Ctrl-C).
`--workers W` runs W threads that share a connection pool; blocks finish out of order, and the checkpoint
(`checkpoints` table) is the highest height below which every block is stored. A restart skips what is stored.

`--record DIR` saves the raw responses of every fetched block (gzipped) into a replay cache, so later runs
(`--source replay:DIR`) need no network. Public endpoints and their rate limits are in
`indexer/sources/endpoints.py`.

**Errors:** transient errors (timeouts, 429/5xx, a dropped database connection) are retried with a doubling delay;
a block that still fails, or has bad data (including a count mismatch between the source and what was written), is
rolled back and recorded in `failed_blocks` while the run goes on. A bug stops the whole run. If 10 blocks in a row
are given up on, the run stops as an outage.

**Benchmark (`bench`):** compares the old pipeline, the single-threaded baseline (commit `3d34de0`, checked out into a
temporary `git worktree` and migrated with its own migrations) and the revamped pipeline on the same consecutive Terra
blocks. `--prepare` records the new indexer's responses into `bench/cache` and fetches the old-format block files into
`bench/blocks` (`--from-cache DIR` derives both from an existing replay cache instead). A run executes the contenders
**one after another**, each in its own scratch database that is dropped afterwards, refuses to start while an
`application_name=indexer` session is active on the server, checks height by height that every contender stored the same
blocks, transactions and messages, and writes `bench/report-<time>.md`. Exit code `0` ran and matched, `1` a parity
mismatch, `2` could not run. The old pipeline's time includes two decode requests per transaction (`--decode local`
answers them from the prepared cache, `--decode live` asks the public nodes). `--live` makes the baseline and the
revamped pipeline fetch from the nodes instead of reading the cache. The scratch databases need a role that may
`CREATE DATABASE`. Results: `docs/benchmarks/final-comparison.md`.

**Exit codes:** `0` finished; `1` stopped by an error or outage; `2` stopped by SIGTERM/SIGINT after the blocks in
flight finished; `3` finished, but some blocks are in `failed_blocks`.

**Environment:** `INDEXER_DB_*` (database), `INDEXER_ENDPOINTS` (JSON list of nodes with `rate`/`burst`),
`INDEXER_ENDPOINT_COOLDOWN` (seconds a failing endpoint is skipped, default 30), `INDEXER_POLL_INTERVAL` (seconds
between head lookups when following, default 6), `INDEXER_BACKFILL_DEPTH` (default 25000), `INDEXER_MAX_ATTEMPTS`
(default 5) and `INDEXER_RETRY_DELAY` (seconds before the first retry, default 1).

Example query:
```graphql
{ address(value: "migaloo1fc4kjfau480nr503yl0r8ml7vvn07d2r7ztjky") {
    type
    messages { role message { type details transaction { hash height } } } } }
```

## Tests
```
pytest -m unit            # no I/O
pytest -m component       # needs postgres-test
pytest -m integration     # needs postgres-test
pytest -m e2e             # starts the indexer and the API as separate processes
pytest -m legacy          # the old pipeline's tests
pytest --update-golden    # rewrite expected-JSON files; review the diff before committing
```
The test database is `INDEXER_TEST_DB_*` (default `127.0.0.1:5433`, database `indexer_test`, user and password
`indexer`). A missing database **fails** the database-backed tests; it never skips them. Run the legacy tests against
a separate database (`INDEXER_TEST_DB_NAME=legacy_test pytest -m legacy`): they reset the `public` schema and create
unqualified tables, which would otherwise land in the `indexer` schema when the database user is called `indexer`. (The
old pipeline itself can use a `legacy` schema now; test `I10` covers that.)

The curated Terra sample under `tests/indexer/data/terra/` (about 50 real `phoenix-1` blocks) was picked with
`tools/curate_sample.py` from a local replay cache.

# ERD
[ERD for indexer](ERD.pdf)


