# First Claude Code Task

Paste this into Claude Code after creating the repo with this documentation.

```text
Read CLAUDE.md and the docs folder.

Create the initial repo skeleton for Phase 1 and the beginning of Phase 2.

Build:

- docker-compose.yml
- .env.example
- Makefile
- README.md
- shared Python package for strategy schemas
- services/api with FastAPI health endpoint
- services/strategy-validator with FastAPI health endpoint and /validate endpoint
- sample strategy config under strategies/quality_ai_overlay_v1.yaml
- pytest tests for the strategy validator
- postgres and redis services in compose

Use Python 3.12, FastAPI, Pydantic, pytest.

Do not implement real Alpha Vantage or Alpaca calls yet.

Keep services minimal and clear.

Make `docker compose up` work.

Make `make test` run tests.
```
