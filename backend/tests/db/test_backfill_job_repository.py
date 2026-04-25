"""BackfillJobRepository — create / state / progress / cancel tests."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.repositories.backfill_job_repository import BackfillJobRepository


def test_create_new_job_is_pending(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(
        from_date=date(2024, 1, 2),
        to_date=date(2024, 1, 10),
        force=False,
        user_id=1,
    )
    db_session.commit()

    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.state == "pending"
    assert fetched.force is False
    assert fetched.processed_days == 0
    assert fetched.total_days == 0
    assert fetched.skipped_existing_days == 0
    assert fetched.failed_days == 0
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.cancel_requested is False
    assert fetched.created_by_user_id == 1


def test_get_active_returns_pending_job(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    db_session.commit()

    active = repo.get_active()
    assert active is not None
    assert active.state == "pending"


def test_get_active_returns_running_job(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    repo.update_state(job.id, "running")
    db_session.commit()

    active = repo.get_active()
    assert active is not None
    assert active.state == "running"
    assert active.started_at is not None


def test_get_active_ignores_terminal_states(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    repo.update_state(job.id, "completed")
    db_session.commit()

    assert repo.get_active() is None


def test_update_state_to_terminal_stamps_finished_at(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    repo.update_state(job.id, "running")
    repo.update_state(job.id, "completed")
    db_session.commit()

    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.state == "completed"
    assert fetched.finished_at is not None


def test_update_state_truncates_long_error(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    huge = "x" * 5000
    repo.update_state(job.id, "failed", error=huge)
    db_session.commit()

    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.error is not None
    assert len(fetched.error) == 1000


def test_increment_progress_is_additive(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    repo.increment_progress(job.id, processed=3)
    repo.increment_progress(job.id, processed=2, skipped=1)
    repo.increment_progress(job.id, failed=1)
    db_session.commit()

    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.processed_days == 5
    assert fetched.skipped_existing_days == 1
    assert fetched.failed_days == 1


def test_increment_progress_rejects_negative_delta(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    with pytest.raises(ValueError):
        repo.increment_progress(job.id, processed=-1)


def test_request_cancel_sets_flag(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    job = repo.create(from_date=date(2024, 1, 1), to_date=date(2024, 1, 5), force=False, user_id=1)
    assert repo.is_cancel_requested(job.id) is False
    repo.request_cancel(job.id)
    db_session.commit()
    assert repo.is_cancel_requested(job.id) is True


def test_update_state_unknown_job_raises(db_session: Session) -> None:
    repo = BackfillJobRepository(db_session)
    with pytest.raises(LookupError):
        repo.update_state(999, "running")
