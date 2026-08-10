"""
Generate the distributed Grover circuit and print the qubit mapping.
This script requires pytket and pytket-dqc to be installed.

Two modes:
  --single-qreg : Use single qreg q[18] (data + ancilla in one register)
  --dual-qreg   : Use separate qreg q[12] + qreg anc[6] (original approach)

The single-qreg approach is recommended because it makes the
data-vs-ancilla mapping explicit after distribution.
"""
import sys
import os

try:
    from pytket.qasm import circuit_from_qasm_str
    from pytket import Circuit, OpType
    from pytket_dqc.placement import Placement
    from pytket_dqc import Distribution
    from pytket_dqc.circuits import HypergraphCircuit
    from pytket_dqc.networks import NISQNetwork
    from pytket_dqc.utils import DQCPass
    from pytket_dqc.distributors import PartitioningAnnealing
except ImportError as e:
    print(f"Error: {e}")
    print("This script requires pytket and pytket-dqc to be installed.")
    sys.exit(1)


# ─── QASM generators ───

def generate_grover_qasm_dual_qreg(n_qubits, target_bitstring, iterations):
    """Original: separate qreg q[n] and qreg anc[m]."""
    if len(target_bitstring) != n_qubits:
        raise ValueError("Target bitstring length must match n_qubits")

    n_ancillas = (n_qubits + 1) // 2
    if n_ancillas < 2 and n_qubits > 3:
        n_ancillas = 2
    if n_qubits <= 3:
        n_ancillas = 0

    lines = [
        'OPENQASM 2.0;',
        'include "qelib1.inc";',
        f'qreg q[{n_qubits}];',
    ]
    if n_ancillas > 0:
        lines.append(f'qreg anc[{n_ancillas}];')
    lines.append(f'creg c[{n_qubits}];')

    lines.append('// --- Step 1: Initialize superposition ---')
    lines += [f'h q[{i}];' for i in range(n_qubits)]

    target_bits = [int(b) for b in target_bitstring]

    needed_ops = []
    current_controls = []
    anc_counter = 0

    for i in range(n_qubits - 1):
        current_controls.append(f'q[{i}]')
        if len(current_controls) == 3:
            needed_ops.append(f'c3x {current_controls[0]}, {current_controls[1]}, {current_controls[2]}, anc[{anc_counter}];')
            current_controls = [f'anc[{anc_counter}]']
            anc_counter += 1

    if len(current_controls) == 2:
        needed_ops.append(f'ccx {current_controls[0]}, {current_controls[1]}, anc[{anc_counter}];')
        current_controls = [f'anc[{anc_counter}]']
        anc_counter += 1

    for iteration in range(iterations):
        lines.append(f'\n// --- Grover Iteration {iteration + 1} ---')
        lines.append('// Oracle')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')
        lines.append(f'h q[{n_qubits-1}];')
        lines += needed_ops
        if n_qubits >= 4:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits-1}];')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')

        lines.append('// Diffusion')
        lines += [f'h q[{i}];' for i in range(n_qubits)]
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines.append(f'h q[{n_qubits-1}];')
        lines += needed_ops
        if n_qubits >= 4:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits-1}];')
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines += [f'h q[{i}];' for i in range(n_qubits)]

    return "\n".join(lines), n_qubits, n_ancillas


def generate_grover_qasm_single_qreg(n_qubits, target_bitstring, iterations):
    """Single qreg: q[0..n-1] = data, q[n..n+m-1] = ancilla."""
    if len(target_bitstring) != n_qubits:
        raise ValueError("Target bitstring length must match n_qubits")

    n_ancillas = (n_qubits + 1) // 2
    if n_ancillas < 2 and n_qubits > 3:
        n_ancillas = 2
    if n_qubits <= 3:
        n_ancillas = 0

    total_qubits = n_qubits + n_ancillas

    lines = [
        'OPENQASM 2.0;',
        'include "qelib1.inc";',
        f'qreg q[{total_qubits}];',
        f'creg c[{n_qubits}];',
    ]

    lines.append('// --- Step 1: Initialize superposition ---')
    lines += [f'h q[{i}];' for i in range(n_qubits)]

    target_bits = [int(b) for b in target_bitstring]

    needed_ops = []
    current_controls = []
    anc_counter = 0

    for i in range(n_qubits - 1):
        current_controls.append(f'q[{i}]')
        if len(current_controls) == 3:
            anc_idx = n_qubits + anc_counter
            needed_ops.append(
                f'c3x {current_controls[0]}, {current_controls[1]}, '
                f'{current_controls[2]}, q[{anc_idx}];'
            )
            current_controls = [f'q[{anc_idx}]']
            anc_counter += 1

    if len(current_controls) == 2:
        anc_idx = n_qubits + anc_counter
        needed_ops.append(
            f'ccx {current_controls[0]}, {current_controls[1]}, q[{anc_idx}];'
        )
        current_controls = [f'q[{anc_idx}]']
        anc_counter += 1

    for iteration in range(iterations):
        lines.append(f'\n// --- Grover Iteration {iteration + 1} ---')
        lines.append('// Oracle')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')
        lines.append(f'h q[{n_qubits-1}];')
        lines += needed_ops
        if n_qubits >= 4:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits-1}];')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')

        lines.append('// Diffusion')
        lines += [f'h q[{i}];' for i in range(n_qubits)]
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines.append(f'h q[{n_qubits-1}];')
        lines += needed_ops
        if n_qubits >= 4:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits-1}];')
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines += [f'h q[{i}];' for i in range(n_qubits)]

    return "\n".join(lines), n_qubits, n_ancillas


def main():
    N_QUBITS = 12
    TARGET_BITSTRING = "101111111111"
    ITERATIONS = 50

    # Parse command line
    use_single_qreg = "--single-qreg" in sys.argv or "--dual-qreg" not in sys.argv
    mode_name = "single-qreg" if use_single_qreg else "dual-qreg"

    print(f"{'='*60}")
    print(f"GENERATING DISTRIBUTED GROVER CIRCUIT ({mode_name})")
    print(f"{'='*60}")
    print(f"  Data qubits: {N_QUBITS}")
    print(f"  Target: |{TARGET_BITSTRING}⟩")
    print(f"  Iterations: {ITERATIONS}")

    if use_single_qreg:
        qasm_string, n_data, n_anc = generate_grover_qasm_single_qreg(
            N_QUBITS, TARGET_BITSTRING, ITERATIONS
        )
        total = n_data + n_anc
        print(f"  Register: qreg q[{total}] (q[0..{n_data-1}]=data, q[{n_data}..{total-1}]=ancilla)")
    else:
        qasm_string, n_data, n_anc = generate_grover_qasm_dual_qreg(
            N_QUBITS, TARGET_BITSTRING, ITERATIONS
        )
        total = n_data + n_anc
        print(f"  Registers: qreg q[{n_data}] + qreg anc[{n_anc}]")

    circ = circuit_from_qasm_str(qasm_string, maxwidth=64)

    print(f"\nOriginal circuit:")
    print(f"  n_qubits: {circ.n_qubits}")
    print(f"  Qubit names: {[str(q) for q in circ.qubits]}")

    # Network: 3 servers, each with enough qubits
    # Server 0 connected to Server 1, Server 0 connected to Server 2
    server_size = total  # Each server can hold all qubits
    network = NISQNetwork(
        [[0, 1], [0, 2]],
        {0: list(range(server_size)),
         1: list(range(server_size, 2 * server_size)),
         2: list(range(2 * server_size, 3 * server_size))}
    )

    DQCPass().apply(circ)

    print(f"\nAfter DQCPass:")
    print(f"  n_qubits: {circ.n_qubits}")

    distribution = PartitioningAnnealing().distribute(circ, network, seed=42)
    assert distribution.is_valid()

    dist_circ = distribution.to_pytket_circuit()

    print(f"\nDistributed circuit:")
    print(f"  n_qubits: {dist_circ.n_qubits}")

    # Analyze qubit mapping
    data_qubits = [q for q in dist_circ.qubits if 'link_register' not in q.reg_name]
    link_qubits = [q for q in dist_circ.qubits if 'link_register' in q.reg_name]

    print(f"\n{'='*60}")
    print(f"QUBIT MAPPING")
    print(f"{'='*60}")

    print(f"\nData qubits ({len(data_qubits)}):")
    data_qubit_info = []
    for q in data_qubits:
        server_name = q.reg_name
        server_idx = q.index[0]
        # For single-qreg: the original qubit index is preserved in the name
        # server_X[idx] -> original q[idx] (approximately, depends on placement)
        role = "DATA" if server_idx < n_data else "ANCILLA"
        if not use_single_qreg:
            role = "UNKNOWN (dual-qreg mode)"
        print(f"  {server_name}[{server_idx}] -> role: {role}")
        data_qubit_info.append((server_name, server_idx, role))

    print(f"\nLink qubits ({len(link_qubits)}):")
    for q in link_qubits:
        print(f"  {q.reg_name}[{q.index[0]}]")

    # Determine measure_qubits for sim.py
    if use_single_qreg:
        print(f"\n{'='*60}")
        print(f"NETSQUID MEASUREMENT CONFIGURATION")
        print(f"{'='*60}")

        measure_qubits = {}
        for server_name, server_idx, role in data_qubit_info:
            server_id = int(server_name.split('_')[1])
            qpu_id = server_id + 1
            ns_pos = 20 + server_idx  # DATA_REGION_START + idx
            if role == "DATA":
                if qpu_id not in measure_qubits:
                    measure_qubits[qpu_id] = []
                measure_qubits[qpu_id].append(ns_pos)

        print(f"\n  measure_qubits = {measure_qubits}")
        print(f"\n  This measures only DATA qubits (q[0..{n_data-1}]),")
        print(f"  skipping ANCILLA qubits (q[{n_data}..{total-1}]).")

    # Save commands
    commands = dist_circ.get_commands()
    suffix = "_single_qreg" if use_single_qreg else "_dual_qreg"
    output_file = os.path.join(os.path.dirname(__file__), f"dist_commands_v3{suffix}.txt")
    with open(output_file, "w") as f:
        f.write("Distributed Circuit Commands:\n")
        for cmd in commands:
            f.write(str(cmd) + "\n")
    print(f"\nSaved {len(commands)} commands to {output_file}")

    # Print placement info
    print(f"\nPlacement info:")
    try:
        placement = distribution.placement
        print(f"  Placement: {placement}")
    except Exception as e:
        print(f"  Could not access placement: {e}")


if __name__ == "__main__":
    main()
