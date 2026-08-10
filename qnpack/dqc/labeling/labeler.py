"""
labeling/labeler.py
-------------------
Unified labeler for DQC commands.

This module provides a single labeling function that processes commands based
on their operation types, not their source.

The labeler:
  1. Assigns entanglement_label to entanglement_gen pairs (emitter + peer)
  2. Assigns start_label to ejpp_start / ejpp_start_link pairs
  3. Assigns end_label to ejpp_end / ejpp_end_link pairs
  4. Handles msg_exchange for cross-QPU classical communication
  5. Inserts entanglement_gen commands for ejpp operations when needed
"""

import logging
from collections import defaultdict

log = logging.getLogger(__name__)


def label_commands(qpu_commands: dict) -> dict:
    """Label per-QPU commands based on operation types.

    This unified labeler processes all command types regardless of their source.
    It examines the commands and applies appropriate
    labeling based on the operation types present.

    Parameters
    ----------
    qpu_commands : dict
        ``{qpu_id: [cmd_dict, ...]}`` as returned by any frontend's parse().

    Returns
    -------
    dict
        A new ``{qpu_id: [cmd_dict, ...]}`` with all labels assigned and
        entanglement_gen commands inserted where needed.
    """
    # Build a fresh copy so we don't mutate the input
    new_commands: dict = {
        qpu_id: [] for qpu_id in qpu_commands
    }

    # Check if we have ejpp operations (need special handling)
    has_ejpp = _has_ejpp_operations(qpu_commands)

    if has_ejpp:
        # Process ejpp operations: assign labels and insert entanglement_gen
        new_commands = _process_ejpp_commands(qpu_commands)
    else:
        # Copy commands as-is for non-ejpp processing
        for qpu_id, cmds in qpu_commands.items():
            new_commands[qpu_id] = [dict(cmd) for cmd in cmds]

    # Label entanglement_gen pairs (for both ejpp and non-ejpp modes)
    _label_entanglement_pairs(new_commands)

    # Handle cross-QPU classical communication (msg_exchange)
    _label_msg_exchange(new_commands)

    return new_commands


# ---------------------------------------------------------------------------
# EJPP Detection
# ---------------------------------------------------------------------------

def _has_ejpp_operations(qpu_commands: dict) -> bool:
    """Return True if any command has ejpp operations."""
    for cmds in qpu_commands.values():
        for cmd in cmds:
            if cmd.get('op') in ('ejpp_start', 'ejpp_end',
                                 'ejpp_start_link', 'ejpp_end_link'):
                return True
    return False


# ---------------------------------------------------------------------------
# EJPP Processing 
# ---------------------------------------------------------------------------

def _process_ejpp_commands(qpu_commands: dict) -> dict:
    """Process ejpp commands: assign labels and insert entanglement_gen pairs.

    This handles ejpp_start, ejpp_end, ejpp_start_link, ejpp_end_link operations.
    """
    # ── Pass 1: build global label maps ──────────────────────────────────────
    ejpp_start_events = []
    for qpu_id in sorted(qpu_commands.keys()):
        for cmd in qpu_commands[qpu_id]:
            if cmd.get('op') == 'ejpp_start':
                ejpp_start_events.append((qpu_id, cmd))

    pair_occurrence: dict = {}
    start_label_map: dict = {}   # (data_qpu_id, link_qpu_id, occ) → int
    ent_label_map:   dict = {}   # (data_qpu_id, link_qpu_id, occ) → "ent_N"
    starting_process_counter = 0
    entanglement_counter = 0

    for data_qpu_id, cmd in ejpp_start_events:
        link_qpu_id = cmd.get('link_qpu_id')
        key = (data_qpu_id, link_qpu_id)
        occ = pair_occurrence.get(key, 0)
        pair_occurrence[key] = occ + 1
        start_label_map[(data_qpu_id, link_qpu_id, occ)] = starting_process_counter
        ent_label_map[(data_qpu_id, link_qpu_id, occ)]   = f"ent_{entanglement_counter}"
        starting_process_counter += 1
        entanglement_counter += 1

    # Similarly for ejpp_end
    ejpp_end_events = []
    for qpu_id in sorted(qpu_commands.keys()):
        for cmd in qpu_commands[qpu_id]:
            if cmd.get('op') == 'ejpp_end':
                ejpp_end_events.append((qpu_id, cmd))

    pair_occ_end: dict = {}
    end_label_map: dict = {}   # (data_qpu_id, link_qpu_id, occ) → int
    ending_process_counter = 0

    for data_qpu_id, cmd in ejpp_end_events:
        link_qpu_id = cmd.get('link_qpu_id')
        key = (data_qpu_id, link_qpu_id)
        occ = pair_occ_end.get(key, 0)
        pair_occ_end[key] = occ + 1
        end_label_map[(data_qpu_id, link_qpu_id, occ)] = ending_process_counter
        ending_process_counter += 1

    # ── Pass 2: rebuild each QPU's command list independently ────────────────
    new_commands: dict = {qpu_id: [] for qpu_id in qpu_commands}

    for qpu_id in sorted(qpu_commands.keys()):
        # Per-QPU occurrence counters
        pair_occ_start_data: dict = {}
        pair_occ_start_link: dict = {}
        pair_occ_end_data:   dict = {}
        pair_occ_end_link:   dict = {}

        for cmd in qpu_commands[qpu_id]:
            op = cmd.get('op')

            # ── ejpp_start (data side) ────────────────────────────────────
            if op == 'ejpp_start':
                data_qpu_id    = qpu_id
                link_qpu_id    = cmd['link_qpu_id']
                key            = (data_qpu_id, link_qpu_id)
                occ            = pair_occ_start_data.get(key, 0)
                pair_occ_start_data[key] = occ + 1

                start_label    = start_label_map[(data_qpu_id, link_qpu_id, occ)]
                ent_label      = ent_label_map[(data_qpu_id, link_qpu_id, occ)]

                data_local     = cmd.get('data_qubit', cmd.get('qubit'))
                l_local        = cmd.get('l_local', 0)
                link_qubit_idx = cmd.get('link_qubit_idx', 0)
                original_qubits = cmd.get('original_qubits', [])

                # entanglement_gen emitter on this (data) QPU
                new_commands[qpu_id].append({
                    "op":                 "entanglement_gen",
                    "role":               "emitter",
                    "params":             [],
                    "qubits":             [l_local],
                    "data_qubit":         data_local,
                    "l_local":            l_local,
                    "original_qubits":    original_qubits,
                    "is_remote":          True,
                    "peer_qpu_id":        link_qpu_id,
                    "peer_qubit":         link_qubit_idx,
                    "entanglement_label": ent_label,
                    "target_start_label": start_label,
                    "start_label":        None,
                    "end_label":          None,
                })

                # labeled ejpp_start on this (data) QPU
                new_commands[qpu_id].append({
                    **cmd,
                    "start_label": start_label,
                    "label":       f"ejpp_start_{start_label}",
                    "clbit":       start_label,
                })

            # ── ejpp_start_link (link side) ───────────────────────────────
            elif op == 'ejpp_start_link':
                data_qpu_id    = cmd.get('data_qpu_id')
                link_qpu_id    = qpu_id
                key            = (data_qpu_id, link_qpu_id)
                occ            = pair_occ_start_link.get(key, 0)
                pair_occ_start_link[key] = occ + 1

                start_label = start_label_map.get((data_qpu_id, link_qpu_id, occ))
                ent_label   = ent_label_map.get((data_qpu_id, link_qpu_id, occ))

                if start_label is None:
                    log.warning(
                        f"[labeler] ejpp_start_link on QPU {qpu_id}: "
                        f"no start_label for (data={data_qpu_id}, link={link_qpu_id}, occ={occ})"
                    )
                    new_commands[qpu_id].append(cmd)
                    continue

                link_qubit_idx = cmd.get('link_qubit_idx', cmd.get('qubit', 0))
                l_local        = cmd.get('l_local', link_qubit_idx)
                original_qubits = cmd.get('original_qubits', [])

                # entanglement_gen peer on this (link) QPU
                new_commands[qpu_id].append({
                    "op":                 "entanglement_gen",
                    "role":               "peer",
                    "params":             [],
                    "qubits":             [link_qubit_idx],
                    "original_qubits":    original_qubits,
                    "is_remote":          True,
                    "peer_qpu_id":        data_qpu_id,
                    "peer_qubit":         l_local,
                    "entanglement_label": ent_label,
                    "target_start_label": start_label,
                    "start_label":        None,
                    "end_label":          None,
                })

                # labeled ejpp_start_link on this (link) QPU
                new_commands[qpu_id].append({
                    **cmd,
                    "start_label": start_label,
                    "label":       f"ejpp_start_link_{start_label}",
                    "clbit":       start_label,
                })

            # ── ejpp_end (data side) ──────────────────────────────────────
            elif op == 'ejpp_end':
                data_qpu_id = qpu_id
                link_qpu_id = cmd.get('link_qpu_id', cmd.get('peer_qpu_id'))
                key         = (data_qpu_id, link_qpu_id)
                occ         = pair_occ_end_data.get(key, 0)
                pair_occ_end_data[key] = occ + 1

                end_label = end_label_map.get((data_qpu_id, link_qpu_id, occ))
                if end_label is None:
                    log.warning(
                        f"[labeler] ejpp_end on QPU {qpu_id}: "
                        f"no end_label for (data={data_qpu_id}, link={link_qpu_id}, occ={occ})"
                    )
                    new_commands[qpu_id].append(cmd)
                    continue

                new_commands[qpu_id].append({
                    **cmd,
                    "end_label": end_label,
                    "label":     f"ejpp_end_{end_label}",
                    "clbit":     end_label,
                })

            # ── ejpp_end_link (link side) ─────────────────────────────────
            elif op == 'ejpp_end_link':
                data_qpu_id = cmd.get('data_qpu_id')
                link_qpu_id = qpu_id
                key         = (data_qpu_id, link_qpu_id)
                occ         = pair_occ_end_link.get(key, 0)
                pair_occ_end_link[key] = occ + 1

                end_label = end_label_map.get((data_qpu_id, link_qpu_id, occ))
                if end_label is None:
                    log.warning(
                        f"[labeler] ejpp_end_link on QPU {qpu_id}: "
                        f"no end_label for (data={data_qpu_id}, link={link_qpu_id}, occ={occ})"
                    )
                    new_commands[qpu_id].append(cmd)
                    continue

                new_commands[qpu_id].append({
                    **cmd,
                    "end_label": end_label,
                    "label":     f"ejpp_end_link_{end_label}",
                    "clbit":     end_label,
                })

            # ── All other commands — pass through unchanged ────────────────
            else:
                new_commands[qpu_id].append(cmd)

    return new_commands


# ---------------------------------------------------------------------------
# Entanglement Labeling
# ---------------------------------------------------------------------------

def _label_entanglement_pairs(new_commands: dict) -> None:
    """Assign entanglement_label to emitter/peer entanglement_gen pairs.

    Mutates new_commands in place. Only labels pairs that don't already have
    an entanglement_label (ejpp processing may have already assigned them).
    """
    entanglement_counter = 0

    for qpu_id in sorted(new_commands.keys()):
        for cmd in new_commands[qpu_id]:
            if (cmd.get('op') == 'entanglement_gen' 
                and cmd.get('role') == 'emitter'
                and cmd.get('entanglement_label') is None):
                
                label = entanglement_counter
                entanglement_counter += 1

                cmd['entanglement_label'] = label

                peer_qpu_id   = cmd.get('peer_qpu_id')
                emitter_qubit = cmd.get('qubit', cmd.get('qubits', [None])[0])

                if peer_qpu_id is not None and peer_qpu_id in new_commands:
                    _label_matching_peer(
                        new_commands[peer_qpu_id],
                        qpu_id,
                        emitter_qubit,
                        label,
                    )


def _label_matching_peer(
    peer_cmd_list: list,
    emitter_qpu_id: int,
    emitter_qubit: int,
    label: int,
) -> None:
    """Find the peer entanglement_gen command and assign label to it."""
    # First try: match by peer_qpu_id and peer_qubit
    for cmd in peer_cmd_list:
        if (
            cmd.get('op') == 'entanglement_gen'
            and cmd.get('role') == 'peer'
            and cmd.get('peer_qpu_id') == emitter_qpu_id
            and cmd.get('peer_qubit') == emitter_qubit
            and cmd.get('entanglement_label') is None
        ):
            cmd['entanglement_label'] = label
            return

    # Fallback: match by peer_qpu_id alone (first unlabeled peer)
    for cmd in peer_cmd_list:
        if (
            cmd.get('op') == 'entanglement_gen'
            and cmd.get('role') == 'peer'
            and cmd.get('peer_qpu_id') == emitter_qpu_id
            and cmd.get('entanglement_label') is None
        ):
            cmd['entanglement_label'] = label
            return

    log.warning(
        f"[labeler] Could not find peer entanglement_gen for "
        f"emitter on QPU_{emitter_qpu_id} qubit {emitter_qubit}"
    )


# ---------------------------------------------------------------------------
# Message Exchange Labeling
# ---------------------------------------------------------------------------

def _clbit_owner_qpu(clbit_name: str):
    """Extract the QPU id encoded in a clbit name like _clbit_comm_qubit2_1."""
    import re
    m = re.match(r'_clbit_comm_qubit(\d+)_', clbit_name or '')
    if m:
        return int(m.group(1))
    return None


def _label_msg_exchange(new_commands: dict) -> None:
    """Replace cross-QPU if_gate commands with msg_sender/msg_receiver pairs.

    Mutates new_commands in place.
    """
    # Index: clbit_name -> [(qpu_id, cmd_index), ...] for measure commands
    clbit_measure_lists: dict = defaultdict(list)
    for qpu_id, cmds in new_commands.items():
        for idx, cmd in enumerate(cmds):
            if cmd.get('op') == 'measure' and cmd.get('clbit'):
                clbit_measure_lists[cmd['clbit']].append((qpu_id, idx))

    # Index: clbit_name -> [(qpu_id, cmd_index), ...] for cross-QPU if_gate commands
    clbit_ifgate_lists: dict = defaultdict(list)
    for qpu_id, cmds in new_commands.items():
        for idx, cmd in enumerate(cmds):
            if cmd.get('op') == 'if_gate':
                clbit_name = cmd.get('clbit')
                owner_qpu  = _clbit_owner_qpu(clbit_name)
                if owner_qpu is not None and owner_qpu != qpu_id:
                    clbit_ifgate_lists[clbit_name].append((qpu_id, idx))

    total_cross_qpu = sum(len(v) for v in clbit_ifgate_lists.values())
    if total_cross_qpu == 0:
        return

    log.debug(f"[labeler] Found {total_cross_qpu} cross-QPU if_gate commands")

    exchange_label_counter = 0

    for clbit_name in sorted(
        set(clbit_measure_lists.keys()) & set(clbit_ifgate_lists.keys())
    ):
        measures = sorted(
            clbit_measure_lists[clbit_name],
            key=lambda x: new_commands[x[0]][x[1]].get('global_idx', 0),
        )
        if_gates = sorted(
            clbit_ifgate_lists[clbit_name],
            key=lambda x: new_commands[x[0]][x[1]].get('global_idx', 0),
        )

        n_pairs = min(len(measures), len(if_gates))
        if n_pairs < len(if_gates):
            log.warning(
                f"[labeler] clbit {clbit_name}: {len(if_gates)} cross-QPU "
                f"if_gates but only {len(measures)} measures — "
                f"{len(if_gates) - n_pairs} unmatched"
            )

        for k in range(n_pairs):
            meas_qpu, meas_idx = measures[k]
            if_qpu,  if_idx   = if_gates[k]

            exchange_label = f"msg_exchange_{exchange_label_counter}"
            exchange_label_counter += 1

            if_cmd   = new_commands[if_qpu][if_idx]
            meas_cmd = new_commands[meas_qpu][meas_idx]

            if_global_idx = if_cmd.get('global_idx', 0)

            # Append msg_sender to the measuring QPU's command list
            new_commands[meas_qpu].append({
                'op':              'msg_sender',
                'label':           exchange_label,
                'msg_type':        'msg_exchange',
                'clbit':           meas_cmd['clbit'],
                'qubit':           meas_cmd.get('qubit'),
                'qubits':          meas_cmd.get('qubits', []),
                'original_qubits': meas_cmd.get('original_qubits', []),
                'params':          [],
                'peer_qpu_id':     if_qpu,
                'is_remote':       True,
                'final_key':       None,
                'start_label':     None,
                'end_label':       exchange_label,
                'if_gate':         None,
                'global_idx':      if_global_idx,
            })

            # Replace the if_gate with msg_receiver in place
            new_commands[if_qpu][if_idx] = {
                'op':              'msg_receiver',
                'label':           exchange_label,
                'msg_type':        'msg_exchange',
                'clbit':           if_cmd.get('clbit'),
                'qubit':           if_cmd.get('qubit'),
                'qubits':          if_cmd.get('qubits', []),
                'original_qubits': if_cmd.get('original_qubits', []),
                'params':          [],
                'peer_qpu_id':     meas_qpu,
                'is_remote':       True,
                'final_key':       None,
                'start_label':     None,
                'end_label':       exchange_label,
                'if_gate': {
                    'gate':   if_cmd.get('gate'),
                    'qubit':  if_cmd.get('qubit'),
                    'qubits': if_cmd.get('qubits', []),
                    'params': if_cmd.get('params', []),
                    'clbit':  if_cmd.get('clbit'),
                } if if_cmd.get('gate') else None,
                'global_idx': if_global_idx,
            }

            log.debug(
                f"[labeler] Created msg_sender/msg_receiver pair: "
                f"sender=QPU_{meas_qpu}(measure {clbit_name}[{k}]), "
                f"receiver=QPU_{if_qpu}(if_gate {clbit_name}[{k}]), "
                f"label={exchange_label}"
            )

    # Re-sort each QPU's command list after appending msg_sender commands
    for qpu_id in new_commands:
        new_commands[qpu_id].sort(key=lambda x: x.get('global_idx', 0))
