"""Exponential-backoff retry decorator for transient failures.

Used on IMAP, Drive, and SMTP calls that fail intermittently due to
network blips or rate limits. The default policy retries 3 times with
0.5s/1.5s/4.5s waits and gives up — total worst case ~7 seconds.

A non-decorator form is provided too for inline use where the wrapped
callable isn't fixed (e.g. lambdas around stdlib calls).

By default, RETRY only on transient-looking exceptions:

  - socket.timeout, TimeoutError, ConnectionError, OSError
  - imaplib.IMAP4.abort, imaplib.IMAP4.error (with retryable messages)
  - googleapiclient.errors.HttpError with 429 / 5xx status
  - smtplib.SMTPServerDisconnected, SMTPConnectError, SMTPHelloError,
    SMTPSenderRefused, SMTPRecipientsRefused (transient cases only),
    SMTPDataError (transient cases only)

Anything else (programming bugs, permanent auth failures, etc.) is
NOT retried — those should surface fast.
"""
from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable

logger = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    """Conservative classifier — return True only when we're confident
    the exception is transient. Unknown errors are NOT retried."""
    import socket
    import imaplib
    import smtplib

    # Network-level: always transient
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        # Specific Windows transient codes
        if any(t in msg for t in ("timeout", "reset", "refused",
                                  "unreachable", "winerror 1450",
                                  "temporarily unavailable")):
            return True
        return False

    # IMAP: abort is always transient (server dropped us). error is
    # mixed — only retry if the message looks transient.
    if isinstance(exc, imaplib.IMAP4.abort):
        return True
    if isinstance(exc, imaplib.IMAP4.error):
        msg = str(exc).lower()
        return any(t in msg for t in ("timeout", "connection",
                                      "try again", "temporary"))

    # SMTP: a handful are clearly transient
    if isinstance(exc, (smtplib.SMTPServerDisconnected,
                        smtplib.SMTPConnectError,
                        smtplib.SMTPHeloError)):
        return True
    if isinstance(exc, (smtplib.SMTPDataError,
                        smtplib.SMTPSenderRefused,
                        smtplib.SMTPRecipientsRefused)):
        # 4xx codes are temporary; 5xx are permanent
        code = getattr(exc, "smtp_code", None)
        return isinstance(code, int) and 400 <= code < 500

    # Google API: 429 / 5xx
    try:
        from googleapiclient.errors import HttpError  # type: ignore
    except Exception:
        HttpError = None  # type: ignore
    if HttpError and isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        try:
            return int(status) in {429, 500, 502, 503, 504}
        except (TypeError, ValueError):
            return False

    return False


def retry(
    attempts: int = 3,
    base_delay: float = 0.5,
    backoff: float = 3.0,
    jitter: float = 0.2,
    *,
    is_transient: Callable[[BaseException], bool] | None = None,
    on_retry: Callable[[BaseException, int], None] | None = None,
):
    """Decorator factory. Wraps a function; retries up to `attempts`
    times on transient exceptions with exponentially growing delay
    (base_delay * backoff**i) plus +/- jitter."""
    classifier = is_transient or _is_transient

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return run_with_retry(
                lambda: fn(*args, **kwargs),
                attempts=attempts, base_delay=base_delay, backoff=backoff,
                jitter=jitter, is_transient=classifier, on_retry=on_retry,
                op_name=fn.__qualname__,
            )
        return wrapper
    return deco


def run_with_retry(
    callable_: Callable[[], object],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    backoff: float = 3.0,
    jitter: float = 0.2,
    is_transient: Callable[[BaseException], bool] | None = None,
    on_retry: Callable[[BaseException, int], None] | None = None,
    op_name: str = "operation",
):
    """Same logic as the decorator but invocable on any zero-arg
    callable, including a lambda around a stdlib function."""
    classifier = is_transient or _is_transient
    last_exc: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return callable_()
        except Exception as e:
            last_exc = e
            if i == attempts - 1 or not classifier(e):
                raise
            delay = base_delay * (backoff ** i)
            if jitter:
                delay *= (1 + random.uniform(-jitter, jitter))
            logger.info(
                "retry: %s attempt %d/%d failed (%s); waiting %.1fs",
                op_name, i + 1, attempts, type(e).__name__, delay)
            if on_retry:
                try:
                    on_retry(e, i + 1)
                except Exception:
                    pass
            time.sleep(delay)
    # Defensive — loop above always returns or raises
    if last_exc:
        raise last_exc
    return None
