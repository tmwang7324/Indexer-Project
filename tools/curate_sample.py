#!/usr/bin/env python3
"""One-off: pick a small, varied set of blocks from a local replay cache (D24).

    python tools/curate_sample.py --cache <replay cache> --out tests/indexer/data/terra [--count 50]

The pick is deterministic. It covers: empty blocks, failed transactions, multi-message
transactions, multi-coin fees, a short run of consecutive heights, every handled message type that occurs, and message types
without a handler. Smaller blocks win ties, so the sample stays around 1 MB. It writes the blocks
in replay-cache format plus manifest.json, which says why each block is there.
"""
import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.errors import BadDataError  # noqa: E402
from indexer.handlers import get_registry  # noqa: E402
from indexer.sources.replay import ReplayCache  # noqa: E402


def describe(block):
    registry = get_registry()
    types = {m.type for tx in block.transactions for m in tx.messages}
    return {
        "tx_num": block.tx_num,
        "types": sorted(types),
        "unhandled": sorted(t for t in types if registry.get(t) is None),
        "failed": [tx.hash for tx in block.transactions if tx.outcome and tx.outcome.code != 0],
        "multi_message": any(len(tx.messages) > 1 for tx in block.transactions),
        "multi_coin_fee": any(len(tx.fee) > 1 for tx in block.transactions),
    }


def file_size(cache, chain_id, height):
    return sum(p.stat().st_size for p in (cache.root / chain_id).glob(f"{height}.*.gz"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chain", default="phoenix-1")
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--run", type=int, default=6, help="length of the consecutive run of heights")
    args = ap.parse_args()

    cache = ReplayCache(args.cache)
    info, skipped = {}, 0
    for height in cache.heights(args.chain):
        try:
            info[height] = describe(cache.block(args.chain, height))
        except BadDataError:
            skipped += 1      # e.g. a block whose extra txs pages were not cached
    print(f"{len(info)} blocks scanned, {skipped} unusable", file=sys.stderr)
    size = {h: file_size(cache, args.chain, h) for h in info}

    picked: dict[int, list] = defaultdict(list)

    def pick(reason, candidates, limit=1):
        n = 0
        for h in sorted(candidates, key=lambda h: (size[h], h)):
            if n >= limit:
                break
            if h not in picked or reason not in picked[h]:
                picked[h].append(reason)
                n += 1

    # a short run of consecutive heights with transactions: the fake node serves ranges, so tests need one
    run = args.run
    windows = [h for h in info if all(h + i in info for i in range(run))]
    if windows:
        best = max(windows, key=lambda h: (sum(info[h + i]["tx_num"] > 0 for i in range(run)),
                                           -sum(size[h + i] for i in range(run)), -h))
        for i in range(run):
            picked[best + i].append("consecutive run")

    empty = [h for h, d in info.items() if d["tx_num"] == 0]
    pick("empty block", empty[::max(1, len(empty) // 3)], 3)
    pick("failed transaction", [h for h, d in info.items() if d["failed"]], 4)
    pick("multi-coin fee", [h for h, d in info.items() if d["multi_coin_fee"]], 2)
    pick("multi-message transaction", [h for h, d in info.items() if d["multi_message"]], 4)
    pick("message type without a handler", [h for h, d in info.items() if d["unhandled"]], 2)

    seen = set(t for h in picked for t in info[h]["types"])
    all_types = {t for d in info.values() for t in d["types"]}
    for t in sorted(all_types - seen):
        pick(f"first block with {t}", [h for h, d in info.items() if t in d["types"]], 1)

    # fill up with the smallest blocks that have transactions, spread over the heights
    rest = sorted(h for h, d in info.items() if d["tx_num"] > 0 and h not in picked)
    step = max(1, len(rest) // max(1, args.count - len(picked)))
    for h in rest[::step]:
        if len(picked) >= args.count:
            break
        picked[h].append("filler")

    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    for h in sorted(picked):
        for f in (cache.root / args.chain).glob(f"{h}.*.gz"):
            (out / args.chain).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, out / args.chain / f.name)
    manifest = {str(h): {"why": picked[h], **info[h]} for h in sorted(picked)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    total = sum(size[h] for h in picked)
    print(f"picked {len(picked)} blocks, {total / 1e6:.2f} MB gzipped", file=sys.stderr)


if __name__ == "__main__":
    main()
