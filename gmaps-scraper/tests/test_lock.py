import pytest

from gmaps.lock import LockBusyError, run_lock


def test_second_acquire_in_same_process_is_busy(tmp_path):
    lock_path = tmp_path / "run.lock"
    with run_lock(lock_path):
        with pytest.raises(LockBusyError):
            with run_lock(lock_path):
                pass


def test_lock_released_after_context_exits(tmp_path):
    lock_path = tmp_path / "run.lock"
    with run_lock(lock_path):
        pass
    # should be free again now
    with run_lock(lock_path):
        pass


def test_lock_creates_parent_dirs(tmp_path):
    lock_path = tmp_path / "nested" / "tmp" / "run.lock"
    with run_lock(lock_path):
        assert lock_path.exists()
