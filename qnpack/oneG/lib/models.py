import logging
import random
from netsquid.components.qdetector import GatedQuantumDetector
from netsquid.qubits.qubitapi import gmeasure, discard
from netsquid.qubits import operators as ops
from qnpack.oneG.lib.operators import create_meas_ops
from qnpack.common.logging import setup_logging

log = logging.getLogger(__name__)


# setup_logging(name=__name__,
#                       level=logging.DEBUG,
#                       logfile=None)

class BSMGatedQuantumDetector(GatedQuantumDetector):
    """BSM detector for 1G repeater chain with added flexible coupling efficiency
    """

    def __init__(self, name, detection_window, coupling_efficiency=1, num_input_ports=1, num_output_ports=1,
                 observable=ops.Z, meas_operators=None, system_delay=0., dead_time=0.,
                 models=None, output_meta=None, error_on_fail=False, properties=None):
        """
        coupling_efficiency: Probability (0 to 1) that an incoming photon is successfully detected.
        """
        self.qin0_new_photon = False
        self.qin1_new_photon = False
        self.coupling_efficiency = coupling_efficiency  # Store coupling efficiency
        log.debug(f"Coupling efficiency: {self.coupling_efficiency}")
        super().__init__(name, detection_window, num_input_ports, num_output_ports,
                         observable, meas_operators, system_delay, dead_time,
                         models, output_meta, error_on_fail, properties)

    def measure(self):
        self.qin0_new_photon = False
        self.qin1_new_photon = False

        if len(self._qubits_per_port["qin0"]) > 0 and self.photon_detected():
            self.qin0_new_photon = True
        if len(self._qubits_per_port["qin1"]) > 0 and self.photon_detected():
            self.qin1_new_photon = True

        if self.qin0_new_photon and self.qin1_new_photon:
            # Both photons detected
            _, q0, _ = self._qubits_per_port["qin0"][-1]  # Left node qubit
            _, q1, _ = self._qubits_per_port["qin1"][-1]  # Right node qubit
            # Check if either qubit is None
            if q0.qstate is None or q1.qstate is None or q0.qstate.qrepr.num_qubits != q1.qstate.qrepr.num_qubits:
                self.ports["cout0"].tx_output([])
                return
            m, prob = gmeasure([q0, q1], meas_operators=create_meas_ops())  # Assuming `create_meas_ops()` exists

            discard(q0)
            discard(q1)

            log.debug(f"m={m} with prob {prob}.")
            self.ports["cout0"].tx_output(m)
        else:
            # Only one photon detected
            log.debug("Only one/both photons are not detected by BSM")
            self.ports["cout0"].tx_output("Only one photon is detected in BSM")

    def photon_detected(self):
        """Returns True if the photon is successfully detected based on coupling efficiency."""
        detected = random.random() < self.coupling_efficiency
        if not detected:
            log.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>Photon is not detected by the detector")
        return detected
