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
python -m indexer run --source rest --from-height N [--to-height M] [--record DIR] [--prefetch N]   # live Terra nodes
python -m api                                                    # GraphQL at http://127.0.0.1:8000/graphql
```
`--prefetch N` (default 4) fetches up to N blocks at once; they are still written one at a time, in height order.
`--record DIR` saves the raw responses of every fetched block (gzipped) into a replay cache, so later runs
(`--source replay:DIR`) need no network. Public endpoints and their rate limits are in
`indexer/sources/endpoints.py`; override them with `INDEXER_ENDPOINTS` (a JSON list) and
`INDEXER_ENDPOINT_COOLDOWN` (seconds a failing endpoint is skipped).

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
`indexer`). A missing database **fails** the database-backed tests; it never skips them. Until the legacy pipeline
moves to its own schema (ticket 12), run the legacy tests against a separate database
(`INDEXER_TEST_DB_NAME=legacy_test pytest -m legacy`): its scripts create unqualified tables, which would otherwise
land in the `indexer` schema when the database user is called `indexer`.

The curated Terra sample under `tests/indexer/data/terra/` (about 50 real `phoenix-1` blocks) was picked with
`tools/curate_sample.py` from a local replay cache.

# ERD
[ERD for indexer](ERD.pdf)


