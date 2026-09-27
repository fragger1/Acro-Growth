import contextlib
import os
from pathlib import Path

from gmaps.config import ROOT

DEFAULT_LOCK_PATH = ROOT / "tmp" / "run.lock"


class LockBusyError(Exception):
    """Raised when another process already holds the run lock."""


def _lock(fd) -> None:
    if os.name == "nt":
        import msvcrt

        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def run_lock(path: Path | None = None):
    """Non-blocking single-instance lock. Raises LockBusyError if already held
    (by this or another process). Held for the duration of the `with` block."""
    lock_path = path or DEFAULT_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "a+b")
    try:
        try:
            _lock(fd)
        except OSError as exc:
            raise LockBusyError(f"lock at {lock_path} is held by another process") from exc
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        fd.close()
