"""
labeling/__init__.py
--------------------
Public API for the labeling package.

Single entry point: ``label_and_build_maps(qpu_commands)``

  1. Labels commands based on their operation types.
  2. Assigns entanglement_label to entanglement_gen pairs.
  3. Assigns start_label/end_label to ejpp operations when present.
  4. Handles cross-QPU classical communication (msg_exchange).
  5. Calls ``build_process_maps()`` to build the coordinator maps needed by
     ``ControllerProtocol``.

Returns ``(labeled_qpu_commands, process_maps)`` where ``process_maps`` is::

    {
        'start_qpus':              {label: set(qpu_ids)},
        'end_qpus':                {label: set(qpu_ids)},
        'entanglement_gen_labels': set(labels),
    }
"""

from .base    import build_process_maps
from .labeler import label_commands

__all__ = [
    "label_and_build_maps",
    "build_process_maps",
    "label_commands",
]


def label_and_build_maps(qpu_commands: dict) -> tuple:
    """Label commands and build process maps.

    Uses a unified labeler that processes commands based on their operation
    types, not their source (tket, qasm, cisco, etc.). The labeler examines
    the commands and applies appropriate labeling automatically.

    Parameters
    ----------
    qpu_commands : dict
        ``{qpu_id: [cmd_dict, ...]}`` as returned by any frontend's ``parse()``.

    Returns
    -------
    tuple
        ``(labeled_qpu_commands, process_maps)``

        - ``labeled_qpu_commands`` – ``{qpu_id: [cmd_dict, ...]}`` with all
          labels assigned and ``entanglement_gen`` pairs inserted where needed.
        - ``process_maps`` – dict with keys ``start_qpus``, ``end_qpus``,
          ``entanglement_gen_labels``.
    """
    labeled = label_commands(qpu_commands)
    process_maps = build_process_maps(labeled)
    return labeled, process_maps
