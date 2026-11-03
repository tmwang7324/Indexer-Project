"""FastAPI app. Run with `python -m api` (binds to 127.0.0.1 only, D15)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from . import db
from .schema import schema


@asynccontextmanager
async def lifespan(app):
    yield
    db.close_pool()


app = FastAPI(title="Indexer API", lifespan=lifespan)
app.include_router(GraphQLRouter(schema), prefix="/graphql")


@app.get("/health")
def health():
    return {"status": "ok"}
