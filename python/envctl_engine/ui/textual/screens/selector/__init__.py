"""Selector screen package."""

import sys as _sys
from . import implementation as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith('__')})
_sys.modules[__name__] = _impl
