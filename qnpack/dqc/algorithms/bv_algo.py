from pytket import Circuit
from pytket.extensions.qiskit import AerBackend


def generate_bv_circuit(n_qubits, secret_string):

    assert len(secret_string) == n_qubits - 1, \
        f"Secret string must have {n_qubits - 1} bits (last qubit is ancilla)"

    c = Circuit(n_qubits)

    for i in range(n_qubits - 1):
        c.H(i)

    c.X(n_qubits - 1)
    c.H(n_qubits - 1)

    target = n_qubits - 1
    for i, bit in enumerate(secret_string):
        if bit == '1':
            c.CX(i, target)

    for i in range(n_qubits - 1):
        c.H(i)

    c.measure_all()
    return c


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
N_QUBITS = 9
SECRET_STRING = "10111111111"   # 11 bits for 12 qubits
# SECRET_STRING = "101"
SECRET_STRING = "10111111"
SHOTS = 1024


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
backend = AerBackend()

circ = generate_bv_circuit(N_QUBITS, SECRET_STRING)
compiled = backend.get_compiled_circuit(circ)

print("\nRunning BV (TKET version)")

handle = backend.process_circuit(compiled, n_shots=SHOTS)
result = backend.get_result(handle)

counts = result.get_counts()
sorted_counts = dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

print("\nTop results:")
for k, v in list(sorted_counts.items())[:5]:
    print(k, ":", v)

top_state = list(sorted_counts.keys())[0]


def decode(state):
    # pytket returns (q[0], q[1], ..., q[11])
    # q[0..10] are the query qubits, q[11] is the ancilla
    # Just take the first n-1 bits, no reversal needed
    return ''.join(str(b) for b in state[:-1])


decoded = decode(top_state)

print("\nDecoded:", decoded)
print("Expected:", SECRET_STRING)

if decoded == SECRET_STRING:
    print("\n✅ SUCCESS")
else:
    print("\n⚠️ mismatch:", top_state)