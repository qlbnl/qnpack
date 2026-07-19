"""
frontends/base.py
-----------------
Abstract base class for all DQC circuit frontends.

Concrete shared behaviour lives here so that TketFrontend and QASM3Frontend
only implement what is genuinely different between them.
"""

from abc import ABC, abstractmethod
import logging

log = logging.getLogger(__name__)


class BaseFrontend(ABC):
    """Abstract base class for all DQC circuit frontends.

    A frontend accepts a circuit source and returns the canonical
    per-QPU command dict.  All mode-specific parsing logic lives in
    the frontend subclass; nothing leaks into ControllerProtocol or
    QPUProtocol.

    Canonical IR
    ------------
    The returned dict maps ``qpu_id`` (int) → ``list[cmd]`` where each
    ``cmd`` is a plain dict with at least::

        {
            'op':              str,          # canonical op name
            'qubits':          list[int],
            'params':          list[float],
            'original_qubits': list[str],
            'is_remote':       bool,
            'start_label':     int | str | None,
            'end_label':       int | str | None,
        }

    Canonical op names
    ------------------
    Local gates   : ``'h'``, ``'x'``, ``'z'``, ``'rz'``, ``'rx'``, ``'ry'``,
                    ``'cx'``, ``'ccx'``, …
    Entanglement  : ``'entanglement_gen'``
    EJPP start    : ``'ejpp_start'``       (data side)
                    ``'ejpp_start_link'``  (link/comm side)
    EJPP end      : ``'ejpp_end'``         (data side)
                    ``'ejpp_end_link'``    (link/comm side)
    Measurement   : ``'measure'``, ``'measure_final'``
    Classical msg : ``'msg_sender'``, ``'msg_receiver'``
    """

    # ── Source management ────────────────────────────────────────────────────

    def load(self, source):
        """Ingest a circuit source (file path, Circuit object, …).

        The default implementation simply stores *source* as ``self._source``.
        Subclasses that need to pre-scan the source (e.g. QASM3Frontend reads
        qubit declarations) should override this method and call ``super().load(source)``
        first.

        Parameters
        ----------
        source : str | object
            Path to a circuit file, a pytket Circuit, or any other
            frontend-specific source representation.
        """
        self._source = source

    # ── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def parse(self, qpu_info=None):
        """Parse the previously loaded source and return the canonical per-QPU
        command dict.

        The source must have been ingested via :meth:`load` before calling
        this method.

        Parameters
        ----------
        qpu_info : dict | None
            QPU topology metadata (comm qubit counts, etc.).

        Returns
        -------
        dict[int, list[dict]]
            ``{qpu_id: [cmd, …]}`` using canonical op names.
        """

    @property
    @abstractmethod
    def needs_datacollector(self):
        """``True`` when the frontend requires a NetSquid DataCollector to
        harvest results (tket-Circuit mode); ``False`` when results are read
        directly from QPU protocol state after the run."""

    # ── Output-register metadata ─────────────────────────────────────────────

    @property
    def num_output_bits(self):
        """Number of output bits in the result register (default 0)."""
        return getattr(self, '_num_output_bits', 0)

    @property
    def output_reg_name(self):
        """Name of the output classical register (default ``'m'``)."""
        return getattr(self, '_output_reg_name', 'm')

    # ── Result helpers (shared concrete implementations) ─────────────────────

    def get_measure_qubits(self, extra_context=None):
        """Return the ``measure_qubits`` mapping, or ``None`` if unavailable.

        The default returns ``None``; subclasses override when they can
        provide a ``{qpu_id: [qubit_pos, …]}`` mapping.

        Parameters
        ----------
        extra_context : dict | None
            Optional caller-supplied context (e.g. tket passes
            ``{'measure_qubits': …}`` here).
        """
        return None

    def get_col_names(self, measure_qubits=None):
        """Return ordered column names for the output register.

        For the ``'m'`` register (Qiskit little-endian convention) the
        indices are reversed so that index 0 is the LSB, e.g.
        ``["m_3", "m_2", "m_1", "m_0"]`` for a 4-bit register.  For any
        other register name the natural order is used.

        Parameters
        ----------
        measure_qubits : dict | None
            Ignored by the default implementation; subclasses may use it
            to derive column names from qubit positions.

        Returns
        -------
        list[str]
        """
        n = self.num_output_bits
        reg = self.output_reg_name
        if reg == 'm':
            order = reversed(range(n))
        else:
            order = range(n)
        return [f"{reg}_{i}" for i in order]

    def get_bitstring(self, row, col_names):
        log.debug(f"[BaseFrontend] get_bitstring: row={row}, col_names={col_names}")
        """Convert a result row dict into a bitstring.

        Parameters
        ----------
        row : dict
            As returned by :meth:`get_result_row` or a DataCollector.
        col_names : list[str]
            Column order (as returned by :meth:`get_col_names`).

        Returns
        -------
        str
            E.g. ``"0110"``; ``"?"`` for any missing column.
        """
        return "".join(
            str(int(row[c])) if row.get(c) is not None else "?"
            for c in col_names
        )

    def _collect_qpu_results(self, protocol):
        """Collect a merged ``{key: value}`` dict from all QPU sub-protocols.

        Searches every sub-protocol that exposes ``final_measurements`` and
        ``classical_memory``.  ``final_measurements`` always wins over
        ``classical_memory`` for the same key.

        Parameters
        ----------
        protocol : DQCProtocol
            The top-level protocol whose sub-protocols hold QPU state.

        Returns
        -------
        dict
        """
        merged = {}
        for proto in protocol.subprotocols.values():
            cm = getattr(proto, 'classical_memory', {})
            fm = getattr(proto, 'final_measurements', {})
            for k, v in cm.items():
                if k not in merged:
                    merged[k] = v
            for k, v in fm.items():
                merged[k] = v  # final_measurements always wins
        return merged

    def get_result_row(self, protocol, run_idx, col_names, qpu_nodes):
        """Return a result row dict from QPU protocol state.

        Uses :meth:`_collect_qpu_results` to gather measurements from all
        QPU sub-protocols, then maps *col_names* to their values.

        Parameters
        ----------
        protocol : DQCProtocol
            The top-level protocol.
        run_idx : int
            Simulation run index (stored as ``"run"`` in the returned row).
        col_names : list[str]
            Column names to collect.
        qpu_nodes : list
            List of QPU nodes (used only for logging / compat; not required
            for result collection).

        Returns
        -------
        dict
            ``{"run": run_idx, "m_0": value, …}`` with ``None`` for any key
            not found in any QPU's state.
        """
        merged = self._collect_qpu_results(protocol)
        log.debug(f"[{type(self).__name__}] get_result_row merged keys={list(merged.keys())}")
        row = {"run": run_idx}
        for key in col_names:
            row[key] = int(merged[key]) if key in merged else None
        log.debug(f"[{type(self).__name__}] get_result_row: col_names={col_names} → row={row}")
        return row
