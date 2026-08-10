"""
Grover's algorithm QASM generator with a SINGLE quantum register.

Instead of separate qreg q[12] and qreg anc[6], this uses a single
qreg q[18] where:
  - q[0..11]  = data qubits (carry the Grover output)
  - q[12..17] = ancilla qubits (workspace, always return to |0>)

This ensures pytket-dqc distributes ALL qubits uniformly across servers.
After distribution, we know which server[idx] positions are data vs ancilla
and only measure the data qubit positions in netsquid.

No Qiskit dependency. Only requires pytket for verification/distribution.
"""

import os


def generate_grover_qasm_single_qreg(n_qubits, target_bitstring, iterations):
    """
    Generates OpenQASM for Grover's algorithm with a single quantum register.

    The multi-controlled gates use ancilla qubits q[n_qubits..n_qubits+n_ancillas-1]
    but they are in the SAME qreg as data qubits.

    Parameters
    ----------
    n_qubits : int
        Number of data qubits.
    target_bitstring : str
        Target bitstring of length n_qubits.
    iterations : int
        Number of Grover iterations.

    Returns
    -------
    tuple of (str, int, int)
        (QASM string, total_qubits, n_ancillas)
    """
    if len(target_bitstring) != n_qubits:
        raise ValueError("Target bitstring length must match n_qubits")

    # Calculate ancillas needed for Toffoli chain decomposition
    # For n data qubits, we need n-2 ancillas to build the control chain
    # q[0],q[1]→anc[0], anc[0],q[2]→anc[1], ..., anc[n-3],q[n-1]→final_control
    if n_qubits <= 3:
        n_ancillas = 0
    else:
        n_ancillas = n_qubits - 2

    total_qubits = n_qubits + n_ancillas

    lines = [
        'OPENQASM 2.0;',
        'include "qelib1.inc";',
        f'qreg q[{total_qubits}];',  # Single register: data + ancilla
        f'creg c[{n_qubits}];',       # Only measure data qubits
    ]

    lines.append('// --- Step 1: Initialize superposition ---')
    lines += [f'h q[{i}];' for i in range(n_qubits)]

    target_bits = [int(b) for b in target_bitstring]

    # Build the multi-controlled gate decomposition using only CCX (Toffoli) gates
    # Strategy: Chain controls together using ancillas
    # For n data qubits, we build: q[0],q[1]→anc[0], anc[0],q[2]→anc[1], ..., anc[n-3],q[n-1]→final
    needed_ops = []
    anc_counter = 0

    if n_qubits <= 3:
        # For 1-3 qubits, no ancillas needed
        pass
    else:
        # Build chain: q[0],q[1]→anc[0], anc[0],q[2]→anc[1], ..., anc[n-3],q[n-1]→final_control
        for i in range(n_qubits - 1):
            if i == 0:
                # First Toffoli: q[0], q[1] -> anc[0]
                anc_idx = n_qubits + anc_counter
                needed_ops.append(
                    f'ccx q[{i}], q[{i+1}], q[{anc_idx}];'
                )
                anc_counter += 1
            elif i < n_qubits - 2:
                # Middle Toffoli: anc[i-1], q[i+1] -> anc[i]
                prev_anc_idx = n_qubits + anc_counter - 1
                curr_anc_idx = n_qubits + anc_counter
                needed_ops.append(
                    f'ccx q[{prev_anc_idx}], q[{i+1}], q[{curr_anc_idx}];'
                )
                anc_counter += 1
            else:
                # Last Toffoli: anc[n-3], q[n-1] -> final_control (stored in anc[n-2])
                prev_anc_idx = n_qubits + anc_counter - 1
                curr_anc_idx = n_qubits + anc_counter
                needed_ops.append(
                    f'ccx q[{prev_anc_idx}], q[{i}], q[{curr_anc_idx}];'
                )
                anc_counter += 1

    for iteration in range(iterations):
        lines.append(f'\n// --- Grover Iteration {iteration + 1} ---')

        # --- Oracle ---
        lines.append('// Oracle')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')

        lines.append(f'h q[{n_qubits - 1}];')

        # Forward chain
        lines += needed_ops
        if n_qubits == 1:
            lines.append(f'z q[0];')
        elif n_qubits == 2:
            lines.append(f'cz q[0], q[1];')
        elif n_qubits == 3:
            lines.append(f'ccx q[0], q[1], q[2];')
        else:
            # Apply final controlled-Z using the accumulated control (final ancilla)
            final_control = n_qubits + n_ancillas - 1
            lines.append(f'h q[{n_qubits - 1}];')
            lines.append(f'cx q[{final_control}], q[{n_qubits - 1}];')
            lines.append(f'h q[{n_qubits - 1}];')
        # Uncompute ladder
        lines += needed_ops[::-1]

        lines.append(f'h q[{n_qubits - 1}];')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')

        # --- Diffusion ---
        lines.append('// Diffusion')
        lines += [f'h q[{i}];' for i in range(n_qubits)]
        lines += [f'x q[{i}];' for i in range(n_qubits)]

        lines.append(f'h q[{n_qubits - 1}];')
        lines += needed_ops
        if n_qubits == 1:
            lines.append(f'z q[0];')
        elif n_qubits == 2:
            lines.append(f'cz q[0], q[1];')
        elif n_qubits == 3:
            lines.append(f'ccx q[0], q[1], q[2];')
        else:
            # Apply final controlled-Z using the accumulated control
            final_control = n_qubits + n_ancillas - 1
            lines.append(f'h q[{n_qubits - 1}];')
            lines.append(f'cx q[{final_control}], q[{n_qubits - 1}];')
            lines.append(f'h q[{n_qubits - 1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits - 1}];')

        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines += [f'h q[{i}];' for i in range(n_qubits)]

    lines.append('\n// --- Measurement ---')
    for i in range(n_qubits):
        lines.append(f'measure q[{i}] -> c[{i}];')

    qasm_str = "\n".join(lines)

    print(f"\n{'='*60}")
    print(f"QASM GENERATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Data qubits:    q[0..{n_qubits-1}]  ({n_qubits} qubits)")
    print(f"  Ancilla qubits: q[{n_qubits}..{total_qubits-1}]  ({n_ancillas} qubits)")
    print(f"  Total qubits:   {total_qubits}")
    print(f"  Single qreg:    qreg q[{total_qubits}]")
    print(f"  Ancillas used:  {anc_counter} out of {n_ancillas}")
    print(f"  Target:         |{target_bitstring}⟩")
    print(f"  Iterations:     {iterations}")
    print(f"{'='*60}")

    return qasm_str, total_qubits, n_ancillas


# ─── Main execution ───

if __name__ == "__main__":
    from pytket.qasm import circuit_from_qasm_str
    from pytket.extensions.qiskit import AerBackend

    N_QUBITS = 12
    TARGET_BITSTRING = "101111111111"
    ITERATIONS = 50

    print(f"Generating Grover QASM with single qreg ({N_QUBITS} data + ancilla qubits)...")

    qasm_string, total_qubits, n_ancillas = generate_grover_qasm_single_qreg(
        N_QUBITS, TARGET_BITSTRING, ITERATIONS
    )

    # Save QASM
    qasm_path = os.path.join(os.path.dirname(__file__), "grover_12q_single_qreg.qasm")
    with open(qasm_path, 'w') as f:
        f.write(qasm_string)
    print(f"\nQASM saved to: {qasm_path}")
    print(f"QASM lines: {len(qasm_string.splitlines())}")

    # Verify qreg declarations
    print(f"\nRegister declarations:")
    for line in qasm_string.split('\n'):
        if line.startswith('qreg') or line.startswith('creg'):
            print(f"  {line}")

    # Load into pytket
    print(f"\nLoading into pytket...")
    circ = circuit_from_qasm_str(qasm_string, maxwidth=64)
    print(f"  Circuit qubits: {circ.n_qubits}")
    print(f"  Circuit gates: {circ.n_gates}")

    # Verify with AerBackend
    backend = AerBackend()
    compiled_circ = backend.get_compiled_circuit(circ)

    print(f"\nRunning Grover's ({N_QUBITS} data qubits, {n_ancillas} ancillas, single qreg)...")
    handle = backend.process_circuit(compiled_circ, n_shots=8000)
    result = backend.get_result(handle)
    counts = result.get_counts()

    sorted_counts = dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))

    print("\nMeasurement Results (Top 5):")
    for outcome, count in list(sorted_counts.items())[:5]:
        # outcome is a tuple of n_qubits bits (only data qubits measured)
        print(f"  State {outcome}: {count} hits")

    target_tuple = tuple(int(b) for b in TARGET_BITSTRING)
    if target_tuple in sorted_counts:
        hits = sorted_counts[target_tuple]
        percentage = (hits / 8000) * 100
        print(f"\n✓ Success! Target {target_tuple} found with {hits}/8000 hits ({percentage:.2f}%).")
    else:
        print(f"\n✗ Target {target_tuple} not found.")
        top = list(sorted_counts.keys())[0]
        print(f"  Top outcome: {top}")

    # Print the mapping info needed for distribution
    print(f"\n{'='*60}")
    print(f"DISTRIBUTION NOTES")
    print(f"{'='*60}")
    print(f"""
After running pytket-dqc PartitioningAnnealing on this circuit:
- The distributed circuit will have {total_qubits} qubits across servers
- q[0..{N_QUBITS-1}] are DATA qubits (carry the Grover output)
- q[{N_QUBITS}..{total_qubits-1}] are ANCILLA qubits (always |0> at end)

To determine which server[idx] maps to which q[i]:
1. After distribution, print the placement:
   for server_id, server in enumerate(dist_circ.get_servers()):
       for qubit in server.qubits:
           print(f"server_{{server_id}}[{{qubit.index[0]}}] -> q[{{qubit.index[0]}}]")

2. In sim.py, set measure_qubits to only include
   positions corresponding to q[0..{N_QUBITS-1}].

3. The qubit name in dist_commands will be q[i] instead of
   separate q[i] and anc[j], making the mapping straightforward.
""")
