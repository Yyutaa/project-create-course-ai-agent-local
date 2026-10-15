"""Single-host SQLite Worker; API requests never execute the Graph."""

import argparse
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from app.v0.execution import Command, ExecutionStore, StopRequested
from app.v0.graph import (
    route_after_batch_plan, route_after_blueprint, route_after_generation,
    route_after_intake, route_after_mission, route_after_quality,
    route_after_repair, route_after_verification,
)
from app.v0.local_config import LocalConfigStore
from app.v0.provider import LocalConfiguredProvider
from app.v0.budget import BudgetedProvider, BudgetStore, TokenLimitReached
from app.v0.sensitive import safe_error
from app.v0.runner import V0Runner
from app.v0.schemas import GraphState
from app.v0.storage import FactStore

ROUTES = {
    "intake": route_after_intake,
    "mission": route_after_mission,
    "blueprint": route_after_blueprint,
    "batch_plan": route_after_batch_plan,
    "generation": route_after_generation,
    "quality": route_after_quality,
    "repair": route_after_repair,
    "verification": route_after_verification,
}


class Worker:
    def __init__(self, path: Path, provider=None, owner: str | None = None):
        self.execution = ExecutionStore(path)
        self.budgeted_provider = BudgetedProvider(
            provider if provider is not None
            else LocalConfiguredProvider(LocalConfigStore(path)),
            BudgetStore(path),
        )
        self.runner = V0Runner(self.budgeted_provider, FactStore(path))
        self.owner = owner or uuid4().hex

    def _resume_state(self, run_id: str) -> GraphState | None:
        checkpoint = self.execution.last_checkpoint(run_id)
        if checkpoint is None:
            return GraphState(run_id=run_id)
        state = GraphState.model_validate_json(checkpoint["state_json"])
        if checkpoint["position"] != "after_node":
            return state.model_copy(update={"last_outcome": "pending", "exit_reason": None})
        if state.last_outcome in ("waiting_for_human", "stopped"):
            return state.model_copy(update={"last_outcome": "pending", "exit_reason": None})
        route = ROUTES.get(state.current_node)
        if route is None:
            return None
        target = route(state)
        if target == "__end__":
            return None
        if target == "route_error":
            raise ValueError("Checkpoint 包含未知 Graph 路由")
        return state.model_copy(
            update={"current_node": target, "last_outcome": "pending", "exit_reason": None}
        )

    def _mark_stopped(self, run_id: str, epoch: int) -> None:
        run = self.runner.get(run_id)
        if run.status == "stopped":
            return
        if run.status in ("ready_for_release", "failed"):
            raise ValueError("STOP 不允许作用于已结束 Run")
        run.status = "stopped"
        active = next(
            (stage for stage in run.stages
             if stage.status in ("running", "waiting_for_human")), None
        )
        if active:
            active.status = "stopped"
            active.failure_reason = "人工 STOP 已受理"
        self.runner.store.record(
            run, "run.stopped", active.name if active else None,
            lease_owner=self.owner, lease_epoch=epoch,
        )

    def _mark_token_stopped(self, run_id: str, epoch: int, error: TokenLimitReached) -> None:
        with self.runner.store.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM events WHERE run_id=? "
                "AND type='budget.token_exhausted' LIMIT 1",
                (run_id,),
            ).fetchone()
        if exists:
            return
        run = self.runner.get(run_id)
        run.status = "stopped"
        stage_name = (
            "quality" if error.next_node in ("repair", "verification")
            else error.next_node
        )
        stage = next(item for item in run.stages if item.name == stage_name)
        stage.status = "stopped"
        stage.failure_reason = "token_limit_reached"
        self.runner.store.record(
            run,
            "budget.token_exhausted",
            stage_name,
            lease_owner=self.owner,
            lease_epoch=epoch,
        )

    def _heartbeat(self, command_id: str, run_id: str, epoch: int, done: Event) -> None:
        while not done.wait(15):
            try:
                self.execution.heartbeat(
                    run_id, self.owner, epoch, command_id=command_id
                )
            except PermissionError:
                return

    def _reconcile_after_artifact(self, run_id: str, epoch: int):
        run = self.runner.get(run_id)
        checkpoint = self.execution.last_checkpoint(run_id)
        if (
            run.status != "running"
            and checkpoint
            and checkpoint["position"] == "after_artifact"
        ):
            state = GraphState.model_validate_json(checkpoint["state_json"])
            outcome = {
                "failed": "failed", "stopped": "stopped",
                "ready_for_release": "succeeded",
            }.get(run.status, "waiting_for_human")
            self.execution.finish_node(
                checkpoint["node_execution_id"],
                state.model_copy(update={"last_outcome": outcome}),
                self.owner, epoch, failed=run.status == "failed",
            )
            checkpoint = self.execution.last_checkpoint(run_id)
        return run, checkpoint

    def _apply(self, command: Command, epoch: int) -> None:
        run_id = command.run_id
        self.budgeted_provider.bind(self.owner, epoch, command.id)
        if command.kind == "STOP":
            self._mark_stopped(run_id, epoch)
            return
        if command.kind == "REVISE":
            self.execution.record_revision(command, self.owner, epoch)
            return
        if command.kind == "MISSION_REVIEW":
            self.execution.apply_mission_review(command, self.owner, epoch)
            run = self.runner.get(run_id)
            if run.status == "waiting_for_human":
                # The same Command was already applied and a later node stopped.
                return
            if run.status != "running":
                raise ValueError("Mission 审批后的 Run 状态无效")
            state = self._resume_state(run_id)
            if state is None:
                return
            checkpoint = self.execution.last_checkpoint(run_id)
            recovery_effect = (
                self.execution.event(run_id, checkpoint["event_id"])
                if checkpoint and checkpoint["event_id"] else None
            )
            try:
                self.runner.execute(
                    run_id, state=state, execution=self.execution,
                    owner=self.owner, epoch=epoch,
                    recovery_effect=recovery_effect, command_id=command.id,
                )
            except StopRequested:
                self._mark_stopped(run_id, epoch)
            except TokenLimitReached as error:
                self._mark_token_stopped(run_id, epoch, error)
            if self.runner.get(run_id).status == "failed":
                raise RuntimeError("Graph 节点业务失败；不自动重试")
            return
        if command.kind == "QUALITY_REVIEW":
            decision = self.execution.apply_quality_review(command, self.owner, epoch)
            checkpoint = self.execution.last_checkpoint(run_id)
            if (
                decision.get("replayed")
                and checkpoint is not None
                and checkpoint["id"] != command.payload["expected_checkpoint_id"]
            ):
                run, _ = self._reconcile_after_artifact(run_id, epoch)
                if run.status == "failed":
                    raise RuntimeError("Graph 节点业务失败；不自动重试")
                if run.status != "running":
                    return
            state = self._resume_state(run_id)
            if state is None:
                return
            checkpoint = self.execution.last_checkpoint(run_id)
            recovery_effect = (
                self.execution.event(run_id, checkpoint["event_id"])
                if checkpoint and checkpoint["event_id"] else None
            )
            try:
                self.runner.execute(
                    run_id, state=state, execution=self.execution,
                    owner=self.owner, epoch=epoch,
                    recovery_effect=recovery_effect, command_id=command.id,
                )
            except StopRequested:
                self._mark_stopped(run_id, epoch)
            except TokenLimitReached as error:
                self._mark_token_stopped(run_id, epoch, error)
            if self.runner.get(run_id).status == "failed":
                raise RuntimeError("Graph 节点业务失败；不自动重试")
            return
        run = self.runner.get(run_id)
        if command.kind == "RESUME":
            if run.status not in ("stopped", "waiting_for_human"):
                raise ValueError("RESUME 仅允许从停止或等待人工状态继续")
            self.execution.prepare_resume(run_id, self.owner, epoch)
        elif run.status != "running":
            run, checkpoint = self._reconcile_after_artifact(run_id, epoch)
            if run.status in ("waiting_for_human", "stopped", "ready_for_release"):
                if checkpoint and checkpoint["position"] in ("after_node", "after_artifact"):
                    return
            if run.status == "failed":
                raise RuntimeError("Graph 节点业务失败；不自动重试")
            raise ValueError("START 不允许从业务失败或终态重试")
        state = self._resume_state(run_id)
        if state is None:
            return
        checkpoint = self.execution.last_checkpoint(run_id)
        recovery_effect = (
            self.execution.event(run_id, checkpoint["event_id"])
            if checkpoint and checkpoint["event_id"] else None
        )
        try:
            self.runner.execute(
                run_id, state=state if self.execution.last_checkpoint(run_id) else None,
                execution=self.execution, owner=self.owner, epoch=epoch,
                recovery_effect=recovery_effect,
                command_id=command.id,
            )
        except StopRequested:
            self._mark_stopped(run_id, epoch)
        except TokenLimitReached as error:
            self._mark_token_stopped(run_id, epoch, error)
        if self.runner.get(run_id).status == "failed":
            raise RuntimeError("Graph 节点业务失败；不自动重试")

    def run_once(self) -> bool:
        command = self.execution.claim(self.owner)
        if command is None:
            return False
        epoch = self.execution.acquire(command.run_id, self.owner)
        if epoch is None:
            self.execution.defer_claim(command.id, self.owner)
            return False
        done = Event()
        heartbeat = Thread(
            target=self._heartbeat,
            args=(command.id, command.run_id, epoch, done),
            daemon=True,
        )
        heartbeat.start()
        try:
            try:
                self._apply(command, epoch)
            except PermissionError:
                # A newer epoch owns the Run. Leave the claimed Command for
                # expiry/takeover; this Worker must not publish a result.
                return False
            except ValueError as error:
                self.execution.finish_command(
                    command.id, self.owner, epoch, "REJECTED", safe_error(error)
                )
            except Exception as error:
                self.execution.finish_command(
                    command.id, self.owner, epoch, "FAILED", safe_error(error)
                )
            else:
                self.execution.finish_command(command.id, self.owner, epoch, "APPLIED")
        finally:
            done.set()
            heartbeat.join(timeout=1)
        return True

    def serve(self, interval_seconds: float = 0.5) -> None:
        while True:
            if not self.run_once():
                Event().wait(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local AI Course Studio worker")
    parser.add_argument("--db", type=Path, default=(
        Path(__file__).resolve().parents[4] / ".course-agent" / "v0-facts.sqlite3"
    ))
    args = parser.parse_args()
    Worker(args.db).serve()


if __name__ == "__main__":
    main()
