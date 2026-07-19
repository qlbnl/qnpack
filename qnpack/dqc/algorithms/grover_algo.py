import os
from pytket.qasm import circuit_from_qasm_str
from pytket.extensions.qiskit import AerBackend
from pytket import Circuit, OpType

# 1. Define the generalized Grover QASM generator
def generate_grover_qasm(n_qubits, target_bitstring, iterations):
    """
    Generates OpenQASM for Grover's algorithm.
    n_qubits: number of data qubits.
    target_bitstring: string of '0's and '1's (length n_qubits).
    iterations: number of Grover iterations.
    """
    if len(target_bitstring) != n_qubits:
        raise ValueError("Target bitstring length must match n_qubits")

    # Determine ancillas needed for large multi-controlled gates
    # We'll use a simple chain logic.
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
    
    # Pre-calculate decomposition of multi-control flip
    # This uses a simple grouping structure.
    needed_ops = []
    current_controls = []
    anc_counter = 0
    
    for i in range(n_qubits - 1): # Controls are q[0] to q[n_qubits-2]
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
        
        # --- Oracle ---
        lines.append('// Oracle')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')
        
        lines.append(f'h q[{n_qubits-1}];')
        
        # Apply forward chain
        lines += needed_ops
        if n_qubits == 1:
            lines.append(f'z q[0];')
        elif n_qubits == 2:
            lines.append(f'cz q[0], q[1];')
        elif n_qubits == 3:
            lines.append(f'ccx q[0], q[1], q[2];')
        else:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        # Uncompute ladder
        lines += needed_ops[::-1]

        lines.append(f'h q[{n_qubits-1}];')
        for i, bit in enumerate(target_bits):
            if bit == 0:
                lines.append(f'x q[{i}];')

        # --- Diffusion ---
        lines.append('// Diffusion')
        lines += [f'h q[{i}];' for i in range(n_qubits)]
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        
        lines.append(f'h q[{n_qubits-1}];')
        lines += needed_ops
        if n_qubits == 1:
            lines.append(f'z q[0];')
        elif n_qubits == 2:
            lines.append(f'cz q[0], q[1];')
        elif n_qubits == 3:
            lines.append(f'ccx q[0], q[1], q[2];')
        else:
            if len(current_controls) == 1:
                lines.append(f'cx {current_controls[0]}, q[{n_qubits-1}];')
        lines += needed_ops[::-1]
        lines.append(f'h q[{n_qubits-1}];')
        
        lines += [f'x q[{i}];' for i in range(n_qubits)]
        lines += [f'h q[{i}];' for i in range(n_qubits)]

    lines.append('\n// --- Measurement ---')
    # Measurement in QASM 2.0: measure q[i] -> c[i]
    for i in range(n_qubits):
        lines.append(f'measure q[{i}] -> c[{i}];')
    return "\n".join(lines)

# 2. Configuration
N_QUBITS = 9
TARGET_BITSTRING = "101111111" # 12 qubits: q0=1, q1=0, q2=1...q11=1

# Optimal iterations approx pi/4 * sqrt(2^n)
# For 8 qubits: ~12
# For 12 qubits: ~45-50
ITERATIONS = 17

# Generate QASM
qasm_string = generate_grover_qasm(N_QUBITS, TARGET_BITSTRING, ITERATIONS)

# 3. Load the circuit into a TKET Circuit object
circ = circuit_from_qasm_str(qasm_string, maxwidth=64)

# 4. Initialize the Backend
backend = AerBackend()

# 5. Compile the circuit
compiled_circ = backend.get_compiled_circuit(circ)

# 6. Execute the circuit
print(f"\nRunning Grover's Algorithm ({N_QUBITS} qubits) on {backend}...")
print(f"Target state: {TARGET_BITSTRING} (iterations: {ITERATIONS})")

handle = backend.process_circuit(compiled_circ, n_shots=8000)

# 7. Retrieve and format results
result = backend.get_result(handle)
counts = result.get_counts()

# Sort counts
sorted_counts = dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))

print("\nMeasurement Results (Top 5):")
for outcome, count in list(sorted_counts.items())[:5]:
    print(f"State {outcome}: {count} hits")

# Verification
# Note: AerBackend returns outcomes as tuples of bits (c0, c1, ..., cN-1)
target_tuple = tuple(int(b) for b in TARGET_BITSTRING)

if target_tuple in sorted_counts:
    hits = sorted_counts[target_tuple]
    total_shots = 8000
    percentage = (hits / total_shots) * 100
    print(f"\nSuccess! Target state {target_tuple} found with {hits}/{total_shots} hits ({percentage:.2f}%).")
else:
    print(f"\nTarget state {target_tuple} not found in measurement results.")
    # Check for endianness issues by printing the top result
    top_outcome = list(sorted_counts.keys())[0]
    print(f"Top outcome was {top_outcome}")
