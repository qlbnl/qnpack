"""
Ancilla-free Grover's algorithm QASM generator using Qiskit.

Uses Qiskit's built-in MCXGate which decomposes multi-controlled X gates
without ancilla qubits. Saves the decomposed QASM to a file for use
with pytket-dqc distribution.

Usage:
    python grover_algo_no_ancilla.py

Output:
    grover_12q_no_ancilla.qasm  — QASM file with only qreg q[12] (no ancillas)
"""

import os
from qiskit import QuantumCircuit, transpile


def generate_grover_circuit(n_qubits, target_bitstring, iterations):
    """
    Build a Grover's algorithm circuit WITHOUT ancilla qubits.

    Parameters
    ----------
    n_qubits : int
        Number of data qubits.
    target_bitstring : str
        Target bitstring of length n_qubits (e.g. "101111111111").
    iterations : int
        Number of Grover iterations.

    Returns
    -------
    QuantumCircuit
        Qiskit circuit with only n_qubits qubits.
    """
    if len(target_bitstring) != n_qubits:
        raise ValueError("Target bitstring length must match n_qubits")

    qc = QuantumCircuit(n_qubits, n_qubits)

    # Step 1: superposition
    qc.h(range(n_qubits))

    target_bits = [int(b) for b in target_bitstring]
    controls = list(range(n_qubits - 1))
    target_q = n_qubits - 1

    for _ in range(iterations):
        # ── Oracle ──
        for i, bit in enumerate(target_bits):
            if bit == 0:
                qc.x(i)

        # MCZ = H . MCX . H
        qc.h(target_q)
        qc.mcx(controls, target_q)
        qc.h(target_q)

        for i, bit in enumerate(target_bits):
            if bit == 0:
                qc.x(i)

        # ── Diffusion ──
        qc.h(range(n_qubits))
        qc.x(range(n_qubits))

        qc.h(target_q)
        qc.mcx(controls, target_q)
        qc.h(target_q)

        qc.x(range(n_qubits))
        qc.h(range(n_qubits))

    # Measurement
    qc.measure(range(n_qubits), range(n_qubits))
    return qc


def save_qasm(qc, filepath):
    """Transpile to basic gates and save QASM 2.0."""
    qc_decomposed = transpile(
        qc,
        basis_gates=['cx', 'u1', 'u2', 'u3', 'h', 'x', 'z',
                     'rz', 'ry', 'rx', 't', 'tdg', 's', 'sdg'],
        optimization_level=0,
    )

    # Qiskit ≥1.0 uses qasm2.dumps(); older versions use .qasm()
    try:
        from qiskit.qasm2 import dumps
        qasm_str = dumps(qc_decomposed)
    except ImportError:
        qasm_str = qc_decomposed.qasm()

    with open(filepath, 'w') as f:
        f.write(qasm_str)

    return qasm_str


# ─── main ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    N_QUBITS = 9
    TARGET_BITSTRING = "101111111"
    ITERATIONS = 17

    print(f"Building Grover circuit: {N_QUBITS} qubits, "
          f"target |{TARGET_BITSTRING}⟩, {ITERATIONS} iterations")

    qc = generate_grover_circuit(N_QUBITS, TARGET_BITSTRING, ITERATIONS)
    print(f"  Qubits in circuit : {qc.num_qubits}")
    print(f"  Depth (high-level): {qc.depth()}")

    # ── Save QASM ──
    qasm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "grover_9q_no_ancilla.qasm")
    print(f"\nTranspiling & saving QASM to {qasm_path} ...")
    qasm_str = save_qasm(qc, qasm_path)

    # Quick stats
    n_lines = len(qasm_str.splitlines())
    for line in qasm_str.splitlines():
        if line.startswith('qreg'):
            print(f"  {line}")
    print(f"  Total QASM lines: {n_lines}")
    print(f"  File saved ✓")

    # ── Verify with Qiskit Aer (if available) ──
    try:
        from qiskit_aer import AerSimulator

        print(f"\nVerifying with AerSimulator (8000 shots) ...")
        backend = AerSimulator()
        qc_run = transpile(qc, backend)
        result = backend.run(qc_run, shots=8000).result()
        counts = result.get_counts()

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        print("  Top 5 results:")
        for bitstr, cnt in sorted_counts[:5]:
            print(f"    |{bitstr}⟩ : {cnt}")

        # Qiskit returns bit-strings in LSB-first order
        target_lsb = TARGET_BITSTRING[::-1]
        hit = counts.get(target_lsb, 0) or counts.get(TARGET_BITSTRING, 0)
        pct = hit / 8000 * 100
        print(f"\n  Target |{TARGET_BITSTRING}⟩ hits: {hit}/8000 ({pct:.2f}%)")
        if pct > 90:
            print("  ✓ Verification PASSED")
        else:
            print("  ✗ Verification FAILED — check iteration count")

    except ImportError:
        print("\n  qiskit-aer not installed; skipping simulation verification.")

    # ── Verify with pytket (if available) ──
    try:
        from pytket.qasm import circuit_from_qasm_str
        from pytket.extensions.qiskit import AerBackend

        print(f"\nLoading QASM into pytket ...")
        circ = circuit_from_qasm_str(qasm_str, maxwidth=64)
        print(f"  pytket qubits: {circ.n_qubits}")
        print(f"  pytket gates : {circ.n_gates}")

        be = AerBackend()
        cc = be.get_compiled_circuit(circ)
        h = be.process_circuit(cc, n_shots=8000)
        res = be.get_result(h)
        cts = res.get_counts()
        scts = sorted(cts.items(), key=lambda x: x[1], reverse=True)

        print("  Top 5 (pytket):")
        for outcome, cnt in scts[:5]:
            print(f"    {outcome}: {cnt}")

        tgt = tuple(int(b) for b in TARGET_BITSTRING)
        if tgt in cts:
            p = cts[tgt] / 8000 * 100
            print(f"\n  Target {tgt}: {cts[tgt]}/8000 ({p:.2f}%)")
            if p > 90:
                print("  ✓ pytket verification PASSED")
        else:
            print(f"  Target {tgt} not found in pytket results")

    except ImportError:
        print("\n  pytket not installed; skipping pytket verification.")
