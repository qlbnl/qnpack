"""
protocols/controller.py
-----------------------
ControllerProtocol — runs on the Central Controller node.

Coordinates QPU and BSM nodes by:
1. Sending commands to all QPUs
2. Collecting ready signals from QPUs at sync points
3. Dispatching clock ticks when both parties for a label are ready
4. Triggering BSM nodes for entanglement generation
"""

import os
import json
import logging

import netsquid as ns
from netsquid.protocols.nodeprotocols import NodeProtocol
from netsquid.components.component import Message
from netsquid.protocols.protocol import Signals

from ..frontends import load_frontend
from ..labeling import label_and_build_maps

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_mapper(mapping_list):
    """Build a bidirectional name mapper from a list of (server, site) pairs."""
    server_to_site = {s: site for s, site in mapping_list}
    site_to_server = {site: s for s, site in mapping_list}

    def mapper(name, to="site"):
        if to == "site":
            return server_to_site.get(name, name)
        elif to == "server":
            return site_to_server.get(name, name)
        return name

    return mapper


def insert_pre_entanglement_commands(
    qpu_commands,
    expected_ent_latency_ns=None,
    one_q_gate_duration_ns=5000,
    two_q_gate_duration_ns=10700,
):
    """Move ``entanglement_gen`` commands earlier in each QPU's command list.

    The goal is to overlap Bell-pair generation (which takes
    *expected_ent_latency_ns*) with local gate execution so that the
    entangled pair is ready by the time the corresponding
    ``starting_process`` needs it.

    Parameters
    ----------
    qpu_commands : dict[int, list[dict]]
        Per-QPU command lists (mutated in place).
    expected_ent_latency_ns : float or None
        Expected entanglement latency.  If None or ≤ 0, no moves are made.
    one_q_gate_duration_ns : float
        Duration of a 1-qubit gate (ns).
    two_q_gate_duration_ns : float
        Duration of a 2-qubit gate (ns).

    Returns
    -------
    dict
        Stats dict with keys ``total_pairs``, ``moved_pairs``,
        ``unmoved_pairs``, ``expected_latency_ns``, ``moves``.
    """
    if expected_ent_latency_ns is None or expected_ent_latency_ns <= 0:
        return {
            "total_pairs": 0,
            "moved_pairs": 0,
            "unmoved_pairs": 0,
            "expected_latency_ns": 0,
            "moves": [],
        }

    SYNC_OPS = {
        'entanglement_gen', 'starting_process', 'starting_process_link',
        'ending_process', 'ending_process_link',
    }

    # Index every entanglement_gen by its label
    ent_pairs = {}
    for qpu_id, cmd_list in qpu_commands.items():
        for idx, cmd in enumerate(cmd_list):
            if cmd.get('op') == 'entanglement_gen':
                label = cmd['entanglement_label']
                ent_pairs.setdefault(label, []).append((qpu_id, idx))

    def _gate_duration(cmd):
        op = cmd.get('op', '')
        if op in SYNC_OPS:
            return 0
        qubits = cmd.get('qubits', [])
        if len(qubits) >= 2:
            return two_q_gate_duration_ns
        return one_q_gate_duration_ns

    def _comm_qubits_of(cmd):
        op = cmd.get('op', '')
        if op == 'entanglement_gen':
            return set(cmd.get('qubits', []))
        if op in ('starting_process', 'ending_process'):
            ll = cmd.get('l_local')
            return {ll} if ll is not None else set()
        if op in ('starting_process_link', 'ending_process_link'):
            return set(cmd.get('qubits', []))
        return set()

    sorted_labels = sorted(
        ent_pairs.keys(), key=lambda lbl: int(lbl.split('_')[1])
    )

    total_pairs = len(sorted_labels)
    moved_pairs = 0
    unmoved_pairs = 0
    moves = []

    for ent_label in sorted_labels:
        locations = ent_pairs[ent_label]
        if len(locations) != 2:
            log.warning(
                f"[pre-ent] entanglement_gen {ent_label} has "
                f"{len(locations)} locations (expected 2); skipping"
            )
            unmoved_pairs += 1
            continue

        current_positions = []
        for qpu_id, _ in locations:
            cmd_list = qpu_commands[qpu_id]
            pos = None
            for i, c in enumerate(cmd_list):
                if (
                    c.get('op') == 'entanglement_gen'
                    and c.get('entanglement_label') == ent_label
                ):
                    pos = i
                    break
            if pos is None:
                log.warning(
                    f"[pre-ent] Cannot find {ent_label} on QPU {qpu_id}"
                )
                break
            current_positions.append((qpu_id, pos))

        if len(current_positions) != 2:
            unmoved_pairs += 1
            continue

        feasible_pullbacks = []
        accumulated_times = []
        for qpu_id, cur_pos in current_positions:
            cmd_list = qpu_commands[qpu_id]
            ent_cmd = cmd_list[cur_pos]
            ent_comm_qubits = _comm_qubits_of(ent_cmd)

            accumulated_ns = 0
            earliest_pos = cur_pos

            for j in range(cur_pos - 1, -1, -1):
                prev_cmd = cmd_list[j]
                prev_op = prev_cmd.get('op', '')

                if prev_op in SYNC_OPS:
                    prev_comm = _comm_qubits_of(prev_cmd)
                    if prev_comm & ent_comm_qubits:
                        break
                    break

                prev_gate_qubits = set(prev_cmd.get('qubits', []))
                if prev_gate_qubits & ent_comm_qubits:
                    break

                gate_ns = _gate_duration(prev_cmd)
                accumulated_ns += gate_ns
                earliest_pos = j

                if accumulated_ns >= expected_ent_latency_ns:
                    break

            pullback = cur_pos - earliest_pos
            feasible_pullbacks.append(pullback)
            accumulated_times.append(accumulated_ns)

        if len(feasible_pullbacks) != 2:
            unmoved_pairs += 1
            continue

        actual_pullback = min(feasible_pullbacks)

        if actual_pullback <= 0:
            unmoved_pairs += 1
            continue

        moved_pairs += 1
        qpu_ids = [qid for qid, _ in current_positions]
        moves.append({
            "label": ent_label,
            "pullback": actual_pullback,
            "feasible": list(feasible_pullbacks),
            "gate_time_ns": list(accumulated_times),
            "qpus": qpu_ids,
        })

        log.debug(
            f"[pre-ent] Moving {ent_label} earlier by {actual_pullback} "
            f"commands (feasible: {feasible_pullbacks})"
        )

        for qpu_id, cur_pos in current_positions:
            cmd_list = qpu_commands[qpu_id]
            new_pos = cur_pos - actual_pullback
            ent_cmd = cmd_list.pop(cur_pos)
            cmd_list.insert(new_pos, ent_cmd)

    return {
        "total_pairs": total_pairs,
        "moved_pairs": moved_pairs,
        "unmoved_pairs": unmoved_pairs,
        "expected_latency_ns": expected_ent_latency_ns,
        "moves": moves,
    }


# ---------------------------------------------------------------------------
# ControllerProtocol
# ---------------------------------------------------------------------------

class ControllerProtocol(NodeProtocol):
    """Protocol running on the Central Controller node.

    Parameters
    ----------
    cfg : Munch
        Simulation configuration.
    node : Node
        The controller node.
    qpu_nodes : list[Node]
        All QPU nodes.
    qpu_info : dict, optional
        QPU topology metadata.
    bsm_info : dict, optional
        BSM topology metadata.
    name : str or None
        Protocol name.
    run_idx : int
        Current simulation run index (used to gate schedule printing).
    frontend : BaseFrontend or None
        Pre-loaded frontend instance.  When provided, the controller
        reuses it instead of calling ``load_frontend`` again.
    """

    def __init__(
        self,
        cfg,
        node,
        qpu_nodes,
        qpu_info=None,
        bsm_info=None,
        name=None,
        run_idx=0,
        frontend=None,
        pre_labeled_commands=None,
        pre_process_maps=None,
    ):
        super().__init__(node, name=name)
        self.cfg = cfg
        self.run_idx = run_idx
        self.frontend = frontend
        self.qpu_nodes = qpu_nodes
        self.num_qpus = len(qpu_nodes)
        self.qpu_commands = {}
        self.qpu_info = qpu_info or {}
        self.bsm_info = bsm_info or {}

        # Pre-labeled commands injected from outside (e.g. the DQC plugin).
        # When set, ControllerProtocol.run() skips frontend.parse(),
        # validate_commands(), and label_and_build_maps() and uses these
        # directly.  Keys must be 1-based integer QPU IDs (matching the
        # qpu_info convention).
        self._pre_labeled_commands = pre_labeled_commands
        self._pre_process_maps = pre_process_maps
        self.mapping_list = [
            ("QPU_1", "LBNL-A"),
            ("QPU_2", "LBNL-B"),
            ("QPU_3", "LBNL-C"),
            ("QPU_4", "LBNL-D"),
        ]

        self.qpu_pair_to_bsm = {}
        self._build_qpu_pair_to_bsm_map()

        self.clk = self.node.subcomponents["CtrlCLK"]

        self.num_bsm_nodes = len(self.bsm_info)

        self.start_qpus = {}
        self.start_ready = {}
        self.end_qpus = {}
        self.end_ready = {}

        self.waiting_qpus = set()
        self.finished_qpus = set()

    # ── BSM mapping ──────────────────────────────────────────────────────────

    def _build_qpu_pair_to_bsm_map(self):
        """Build a mapping from QPU-pair to ``(bsm_id, bsm_label)``."""
        label_to_qpu_id = {
            label: info["qpu_id"] for label, info in self.qpu_info.items()
        }

        for bsm_label, bsm_inf in self.bsm_info.items():
            bsm_id = bsm_inf["bsm_id"]
            left_label = bsm_inf.get("left_qpu")
            right_label = bsm_inf.get("right_qpu")

            if left_label in label_to_qpu_id and right_label in label_to_qpu_id:
                left_qpu_id = label_to_qpu_id[left_label]
                right_qpu_id = label_to_qpu_id[right_label]
                pair = frozenset({left_qpu_id, right_qpu_id})
                self.qpu_pair_to_bsm[pair] = (bsm_id, bsm_label)
                log.debug(
                    f"[Controller] BSM mapping: QPU_{left_qpu_id} & QPU_{right_qpu_id} "
                    f"-> BSM_Node{bsm_id} ({bsm_label})"
                )

        log.debug(f"[Controller] QPU-pair -> BSM map: {self.qpu_pair_to_bsm}")

    # ── Messaging ────────────────────────────────────────────────────────────

    def send_start_entanglement_to_bsm(self, qpu_ids, start_label):
        """Send a 'Start Entanglement' message to the BSM node."""
        pair = frozenset(qpu_ids)
        bsm_entry = self.qpu_pair_to_bsm.get(pair)

        if bsm_entry is None:
            log.warning(
                f"[Controller] No BSM node found for QPU pair {qpu_ids}"
            )
            return

        bsm_id, bsm_label = bsm_entry
        port_name = f"ctrl_bsm{bsm_id}_port"
        if port_name in self.node.ports:
            msg = Message(items={
                'type': 'start_entanglement',
                'start_label': start_label,
                'qpu_ids': list(qpu_ids),
                'bsm_id': bsm_id,
                'bsm_label': bsm_label,
            })
            self.node.ports[port_name].tx_output(msg)
            log.debug(
                f"[Controller] Sent 'Start Entanglement' to BSM_Node{bsm_id} "
                f"({bsm_label}) via {port_name} for start_label={start_label}, "
                f"QPUs={qpu_ids}"
            )
        else:
            log.error(
                f"[Controller] Port {port_name} not found on {self.node.name}"
            )

    def send_commands_to_qpu(self, qpu_id, commands):
        """Send commands to a specific QPU via ctrl port."""
        port_name = f"ctrl{qpu_id}_port"
        if port_name in self.node.ports:
            msg = Message(items={'commands': commands, 'qpu_id': qpu_id})
            self.node.ports[port_name].tx_output(msg)
            log.debug(
                f"[{self.node.name}] Sent {len(commands)} commands to QPU_{qpu_id}"
            )
        else:
            log.error(f"[{self.node.name}] Port {port_name} not found")

    def send_clock_tick_to_all(
        self, qpu_ids, start_label=None, end_label=None, bsm_label=None
    ):
        """Send a single clock tick to multiple QPUs simultaneously."""
        if not self.clk.is_running:
            self.clk.start()
        log.debug(
            f"{ns.sim_time()} Controller: Clock running: {self.clk.is_running}, "
            f"num_ticks: {self.clk.num_ticks} at {self.node.name}"
        )

        def _build_port_names():
            return [f"comm{qpu_id_iter}_port" for qpu_id_iter in self.qpu_commands]

        def _build_combined_ev():
            _clk_ev = self.await_port_output(self.clk.ports["cout"])
            _comm_ev = None
            for pn in _build_port_names():
                if pn in self.node.ports:
                    port_ev = self.await_port_input(self.node.ports[pn])
                    _comm_ev = port_ev if _comm_ev is None else _comm_ev | port_ev
            if _comm_ev is not None:
                return _clk_ev | _comm_ev
            return _clk_ev

        combined_ev = _build_combined_ev()
        clk_received = False

        while not clk_received:
            yield combined_ev

            clk_msg = self.clk.ports["cout"].rx_output()
            if clk_msg is not None:
                clk_received = True

            for pn in _build_port_names():
                if pn in self.node.ports:
                    comm_msg = self.node.ports[pn].rx_input()
                    if comm_msg is not None:
                        self.process_ready_message(comm_msg)

            if not clk_received:
                combined_ev = _build_combined_ev()

        for qpu_id in qpu_ids:
            port_name = f"clk{qpu_id}_port"
            if port_name in self.node.ports:
                msg = Message(items={
                    'start_label': start_label,
                    'end_label': end_label,
                    'bsm_label': bsm_label,
                    'clk_tick': clk_msg,
                })
                self.node.ports[port_name].tx_output(msg)
                log.debug(
                    f"[Controller] Sent clock tick to QPU_{qpu_id}, "
                    f"start_label={start_label}, end_label={end_label}, "
                    f"bsm_label={bsm_label}"
                )
            else:
                log.error(
                    f"[Controller] Port {port_name} not found on {self.node.name}"
                )

    # ── Process maps ─────────────────────────────────────────────────────────

    def process_ready_message(self, msg):
        """Process a ready message from a QPU and store it."""
        item = msg.items[0]
        recv_qpu = item.get('qpu_id')
        recv_type = item.get('type')
        start_label = item.get('start_label')
        end_label = item.get('end_label')

        if recv_type == 'start_ready' and start_label is not None:
            if start_label not in self.start_ready:
                self.start_ready[start_label] = set()
            self.start_ready[start_label].add(recv_qpu)
            self.waiting_qpus.add(recv_qpu)
            log.debug(
                f"[Controller] QPU_{recv_qpu} ready for start_label={start_label}"
            )
            return ('start', start_label, recv_qpu)

        elif recv_type == 'end_ready' and end_label is not None:
            if end_label not in self.end_ready:
                self.end_ready[end_label] = set()
            self.end_ready[end_label].add(recv_qpu)
            self.waiting_qpus.add(recv_qpu)
            log.debug(
                f"[Controller] QPU_{recv_qpu} ready for end_label={end_label}"
            )
            return ('end', end_label, recv_qpu)

        elif recv_type == 'done':
            self.finished_qpus.add(recv_qpu)
            log.debug(
                f"[Controller] QPU_{recv_qpu} done. "
                f"finished_qpus={self.finished_qpus} "
                f"({len(self.finished_qpus)}/{self.num_qpus})"
            )
            return ('done', None, recv_qpu)

        return (None, None, recv_qpu)

    def get_next_ready_process(self):
        """Find the next process (start or end) that has both parties ready."""

        def sort_key(label):
            if isinstance(label, str) and label.startswith("ent_"):
                try:
                    n = int(label[4:])
                except ValueError:
                    n = 0
                return (0, n, label)
            elif isinstance(label, int):
                return (1, label, "")
            else:
                return (2, 0, str(label))

        for label in sorted(self.start_qpus.keys(), key=sort_key):
            required = self.start_qpus[label]
            ready = self.start_ready.get(label, set())
            if required == ready:
                return (True, label)

        for label in sorted(self.end_qpus.keys()):
            required = self.end_qpus[label]
            ready = self.end_ready.get(label, set())
            if required == ready:
                return (False, label)

        return (None, None)

    # ── Schedule printing ────────────────────────────────────────────────────

    def compute_timeslot_schedule(self, qpu_commands, mapping_list):
        """Compute a timeslot schedule with commands aligned across QPUs."""
        map_name = create_mapper(mapping_list)
        qpu_ids = sorted(qpu_commands.keys())
        cursors = {qid: 0 for qid in qpu_ids}

        start_label_qpus = {}
        end_label_qpus = {}
        entanglement_label_qpus = {}
        for qid in qpu_ids:
            for cmd in qpu_commands[qid]:
                sl = cmd.get('start_label')
                el = cmd.get('end_label')
                if sl is not None:
                    start_label_qpus.setdefault(sl, set()).add(qid)
                if el is not None:
                    end_label_qpus.setdefault(el, set()).add(qid)
                ent_l = cmd.get('entanglement_label')
                if ent_l is not None and cmd['op'] == 'entanglement_gen':
                    entanglement_label_qpus.setdefault(ent_l, set()).add(qid)

        schedule = []

        def cmd_description(cmd):
            op = cmd['op']
            orig = cmd.get('original_qubits', [])
            sl = cmd.get('start_label') or cmd.get('target_start_label')
            el = cmd.get('end_label')
            if op == 'pre_entanglement':
                return f"PRE_ENTG (sl={sl})" if sl is not None else "PRE_ENTG"
            desc = f"{op} {', '.join(orig)}" if orig else op
            if sl is not None:
                desc += f" (sl={sl})"
            elif el is not None:
                desc += f" (el={el})"
            return desc

        def current_cmd(qid):
            idx = cursors[qid]
            cmds = qpu_commands[qid]
            return cmds[idx] if idx < len(cmds) else None

        def is_sync_cmd(cmd):
            if cmd is None:
                return False
            if cmd.get('start_label') is not None:
                return True
            if cmd.get('end_label') is not None:
                return True
            if (
                cmd.get('entanglement_label') is not None
                and cmd['op'] == 'entanglement_gen'
            ):
                return True
            return False

        max_iterations = sum(len(cmds) for cmds in qpu_commands.values()) * 2
        iteration = 0

        while any(cursors[qid] < len(qpu_commands[qid]) for qid in qpu_ids):
            iteration += 1
            if iteration > max_iterations:
                log.warning(
                    "[Controller] Timeslot scheduling exceeded max iterations, breaking."
                )
                break

            slot = {map_name(f"QPU_{qid}", to="site"): "" for qid in qpu_ids}
            advanced = set()
            sync_found = False

            current_start_labels = {}
            current_end_labels = {}
            current_ent_labels = {}

            for qid in qpu_ids:
                cmd = current_cmd(qid)
                if cmd is None:
                    continue
                sl = cmd.get('start_label')
                el = cmd.get('end_label')
                ent_l = cmd.get('entanglement_label')
                if ent_l is not None and cmd['op'] == 'entanglement_gen':
                    current_ent_labels.setdefault(ent_l, set()).add(qid)
                if sl is not None:
                    current_start_labels.setdefault(sl, set()).add(qid)
                if el is not None:
                    current_end_labels.setdefault(el, set()).add(qid)

            for label in sorted(current_ent_labels.keys()):
                required = entanglement_label_qpus.get(label, set())
                ready = current_ent_labels.get(label, set())
                if required == ready:
                    for qid in required:
                        cmd = current_cmd(qid)
                        site = map_name(f"QPU_{qid}", to="site")
                        slot[site] = cmd_description(cmd)
                        advanced.add(qid)
                    sync_found = True
                    break

            if not sync_found:
                for label in sorted(current_start_labels.keys()):
                    required = start_label_qpus.get(label, set())
                    ready = current_start_labels.get(label, set())
                    if required == ready:
                        for qid in required:
                            cmd = current_cmd(qid)
                            site = map_name(f"QPU_{qid}", to="site")
                            slot[site] = cmd_description(cmd)
                            advanced.add(qid)
                        sync_found = True
                        break

            if not sync_found:
                for label in sorted(current_end_labels.keys()):
                    required = end_label_qpus.get(label, set())
                    ready = current_end_labels.get(label, set())
                    if required == ready:
                        for qid in required:
                            cmd = current_cmd(qid)
                            site = map_name(f"QPU_{qid}", to="site")
                            slot[site] = cmd_description(cmd)
                            advanced.add(qid)
                        sync_found = True
                        break

            if not sync_found:
                for qid in qpu_ids:
                    cmd = current_cmd(qid)
                    if cmd is None:
                        continue
                    if is_sync_cmd(cmd):
                        continue
                    site = map_name(f"QPU_{qid}", to="site")
                    slot[site] = cmd_description(cmd)
                    advanced.add(qid)

                if not advanced:
                    for qid in qpu_ids:
                        cmd = current_cmd(qid)
                        if cmd is not None:
                            site = map_name(f"QPU_{qid}", to="site")
                            slot[site] = cmd_description(cmd)
                            advanced.add(qid)
                            break

            for qid in advanced:
                cursors[qid] += 1

            schedule.append(slot)

        return schedule

    def print_timeslot_schedule(self, schedule, mapping_list):
        """Print the timeslot schedule as a formatted table."""
        map_name = create_mapper(mapping_list)

        qpu_names = set()
        for slot in schedule:
            qpu_names.update(slot.keys())
        qpu_names = sorted(qpu_names)

        slot_col_width = max(len("Slot"), len(str(len(schedule) - 1))) + 2
        col_widths = {}
        for qpu in qpu_names:
            max_content = len(qpu)
            for slot in schedule:
                content = slot.get(qpu, "")
                max_content = max(max_content, len(content))
            col_widths[qpu] = max_content + 2

        total_width = slot_col_width + sum(col_widths.values())
        header = f"{'Slot':<{slot_col_width}}" + "".join(
            f"{qpu:<{col_widths[qpu]}}" for qpu in qpu_names
        )
        separator = "-" * total_width
        print(header)
        print(separator)

        for t, slot in enumerate(schedule):
            has_pre_entg = any(
                "PRE_ENTG" in slot.get(qpu, "") for qpu in qpu_names
            )
            has_start = any(
                "starting_process" in slot.get(qpu, "") for qpu in qpu_names
            )

            suffix = ""
            if has_pre_entg:
                suffix = "  ◄── PRE_ENTG"
            elif has_start:
                suffix = "  ◄── SYNC"

            row = (
                f"{t:<{slot_col_width}}"
                + "".join(
                    f"{slot.get(qpu, ''):<{col_widths[qpu]}}" for qpu in qpu_names
                )
                + suffix
            )
            print(row)

        print(separator)
        print(f"Total timeslots: {len(schedule)}")

    def _print_pre_ent_summary(self, stats):
        """Print a human-readable summary of pre-entanglement scheduling."""
        total = stats["total_pairs"]
        moved = stats["moved_pairs"]
        unmoved = stats["unmoved_pairs"]
        latency = stats["expected_latency_ns"]

        log.info("=" * 60)
        log.info("PRE-ENTANGLEMENT SCHEDULING SUMMARY")
        log.info("=" * 60)
        log.info(
            f"  Expected entanglement latency : {latency:,.0f} ns "
            f"({latency / 1e6:.3f} ms)"
        )
        log.info(f"  Total entanglement pairs      : {total}")
        log.info(f"  Pairs moved earlier           : {moved}")
        log.info(f"  Pairs not moved (at barrier)  : {unmoved}")
        if total > 0:
            log.info(
                f"  Move rate                     : "
                f"{moved / total * 100:.1f}%"
            )

        if stats["moves"]:
            log.info("-" * 60)
            log.info(
                f"  {'Label':<10} {'QPUs':<10} {'Pullback':>8} "
                f"{'Feasible':>12} {'Gate time (ns)':>20}"
            )
            log.info("-" * 60)
            total_gate_time = 0.0
            for m in stats["moves"]:
                qpus_str = f"{m['qpus'][0]},{m['qpus'][1]}"
                feas_str = f"[{m['feasible'][0]},{m['feasible'][1]}]"
                gt = m["gate_time_ns"]
                gt_str = f"[{gt[0]:,.0f}, {gt[1]:,.0f}]"
                effective_overlap = min(gt[0], gt[1])
                total_gate_time += effective_overlap
                log.info(
                    f"  {m['label']:<10} {qpus_str:<10} "
                    f"{m['pullback']:>8} {feas_str:>12} {gt_str:>20}"
                )

            avg_overlap = total_gate_time / len(stats["moves"])
            coverage = (avg_overlap / latency * 100) if latency > 0 else 0
            log.info("-" * 60)
            log.info(
                f"  Avg effective gate overlap    : {avg_overlap:,.0f} ns "
                f"({coverage:.1f}% of expected latency)"
            )
            log.info(
                f"  Total gate time overlapped    : {total_gate_time:,.0f} ns "
                f"({total_gate_time / 1e6:.3f} ms)"
            )
        log.info("=" * 60)

    # ── Main run loop ────────────────────────────────────────────────────────

    def run(self):
        log.debug(f"[{self.node.name}] Starting at time {ns.sim_time()}")

        circuit_cfg = getattr(self.cfg, 'circuit', None)

        if self._pre_labeled_commands is not None:
            # ── Fast path: pre-labeled commands supplied by the DQC plugin ────
            # Skip parse, validate, and label — the plugin has already done this.
            log.debug("[Controller] Using pre-labeled commands from DQC plugin")
            self.qpu_commands        = self._pre_labeled_commands
            self.start_qpus          = self._pre_process_maps['start_qpus']
            self.end_qpus            = self._pre_process_maps['end_qpus']
            self.entanglement_gen_labels = self._pre_process_maps['entanglement_gen_labels']
            self.start_ready = {k: set() for k in self.start_qpus}
            self.end_ready   = {k: set() for k in self.end_qpus}
        else:
            # ── Normal path: parse → validate → label ────────────────────────
            if self.frontend is not None:
                frontend = self.frontend
            else:
                frontend, _ = load_frontend(circuit_cfg)
            qpu_info = {
                i: {'num_qubits': qpu_node.qmemory.num_positions}
                for i, qpu_node in enumerate(self.qpu_nodes, start=1)
            }
            parsed = frontend.parse(qpu_info)

            # ── Validate parsed commands against the instruction-set registry ──
            from qnpack.dqc.models.validation import validate_commands
            validation_errors = validate_commands(parsed)
            if validation_errors:
                for ve in validation_errors:
                    if ve.severity == "error":
                        log.error(str(ve))
                    else:
                        log.warning(str(ve))
                hard_errors = [ve for ve in validation_errors if ve.severity == "error"]
                if hard_errors:
                    raise ValueError(
                        f"Circuit validation failed with {len(hard_errors)} error(s) "
                        f"(and {len(validation_errors) - len(hard_errors)} warning(s)). "
                        f"See log output above for details."
                    )

            for qpu_id, commands in parsed.items():
                self.qpu_commands[qpu_id] = commands

            # ── Label commands and build process maps ─────────────────────────
            labeled, process_maps = label_and_build_maps(self.qpu_commands)
            self.qpu_commands = labeled
            self.start_qpus              = process_maps['start_qpus']
            self.end_qpus                = process_maps['end_qpus']
            self.entanglement_gen_labels = process_maps['entanglement_gen_labels']
            self.start_ready = {k: set() for k in self.start_qpus}
            self.end_ready   = {k: set() for k in self.end_qpus}

        if getattr(self.cfg.circuit, 'pre_schedule_entanglement', False):
            expected_latency = getattr(
                self.cfg.circuit, 'expected_ent_latency_ns', 0
            )
            stats = insert_pre_entanglement_commands(
                self.qpu_commands,
                expected_ent_latency_ns=expected_latency,
            )
            self._print_pre_ent_summary(stats)

        self.active_qpu_ids = set(self.qpu_commands.keys())
        self.num_active_qpus = len(self.active_qpu_ids)
        log.debug(
            f"[Controller] Active QPUs (have commands): {self.active_qpu_ids} "
            f"({self.num_active_qpus}/{self.num_qpus} total)"
        )

        if self.run_idx == 0:
            with open("qpu_partitioned_commands.json", "w") as f:
                json.dump(self.qpu_commands, f, indent=2)
            log.debug("Saved all QPU commands to qpu_partitioned_commands.json")

            schedule = self.compute_timeslot_schedule(
                self.qpu_commands, self.mapping_list
            )
            self.print_timeslot_schedule(schedule, self.mapping_list)

        for qpu_id, commands in self.qpu_commands.items():
            self.send_commands_to_qpu(qpu_id, commands)

        log.debug(">>> Starting execution <<<")

        while (
            self.start_qpus
            or self.end_qpus
            or len(self.finished_qpus) < self.num_active_qpus
        ):
            log.debug(
                f"[Controller] Loop top: finished={self.finished_qpus}, "
                f"need={self.num_active_qpus}, waiting={self.waiting_qpus}"
            )

            # Drain all buffered messages
            found_buffered = True
            while found_buffered:
                found_buffered = False
                for qpu_id in self.active_qpu_ids:
                    port_name = f"comm{qpu_id}_port"
                    if port_name in self.node.ports:
                        while True:
                            msg = self.node.ports[port_name].rx_input()
                            if msg is None:
                                break
                            self.process_ready_message(msg)
                            found_buffered = True

            if (
                not self.start_qpus
                and not self.end_qpus
                and len(self.finished_qpus) >= self.num_active_qpus
            ):
                break

            is_start, label = self.get_next_ready_process()

            if is_start is not None:
                if is_start:
                    qpus_involved = self.start_qpus[label]

                    pair = frozenset(qpus_involved)
                    bsm_entry = self.qpu_pair_to_bsm.get(pair)
                    bsm_label = bsm_entry[1] if bsm_entry else None

                    needs_bsm = label in self.entanglement_gen_labels
                    label_type = (
                        "entanglement_gen" if needs_bsm else "starting_process"
                    )
                    log.debug(
                        f">>> Executing {label_type} {label} with "
                        f"QPUs {qpus_involved}, BSM={bsm_label} <<<"
                    )

                    yield from self.send_clock_tick_to_all(
                        qpus_involved, start_label=label, bsm_label=bsm_label
                    )
                    for qpu_id in qpus_involved:
                        self.waiting_qpus.discard(qpu_id)

                    if needs_bsm:
                        self.send_start_entanglement_to_bsm(
                            qpus_involved, start_label=label
                        )

                    self.start_ready[label] = set()
                    del self.start_qpus[label]
                else:
                    qpus_involved = self.end_qpus[label]
                    log.debug(
                        f">>> Executing ending_process {label} with "
                        f"QPUs {qpus_involved} <<<"
                    )

                    yield from self.send_clock_tick_to_all(
                        qpus_involved, end_label=label
                    )
                    for qpu_id in qpus_involved:
                        self.waiting_qpus.discard(qpu_id)

                    self.end_ready[label] = set()
                    del self.end_qpus[label]

                continue

            # No ready process — wait for QPU messages
            log.debug(
                f"[Controller] No ready process. "
                f"finished={len(self.finished_qpus)}/{self.num_active_qpus} "
                f"start_qpus={list(self.start_qpus.keys())[:10]}, "
                f"start_ready={dict((k, v) for k, v in self.start_ready.items() if v)}"
            )
            ev_expr = None
            for qpu_id in self.active_qpu_ids:
                port_name = f"comm{qpu_id}_port"
                if port_name in self.node.ports:
                    port = self.node.ports[port_name]
                    ev_expr = (
                        self.await_port_input(port)
                        if ev_expr is None
                        else ev_expr | self.await_port_input(port)
                    )

            yield ev_expr
            log.debug(f"[Controller] Woke up at time={ns.sim_time()}")

            drain_round = 0
            while True:
                any_found = False
                for qpu_id in self.active_qpu_ids:
                    port_name = f"comm{qpu_id}_port"
                    if port_name in self.node.ports:
                        while True:
                            msg = self.node.ports[port_name].rx_input()
                            if msg is None:
                                break
                            result = self.process_ready_message(msg)
                            log.debug(
                                f"[Controller] Drained from {port_name}: {result}"
                            )
                            any_found = True
                drain_round += 1
                if not any_found:
                    break
            log.debug(
                f"[Controller] After drain: drain_rounds={drain_round}"
            )

        if self.clk.is_running:
            self.clk.stop()
        log.debug(f"[{self.node.name}] All QPUs done at {ns.sim_time()}")
        self.send_signal(Signals.SUCCESS)
