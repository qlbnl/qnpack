"""
labeling/base.py
----------------
Scans labeled per-QPU command dicts and builds the three maps that the
controller needs to coordinate entanglement and EJPP processes:

    start_qpus  : label → set of QPU IDs that participate in that start event
    end_qpus    : label → set of QPU IDs that participate in that end event
    entanglement_gen_labels : set of all entanglement_label values seen on
                              entanglement_gen commands
"""

import logging

log = logging.getLogger(__name__)


def build_process_maps(qpu_commands: dict) -> dict:
    """Build mappings of start_label/end_label → set of QPU IDs involved.

    Parameters
    ----------
    qpu_commands : dict
        ``{qpu_id: [cmd_dict, ...]}`` — already labeled by a labeler.

    Returns
    -------
    dict with keys:
        ``start_qpus``             – ``{label: set(qpu_ids)}``
        ``end_qpus``               – ``{label: set(qpu_ids)}``
        ``entanglement_gen_labels`` – ``set(labels)``
    """
    entanglement_gen_labels: set = set()
    start_qpus: dict = {}
    end_qpus: dict = {}

    for qpu_id, cmds in qpu_commands.items():
        for cmd in cmds:
            start_label = cmd.get('start_label')
            end_label   = cmd.get('end_label')
            ent_label   = cmd.get('entanglement_label')

            if ent_label is not None and cmd['op'] == 'entanglement_gen':
                entanglement_gen_labels.add(ent_label)
                if ent_label not in start_qpus:
                    start_qpus[ent_label] = set()
                start_qpus[ent_label].add(qpu_id)

            if start_label is not None:
                if start_label not in start_qpus:
                    start_qpus[start_label] = set()
                start_qpus[start_label].add(qpu_id)

            if end_label is not None:
                if end_label not in end_qpus:
                    end_qpus[end_label] = set()
                end_qpus[end_label].add(qpu_id)

    log.debug(f"[build_process_maps] start_qpus: {start_qpus}")
    log.debug(f"[build_process_maps] end_qpus: {end_qpus}")
    log.debug(f"[build_process_maps] entanglement_gen_labels: {entanglement_gen_labels}")

    return {
        'start_qpus':              start_qpus,
        'end_qpus':                end_qpus,
        'entanglement_gen_labels': entanglement_gen_labels,
    }
