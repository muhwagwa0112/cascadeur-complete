"""Cascadeur user-command package for Cascadeur Complete."""

# Cascadeur imports this package on its UI thread while registering commands,
# which is the earliest point the queue pump can start. Command and event entry
# points call ensure_installed() again, so a failure here is never fatal.
try:
    from . import pump as _pump

    _pump.ensure_installed()
except Exception as _exc:  # pragma: no cover - depends on the host process
    print("[cascadeur-complete-pump] startup install skipped:", _exc)
