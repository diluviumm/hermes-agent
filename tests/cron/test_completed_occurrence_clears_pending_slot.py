"""Regression: the completed-occurrence dedupe branch must clear ``pending_slot``.

2026-10-02 live incident (this machine): job ``hindsight-backup`` accumulated 167
failed executions over ~3h (60/hour), every row carrying the SAME
``scheduled_instant`` and the error ``Fire claim lost; execution was not
started.``, while the model provider was returning 404 — i.e. the storm was
re-triggered by the scheduler, not by the provider.

Mechanism (the loop this test pins):

1. A tick stamps ``pending_slot`` for the due occurrence just before dispatch.
2. The run completes; the executions ledger records that occurrence as completed.
3. The stamp is normally dropped by ``claim_job_for_fire``'s success path — but
   when the claim is refused by the completed-occurrence dedupe gate it returned
   early WITHOUT clearing the stamp.
4. The next scan's ``_restore_unclaimed_slot`` sees the surviving stamp, restores
   the already-completed instant as ``next_run_at``, the tick dispatches again,
   the dedupe refuses again — forever. Each lap writes another ``failed``
   execution row, so the job looks permanently broken and `hermes cron doctor`
   keeps flagging it.

The fix clears the stamp in the dedupe branch, which is correct on its own terms:
the instant is already accounted for in the ledger, so no pending_slot may
outlive it. Restoring it can only ever produce a claim that this same gate
refuses.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with a recurring no_agent interval job."""
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "cron" / "output").mkdir(parents=True)
    (hermes_home / "scripts").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    import cron.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "HERMES_DIR", hermes_home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", hermes_home / "cron")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", hermes_home / "cron" / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", hermes_home / "cron" / "output")

    from cron import executions as executions_mod

    monkeypatch.setattr(executions_mod, "EXECUTIONS_FILE", hermes_home / "cron" / "executions.db")

    job = jobs_mod.create_job(
        prompt="probe", schedule="every 5m", no_agent=True, script="probe.py",
    )
    (hermes_home / "scripts" / "probe.py").write_text("print('ok')\n")
    return {"home": hermes_home, "job_id": job["id"]}


def _plant_orphan_stamp(jobs_mod, job_id: str, instant: str) -> None:
    """Write ``pending_slot`` for *instant* straight into jobs.json.

    ``update_job`` normalizes the record and would drop the stamp, so the
    incident's exact on-disk state is authored here directly.
    """
    raw = json.loads(jobs_mod.JOBS_FILE.read_text())
    for record in raw["jobs"]:
        if record["id"] == job_id:
            record["next_run_at"] = instant
            record["pending_slot"] = {
                "scheduled_at": instant,
                "by": jobs_mod._machine_id(),
                "at": datetime.now(timezone.utc).isoformat(),
            }
    jobs_mod.JOBS_FILE.write_text(json.dumps(raw, indent=2))


def test_completed_occurrence_dedupe_clears_pending_slot(cron_env, monkeypatch):
    """GREEN: a claim refused by the completed-occurrence gate drops the stamp.

    RED on unfixed code: the stamp survives, which is the first lap of the
    re-fire storm.
    """
    import cron.jobs as jobs_mod
    from cron import executions as executions_mod
    from cron.occurrences import completed_occurrence

    job_id = cron_env["job_id"]
    instant = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).replace(microsecond=0).isoformat()

    # The occurrence is already accounted for in the executions ledger.
    execution = executions_mod.create_execution(job_id, source="builtin")
    executions_mod.set_execution_occurrence(execution["id"], instant)
    executions_mod.finish_execution(execution["id"], success=True)
    assert completed_occurrence(jobs_mod.get_job(job_id), instant) is True

    # ...but the tick's pending_slot stamp for it is still on the record.
    _plant_orphan_stamp(jobs_mod, job_id, instant)
    assert jobs_mod.get_job(job_id).get("pending_slot"), "precondition: stamp planted"

    claimed = jobs_mod.claim_job_for_fire(job_id)

    assert claimed is False, "a completed occurrence must not be claimable"
    assert jobs_mod.get_job(job_id).get("pending_slot") is None, (
        "the dedupe branch must clear pending_slot — leaving it set makes "
        "_restore_unclaimed_slot restore this completed instant on every tick, "
        "re-firing the job (and writing a failed execution row) forever"
    )


def test_repeated_ticks_do_not_storm(cron_env, monkeypatch):
    """GREEN: after the dedupe clears the stamp, further ticks add no executions.

    This is the end-to-end shape of the incident: the job stops re-firing and
    the ledger stops growing.
    """
    import cron.jobs as jobs_mod
    from cron import executions as executions_mod
    from cron import scheduler as scheduler_mod

    monkeypatch.setattr(
        scheduler_mod, "_hermes_home", cron_env["home"],
    )
    job_id = cron_env["job_id"]
    instant = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).replace(microsecond=0).isoformat()

    execution = executions_mod.create_execution(job_id, source="builtin")
    executions_mod.set_execution_occurrence(execution["id"], instant)
    executions_mod.finish_execution(execution["id"], success=True)
    _plant_orphan_stamp(jobs_mod, job_id, instant)

    before = len(executions_mod.list_executions())
    for _ in range(3):
        scheduler_mod.tick(verbose=False, sync=True)
    after = len(executions_mod.list_executions())

    assert after == before, (
        f"tick added {after - before} execution(s) for an already-completed "
        "occurrence — this is the re-fire storm (167 rows / 3h live)"
    )
