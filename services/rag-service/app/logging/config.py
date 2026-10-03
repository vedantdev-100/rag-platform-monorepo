"""
Structured JSON logging via structlog.

Why a dedicated `logging` module instead of living in `core/`: as RAG and
agent pipelines are added, logging concerns grow beyond "configure once at
startup" — request correlation middleware, per-component log adapters
(retriever logs, agent-step logs, eval-run logs) all belong here. Keeping
it as its own package means those additions don't keep bloating `core/`.

Note: this package is named `app.logging`, distinct from the stdlib
`logging` module. Because Python 3 uses absolute imports by default, the
`import logging` line below resolves to the stdlib module correctly as
long as the app is always run as a package (`uv run uvicorn app.main:app`,
never `cd app && python main.py`). Do not add `app/` itself to `sys.path`.
"""
import logging
import sys

import structlog


def configure_logging(debug: bool = False) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if debug else logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
