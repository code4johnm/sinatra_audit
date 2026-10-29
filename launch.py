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

if len(sys.argv) != 2:
    sys.stderr.write("usage: launch.py /opt/sinatra/<script>.py\n")
    sys.exit(2)

script = sys.argv[1]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
