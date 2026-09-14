"""Weave tracing when it is installed and configured; a no-op otherwise."""

import functools

try:
    import weave
except ImportError:  # the web image does not need weave
    weave = None

_enabled = False


def init(project: str) -> None:
    global _enabled
    if weave and project:
        weave.init(project)
        _enabled = True


def op(fn):
    """Trace `fn` as a Weave op when tracing is available (ops run untraced until init is called)."""
    if weave is None:
        return fn
    traced = weave.op(fn)

    @functools.wraps(fn)
    def call(*args, **kwargs):
        return traced(*args, **kwargs) if _enabled else fn(*args, **kwargs)

    return call
