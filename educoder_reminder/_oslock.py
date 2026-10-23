"""Cross-platform non-blocking exclusive file lock.

POSIX uses fcntl.flock; Windows (no fcntl) uses msvcrt.locking on one byte.
Keeps the lock semantics identical so the caller only sees LockError when held.
"""
import os

try:
    import fcntl
    HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    HAVE_FCNTL = False


class LockError(RuntimeError):
    """Raised when the lock is already held by another process."""


def lock_nonblocking(handle):
    """Acquire an exclusive non-blocking lock; raise LockError if held."""
    if HAVE_FCNTL:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockError('lock held') from None
        return
    # Windows: lock a single byte, ensuring the file has at least one byte first.
    import msvcrt
    handle.seek(0)
    if not handle.read(1):
        handle.seek(0, os.SEEK_END)
        handle.write(b'\0')
        handle.flush()
        handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise LockError('lock held') from None


def unlock(handle):
    """Release a lock previously acquired by lock_nonblocking."""
    if HAVE_FCNTL:
        fcntl.flock(handle, fcntl.LOCK_UN)
        return
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
