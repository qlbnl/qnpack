import numpy as np
from netsquid.qubits.operators import Operator


def create_meas_ops():
    """Measurement operators to be used by BSM Detector.
    n0 & n1: BSM fail
    na & nb: BSM successful
    """
    m0 = np.diag([1, 0, 0, 0])
    ma = np.array([[0, 0, 0, 0],
                   [0, 1/2, 1/2, 0],
                   [0, 1/2, 1/2, 0],
                   [0, 0, 0, 0]],
                  dtype=complex)
    mb = np.array([[0, 0, 0, 0],
                   [0, 1/2, -1/2, 0],
                   [0, -1/2, 1/2, 0],
                   [0, 0, 0, 0]],
                  dtype=complex)
    m1 = np.diag([0, 0, 0, 1])
    n0 = Operator("n0", m0)
    na = Operator("nA", ma)
    nb = Operator("nB", mb)
    n1 = Operator("n1", m1)
    return [n0, n1, na, nb]
