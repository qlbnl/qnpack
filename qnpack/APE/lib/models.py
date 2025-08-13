import numpy as np
import math
from netsquid.qubits.operators import *
from netsquid.qubits import operators as ops
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits.qubitapi import operate, discard
from netsquid.components import QuantumChannel
from netsquid.components.qdetector import GatedQuantumDetector
from netsquid.util import simtools
from netsquid.components.models import (
    QuantumErrorModel,
    FibreLossModel
)
from qnpack.common.utils import ForcedRNG
from qnpack.APE.lib.custom_qubitapi import (
    my_measure,
    my_gmeasure
)

# Used in ancilla qubit for performing local complementation of graph state
Rx = ops.create_rotation_op(np.pi/2, (1, 0, 0))
# Used in CorePhotonicProcessing for performing local complementation of graph state
Rz = ops.create_rotation_op(-np.pi/2, (0, 0, 1))

# class measurement_outcomes_collector():
#
#    def __init__(self):
#        self.reset()
#
#    def reset(self):
#        self.spd_list=[]
#        self.bsm_list=[]
#        self.spd_cnt=0
#        self.bsm_cnt=0
#        self.is_meas_mismatch=False


class measurement_outcomes_collector():

    def __init__(self):
        self.reset()

    def reset(self):
        self.spd_dict = {}
        self.bsm_dict = {}
        self.spd_cnt_dict = {}
        self.bsm_cnt_dict = {}
        self.is_meas_mismatch = False


m_collector = measurement_outcomes_collector()


class FibreDepolarizeModel(QuantumErrorModel):
    """Custom non-physical error model used to show the effectiveness
    of repeater chains.

    The default values are chosen to make a nice figure,
    and don't represent any physical system.

    Parameters
    ----------
    p_depol_init : float, optional
        Probability of depolarization on entering a fibre.
        Must be between 0 and 1. Default 0.009
    p_depol_length : float, optional
        Probability of depolarization per km of fibre.
        Must be between 0 and 1. Default 0.025

    """

    def __init__(self, p_depol_init=0.009, p_depol_length=0.025, rng_noise=None):
        super().__init__()
        self.properties['p_depol_init'] = p_depol_init
        self.properties['p_depol_length'] = p_depol_length
        self.required_properties = ['length']
        if rng_noise == None:
            self.rng_noise = simtools.get_random_state()
        else:
            self.rng_noise = rng_noise
        # self.rng_noise = np.random.default_rng(0)
        # self.rng_loss = np.random.default_rng(0)
        # if seed:
        #    # Set the seed of the rng_noise which is used in FibreDepolarizeModel
        #    self.rng_noise.__setstate__(np.random.default_rng(seed=seed).__getstate__())

    def error_operation(self, qubits, delta_time=0, **kwargs):
        """Uses the length property to calculate a depolarization probability,
        and applies it to the qubits.

        Parameters
        ----------
        qubits : tuple of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits to apply noise to.
        delta_time : float, optional
            Time qubits have spent on a component [ns]. Not used.

        """
        for qubit in qubits:
            prob = 1 - (1 - self.properties['p_depol_init']) * np.power(
                10, - kwargs['length']**2 * self.properties['p_depol_length'] / 10)
            # perform_depolarization = (self.rng_noise.random() < prob)
            perform_depolarization = (self.rng_noise.random_sample() < prob)
            # print("prob",prob,"perform_depolarization",perform_depolarization)
            if perform_depolarization:
                # [depolarization_gate] = self.rng_noise.integers(low=0, high=4, size=1)
                [depolarization_gate] = self.rng_noise.randint(low=0, high=4, size=1)
                # print("depolarization_gate",depolarization_gate)
                if depolarization_gate == 1:
                    qapi.operate(qubit, ops.X)
                elif depolarization_gate == 2:
                    qapi.operate(qubit, ops.Y)
                elif depolarization_gate == 3:
                    qapi.operate(qubit, ops.Z)


class oldMyFibreLossModel(FibreLossModel):

    def error_operation(self, qubits, delta_time=0, **kwargs):
        """Error operation to apply to qubits.

        Parameters
        ----------
        qubits : tuple of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits to apply noise to.
        delta_time : float, optional
            Time qubits have spent on a component [ns].

        """
        # self.apply_loss(qubits, delta_time, **kwargs)
        for idx, qubit in enumerate(qubits):
            if qubit is None:
                continue
            prob_loss = 1 - (1 - self.p_loss_init) * np.power(10, - kwargs['length'] * self.p_loss_length / 10)
            # prob_loss = 1 - np.exp(-kwargs['length'] / attenuation_length)
            # print(f"Prob_loss {prob_loss} with length {kwargs['length']}")
            self.lose_qubit(qubits, idx, prob_loss, rng=self.properties['rng'])


class MyFibreLossModel(FibreLossModel):
    """Adapted from FibreLossModel. The only modification is to comment out qapi.discard(qubit) in lose_qubit.
    As a result, lost qubit is still entangled to the remaining qubit, but removed from the qchannel so it would 
    no longer arrive the components(detectors) connected to the end of the qchannel.
    """

    def __init__(self, discard=True, p_loss_init=0, p_loss_length=0, rng=None, hide_fixed_photons=False):
        super().__init__(p_loss_init, p_loss_length, rng)
        self.discard = discard
        self.hide_fixed_photons = hide_fixed_photons
        MyFibreLossModel.lost_photon_ls = []

    def my_lose_qubit(self, qubits, qubit_index, prob_loss=1., rng=None):
        """Helper function to lose a qubit. 

        Parameters
        ----------
        qubits : list of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits from which a qubit should be lost.
        qubit_index : int
            Index of the qubit that should be lost.
        prob_loss : float, optional
            Probability with which the qubit is lost, used in case of number state3.
        rng : :obj:`numpy.random.RandomState`, optional
            The random number generator to use. Default `simtools.get_random_state()`.

        Notes
        -----
            In the case of a standard qubit item, it is discarded from its shared quantum state (if applicable).

            If the qubit represents a number state (e.g. presence of a photon), the qubit is amplitude dampened
            according to the loss probability.

        """
        qubit = qubits[qubit_index]
        if qubit is None or qubit.qstate is None:
            return
        if qubit.is_number_state:
            # If qubit is a number state, then we want to amplitude dampen
            # towards |0> but not physically lose it.
            qapi.amplitude_dampen(qubit, gamma=prob_loss, prob=1.)
        else:
            if self.hide_fixed_photons:
                if qubit.name in MyFibreLossModel.lost_photon_ls:
                    qubits[qubit_index] = None
            else:
                if rng is None:
                    rng = simtools.get_random_state()

                # Modify here if photon name in noise_lost_ls, then have loss
                if math.isclose(prob_loss, 1.) or rng.random_sample() <= prob_loss:
                    # If self.discard==False, the lost qubit would remain entangled but removed from the qchannel
                    # print(f"{ns.sim_time():.1f}:self.discard inside MyFibreLossModel {self.discard}")
                    if self.discard:
                        qapi.discard(qubit)
                        # print(f"{ns.sim_time():.1f}:photon loss happens at",qubit,"and qubit is discarded")
                    # else:
                        # print(f"{ns.sim_time():.1f}:photon loss happens at",qubit,"but qubit is not discarded")
                    qubits[qubit_index] = None
                    MyFibreLossModel.lost_photon_ls.append(qubit.name)

    def error_operation(self, qubits, delta_time=0, **kwargs):
        """Error operation to apply to qubits.

        Parameters
        ----------
        qubits : tuple of :obj:`~netsquid.qubits.qubit.Qubit`
            Qubits to apply noise to.
        delta_time : float, optional
            Time qubits have spent on a component [ns].

        """
        # self.apply_loss(qubits, delta_time, **kwargs)
        for idx, qubit in enumerate(qubits):
            if qubit is None:
                continue
            prob_loss = 1 - (1 - self.p_loss_init) * np.power(10, - kwargs['length'] * self.p_loss_length / 10)
            # prob_loss = 1 - np.exp(-kwargs['length'] / attenuation_length)
            # print(f"Prob_loss {prob_loss} with length {kwargs['length']}")
            self.my_lose_qubit(qubits, idx, prob_loss, rng=self.properties['rng'])


class SPGatedQuantumDetector(GatedQuantumDetector):
    """Single-photon detector for measurement of core qubits in measurement node.
    Subclass from GatedQuantumDetector to pass a custom parameter 'rng_measure' 
    to be used during measurement.
    Also, add an option to perform phase gate before measurement. This is required for all 1st-level tree photons. 
    Since S^dagger Z S=Z, it could be omitted when measurement basis is Z.
    """

    def __init__(self, name, detection_window, num_input_ports=1, num_output_ports=1,
                 observable=ops.Z, meas_operators=None, system_delay=0., dead_time=0.,
                 models=None, output_meta=None, error_on_fail=False, properties=None, rng_measure=None, phase_gate=False, is_forced_outcome=False):
        self.observable = observable
        self.rng_measure = rng_measure
        self.phase_gate = phase_gate
        self.is_forced_outcome = is_forced_outcome
        super().__init__(name, detection_window, num_input_ports, num_output_ports,
                         observable, meas_operators, system_delay, dead_time,
                         models, output_meta, error_on_fail, properties)

    def measure(self):
        _, q0, _ = self._qubits_per_port["qin0"][0]
        # Perform phase gate before measurement. This is required for all 1st-level tree photons.
        # Since S^dagger Z S=Z, it could be omitted when measurement basis is Z.
        if self.phase_gate:
            operate(q0, ops.S.inv)
            operate(q0, Rz)
            # print(ops.S.inv)
        #    m1,prob1=measure(q0, ops.Y, rng_measure=self.rng_measure)
        #    print("Photons to be applied S gate:",q0)

        if self.is_forced_outcome:
            # forced_outcome=m_collector.spd_list[m_collector.spd_cnt]
            # m_collector.spd_cnt+=1
            forced_outcome = self.get_forced_outcome()
            # Do forced outcome here
            m1, prob1 = my_measure(q0, self.observable, rng_measure=ForcedRNG(forced_outcome))
            # print(f"{ns.sim_time():.1f}:inside SPD, {self.name},{q0},{m1},{prob1},forced_outcome:{forced_outcome}")
            try:
                assert m1 == forced_outcome, f"Forced outcome is different than actual outcome,{forced_outcome},{m_collector.spd_dict[self.name]},{m_collector.spd_cnt_dict[self.name]-1}"
            # Code that runs if the assertion passes
            except AssertionError as e:
             # Code to handle the assertion error
                # print(f"Assertion failed")
                # print(f"Assertion failed: {e}")
                m_collector.is_meas_mismatch = True
        else:
            m1, prob1 = my_measure(q0, self.observable, rng_measure=self.rng_measure)
            # m_collector.spd_list.append(m1)
            self.store_meas_outcome(m1)

            # print(f"{ns.sim_time():.1f}: inside SPD",self.name,q0,m1,prob1)
        discard(q0)
        # print("inside SPD", self.name, q0, m1, prob1)
        # print(f"m1={m1} with prob {prob1}")
        self.ports["cout0"].tx_output(m1)
        self._qubits_per_port["qin0"] = []

    def store_meas_outcome(self, m):
        if self.name in m_collector.spd_dict:
            m_collector.spd_dict[self.name].append(m)
        else:
            m_collector.spd_dict[self.name] = [m]

    def get_forced_outcome(self):
        if self.name in m_collector.spd_cnt_dict:
            forced_outcome = m_collector.spd_dict[self.name][m_collector.spd_cnt_dict[self.name]]
            m_collector.spd_cnt_dict[self.name] += 1
        else:
            forced_outcome = m_collector.spd_dict[self.name][0]
            m_collector.spd_cnt_dict[self.name] = 1
        return forced_outcome

    def store_meas_outcome(self, m):
        if self.name in m_collector.spd_dict:
            m_collector.spd_dict[self.name].append(m)
        else:
            m_collector.spd_dict[self.name] = [m]

    def get_forced_outcome(self):
        if self.name in m_collector.spd_cnt_dict:
            forced_outcome = m_collector.spd_dict[self.name][m_collector.spd_cnt_dict[self.name]]
            m_collector.spd_cnt_dict[self.name] += 1
        else:
            forced_outcome = m_collector.spd_dict[self.name][0]
            m_collector.spd_cnt_dict[self.name] = 1
        return forced_outcome


class BSMGatedQuantumDetector(GatedQuantumDetector):
    """BSM detector for stab repr (not applicable for GSLC repr since it does not support gmeasure in NetSquid)
    Failed BSM is equivalent to a XZ measurement with outcome m1=1 followed by XI measurement (outcome m2=0 or 1).
    Karus operators: U2=<+1|, U3=<-0|
    Successful BSM is equivalent to a XZ measurement with outcome m1=0 followed by ZX measruement (outcome m2=0 or 1).
    Karus operators: U0=<+0|+<-1|, U1=<+0|-<-1|
    Final BSM outcome is output at port "cout0" as 2*m1+m2={0,1,2 or 3}
    In addition, Rx gate is implemented on all arriving qubit for local complementation of the leaf qubits. This is 
    a part of the encoded RGS generation scheme.
    """

    def __init__(self, name, detection_window, num_input_ports=1, num_output_ports=1,
                 observable=ops.Z, meas_operators=None, system_delay=0., dead_time=0.,
                 models=None, output_meta=None, error_on_fail=False, properties=None, end_node_dir=None, rng_measure=None, is_forced_outcome=False):
        self.qin0_cnt = 0
        self.qin1_cnt = 0
        self.qin0_new_photon = False
        self.qin1_new_photon = False
        self.end_node_dir = end_node_dir
        self.rng_measure = rng_measure
        self.is_forced_outcome = is_forced_outcome
        super().__init__(name, detection_window, num_input_ports, num_output_ports,
                         observable, meas_operators, system_delay, dead_time,
                         models, output_meta, error_on_fail, properties)

    def measure(self):
        if len(self._qubits_per_port["qin0"]) > 0:
            self.qin0_new_photon = True
        if len(self._qubits_per_port["qin1"]) > 0:
            self.qin1_new_photon = True

        if self.qin0_new_photon & self.qin1_new_photon:
            _, q0, _ = self._qubits_per_port["qin0"][0]  # qubit coming from the left node
            _, q1, _ = self._qubits_per_port["qin1"][0]  # qubit coming from the right node
            # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q0} and {q1}")
            if self.end_node_dir != "left":
                operate(q0, Rx)
                # print("Rx on left photon",q0)
            if self.end_node_dir != "right":
                operate(q1, Rx)
                # print("Rx on right photon",q1)

            if self.is_forced_outcome:
                m1, prob1 = self.forced_my_gmeasure([q0, q1], ops.X ^ ops.Z)
                if m1 == 0:
                    m2, prob2 = self.forced_my_gmeasure([q0, q1], ops.Z ^ ops.X)
                else:
                    m2, prob2 = self.forced_my_measure(q0, ops.X)

            else:
                m1, prob1 = my_gmeasure([q0, q1], ops.X ^ ops.Z, rng_measure=self.rng_measure)
                # Store measurement outcome for forced outcome on noiseless case
                # m_collector.bsm_list.append(m1)
                self.store_meas_outcome(m1)

                if m1 == 0:
                    m2, prob2 = my_gmeasure([q0, q1], ops.Z ^ ops.X, rng_measure=self.rng_measure)
                else:
                    m2, prob2 = my_measure(q0, ops.X, rng_measure=self.rng_measure)

                # m_collector.bsm_list.append(m2)
                self.store_meas_outcome(m2)

            # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q0} and {q1}, outcome={2*m1+m2}")
            discard(q0)
            discard(q1)
            # print(f"m1={m1} with prob {prob1}. m2={m2} with prob {prob2}")
            self.ports["cout0"].tx_output(2*m1+m2)

        elif self.qin0_new_photon or self.qin1_new_photon:
            self.ports["cout0"].tx_output("One photon detected in BSM")

            if self.qin0_new_photon:
                _, q0, _ = self._qubits_per_port["qin0"][0]
                # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q0} from the left")
                if self.end_node_dir != "left":
                    operate(q0, Rx)
                # BSMGatedQuantumDetector.debug_qubit_ls.append(q0)
                if self.is_forced_outcome:
                    m2, prob2 = self.forced_my_measure(q0, ops.X)
                else:
                    m2, prob2 = my_measure(q0, ops.X, rng_measure=self.rng_measure)
                    # m_collector.bsm_list.append(m2)
                    self.store_meas_outcome(m2)
                # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q0} from the left, outcome={m2},{prob2}")

            else:
                _, q1, _ = self._qubits_per_port["qin1"][0]
                # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q1} from the right")
                if self.end_node_dir != "right":
                    operate(q1, Rx)
                # BSMGatedQuantumDetector.debug_qubit_ls.append(q1)
                if self.is_forced_outcome:
                    m2, prob2 = self.forced_my_measure(q1, ops.Z)
                else:
                    m2, prob2 = my_measure(q1, ops.Z, rng_measure=self.rng_measure)
                    # m_collector.bsm_list.append(m2)
                    self.store_meas_outcome(m2)
                # print(f"{ns.sim_time():.1f}: BSM in node {self.name},with photon {q1} from the right, outcome={m2},{prob2}")

        self.qin0_new_photon = False
        self.qin1_new_photon = False
        self._qubits_per_port["qin0"] = []
        self._qubits_per_port["qin1"] = []

    def get_forced_outcome(self):
        if self.name in m_collector.bsm_cnt_dict:
            # print(self.name,m_collector.bsm_dict[self.name],m_collector.bsm_cnt_dict[self.name])
            forced_outcome = m_collector.bsm_dict[self.name][m_collector.bsm_cnt_dict[self.name]]
            m_collector.bsm_cnt_dict[self.name] += 1
        else:
            forced_outcome = m_collector.bsm_dict[self.name][0]
            m_collector.bsm_cnt_dict[self.name] = 1
        return forced_outcome

    def forced_my_gmeasure(self, qubits, meas_operators):
        # forced_outcome=m_collector.bsm_list[m_collector.bsm_cnt]
        # m_collector.bsm_cnt+=1
        forced_outcome = self.get_forced_outcome()

        # Do forced outcome here
        m, prob = my_gmeasure(qubits, meas_operators, rng_measure=ForcedRNG(forced_outcome))
        # print("forced_my_gmeasure m",m,"prob",prob,"forced_outcome",forced_outcome,"qubits",qubits,"m_collector.bsm_cnt",m_collector.bsm_cnt-1)
        assert m == forced_outcome, f"Forced outcome is different than actual outcome,{forced_outcome},{m_collector.bsm_list},{m_collector.bsm_cnt-1}"
        return m, prob

    def forced_my_measure(self, qubit, observable):
        # forced_outcome=m_collector.bsm_list[m_collector.bsm_cnt]
        # m_collector.bsm_cnt+=1
        forced_outcome = self.get_forced_outcome()

        # Do forced outcome here
        m, prob = my_measure(qubit, observable, rng_measure=ForcedRNG(forced_outcome))
        # print("forced_my_measure m",m,"prob",prob,"forced_outcome",forced_outcome,"qubit",qubit,"m_collector.bsm_cnt",m_collector.bsm_cnt-1)
        assert m == forced_outcome, "Forced outcome is different than actual outcome"
        return m, prob

    def store_meas_outcome(self, m):
        if self.name in m_collector.bsm_dict:
            m_collector.bsm_dict[self.name].append(m)
        else:
            m_collector.bsm_dict[self.name] = [m]


class LeafPhotonicProcessing(QuantumChannel):
    """Implement the required photonic qubit gates for leaf photons here. 
    Modeled by quantum channel because photonic gates are performed by passive linear optic elements 
    """

    def __init__(self, name, delay=0):
        super().__init__(name=name, delay=delay)

    def preprocess_inputs(self, delay, qubits):
        # print(f"{ns.sim_time():.1f}:delay {delay},qubits {qubits}")
        # print("before",qubits[0].qstate.qrepr.check_matrix)
        operate(qubits[0], H)
        # print("after",qubits[0].qstate.qrepr.check_matrix)
        # return qubits
        return super().preprocess_inputs(delay, qubits)


class CorePhotonicProcessing(QuantumChannel):
    """Implement the required photonic qubit gates for core photons here. 
    Also, implement sufficient delay time such that core photons would arrive at measurement nodes after leaf photons.
    Modeled by quantum channel because photonic gates are performed by passive linear optic elements
    """

    def __init__(self, name, delay=0):
        super().__init__(name=name, delay=delay)

    def preprocess_inputs(self, delay, qubits):
        # operate(qubits[0], Rz)
        # return qubits
        return super().preprocess_inputs(delay, qubits)

# class EndNodePhotonicProcessing(QuantumChannel):
#    """Implement the required photonic qubit gates for leaf photons here.
#    Modeled by quantum channel because photonic gates are performed by passive linear optic elements
#    """
#    def __init__(self, name, delay=0,depolarize_prob=0):
#        super().__init__(name=name,delay=delay)
#        self.depolarize_prob=depolarize_prob


class Level2CorePhotonicProcessing(QuantumChannel):
    """Implement the required photonic qubit gates for core photons here. 
    Also, implement sufficient delay time such that core photons would arrive at measurement nodes after leaf photons.
    Modeled by quantum channel because photonic gates are performed by passive linear optic elements
    """

    def __init__(self, name, delay=0):
        super().__init__(name=name, delay=delay)

    def preprocess_inputs(self, delay, qubits):
        operate(qubits[0], H)
        # return qubits
        return super().preprocess_inputs(delay, qubits)
