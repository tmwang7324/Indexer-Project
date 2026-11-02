import os

import uvicorn

if __name__ == "__main__":
    # Localhost only (D15). Compose (ticket 13) publishes the port on the host's loopback.
    uvicorn.run("api.main:app", host=os.environ.get("INDEXER_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("INDEXER_API_PORT", "8000")), log_level="warning")
