import six


if six.PY3:
    import contextlib
    from collections.abc import Callable
else:
    import contextlib2 as contextlib
    from collections import Callable


def qualname_func(func):
    if six.PY3:
        return func.__qualname__
    return "%s.%s" % (func.__module__, func.__name__)


try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

try:
    import_errors = (ImportError, ModuleNotFoundError)
except Exception:
    # we are python2
    import_errors = (ImportError,)

__all__ = ["contextlib", "qualname_func", "import_errors", "Callable"]
