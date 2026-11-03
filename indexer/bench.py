"""Old-vs-new benchmark (D9, D10, ticket 14).

One command prepares a set of consecutive blocks, runs each contender into its OWN scratch database one after
another, checks that they stored the same blocks, transactions and messages, and writes a report.

Contenders:
  old       the shell pipeline (`load_transactions.sh`) on old-format block files, schema `legacy`
  baseline  the single-threaded first version of the new indexer (commit 3d34de0, `tools/bench_single_threaded.py`)
  new       the multi-threaded pipeline of this tree

They never run at the same time: concurrent runs would compete for CPU, disk and the network and skew every
number. The command also refuses to start while another indexer session is active on the database server.
It is a tool, not a test (D25); the tool itself is tested with fakes.
"""
import base64
import contextlib
import copy
import gzip
import hashlib
import http.server
import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg2

from .config import DbSettings
from .pipeline import Pipeline
from .sources.replay import ReplayCache, ReplaySource
from .sources.rest import RestSource

log = logging.getLogger("indexer.bench")

REPO = Path(__file__).resolve().parents[1]
CHAIN = "phoenix-1"
DEFAULT_BASELINE_REF = "3d34de0"
DEFAULT_DIR = Path("bench")                      # git-ignored: prepared inputs and reports
CONTENDERS = ("old", "baseline", "new")
# The consensus-address prefix of each chain (the old file format carries it in sdk_block)
VALCONS_PREFIX = {"phoenix-1": "terravalcons", "migaloo-1": "migaloovalcons"}


EXIT_PARITY, EXIT_CANNOT_RUN = 1, 2              # exit codes of `bench`: 0 ran and matched


class BenchError(Exception):
    """The benchmark cannot run (bad arguments, an indexer already running, a contender failed)."""


def parse_heights(spec: str) -> range:
    try:
        first, last = (int(x) for x in spec.split(":"))
    except ValueError:
        raise BenchError(f"--heights must look like 23263983:23264982, not {spec!r}") from None
    if first > last:
        raise BenchError(f"--heights {spec}: the first height is above the last")
    return range(first, last + 1)


# --- the old file format (/cosmos/base/tendermint/v1beta1/blocks/{h}) ----------------------------------------
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values) -> int:
    generator = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= generator[i] if (top >> i) & 1 else 0
    return chk


def bech32_encode(hrp: str, data: bytes) -> str:
    """BIP-173 bech32 of raw bytes (a consensus address is bech32(prefix + 'valcons', 20 bytes))."""
    acc, bits, five = 0, 0, []
    for byte in data:
        acc, bits = (acc << 8) | byte, bits + 8
        while bits >= 5:
            bits -= 5
            five.append((acc >> bits) & 31)
    if bits:
        five.append((acc << (5 - bits)) & 31)
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    checksum = _bech32_polymod(expanded + five + [0] * 6) ^ 1
    five += [(checksum >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in five)


def old_format_from_cache(pages: list, chain_id: str) -> dict:
    """An old-format block file built from a replay cache entry. The tendermint block and its id are the node's own
    answer; `sdk_block` repeats the block with the proposer written as a consensus address, which is the only
    difference the old validator looks at. Used when there is no node to fetch the real file from."""
    doc = json.loads(pages[0])
    block = doc["block"]
    sdk_block = copy.deepcopy(block)
    proposer = base64.b64decode(block["header"]["proposer_address"])
    sdk_block["header"]["proposer_address"] = bech32_encode(VALCONS_PREFIX.get(chain_id, "terravalcons"), proposer)
    return {"block_id": doc["block_id"], "block": block, "sdk_block": sdk_block}


def decoded_by_tx_bytes(pages: list) -> dict:
    """{tx bytes (base64): the decode endpoint's answer} for one cached block. `block.data.txs[i]` and `txs[i]` are
    the same transaction, in the same order, as raw bytes and decoded."""
    doc = json.loads(pages[0])
    raw = doc["block"]["data"]["txs"] or []
    decoded = [tx for page in pages for tx in json.loads(page).get("txs", [])]
    if len(raw) != len(decoded):
        raise BenchError(f"block {doc['block']['header']['height']}: {len(raw)} transactions but {len(decoded)} decoded")
    return {r: {"tx": d} for r, d in zip(raw, decoded)}


class DecodeServer:
    """A local stand-in for `POST /cosmos/tx/v1beta1/decode`. The old pipeline asks it twice per transaction (once to
    load, once to verify), so its cost is a localhost HTTP call, not a public node's latency."""

    def __init__(self, answers: dict):
        self.answers, self.requests = answers, 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                owner.requests += 1
                answer = owner.answers.get(body.get("tx_bytes"))
                payload = json.dumps(answer if answer is not None else {"code": 3, "message": "unknown tx"}).encode()
                self.send_response(200 if answer is not None else 400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @classmethod
    def for_cache(cls, cache: ReplayCache, chain_id: str, heights) -> "DecodeServer":
        answers = {}
        for h in heights:
            pages, _ = cache.read(chain_id, h)
            answers.update(decoded_by_tx_bytes(pages))
        return cls(answers)


# --- preparing the inputs ---------------------------------------------------------------------------------------
@dataclass
class Inputs:
    root: Path
    chain_id: str = CHAIN

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def blocks(self) -> Path:
        return self.root / "blocks"


def prepare_from_cache(inputs: Inputs, source_cache: Path, heights: range) -> None:
    """Copy `heights` from an existing replay cache and derive the old-format files from it."""
    src, dst = ReplayCache(source_cache), ReplayCache(inputs.cache)
    inputs.blocks.mkdir(parents=True, exist_ok=True)
    for h in heights:
        pages, results = src.read(inputs.chain_id, h)
        dst.write(inputs.chain_id, h, pages, results)
        (inputs.blocks / str(h)).write_text(json.dumps(old_format_from_cache(pages, inputs.chain_id), indent=2))


def prepare_live(inputs: Inputs, heights: range, threads: int = 8) -> None:
    """Record the new indexer's responses into the replay cache and fetch the old-format file of every height."""
    source = RestSource(chain_id=inputs.chain_id, record=str(inputs.cache))
    inputs.blocks.mkdir(parents=True, exist_ok=True)

    def one(h: int) -> None:
        source.block(h)                                    # records the two responses
        (inputs.blocks / str(h)).write_bytes(source.fetch_old_format(h))

    with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="bench-prepare") as pool:
        for future in [pool.submit(one, h) for h in heights]:
            future.result()


# --- scratch databases --------------------------------------------------------------------------------------------
def _connect(settings: DbSettings, dbname: Optional[str] = None):
    return psycopg2.connect(host=settings.host, port=settings.port, dbname=dbname or settings.name,
                            user=settings.user, password=settings.password, connect_timeout=10)


def refuse_if_indexer_active(settings: DbSettings) -> None:
    """Contenders must not share the server with a running indexer: it would skew the numbers."""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = 'indexer' "
                        "AND pid <> pg_backend_pid()")
            active = cur.fetchone()[0]
    finally:
        conn.close()
    if active:
        raise BenchError(f"{active} indexer session(s) are active on {settings.host}:{settings.port}; stop the "
                         f"indexer first, the benchmark must have the database server to itself")


@contextlib.contextmanager
def scratch_database(settings: DbSettings, label: str, keep: bool = False):
    """CREATE DATABASE for one contender, DROP it afterwards. Yields DbSettings pointing at it."""
    name = f"bench_{label}_{os.getpid()}_{int(time.time())}"
    admin = _connect(settings)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{name}"')
    try:
        yield DbSettings(settings.host, settings.port, name, settings.user, settings.password)
    finally:
        if keep:
            log.info("kept database %s", name)
        else:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def _env(settings: DbSettings, **extra) -> dict:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("INDEXER_DB_") or k == "PGOPTIONS"]:
        del env[key]
    env.update(settings.as_env())
    env.update(extra)
    return env


def _migrate(settings: DbSettings, cwd: Path) -> None:
    env = _env(settings, PYTHONPATH=str(cwd))
    done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=cwd, env=env,
                          capture_output=True, text=True)
    if done.returncode:
        raise BenchError(f"alembic upgrade head failed in {cwd}:\n{done.stderr[-2000:]}")


# --- results ------------------------------------------------------------------------------------------------------
@dataclass
class Result:
    pipeline: str
    label: str
    seconds: float = 0.0
    blocks: int = 0
    transactions: int = 0
    messages: int = 0
    note: str = ""
    summary: dict = field(default_factory=dict)          # {height: (transactions, messages)} as the database holds it
    ok: bool = True

    @property
    def blocks_per_s(self) -> float:
        return self.blocks / self.seconds if self.seconds else 0.0

    @property
    def tx_per_s(self) -> float:
        return self.transactions / self.seconds if self.seconds else 0.0

    @property
    def msgs_per_s(self) -> float:
        return self.messages / self.seconds if self.seconds else 0.0


def summary_new(settings: DbSettings) -> dict:
    """{height: (transactions, messages)} from an `indexer`-schema database."""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT b.height, count(DISTINCT t.tx_id), count(m.message_id)
                           FROM indexer.blocks b LEFT JOIN indexer.transactions t ON t.block_id = b.block_id
                           LEFT JOIN indexer.messages m ON m.tx_id = t.tx_id GROUP BY b.height""")
            return {int(h): (int(t), int(m)) for h, t, m in cur.fetchall()}
    finally:
        conn.close()


def message_types_new(settings: DbSettings) -> dict:
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT b.height, m.type, count(*) FROM indexer.blocks b
                           JOIN indexer.transactions t ON t.block_id = b.block_id
                           JOIN indexer.messages m ON m.tx_id = t.tx_id GROUP BY 1, 2""")
            out = {}
            for h, type_, n in cur.fetchall():
                out.setdefault(int(h), {})[type_] = int(n)
            return out
    finally:
        conn.close()


def summary_old(settings: DbSettings, schema: str = "legacy") -> dict:
    """The same from the old pipeline's tables: one table per message type, each with a tx_id column."""
    conn = _connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT table_name FROM information_schema.columns
                           WHERE table_schema = %s AND column_name = 'tx_id' AND table_name <> 'transactions'""",
                        (schema,))
            tables = [r[0] for r in cur.fetchall()]
            cur.execute(f'SELECT height::bigint, tx_num FROM "{schema}".blocks')
            blocks = {int(h): int(n) for h, n in cur.fetchall()}
            cur.execute(f'SELECT height::bigint, count(*) FROM "{schema}".transactions GROUP BY 1')
            txs = {int(h): int(n) for h, n in cur.fetchall()}
            msgs = {}
            for table in tables:
                cur.execute(f'SELECT t.height::bigint, count(*) FROM "{schema}"."{table}" m '
                            f'JOIN "{schema}".transactions t ON t.tx_id = m.tx_id GROUP BY 1')
                for h, n in cur.fetchall():
                    msgs[int(h)] = msgs.get(int(h), 0) + int(n)
            return {h: (txs.get(h, 0), msgs.get(h, 0)) for h in blocks}
    finally:
        conn.close()


def supported_by_old() -> set:
    return set(json.loads((REPO / "type.json").read_text()))


# --- the contenders -----------------------------------------------------------------------------------------------
def run_old(inputs: Inputs, heights: range, settings: DbSettings, decode_urls: Optional[str]) -> Result:
    """`load_transactions.sh` on the old-format files, in schema `legacy` of its own scratch database."""
    schema = "legacy"
    with tempfile.TemporaryDirectory(prefix="bench-old-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        for path in REPO.glob("*.py"):
            (work / path.name).symlink_to(path)
        for name in ("Txs.sql", "type.json", "types_script", "load_transactions.sh"):
            (work / name).symlink_to(REPO / name)
        (work / "info.json").write_text(json.dumps({"psql": {
            "db_name": settings.name, "db_user": settings.user, "db_password": settings.password,
            "db_host": settings.host, "db_port": str(settings.port), "db_schema": schema}}))
        env = _env(settings, INDEXER_DB_SCHEMA=schema)
        if decode_urls:
            env["LEGACY_DECODE_URLS"] = decode_urls
        # Only the files of the requested heights, in height order (the script walks the folder in name order)
        wanted = Path(tmp) / "blocks"
        wanted.mkdir()
        for h in heights:
            (wanted / str(h)).symlink_to((inputs.blocks / str(h)).resolve())
        start = time.perf_counter()
        done = subprocess.run(["bash", "load_transactions.sh", "-t", "-b", str(wanted), "-o", str(Path(tmp) / "log")],
                              cwd=work, env=env, capture_output=True, text=True)
        seconds = time.perf_counter() - start
        if done.returncode:
            raise BenchError(f"the old pipeline exited {done.returncode}:\n{(done.stdout + done.stderr)[-2000:]}")
    summary = summary_old(settings, schema)
    return Result("old", "old pipeline (load_transactions.sh)", seconds, len(summary),
                  sum(t for t, _ in summary.values()), sum(m for _, m in summary.values()),
                  note="includes 2 decode requests per transaction", summary=summary)


def run_new(inputs: Inputs, heights: range, settings: DbSettings, workers: int, live: bool) -> Result:
    """The multi-threaded pipeline of this tree, in-process so the clock covers only the run."""
    _migrate(settings, REPO)
    source = (RestSource(heights.start, heights.stop - 1, chain_id=inputs.chain_id) if live
              else ReplaySource(str(inputs.cache), from_height=heights.start))
    pipeline = Pipeline(source, workers=workers, settings=settings)
    package_log = logging.getLogger("indexer")
    previous = package_log.level
    package_log.setLevel(logging.WARNING)          # a log line per block would be part of the time measured
    try:
        start = time.perf_counter()
        stats = pipeline.run()
        seconds = time.perf_counter() - start
    finally:
        package_log.setLevel(previous)
    if stats.failed:
        raise BenchError(f"the new pipeline put {stats.failed} block(s) in failed_blocks")
    summary = summary_new(settings)
    return Result("new", f"revamped pipeline ({workers} workers)", seconds, len(summary),
                  sum(t for t, _ in summary.values()), sum(m for _, m in summary.values()),
                  note="live fetch" if live else "replay cache", summary=summary)


def run_baseline(inputs: Inputs, heights: range, settings: DbSettings, ref: str, command: Optional[str],
                 live: bool) -> Result:
    """The single-threaded baseline. By default a `git worktree` of `ref`, migrated with that commit's own
    migrations; `command` replaces the tool's command line (the hermetic test uses the current tree's copy)."""
    worktree = None
    try:
        if command is None:
            worktree = Path(tempfile.mkdtemp(prefix="bench-baseline-"))
            added = subprocess.run(["git", "worktree", "add", "--detach", str(worktree), ref], cwd=REPO,
                                   capture_output=True, text=True)
            if added.returncode:
                raise BenchError(f"git worktree add {ref} failed (is the commit in this clone?):\n{added.stderr}")
            cwd = worktree
        else:
            cwd = REPO
        _migrate(settings, cwd)
        if command is None:
            tool = [sys.executable, "tools/bench_single_threaded.py"]
            args = (["--live", str(len(heights)), "--from-height", str(heights.start)] if live
                    else ["--replay", str(inputs.cache.resolve())]) + ["--reset"]
            argv = tool + args
        else:
            for key, value in {"cache": inputs.cache.resolve(), "start": heights.start, "count": len(heights),
                               "python": sys.executable}.items():           # not str.format: the command may hold JSON
                command = command.replace("{" + key + "}", str(value))
            argv = shlex.split(command)
        done = subprocess.run(argv, cwd=cwd, env=_env(settings, PYTHONPATH=str(cwd)), capture_output=True, text=True)
        if done.returncode:
            raise BenchError(f"the baseline exited {done.returncode}:\n{(done.stdout + done.stderr)[-2000:]}")
        line = [ln for ln in done.stdout.splitlines() if ln.startswith("{")][-1]
        data = json.loads(line)
        summary = summary_new(settings)
        return Result("baseline", f"single-threaded baseline ({ref if command is None else 'custom command'})",
                      data["seconds"], data["blocks"], data["transactions"], data["messages"],
                      note="live fetch" if live else "replay cache", summary=summary)
    finally:
        if worktree is not None:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=REPO, capture_output=True)
            shutil.rmtree(worktree, ignore_errors=True)


# --- parity -------------------------------------------------------------------------------------------------------
@dataclass
class Mismatch:
    height: int
    pipeline: str
    what: str
    expected: object
    actual: object

    def __str__(self) -> str:
        return f"{self.height}: {self.pipeline}: {self.what}: expected {self.expected}, found {self.actual}"


def check_parity(results: list, expected: dict, old_expected: Optional[dict] = None) -> list:
    """Every height where a contender's blocks, transactions or messages differ from the reference (`expected`
    = what the source says: {height: (transactions, messages)}). The old pipeline only knows some message types, so
    its message count is compared with `old_expected` (the source's messages of types it supports)."""
    problems = []
    for r in results:
        reference = old_expected if (r.pipeline == "old" and old_expected is not None) else expected
        for h in sorted(set(reference) | set(r.summary)):
            if h not in r.summary:
                problems.append(Mismatch(h, r.pipeline, "block", "stored", "missing"))
            elif h not in reference:
                problems.append(Mismatch(h, r.pipeline, "block", "absent", "stored"))
            else:
                want, have = reference[h], r.summary[h]
                if want[0] != have[0]:
                    problems.append(Mismatch(h, r.pipeline, "transactions", want[0], have[0]))
                if want[1] != have[1]:
                    problems.append(Mismatch(h, r.pipeline, "messages", want[1], have[1]))
    return problems


def source_expectation(inputs: Inputs, heights: range) -> tuple:
    """(what the source says, the same restricted to message types the old pipeline supports, unsupported count)."""
    from .parse import parse_txs_block
    cache = ReplayCache(inputs.cache)
    known = supported_by_old()
    full, restricted, unsupported = {}, {}, 0
    for h in heights:
        pages, results = cache.read(inputs.chain_id, h)
        block = parse_txs_block([json.loads(p) for p in pages], json.loads(results))
        msgs = [m for t in block.transactions for m in t.messages]
        full[h] = (block.tx_num, len(msgs))
        ok = [m for m in msgs if m.type in known]
        restricted[h] = (block.tx_num, len(ok))
        unsupported += len(msgs) - len(ok)
    return full, restricted, unsupported


# --- the report ---------------------------------------------------------------------------------------------------
def write_report(path: Path, heights: range, results: list, problems: list, unsupported: int, mode: str,
                 decode: str, workers: int) -> None:
    def row(r: Result) -> str:
        return (f"| {r.label} | {r.blocks} | {r.transactions} | {r.messages} | {r.seconds:.2f} | "
                f"{r.blocks_per_s:.1f} | {r.tx_per_s:.1f} | {r.msgs_per_s:.1f} | {r.note} |")

    lines = [
        f"# Benchmark report {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Heights {heights.start} to {heights.stop - 1} ({len(heights)} blocks). Mode: **{mode}**. "
        f"Workers for the revamped pipeline: {workers}.",
        f"Environment: Python {platform.python_version()}, {platform.system()} {platform.release()}, "
        f"{os.cpu_count()} CPUs; each contender ran alone, one after another, in its own scratch database.",
        "",
        "| Pipeline | Blocks | Tx | Messages | Seconds | Blocks/s | Tx/s | Msgs/s | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
        *(row(r) for r in results),
        "",
        "## How to read the figures",
        "- **The old pipeline's time includes two HTTP decode requests per transaction** (one to load, one to verify), "
        + ("answered by a local fake here, so no public-network latency is in the figure. "
           if decode == "local" else "sent to the public nodes, so network latency and their rate limits are in the figure. ")
        + "It also starts a new Python process for every block and every transaction; that cost belongs to the "
        "old design and is measured as it is.",
        "- The new indexer's figures come from "
        + ("a live fetch." if mode == "live" else "the replay cache (no network), so they are not like for like with a live old pipeline."),
        f"- Messages of types the old pipeline does not know ({unsupported} in this range) are not counted against it.",
        "",
        "## Parity",
    ]
    if problems:
        lines += [f"**{len(problems)} mismatch(es):**", "", *(f"- {p}" for p in problems)]
    else:
        lines += ["All contenders stored the same blocks, transactions and messages as the source, height by height."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


# --- the command --------------------------------------------------------------------------------------------------
def run_bench(args) -> int:
    heights = parse_heights(args.heights)
    inputs = Inputs(Path(args.dir))
    if args.prepare:
        if args.from_cache:
            prepare_from_cache(inputs, Path(args.from_cache), heights)
        else:
            prepare_live(inputs, heights)
        print(f"bench: prepared {len(heights)} blocks in {inputs.root}")
        return 0
    cache = ReplayCache(inputs.cache)
    missing = [h for h in heights if not cache.has(inputs.chain_id, h) or not (inputs.blocks / str(h)).exists()]
    if missing:
        raise BenchError(f"{len(missing)} height(s) are not prepared (first: {missing[0]}); run with --prepare first")
    chosen = [c.strip() for c in args.only.split(",")] if args.only else list(CONTENDERS)
    unknown = set(chosen) - set(CONTENDERS)
    if unknown:
        raise BenchError(f"--only: unknown contender(s) {sorted(unknown)}; choose from {list(CONTENDERS)}")
    settings = DbSettings.from_env()
    refuse_if_indexer_active(settings)
    expected, old_expected, unsupported = source_expectation(inputs, heights)

    results = []
    decode_cm = DecodeServer.for_cache(cache, inputs.chain_id, heights) if args.decode == "local" else contextlib.nullcontext()
    with decode_cm as decode:
        for name in chosen:                                  # strictly one after another
            print(f"bench: running {name} ...", flush=True)
            with scratch_database(settings, name, keep=args.keep_db) as db:
                if name == "old":
                    results.append(run_old(inputs, heights, db, decode.url if decode else None))
                elif name == "baseline":
                    results.append(run_baseline(inputs, heights, db, args.baseline_ref, args.baseline_cmd, args.live))
                else:
                    results.append(run_new(inputs, heights, db, args.workers, args.live))
            r = results[-1]
            print(f"bench: {name}: {r.blocks} blocks in {r.seconds:.2f}s = {r.blocks_per_s:.1f} blocks/s, "
                  f"{r.tx_per_s:.1f} tx/s", flush=True)
    problems = check_parity(results, expected, old_expected)
    report = Path(args.report_dir or inputs.root) / f"report-{datetime.now():%Y-%m-%d-%H%M%S}.md"
    write_report(report, heights, results, problems, unsupported, "live" if args.live else "offline (replay cache)",
                 args.decode, args.workers)
    print(f"bench: report written to {report}")
    for p in problems:
        print(f"bench: PARITY MISMATCH {p}")
    return EXIT_PARITY if problems else 0
