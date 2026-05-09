import os
from fastapi import FastAPI

SERVICE_NAME = os.getenv("SERVICE_NAME", "stub")

app = FastAPI(title=SERVICE_NAME)


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "note": "stub — not yet implemented"}
