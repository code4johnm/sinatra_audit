#!/usr/bin/env python3
"""Headless runner for the SINTRA scripts. Agg backend, no display, show() does not block."""

import os
import runpy
import sys

os.environ["MPLBACKEND"] = "Agg"
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt

_orig_figure = plt.figure


def _figure(*args, **kwargs):
    fig = _orig_figure(*args, **kwargs)
    if getattr(fig.canvas, "manager", None) is None:

        class _Manager:
            def set_window_title(self, _title):
                return None

        fig.canvas.manager = _Manager()
    return fig


plt.figure = _figure
plt.show = lambda *_args, **_kwargs: None


def _require_writable_output():
    """The sandbox uid cannot create the HUD PNG unless the workdir is writable."""
    out_dir = os.path.abspath(os.environ.get("SINTRA_OUTPUT", os.getcwd()))
    if not os.path.isdir(out_dir) or not os.access(out_dir, os.W_OK | os.X_OK):
        sys.stderr.write(
            f"output directory is not writable by uid {os.getuid()}: {out_dir}\n"
            "NTFS/fuseblk bind mounts ignore chmod, so uid 10001 cannot be granted write.\n"
            "Run as the directory owner, or use ./run-live.sh (it selects a uid that can write).\n"
        )
        sys.exit(13)
    os.environ["SINTRA_OUTPUT"] = out_dir


_require_writable_output()

if len(sys.argv) != 2:
    sys.stderr.write("usage: launch.py /opt/sinatra/<script>.py\n")
    sys.exit(2)

script = sys.argv[1]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
