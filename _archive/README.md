# Archived Services

These three services were consolidated into `services/pipeline` in Phase 7.
Their math modules were copied verbatim into `services/pipeline/app/`:

| Archived service | Now lives in |
|---|---|
| `factor-engine/` | `services/pipeline/app/factors.py` |
| `ranker/`        | `services/pipeline/app/rank.py`, `regime.py` |
| `delta-engine/`  | `services/pipeline/app/engine.py` |

`docker-compose.yml` no longer launches these services.
The original directories are kept here for reference only.
