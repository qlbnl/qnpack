#!/usr/bin/env python3
"""
Draw compact circuit diagrams for 1-iteration 4-qubit Grover's algorithm.

Produces three diagrams:
  1. 1-QPU  (grover4_1iter_1qpu_4comp_4comm.qasm)
  2. 2-QPU  (grover4_1iter_2qpu_2comp_2comm.qasm)
  3. 3-QPU  (grover4_1iter_3qpu_2comp_2comm_1comp_1comm.qasm)

Each diagram is saved as both PDF and PNG in the results/ sub-directory and
a summary is printed to stdout.

Usage:
    python draw_circuit_diagram_4q.py          # all three diagrams
    python draw_circuit_diagram_4q.py <file>   # single QASM file
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
import re, os, sys, math
from collections import OrderedDict

# ─── Colors ─────────────────────────────────────────────────────────
C_DATA   = "#2c3e50"
C_COMM   = "#95a5a6"
C_CX     = "#2c3e50"
C_ENT    = "#8e44ad"
C_MEAS   = "#2c3e50"
C_SQ     = "#1a6fa8"
C_QPU_COLORS = ["#eaf2f8", "#fef9e7", "#fdf2e9", "#f4ecf7"]
C_ORACLE = "#fde8e8"
C_DIFF   = "#e8f4fd"

GW    = 0.36
GH    = 0.42
XSTEP = 0.50

# ── Font sizes (enlarged for readability) ───────────────────────────
FS_GATE   = 9    # gate label inside box
FS_LABEL  = 22   # qubit wire labels (q / c names on left)
FS_INIT   = 22   # |0⟩ state labels
FS_QPU    = 16   # QPU header
FS_TITLE  = 32   # figure title
FS_LEGEND = 20   # legend (bottom labels)
FS_MEAS   = 18   # measurement bit label (m_i below meas box)
FS_EPR    = 11   # EPR box label
FS_SEC    = 32   # Oracle / Diffusion section label

PI = math.pi

SQ_OPS = {'h', 'sx', 'rz', 'x'}


# ═══════════════════════════════════════════════════════════════════
#  ANGLE HELPERS
# ═══════════════════════════════════════════════════════════════════
def _eval_angle(expr):
    expr = expr.strip()
    expr = re.sub(r'\bpi\b', str(PI), expr)
    try:
        return float(eval(expr, {"__builtins__": {}}, {"pi": PI}))
    except Exception:
        return 0.0


def _angle_near(a, b, tol=1e-6):
    diff = (a - b) % (2 * PI)
    return diff < tol or abs(diff - 2 * PI) < tol


def _fmt_angle(rad):
    frac = rad / PI
    for num in range(1, 9):
        for den in range(1, 9):
            if abs(frac - num / den) < 1e-4:
                return f"{num}π" if den == 1 else f"{num}π/{den}"
            if abs(frac + num / den) < 1e-4:
                return f"-{num}π" if den == 1 else f"-{num}π/{den}"
    return f"{frac:.2f}π"


def _sq_label(gate_list):
    """Compact label for a run of single-qubit gates on one qubit."""
    recomposed = []
    j = 0
    while j < len(gate_list):
        g, a = gate_list[j]
        # H = rz(π/2) sx rz(π/2)
        if (g == 'rz' and _angle_near(abs(a), PI/2)
                and j+2 < len(gate_list)
                and gate_list[j+1][0] == 'sx'
                and gate_list[j+2][0] == 'rz'
                and _angle_near(abs(gate_list[j+2][1]), PI/2)):
            recomposed.append(('h', None))
            j += 3
            continue
        # X pattern (drop)
        if (g == 'rz' and _angle_near(abs(a), PI)
                and j+4 < len(gate_list)
                and gate_list[j+1][0] == 'sx'
                and gate_list[j+2][0] == 'rz'
                and _angle_near(abs(gate_list[j+2][1]), 2*PI)
                and gate_list[j+3][0] == 'sx'
                and gate_list[j+4][0] == 'rz'
                and _angle_near(abs(gate_list[j+4][1]), 3*PI)):
            j += 5
            continue
        recomposed.append((g, a))
        j += 1

    merged = []
    for g, a in recomposed:
        if g == 'rz' and merged and merged[-1][0] == 'rz':
            merged[-1] = ('rz', merged[-1][1] + a)
        else:
            merged.append((g, a))
    merged = [(g, a) for g, a in merged if not (g == 'rz' and abs(a % (2*PI)) < 1e-6)]

    if not merged:
        return None

    parts = []
    for g, a in merged:
        if g == 'h':
            parts.append("H")
        elif g == 'sx':
            parts.append("SX")
        elif g == 'rz':
            parts.append(f"Rz({_fmt_angle(a)})")
        elif g == 'x':
            pass
    parts = [p for p in parts if p]
    if not parts:
        return None
    return "·".join(parts)


# ═══════════════════════════════════════════════════════════════════
#  QASM PARSER
# ═══════════════════════════════════════════════════════════════════
def parse_qasm(filepath):
    """
    Parse QASM and return (ops, qubit_order, qpu_map, meas_map, diffusion_op_idx).
    Single-qubit gate runs are collapsed into sq_block ops.
    """
    qubit_order = []
    meas_map = {}
    raw_ops = []
    diffusion_raw_idx = None

    with open(filepath) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if '// DIFFUSION_START' in line:
            diffusion_raw_idx = len(raw_ops)
            continue

        if not line or line.startswith("OPENQASM") or line.startswith("include") \
           or line.startswith("bit[") or line.startswith("//"):
            continue
        if line.startswith("gate "):
            while i < len(lines) and "}" not in lines[i]:
                i += 1
            i += 1
            continue
        if line == "}":
            continue

        m = re.match(r'qubit\[\d+\]\s+(\w+)\s*;', line)
        if m:
            qubit_order.append(m.group(1))
            continue

        m = re.match(r'cx\s+(\w+)\[0\]\s*,\s*(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'cx', 'qubits': [m.group(1), m.group(2)]})
            continue

        m = re.match(r'entanglement\s+(\w+)\[0\]\s*,\s*(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'entanglement', 'qubits': [m.group(1), m.group(2)]})
            continue

        m = re.match(r'm\[(\d+)\]\s*=\s*measure\s+(\w+)\[0\]\s*;', line)
        if m:
            bit_idx = int(m.group(1))
            qname = m.group(2)
            meas_map[qname] = bit_idx
            raw_ops.append({'op': 'final_measure', 'bit_idx': bit_idx, 'qubits': [qname]})
            continue

        m = re.match(r'rz\(([^)]+)\)\s+(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'rz', 'qubits': [m.group(2)], 'angle': _eval_angle(m.group(1))})
            continue

        m = re.match(r'sx\s+(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'sx', 'qubits': [m.group(1)]})
            continue

        m = re.match(r'h\s+(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'h', 'qubits': [m.group(1)]})
            continue

        m = re.match(r'x\s+(\w+)\[0\]\s*;', line)
        if m:
            raw_ops.append({'op': 'x', 'qubits': [m.group(1)]})
            continue

    ops, diffusion_op_idx = _collapse_sq(raw_ops, diffusion_raw_idx)

    qpu_map = {}
    for q in qubit_order:
        m = re.match(r'_(?:comm_)?qubit(\d+)_', q)
        if m:
            qpu_map[q] = int(m.group(1))

    return ops, qubit_order, qpu_map, meas_map, diffusion_op_idx


def _collapse_sq(raw_ops, diffusion_raw_idx):
    """Collapse consecutive single-qubit ops into sq_block ops."""
    pending = {}
    result = []
    result_diff_idx = None

    def flush(q):
        if q in pending and pending[q]:
            lbl = _sq_label(pending[q])
            if lbl:
                result.append({'op': 'sq_block', 'qubits': [q], 'label': lbl})
            del pending[q]

    def flush_all():
        for q in list(pending.keys()):
            flush(q)

    for k, op in enumerate(raw_ops):
        if diffusion_raw_idx is not None and k == diffusion_raw_idx:
            flush_all()
            result_diff_idx = len(result)

        o = op['op']
        q0 = op['qubits'][0]

        if o in SQ_OPS:
            angle = op.get('angle', None)
            pending.setdefault(q0, []).append((o, angle))
        elif o == 'cx':
            q1 = op['qubits'][1]
            flush(q0)
            flush(q1)
            result.append(op)
        elif o == 'entanglement':
            q1 = op['qubits'][1]
            flush(q0)
            flush(q1)
            result.append(op)
        elif o == 'final_measure':
            flush(q0)
            result.append(op)
        else:
            flush_all()
            result.append(op)

    flush_all()

    if diffusion_raw_idx is not None and result_diff_idx is None:
        result_diff_idx = len(result)

    return result, result_diff_idx


# ═══════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════
def _is_comm(q):
    return '_comm_' in q


def build_layout(qubit_order, qpu_map):
    qpu_groups = OrderedDict()
    for q in qubit_order:
        qid = qpu_map.get(q, 0)
        qpu_groups.setdefault(qid, []).append(q)

    for qid in qpu_groups:
        data_q = [q for q in qpu_groups[qid] if not _is_comm(q)]
        comm_q = [q for q in qpu_groups[qid] if _is_comm(q)]
        qpu_groups[qid] = data_q + comm_q

    sorted_qpus = sorted(qpu_groups.keys())
    wire_y = {}
    y = 0
    for idx, qid in enumerate(reversed(sorted_qpus)):
        qubits = qpu_groups[qid]
        for q in qubits:
            wire_y[q] = y
            y -= 0.85
        if idx < len(sorted_qpus) - 1:
            y -= 0.6

    return wire_y, qpu_groups


def nice_label(q, meas_map):
    m = re.match(r'_(?:comm_)?qubit(\d+)_(\d+)', q)
    if not m:
        return q
    qpu_id, idx = m.group(1), m.group(2)
    if _is_comm(q):
        return f"$c_{{{qpu_id},{idx}}}$"
    else:
        bit_idx = meas_map.get(q)
        bit_str = f" → $m_{{{bit_idx}}}$" if bit_idx is not None else ""
        return f"$q_{{{qpu_id},{idx}}}${bit_str}"


# ═══════════════════════════════════════════════════════════════════
#  CIRCUIT DRAWER
# ═══════════════════════════════════════════════════════════════════
class CircuitDrawer:
    def __init__(self, ax, wire_y, qubit_order):
        self.ax = ax
        self.wire_y = wire_y
        self.qubit_order = qubit_order
        self.wire_x = {q: 0.3 for q in qubit_order}

    def _next_x(self, qubits):
        return max(self.wire_x[q] for q in qubits) + XSTEP

    def _advance(self, qubits, x, w=GW):
        for q in qubits:
            self.wire_x[q] = x + w / 2

    def _wires_between(self, q1, q2):
        i1 = self.qubit_order.index(q1)
        i2 = self.qubit_order.index(q2)
        lo, hi = min(i1, i2), max(i1, i2)
        return [self.qubit_order[k] for k in range(lo, hi + 1)]

    def draw_sq_block(self, q, label):
        x = self._next_x([q])
        y = self.wire_y[q]
        # Estimate width: ~0.065 data-units per character at FS_GATE=9, 200dpi
        n_chars = len(label)
        w = max(GW, 0.065 * n_chars + 0.10)
        h = GH
        rect = FancyBboxPatch(
            (x - w/2, y - h/2), w, h,
            boxstyle="round,pad=0.02",
            facecolor=C_SQ, edgecolor="black", lw=0.6, alpha=0.9, zorder=5)
        self.ax.add_patch(rect)
        self.ax.text(x, y, label, ha="center", va="center",
                     fontsize=FS_GATE, fontweight="bold",
                     color="white", zorder=6)
        self._advance([q], x, w=w)

    def draw_cx(self, ctrl, tgt):
        between = self._wires_between(ctrl, tgt)
        x = self._next_x(between)
        yc, yt = self.wire_y[ctrl], self.wire_y[tgt]
        self.ax.plot([x, x], [yc, yt], color=C_CX, lw=1.6, zorder=4)
        self.ax.plot(x, yc, "o", color=C_CX, ms=9, zorder=5)
        r = 0.15
        c = plt.Circle((x, yt), r, fill=False, ec=C_CX, lw=1.6, zorder=5)
        self.ax.add_patch(c)
        self.ax.plot([x-r, x+r], [yt, yt], color=C_CX, lw=1.2, zorder=5)
        self.ax.plot([x, x], [yt-r, yt+r], color=C_CX, lw=1.2, zorder=5)
        self._advance(between, x)

    def draw_entanglement(self, q1, q2):
        between = self._wires_between(q1, q2)
        x = self._next_x(between)
        y1, y2 = self.wire_y[q1], self.wire_y[q2]
        y_lo, y_hi = min(y1, y2), max(y1, y2)
        w = 0.50
        h = y_hi - y_lo + GH
        rect = FancyBboxPatch(
            (x - w/2, y_lo - GH/2), w, h,
            boxstyle="round,pad=0.02",
            facecolor=C_ENT, edgecolor="black", lw=0.7, alpha=0.85, zorder=5)
        self.ax.add_patch(rect)
        self.ax.text(x, (y_lo + y_hi)/2, "EPR",
                     ha="center", va="center", fontsize=FS_EPR,
                     fontweight="bold", color="white", zorder=6)
        self._advance(between, x, w=w)

    def draw_measure(self, q, bit_idx=None):
        x = self._next_x([q])
        y = self.wire_y[q]
        s = 0.19
        rect = FancyBboxPatch(
            (x - s, y - s), 2*s, 2*s,
            boxstyle="round,pad=0.01",
            facecolor="white", edgecolor=C_MEAS, lw=0.9, zorder=5)
        self.ax.add_patch(rect)
        theta = np.linspace(np.pi, 0, 12)
        r = 0.09
        self.ax.plot(x + r*np.cos(theta), y - 0.03 + r*np.sin(theta),
                     color=C_MEAS, lw=0.7, zorder=6)
        self.ax.annotate("", xy=(x+0.08, y+0.09), xytext=(x, y-0.03),
                         arrowprops=dict(arrowstyle="->,head_width=0.03,head_length=0.03",
                                         color=C_MEAS, lw=0.6), zorder=6)
        if bit_idx is not None:
            self.ax.text(x, y - s - 0.12, f"$m_{{{bit_idx}}}$",
                         ha="center", va="top", fontsize=FS_MEAS, color=C_MEAS)
        self._advance([q], x)

    def current_x(self):
        return max(self.wire_x.values())

    def get_max_x(self):
        return max(self.wire_x.values())


# ═══════════════════════════════════════════════════════════════════
#  MAIN DRAW FUNCTION
# ═══════════════════════════════════════════════════════════════════
def draw_circuit(qasm_path, output_prefix=None, title_override=None):
    ops, qubit_order, qpu_map, meas_map, diffusion_op_idx = parse_qasm(qasm_path)
    wire_y, qpu_groups = build_layout(qubit_order, qpu_map)

    n_qubits = len(qubit_order)
    n_ops    = len(ops)
    n_qpus   = len(qpu_groups)

    op_counts = {}
    for op in ops:
        op_counts[op['op']] = op_counts.get(op['op'], 0) + 1

    # ── Print summary ────────────────────────────────────────────
    print("=" * 60)
    print(f"File   : {os.path.basename(qasm_path)}")
    print(f"Qubits : {n_qubits}   Ops (collapsed): {n_ops}   QPUs: {n_qpus}")
    print(f"Op breakdown : {op_counts}")
    print(f"Diffusion starts at op index: {diffusion_op_idx}")
    for qid, qubits in sorted(qpu_groups.items()):
        nd = sum(1 for q in qubits if not _is_comm(q))
        nc = sum(1 for q in qubits if _is_comm(q))
        print(f"  QPU {qid}: {nd} data + {nc} comm qubits")
    print()

    # ── Figure sizing ────────────────────────────────────────────
    est_width  = n_ops * XSTEP + 4.0
    fig_width  = min(max(12, est_width), 60)
    fig_height = max(5.0, n_qubits * 0.85 + (n_qpus - 1) * 0.6 + 4.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_aspect("equal")

    drawer = CircuitDrawer(ax, wire_y, qubit_order)
    diffusion_x_start = None

    for k, op in enumerate(ops):
        if diffusion_op_idx is not None and k == diffusion_op_idx:
            diffusion_x_start = drawer.current_x() + XSTEP * 0.5

        q = op['qubits']
        if op['op'] == 'sq_block':
            drawer.draw_sq_block(q[0], op['label'])
        elif op['op'] == 'cx':
            drawer.draw_cx(q[0], q[1])
        elif op['op'] == 'entanglement':
            drawer.draw_entanglement(q[0], q[1])
        elif op['op'] == 'final_measure':
            drawer.draw_measure(q[0], bit_idx=op['bit_idx'])

    X_END   = drawer.get_max_x() + 0.5
    X_START = 0.0

    all_ys = list(wire_y.values())
    y_bot  = min(all_ys) - 0.55
    y_top  = max(all_ys) + 0.55

    # ── Section shading (Oracle / Diffusion) ─────────────────────
    if diffusion_x_start is not None:
        # Oracle region — extend box upward to include label
        oracle_top = y_top + 0.55
        ax.add_patch(FancyBboxPatch(
            (X_START - 0.05, y_bot),
            diffusion_x_start - X_START + 0.05, oracle_top - y_bot,
            boxstyle="square,pad=0",
            facecolor=C_ORACLE, edgecolor="none", alpha=0.25, zorder=-2))
        ax.text((X_START + diffusion_x_start) / 2, oracle_top - 0.05,
                "Oracle", ha="center", va="top",
                fontsize=FS_SEC, fontweight="bold", color="#c0392b")

        # Diffusion region — extend box upward to include label
        diff_top = y_top + 0.55
        ax.add_patch(FancyBboxPatch(
            (diffusion_x_start, y_bot),
            X_END - diffusion_x_start + 0.05, diff_top - y_bot,
            boxstyle="square,pad=0",
            facecolor=C_DIFF, edgecolor="none", alpha=0.25, zorder=-2))
        ax.text((diffusion_x_start + X_END) / 2, diff_top - 0.05,
                "Diffusion", ha="center", va="top",
                fontsize=FS_SEC, fontweight="bold", color="#1a5276")

        ax.plot([diffusion_x_start, diffusion_x_start], [y_bot - 0.1, diff_top],
                color="grey", lw=1.4, ls="--", alpha=0.7, zorder=1)

    # ── Wires ────────────────────────────────────────────────────
    for q in qubit_order:
        y    = wire_y[q]
        is_d = not _is_comm(q)
        ax.plot([X_START, X_END], [y, y],
                color=C_DATA if is_d else C_COMM,
                lw=1.2 if is_d else 0.6,
                ls="-" if is_d else (0, (3, 2)), zorder=0)

    # ── Wire labels (qubit names) ─────────────────────────────────
    for q in qubit_order:
        y    = wire_y[q]
        is_d = not _is_comm(q)
        lbl  = nice_label(q, meas_map)
        ax.text(X_START - 0.14, y, lbl, ha="right", va="center",
                fontsize=FS_LABEL, fontweight="bold",
                color=C_DATA if is_d else C_COMM)

    # ── |0⟩ state labels ─────────────────────────────────────────
    for q in qubit_order:
        ax.text(X_START - 2.5, wire_y[q], "$|0\\rangle$",
                ha="center", va="center", fontsize=FS_INIT, color="#444")

    # ── QPU background boxes ──────────────────────────────────────
    sorted_qpus = sorted(qpu_groups.keys())
    for idx, qid in enumerate(sorted_qpus):
        qubits = qpu_groups[qid]
        ys     = [wire_y[q] for q in qubits]
        y_lo, y_hi = min(ys), max(ys)
        m      = 0.35
        color  = C_QPU_COLORS[idx % len(C_QPU_COLORS)]
        rect   = FancyBboxPatch(
            (X_START - 0.10, y_lo - m), X_END - X_START + 0.20, y_hi - y_lo + 2*m,
            boxstyle="round,pad=0.05",
            facecolor=color, edgecolor="grey", lw=0.5, alpha=0.35, zorder=-1)
        ax.add_patch(rect)
        nd = sum(1 for q in qubits if not _is_comm(q))
        nc = sum(1 for q in qubits if _is_comm(q))
        ax.text(X_START - 0.05, y_hi + m + 0.08,
                f"QPU {qid}  ({nd}d + {nc}c)",
                ha="left", va="bottom", fontsize=FS_QPU, fontweight="bold", color="#2c3e50")

    # ── QPU separators ────────────────────────────────────────────
    for idx in range(len(sorted_qpus) - 1):
        qid1 = sorted_qpus[idx]
        qid2 = sorted_qpus[idx + 1]
        ys1  = [wire_y[q] for q in qpu_groups[qid1]]
        ys2  = [wire_y[q] for q in qpu_groups[qid2]]
        sep_y = (min(ys1) + max(ys2)) / 2
        ax.plot([X_START - 0.2, X_END + 0.2], [sep_y, sep_y],
                color="grey", lw=0.9, ls=":", alpha=0.5, zorder=-1)

    # ── Legend ────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor=C_SQ,  ec="black", label="Single-qubit gates (H/SX/Rz)"),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CX,
                   ms=7, label="CX (ctrl)"),
        mpatches.Patch(facecolor=C_ENT, ec="black", label="EPR entanglement"),
        plt.Line2D([0], [0], color=C_DATA, lw=1.2, label="Data qubit"),
        plt.Line2D([0], [0], color=C_COMM, lw=0.6, ls="--", label="Comm qubit"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=FS_LEGEND,
              framealpha=0.9, ncol=5, bbox_to_anchor=(1.0, -0.07))

    ax.set_xlim(X_START - 3.2, X_END + 0.2)
    ax.set_ylim(min(all_ys) - 0.7, max(all_ys) + 0.55)
    ax.axis("off")

    n_data = sum(1 for q in qubit_order if not _is_comm(q))
    title  = title_override or (
        f"4-Qubit Grover's Algorithm (1 iteration) — {n_qpus} QPU{'s' if n_qpus > 1 else ''}, "
        f"{n_data} data qubits"
    )
    fig.suptitle(title, fontsize=FS_TITLE, fontweight="bold", y=1.0)

    fig.subplots_adjust(top=0.97, bottom=0.04, left=0.01, right=0.99)

    out_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)
    prefix   = output_prefix or os.path.splitext(os.path.basename(qasm_path))[0]
    pdf_path = os.path.join(out_dir, f"{prefix}_circuit.pdf")
    # png_path = os.path.join(out_dir, f"{prefix}_circuit.png")
    plt.savefig(pdf_path, dpi=200, bbox_inches="tight", pad_inches=0.05)
    # plt.savefig(png_path, dpi=200, bbox_inches="tight", pad_inches=0.05)
    print(f"  → Saved PDF : {pdf_path}")
    # print(f"  → Saved PNG : {png_path}")
    print()
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) > 1:
        qasm_path = sys.argv[1]
        if not os.path.isabs(qasm_path):
            qasm_path = os.path.join(base_dir, qasm_path)
        draw_circuit(qasm_path)
        return

    # All three 4-qubit 1-iteration configurations
    configs = [
        (
            "qasm/grover4_1iter_1qpu_4comp_4comm.qasm",
            "grover4_1iter_1qpu",
            "4-Qubit Grover's Algorithm (1 iteration) — 1 QPU, 4 data qubits",
        ),
        (
            "qasm/grover4_1iter_2qpu_2comp_2comm.qasm",
            "grover4_1iter_2qpu",
            "4-Qubit Grover's Algorithm (1 iteration) — 2 QPUs, 4 data qubits",
        ),
        (
            "qasm/grover4_1iter_3qpu_2comp_2comm_1comp_1comm.qasm",
            "grover4_1iter_3qpu",
            "4-Qubit Grover's Algorithm (1 iteration) — 3 QPUs, 4 data qubits",
        ),
    ]

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  4-Qubit Grover Circuit Diagrams  (1 iteration)          ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    for rel_path, prefix, title in configs:
        qasm_path = os.path.join(base_dir, rel_path)
        if os.path.exists(qasm_path):
            draw_circuit(qasm_path, output_prefix=prefix, title_override=title)
        else:
            print(f"WARNING: {qasm_path} not found — skipping\n")

    print("Done.")


if __name__ == "__main__":
    main()
