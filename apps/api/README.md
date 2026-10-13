# Verina API

FastAPI service. Python 3.12+ (developed on 3.14).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on macOS/Linux
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy
.venv/Scripts/python -m uvicorn verina.main:create_app --factory --reload
```

Configuration is read from environment variables prefixed `VERINA_` (see `.env.example`).
