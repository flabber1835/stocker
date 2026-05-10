import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.factors import compute_all_factors
from app.regime import detect_regime, resolve_confirmed_regime
from stock_strategy_shared.schemas.strategy import StrategyConfig

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""


def _load_strategy(path: str) -> StrategyConfig:
    import yaml
    with open(path) as f:
        raw = f.read()
    global config_hash
    config_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return StrategyConfig(**yaml.safe_load(raw))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine
    strategy = _load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    yield
    await engine.dispose()


app = FastAPI(title="factor-engine", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "factor-engine",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }
