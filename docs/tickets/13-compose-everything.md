# 13 · Compose for everything

**Slice:** `docker compose up` starts the whole project. PostgreSQL first, then a one-off migrate step (`alembic upgrade head`), then the indexer following Terra and the API on localhost. The old pipeline runs as a one-off container that already has `psql` and `jq`.

**Acceptance test (E2E):** `E2`: in CI, bring up the stack with the indexer pointed at the committed replay sample (no network, D25). Wait until the checkpoint reaches the sample's last height, then query `block(chainId: "phoenix-1", height: <last>)` through the published port and compare with the expected-JSON file. Then stop the indexer, run the legacy one-off container on the Migaloo fixtures and check its row counts (the old pipeline is a baseline and never runs alongside the indexer). Tear the stack down.

**Depends on:** 10, 11, 12 · **Decisions:** D13, D15

## Scope
- **In:**
  - `docker-compose.yml` with `postgres` (named volume), `migrate`, `indexer`, `api` (published on 127.0.0.1 only), `legacy` (one-off profile: never started by `up`, run by hand while the indexer is stopped) and the existing `postgres-test`;
  - Dockerfiles for the Python service and the legacy image;
  - health checks and start ordering;
  - the replay cache as a mounted folder;
  - replacing the README's `docker run` section with the Compose instructions.
- **Out:** production deployment (D1).

## Spec
- **Configuration:** environment variables only. The service host is `postgres` inside Compose, `localhost` from the host.
- **Start ordering:** `indexer` and `api` wait for `migrate` to complete successfully (`depends_on: condition: service_completed_successfully`).

## Acceptance criteria
- [ ] From a clean checkout, `docker compose up` reaches a queryable API with no host dependencies except Docker.
- [ ] The CI stack test passes without network access to public nodes.
- [ ] The README describes start, stop, reset and running the legacy loader with Compose, and says to stop the indexer first.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E2 | e2e | Compose stack: index the replay sample, query the API, run the legacy loader |
