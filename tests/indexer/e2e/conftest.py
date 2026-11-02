"""End-to-end harness: a separate indexer process fills the database, a separate API process serves it."""
import json
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from indexer_support import db as dbtools

REPO = dbtools.REPO

# One indexing run per module (Rule 6). Each entry is the arguments of `python -m indexer`.
INDEX_RUNS = [
    ["run", "--source", "files:test_blocks"],
]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class GraphQLClient:
    def __init__(self, url):
        self.url = url

    def query(self, text: str) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps({"query": text}).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


@pytest.fixture(scope="module")
def graphql(migrated_db):
    dbtools.truncate_all(migrated_db)
    env = dbtools.child_env(migrated_db)
    for args in INDEX_RUNS:
        done = subprocess.run([sys.executable, "-m", "indexer", *args], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, f"indexer {args} failed:\n{done.stderr}"
    port = _free_port()
    api = subprocess.Popen([sys.executable, "-m", "api"], cwd=REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True,
                           env={**env, "INDEXER_API_PORT": str(port)})
    try:
        deadline = time.time() + 30
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
                break
            except OSError:
                if api.poll() is not None or time.time() > deadline:
                    raise RuntimeError("API did not start:\n" + (api.stdout.read() if api.stdout else ""))
                time.sleep(0.2)
        yield GraphQLClient(f"http://127.0.0.1:{port}/graphql")
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
        dbtools.truncate_all(migrated_db)
