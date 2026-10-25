"""Dual-write LangGraph checkpoints for runtime inspection and learning."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver


CHECKPOINT_FILENAME = "langgraph-checkpoints.sqlite3"
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("app.v0.schemas", "ArtifactRef"),
        ("app.v0.schemas", "LoopCounts"),
        # BudgetedProvider runs provider calls through LangGraph `task()`,
        # whose results are checkpointed and replayed on resume.
        ("app.v0.provider", "AgentResponse"),
        ("app.v0.provider", "ToolTurn"),
    ],
)


def checkpoint_path(facts_path: Path) -> Path:
    return Path(facts_path).with_name(CHECKPOINT_FILENAME)


def thread_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def graph_config(run_id: str) -> dict:
    return {**thread_config(run_id), "recursion_limit": 100}


@contextmanager
def open_checkpointer(path: Path | str) -> Iterator[SqliteSaver]:
    connection = sqlite3.connect(
        str(path), timeout=30, check_same_thread=False,
    )
    try:
        saver = SqliteSaver(connection, serde=SERDE)
        saver.setup()
        yield saver
    finally:
        connection.close()


def latest_checkpoint(path: Path | str, run_id: str):
    with open_checkpointer(path) as saver:
        return saver.get_tuple(thread_config(run_id))
