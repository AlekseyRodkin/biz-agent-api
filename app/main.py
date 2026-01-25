from fastapi import FastAPI
from datetime import datetime

app = FastAPI(
    title="Biz Agent API",
    description="Business Agent API backend service",
    version="0.2.0"
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.2.0"
    }


@app.get("/")
async def root():
    return {"message": "Biz Agent API is running"}
