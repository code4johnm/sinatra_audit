"""Shared HUD layout: open panels, and the white method-redaction block."""

from __future__ import annotations

from datetime import datetime, timezone

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

FIG_FACE = "#070b14"
AX_FACE = "#0d1322"
INK = "#0b1220"
CYAN = "#00e5ff"
WHITE = "#ffffff"
GRID = "#1e293b"
MUTED = "#cbd5e1"

FIGSIZE = (18.8, 12.6)
ADJUST = dict(left=0.055, right=0.975, top=0.885, bottom=0.058, wspace=0.34, hspace=0.50)


def utc_stamp(when: datetime | str | None = None) -> str:
    """One readable UTC date for the method block."""
    if when is None:
        when = datetime.now(timezone.utc)
    if isinstance(when, str):
        text = " ".join(when.split())
        if text and "UTC" not in text.upper():
            text += " UTC"
        return text
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")


def group_hash(digest: str) -> str:
    raw = "".join(ch for ch in (digest or "").upper() if ch in "0123456789ABCDEF")
    if not raw:
        raw = "0" * 16
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def open_figure(title: str):
    """2x2 HUD with room for titles, legends, and callouts."""
    fig = plt.figure(figsize=FIGSIZE, facecolor=FIG_FACE)
    gs = gridspec.GridSpec(
        2,
        2,
        height_ratios=[1.0, 1.0],
        width_ratios=[1.15, 1.0],
        figure=fig,
    )
    fig.subplots_adjust(**ADJUST)
    fig.suptitle(
        title,
        fontsize=15,
        fontweight="bold",
        color=CYAN,
        y=0.965,
        linespacing=1.35,
    )
    return fig, gs


def add_panel(fig, spec, face: str = AX_FACE):
    ax = fig.add_subplot(spec, facecolor=face)
    ax.tick_params(labelsize=8.5, colors=MUTED, pad=4, length=3.5)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.xaxis.label.set_size(9.5)
    ax.yaxis.label.set_size(9.5)
    ax.xaxis.labelpad = 8
    ax.yaxis.labelpad = 8
    for spine in ax.spines.values():
        spine.set_color("#243044")
    return ax


def panel_title(ax, text: str, color: str = "#e5e7eb") -> None:
    ax.set_title(text, fontsize=11, fontweight="bold", color=color, pad=10, loc="left")


def park_legend(ax, loc: str = "upper left"):
    leg = ax.legend(
        loc=loc,
        fontsize=7.6,
        framealpha=0.94,
        borderpad=0.55,
        labelspacing=0.4,
        handlelength=1.7,
        borderaxespad=0.6,
    )
    if leg is not None:
        frame = leg.get_frame()
        frame.set_facecolor("#0b1220")
        frame.set_edgecolor("#334155")
        frame.set_linewidth(0.6)
    return leg


def method_redacted_block(ax, when, digest: str, *, x: float = 0.03, y: float = 0.96):
    """White futuristic METHOD REDACTED BLOCK. Date and hash sit inside it."""
    stamp = utc_stamp(when)
    grouped = group_hash(digest)
    date_line = f"DATE    {stamp}"
    hash_line = f"HASH    {grouped}"
    rule = "─" * max(len("METHOD REDACTED BLOCK"), len(date_line), len(hash_line))
    body = f"METHOD REDACTED BLOCK\n{rule}\n{date_line}\n{hash_line}"
    return ax.text(
        x,
        y,
        body,
        transform=ax.transAxes,
        fontsize=8.5,
        fontfamily="DejaVu Sans Mono",
        color=INK,
        ha="left",
        va="top",
        linespacing=1.65,
        zorder=9,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.9",
            facecolor=WHITE,
            edgecolor=CYAN,
            linewidth=1.8,
            alpha=1.0,
        ),
    )


def telemetry_card(ax, text: str, *, edge: str, x: float = 0.40, y: float = 0.96):
    """Dark readout parked in the open corner, not on the curve."""
    return ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=7.7,
        fontfamily="DejaVu Sans Mono",
        color="#f8fafc",
        ha="left",
        va="top",
        linespacing=1.45,
        zorder=8,
        bbox=dict(
            boxstyle="round,pad=0.7",
            facecolor="#05070c",
            edgecolor=edge,
            linewidth=1.3,
            alpha=0.94,
        ),
    )


def spread_callouts(ax, xs, ys, labels, *, xlim, ylim) -> None:
    """Park every callout in one open column so clustered markers stay readable."""
    xs = [float(v) for v in xs]
    ys = [float(v) for v in ys]
    labels = [_one_line(lb) for lb in labels]
    xspan = max(float(xlim[1] - xlim[0]), 1.0)
    yspan = max(float(ylim[1] - ylim[0]), 1.0)
    order = sorted(range(len(xs)), key=lambda i: (ys[i], xs[i]))
    n = len(order)
    label_x = xlim[0] + 0.70 * xspan
    y_lo = ylim[0] + 0.08 * yspan
    y_hi = ylim[1] - 0.10 * yspan
    for rank, i in enumerate(order):
        ty = y_lo if n == 1 else y_lo + (y_hi - y_lo) * (rank / (n - 1))
        ax.annotate(
            labels[i],
            xy=(xs[i], ys[i]),
            xytext=(label_x, ty),
            textcoords="data",
            fontsize=8.4,
            color="#f8fafc",
            fontweight="medium",
            ha="left",
            va="center",
            arrowprops=dict(
                arrowstyle="-",
                color="#64748b",
                lw=0.7,
                shrinkA=0,
                shrinkB=6,
            ),
            zorder=8,
            annotation_clip=False,
        )


def _one_line(raw: str) -> str:
    text = str(raw).strip()
    if "(" in text and text.endswith(")"):
        nid, name = text.split("(", 1)
        return f"{nid.strip()}  {name[:-1].strip()}"
    return text
