"""
frontends/qasm3_frontend.py
---------------------------
QASM3Frontend: parser using openqasm3 AST — converts a QASM 3.0 file into the
canonical per-QPU command IR. All labeling (entanglement_label, msg_exchange
labels) is performed by the labeling layer (labeling/qasm_labeler.py).

Op names emitted (canonical):
    entanglement_gen  — Bell-pair generation (entanglement_label=None)
    measure           — intermediate measurement to classical bit
    if_gate           — conditional gate (cross-QPU clbit; labeling converts
                        these to msg_sender / msg_receiver pairs)
    measure_final     — final output measurement
    gate              — local single- or two-qubit gate
"""

import logging
from collections import OrderedDict
from openqasm3 import ast
from openqasm3.parser import parse
from openqasm3.visitor import QASMVisitor

from .base import BaseFrontend
from .util import DATA_REGION_START

log = logging.getLogger(__name__)


class QASM3CommandExtractor(QASMVisitor):
    """
    AST visitor that extracts commands and organizes them by QPU.
    """
    
    def __init__(self, output_reg_name='m'):
        self.qpu_commands = {}
        self.qubit_to_qpu = {}  # Maps qubit names to QPU IDs
        self.measure_qubits = OrderedDict()
        self.num_output_bits = 0
        self.output_reg_name = output_reg_name
        self.global_idx = 0
        super().__init__()
    
    def visit_QubitDeclaration(self, node):
        """Extract qubit declarations and map to QPUs."""
        if hasattr(node, 'qubit'):
            qubit_node = node.qubit
            if hasattr(qubit_node, 'name'):
                reg_name = qubit_node.name
                
                # Parse QPU ID from qubit name like _qubit1_2 or _comm_qubit1_1
                if reg_name.startswith('_qubit') or reg_name.startswith('_comm_qubit'):
                    parts = reg_name.split('_')
                    # Extract QPU ID from name
                    for part in parts:
                        if part.startswith('qubit') and len(part) > 5:
                            try:
                                qpu_id = int(part[5:].split('_')[0])
                                self.qubit_to_qpu[reg_name] = qpu_id
                                if qpu_id not in self.qpu_commands:
                                    self.qpu_commands[qpu_id] = []
                                
                                # Track data qubits for measurement
                                if reg_name.startswith('_qubit'):
                                    data_idx_str = reg_name.split('_')[-1]
                                    try:
                                        data_idx = int(data_idx_str)
                                        local_pos = DATA_REGION_START + (data_idx - 1)
                                        self.measure_qubits.setdefault(qpu_id, []).append(local_pos)
                                    except ValueError:
                                        pass
                                break
                            except (ValueError, IndexError):
                                pass
        
        return self.generic_visit(node)
    
    def visit_ClassicalDeclaration(self, node):
        """Extract classical bit declarations."""
        if hasattr(node, 'identifier') and hasattr(node.identifier, 'name'):
            reg_name = node.identifier.name
            # Track output register
            if not reg_name.startswith('_clbit'):
                size = 1
                if hasattr(node.type, 'size') and hasattr(node.type.size, 'value'):
                    size = node.type.size.value
                if self.num_output_bits == 0:
                    self.num_output_bits = size
                    self.output_reg_name = reg_name
        
        return self.generic_visit(node)
    
    def visit_QuantumGateDefinition(self, node):
        """Skip gate definitions - we only want gate applications."""
        return None  # Don't visit children
    
    def visit_QuantumGate(self, node):
        """Extract quantum gate operations - just read from AST."""
        self.global_idx += 1
        
        # Extract gate name directly from AST
        gate_name = node.name.name
        gate_name = gate_name.lower()
        
        # Extract qubits
        qubits = []
        qubit_names = []
        for q in node.qubits:
            qubit_info = self._extract_qubit_info(q)
            if qubit_info:
                qubits.append(qubit_info)
                qubit_names.append(qubit_info['name'])
        
        if not qubits:
            return self.generic_visit(node)
        
        # Extract parameters directly from AST
        params = []
        if hasattr(node, 'arguments') and node.arguments:
            for arg in node.arguments:
                param_val = self._eval_parameter(arg)
                params.append(param_val)
        
        # Determine operation type and build command
        # Special handling for entanglement (2-qubit remote operation)
        if gate_name == 'entanglement' and len(qubits) >= 2:
            q0, q1 = qubits[0], qubits[1]
            qpu0_id, qpu1_id = q0['qpu_id'], q1['qpu_id']
            
            self.qpu_commands.setdefault(qpu0_id, []).append({
                "op": "entanglement_gen",
                "role": "emitter",
                "qubit": q0['local_idx'],
                "qubits": [q0['local_idx']],
                "params": params,
                "original_qubits": qubit_names,
                "is_remote": True,
                "peer_qpu_id": qpu1_id,
                "peer_qubit": q1['local_idx'],
                "entanglement_label": None,
                "final_key": None,
                "start_label": None,
                "end_label": None,
                "global_idx": self.global_idx,
            })
            
            self.qpu_commands.setdefault(qpu1_id, []).append({
                "op": "entanglement_gen",
                "role": "peer",
                "qubit": q1['local_idx'],
                "qubits": [q1['local_idx']],
                "params": params,
                "original_qubits": qubit_names,
                "is_remote": True,
                "peer_qpu_id": qpu0_id,
                "peer_qubit": q0['local_idx'],
                "entanglement_label": None,
                "final_key": None,
                "start_label": None,
                "end_label": None,
                "global_idx": self.global_idx,
            })
        
        # Multi-qubit gates on same QPU
        elif len(qubits) >= 2:
            # Check all qubits are on same QPU
            qpu_id = qubits[0]['qpu_id']
            if all(q['qpu_id'] == qpu_id for q in qubits):
                local_indices = [q['local_idx'] for q in qubits]
                self.qpu_commands.setdefault(qpu_id, []).append({
                    "op": "gate",
                    "gate": gate_name,
                    "qubit": local_indices[0],
                    "qubits": local_indices,
                    "params": params,
                    "original_qubits": qubit_names,
                    "is_remote": False,
                    "final_key": None,
                    "start_label": None,
                    "end_label": None,
                    "global_idx": self.global_idx,
                })
        
        # Single-qubit gates
        else:
            q = qubits[0]
            self.qpu_commands.setdefault(q['qpu_id'], []).append({
                "op": "gate",
                "gate": gate_name,
                "qubit": q['local_idx'],
                "qubits": [q['local_idx']],
                "params": params,
                "original_qubits": qubit_names,
                "is_remote": False,
                "final_key": None,
                "start_label": None,
                "end_label": None,
                "global_idx": self.global_idx,
            })
        
        return self.generic_visit(node)
    
    def visit_QuantumMeasurementStatement(self, node):
        """Extract measurement operations."""
        self.global_idx += 1
        
        # Extract qubit
        qubit_info = None
        if hasattr(node, 'measure') and hasattr(node.measure, 'qubit'):
            qubit_info = self._extract_qubit_info(node.measure.qubit)
        
        # Extract target bit - first with index to check if final
        bit_name_with_idx = None
        bit_name_no_idx = None
        if hasattr(node, 'target'):
            bit_name_with_idx = self._extract_bit_name(node.target, include_index=True)
            bit_name_no_idx = self._extract_bit_name(node.target, include_index=False)
        
        if not qubit_info:
            return self.generic_visit(node)
        
        # Determine if this is a final measurement or intermediate
        # Final measurements go to the output register (e.g., 'm[0]', 'm[1]')
        is_final = bit_name_no_idx and bit_name_no_idx == self.output_reg_name
        
        # Extract measurement index for final measurements
        m_idx = None
        if is_final and bit_name_with_idx and '[' in bit_name_with_idx:
            try:
                m_idx = int(bit_name_with_idx.split('[')[1].split(']')[0])
            except (ValueError, IndexError):
                pass

        final_key = None
        if is_final and m_idx is not None:
            final_key = f"{self.output_reg_name}_{m_idx}"

        # For intermediate measurements, use register name without index
        # (matches old regex parser behavior)
        clbit_for_cmd = bit_name_no_idx if not is_final else None

        log.debug(
            f"[qasm3_frontend] visit_QuantumMeasurementStatement: "
            f"bit_name={bit_name_with_idx!r}, is_final={is_final}, m_idx={m_idx}, final_key={final_key!r}"
        )

        cmd = {
            "op": "measure_final" if is_final else "measure",
            "qubit": qubit_info['local_idx'],
            "qubits": [qubit_info['local_idx']],
            "clbit": clbit_for_cmd,
            "final_key": final_key,
            "params": [],
            "original_qubits": [qubit_info['name']],
            "is_remote": False,
            "start_label": None,
            "end_label": None,
            "global_idx": self.global_idx,
        }
        
        self.qpu_commands.setdefault(qubit_info['qpu_id'], []).append(cmd)
        
        return self.generic_visit(node)
    
    def visit_QuantumReset(self, node):
        """Extract reset operations."""
        self.global_idx += 1
        
        # Extract qubit
        qubit_info = None
        if hasattr(node, 'qubits') and node.qubits:
            qubit_info = self._extract_qubit_info(node.qubits)
        
        if not qubit_info:
            return self.generic_visit(node)
        
        cmd = {
            "op": "gate",
            "gate": "reset",
            "qubit": qubit_info['local_idx'],
            "qubits": [qubit_info['local_idx']],
            "params": [],
            "original_qubits": [qubit_info['name']],
            "is_remote": False,
            "final_key": None,
            "start_label": None,
            "end_label": None,
            "global_idx": self.global_idx,
        }
        
        self.qpu_commands.setdefault(qubit_info['qpu_id'], []).append(cmd)
        
        return self.generic_visit(node)
    
    def visit_BranchingStatement(self, node):
        """Extract conditional (if) statements."""
        self.global_idx += 1
        
        # Extract condition bit - use register name without index
        # (matches old regex parser behavior)
        clbit_name = None
        if hasattr(node, 'condition'):
            clbit_name = self._extract_bit_name(node.condition, include_index=False)
        
        # Extract gate from if body
        if hasattr(node, 'if_block') and node.if_block:
            for stmt in node.if_block:
                if isinstance(stmt, ast.QuantumGate):
                    gate_name = stmt.name.name if hasattr(stmt.name, 'name') else str(stmt.name)
                    gate_name = gate_name.lower()
                    
                    # Extract qubit
                    qubit_info = None
                    if stmt.qubits:
                        qubit_info = self._extract_qubit_info(stmt.qubits[0])
                    
                    if not qubit_info:
                        continue
                    
                    # Extract parameters
                    params = []
                    if hasattr(stmt, 'arguments') and stmt.arguments:
                        for arg in stmt.arguments:
                            params.append(self._eval_parameter(arg))
                    
                    self.qpu_commands.setdefault(qubit_info['qpu_id'], []).append({
                        "op": "if_gate",
                        "gate": gate_name,
                        "qubit": qubit_info['local_idx'],
                        "qubits": [qubit_info['local_idx']],
                        "clbit": clbit_name,
                        "final_key": None,
                        "params": params,
                        "original_qubits": [qubit_info['name']],
                        "is_remote": False,
                        "start_label": None,
                        "end_label": None,
                        "global_idx": self.global_idx,
                    })
        
        # Don't call generic_visit - we've already processed the if_block contents
        # and don't want the gates inside to be visited again by visit_QuantumGate
        return None
    
    def _extract_qubit_info(self, qubit_node):
        """Extract qubit information including QPU ID and local index from AST."""
        # Extract name from AST
        name = qubit_node.name.name

        # Extract index from AST. The structure is a list of lists of expressions.
        # e.g., q[1] -> [[IntegerLiteral(1)]]
        index = qubit_node.indices[0][0].value

        # Determine QPU ID from qubit registry
        qpu_id = self.qubit_to_qpu[name]

        # Calculate local index based on naming convention
        if name.startswith('_qubit'):
            # Data qubit: _qubit{QPU}_{data_idx}
            data_idx = int(name.split('_')[-1])
            local_idx = DATA_REGION_START + (data_idx - 1)
        elif name.startswith('_comm_qubit'):
            # Communication qubit: _comm_qubit{QPU}_{comm_idx}
            comm_idx = int(name.split('_')[-1])
            local_idx = comm_idx - 1
        else:
            local_idx = index

        return {
            'name': f"{name}[{index}]",
            'qpu_id': qpu_id,
            'local_idx': local_idx,
            'reg_name': name,
            'index': index
        }
    
    def _extract_bit_name(self, bit_node, include_index=True):
        """Extract classical bit name from different AST node types.
        
        Parameters
        ----------
        bit_node : AST node
            The AST node representing the classical bit.
        include_index : bool
            If True, include the index in the name (e.g., 'm[0]').
            If False, return just the register name (e.g., '_clbit_comm_qubit1_1').
            The old regex parser used register names without indices for
            intermediate clbits in measure/if_gate commands.
        """
        if isinstance(bit_node, ast.IndexedIdentifier):
            # Handles `measure q -> c[0]`
            name = bit_node.name.name
            if include_index:
                idx = bit_node.indices[0][0].value
                return f"{name}[{idx}]"
            return name
        if isinstance(bit_node, ast.IndexExpression):
            # Handles indexed bits in conditions like `if(c[0])`
            name = bit_node.collection.name
            if include_index:
                idx = bit_node.index[0].value
                return f"{name}[{idx}]"
            return name
        if isinstance(bit_node, ast.Identifier):
            # Handles simple identifiers like `c`
            return bit_node.name
        if isinstance(bit_node, ast.BinaryExpression):
            # Handles conditions like `if (c == 1)`, assumes bit is on the left
            return self._extract_bit_name(bit_node.lhs, include_index=include_index)
        
        raise TypeError(f"Could not extract bit name from AST node type {type(bit_node)}")
    
    def _eval_parameter(self, param_node):
        """Evaluate parameter expression to float (in units of pi)."""
        if hasattr(param_node, 'value'):
            return float(param_node.value)
        
        # Handle unary expressions (e.g., -pi, -pi/2)
        if hasattr(param_node, 'expression') and hasattr(param_node, 'op'):
            # This is a UnaryExpression
            inner_val = self._eval_parameter(param_node.expression)
            op = param_node.op.name if hasattr(param_node.op, 'name') else str(param_node.op)
            if op == '-':
                return -inner_val
            elif op == '+':
                return inner_val
            elif op == '~':
                return ~int(inner_val)
            elif op == '!':
                return 0.0 if inner_val else 1.0
            return inner_val
        
        # Handle binary operations (openqasm3 uses BinaryOperator enum)
        if hasattr(param_node, 'op') and hasattr(param_node, 'lhs') and hasattr(param_node, 'rhs'):
            left = self._eval_parameter(param_node.lhs)
            right = self._eval_parameter(param_node.rhs)
            # Use op.name to get the operator symbol (e.g., '/', '*', '+', '-')
            op = param_node.op.name if hasattr(param_node.op, 'name') else str(param_node.op)
            
            if op == '/':
                return left / right if right != 0 else 0
            elif op == '*':
                return left * right
            elif op == '+':
                return left + right
            elif op == '-':
                return left - right
        
        # Handle pi constant
        if hasattr(param_node, 'name'):
            name = str(param_node.name)
            if name == 'pi':
                return 1.0  # In units of pi
        
        return 0.0


class QASM3Frontend(BaseFrontend):
    """Parse a QASM 3.0 file into canonical per-QPU commands using openqasm3 AST.
    
    Results are read directly from QPU protocol state after the run
    (``needs_datacollector=False``).
    """

    def __init__(self):
        self._source = None
        self._measure_qubits = None
        self._num_output_bits = 0
        self._output_reg_name = 'm'
        self._extractor = None

    # ── BaseFrontend abstract property ───────────────────────────────────────

    @property
    def needs_datacollector(self):
        """QASM3Frontend reads results directly from QPU protocol state."""
        return False

    # ── Source loading ───────────────────────────────────────────────────────

    def load(self, qasm_file):
        """Load and pre-scan a QASM 3.0 file using AST parser.

        Parameters
        ----------
        qasm_file : str
            Path to the QASM 3.0 source file.
        """
        super().load(qasm_file)
        
        # Read file
        with open(qasm_file, 'r') as f:
            qasm_str = f.read()
        
        # Parse AST
        ast_tree = parse(qasm_str)

        
        # Extract metadata
        extractor = QASM3CommandExtractor()
        extractor.visit(ast_tree)
        
        self._measure_qubits = extractor.measure_qubits
        self._num_output_bits = extractor.num_output_bits
        self._output_reg_name = extractor.output_reg_name
        
        log.info(f"[QASM3Frontend] Loaded {qasm_file}: "
                 f"output_bits={self._num_output_bits}, reg='{self._output_reg_name}', "
                 f"measure_qubits={dict(self._measure_qubits)}")

    # ── Metadata helpers ─────────────────────────────────────────────────────

    def get_measure_qubits(self, extra_context=None):
        """Return the measure_qubits dict extracted by :meth:`load`."""
        return self._measure_qubits

    # ── Parsing ──────────────────────────────────────────────────────────────

    def parse(self, qpu_info=None):
        """Parse the previously loaded QASM 3.0 file using AST and return ``{qpu_id: [cmd, …]}``.

        Parameters
        ----------
        qpu_info : dict | None
            Unused for QASM3 — qubit ownership is encoded in qubit names.

        Returns
        -------
        dict[int, list[dict]]
        """
        # Read file
        with open(self._source, 'r') as f:
            qasm_str = f.read()
        
        # Parse AST
        ast_tree = parse(qasm_str)
        
        # Extract commands, passing the output_reg_name from load()
        extractor = QASM3CommandExtractor(output_reg_name=self._output_reg_name)
        extractor.visit(ast_tree)
        
        # Sort commands by global index
        for qpu_id in extractor.qpu_commands:
            extractor.qpu_commands[qpu_id].sort(key=lambda x: x.get("global_idx", 0))
        
        total = sum(len(v) for v in extractor.qpu_commands.values())
        log.debug(
            f"[QASM3Frontend] Parsed {total} total commands — "
            + ", ".join(f"QPU_{k}={len(v)}" for k, v in sorted(extractor.qpu_commands.items()))
        )
        
        return extractor.qpu_commands
