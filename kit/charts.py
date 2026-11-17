"""Tiny SVG chart writer (no matplotlib needed). Log scales, because results span 1000x or more."""
import math
from html import escape

FAMILY_COLORS = {"C": "#2563eb", "Python": "#d97706", "Python + my C": "#059669", "Python + C library": "#7c3aed"}


def fmt_ns(ns):
    if ns < 1:
        return f"{ns:.2g} ns"
    if ns < 1_000:
        return f"{ns:.3g} ns"
    if ns < 1_000_000:
        return f"{ns / 1e3:.3g} µs"
    if ns < 1_000_000_000:
        return f"{ns / 1e6:.3g} ms"
    return f"{ns / 1e9:.3g} s"


def _log_ticks(lo, hi):
    a, b = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    return [10 ** e for e in range(a, b + 1)]


def bar_chart(path, title, items, xlabel):
    """items: [(label, value_ns, family[, extra text])], drawn as horizontal bars on a log axis."""
    items = [tuple(i) + ("",) * (4 - len(i)) for i in items if i[1] and i[1] > 0]
    if not items:
        return
    left, right, top, bar_h, gap = 260, 210, 64, 24, 8
    width = 1100
    plot_w = width - left - right
    height = top + len(items) * (bar_h + gap) + 70
    ticks = _log_ticks(min(i[1] for i in items) / 1.5, max(i[1] for i in items) * 1.5)
    lo, hi = math.log10(ticks[0]), math.log10(ticks[-1])
    x = lambda v: left + (math.log10(v) - lo) / (hi - lo) * plot_w
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="system-ui, sans-serif" font-size="13">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="{left}" y="28" font-size="16" font-weight="600" fill="#111827">{escape(title)}</text>']
    for t in ticks:
        out.append(f'<line x1="{x(t):.1f}" y1="{top - 8}" x2="{x(t):.1f}" y2="{height - 52}" stroke="#e5e7eb"/>')
        out.append(f'<text x="{x(t):.1f}" y="{height - 36}" text-anchor="middle" fill="#6b7280">{fmt_ns(t)}</text>')
    for i, (label, v, fam, extra) in enumerate(items):
        y = top + i * (bar_h + gap)
        color = FAMILY_COLORS.get(fam, "#4b5563")
        out.append(f'<text x="{left - 10}" y="{y + bar_h * 0.7:.1f}" text-anchor="end" fill="#111827">{escape(label)}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{max(2, x(v) - left):.1f}" height="{bar_h}" rx="3" fill="{color}"/>')
        text = fmt_ns(v) + (f"  ·  {extra}" if extra else "")
        out.append(f'<text x="{x(v) + 6:.1f}" y="{y + bar_h * 0.7:.1f}" fill="#111827">{escape(text)}</text>')
    out.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 12}" text-anchor="middle" fill="#374151">{escape(xlabel)}</text>')
    lx = left
    for fam in dict.fromkeys(i[2] for i in items):
        out.append(f'<rect x="{lx}" y="40" width="12" height="12" fill="{FAMILY_COLORS.get(fam, "#4b5563")}"/>')
        out.append(f'<text x="{lx + 17}" y="51" fill="#374151">{escape(fam)}</text>')
        lx += 30 + 8 * len(fam)
    out.append("</svg>")
    path.write_text("\n".join(out))
