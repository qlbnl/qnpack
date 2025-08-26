import logging
import netsquid as ns
import netsquid.components.instructions as instr
from netsquid.protocols import NodeProtocol, Signals, LocalProtocol
from qnpack.APE.lib.params import APEParams
from qnpack.APE.lib.programs import (
    EmitterAncillaInitProgram,
    EndNodeEmitterInitProgram,
    EmitterInitProgram,
    INSTR_EMIT_PHOTON,
    my_INSTR_MEASURE_X,
    my_INSTR_MEASURE_Y,
    my_INSTR_MEASURE_Z
)
from qnpack.APE.lib.models import m_collector
from qnpack.APE.lib.drawGS import plot_qubit_graph_without_split, pick_entangled_qubits
from qnpack.APE.lib.verification import verification

log = logging.getLogger(__name__)


class ControlProtocol(NodeProtocol):
    """Protocol on control node to receive measurement results and send to the end node
    """

    def __init__(self, cfg, node, num_repeater, name=None):
        # name = name if name else "ControlProtocol{}".format(node.name)
        self.meas_results = {}
        self.num_repeater = num_repeater
        self.cfg = cfg
        super().__init__(node=node, name=name)

    def run(self):
        log.debug('control protocol is run')
        yield from self.recv_ctrl_msg()
        log.debug("In control protocol, msg are received from all BSM nodes:", self.meas_results)
        # verify=verification(num_repeater,self.cfg.rgs.num_branches_half,data_noise["CRP_result"])
        verify = verification(self.num_repeater, self.cfg.rgs.num_branches_half, self.meas_results)
        verify.start()
        qrepr_veri = verify.get_expected_Bell_pair()
        log.debug("qrepr_veri inside control protocol", qrepr_veri)
        self.send_ctrl_msg(nname="a", msg=qrepr_veri)
        self.send_ctrl_msg(nname="b", msg=qrepr_veri)
        log.debug("Complete sending ctrl msg")

    def send_ctrl_msg(self, nname, msg=""):
        self.node.ports[f"cport_to_{nname}"].tx_output(msg)

    def recv_ctrl_msg(self):  # what is supposed to input into nodes? can I just use num_repeater?
        ev_expr = None
        num_bsm = self.num_repeater+1
        for n in range(num_bsm):
            cport = self.node.ports[f"cport_from_bsm{n}"]
            ev_expr |= self.await_port_input(cport)
        waiting = num_bsm*2  # Each bsm contains two protocols (left and right) to send message to control node
        while waiting:
            log.debug("waiting for message in control node", ev_expr)
            yield ev_expr
            log.debug("one message in control node arrived")
            rport = ev_expr.triggered_events[0].source
            res = rport.rx_input()
            protocol, result = res.items[0]
            log.debug('rport', rport, "res", res, "res.items[0]", res.items[0])
            self.meas_results[protocol] = result
            waiting -= 1


class EndNodeEmissionProtocol(NodeProtocol):
    """Protocol on end node to emit photon from memory qubit.
    end_dir="left"
    neighbor_node_dir_to=["right","left","right","left","right","left"]
    """

    def __init__(self, cfg, node,  num_matter_qubit, end_dir, neighbor_node_dir_to, name=None):
        name = name if name else "EndNodeEmissionProtocol{}".format(node.name)
        self.num_matter_qubit = num_matter_qubit
        self.end_dir = end_dir
        if end_dir == "left":
            self.send_dir = "right"
        else:
            self.send_dir = "left"

        self.neighbor_node_dir_to = neighbor_node_dir_to
        self.leaf_photon_clock_time = APEParams.leaf_photon_clock_time(cfg)
        super().__init__(node=node, name=name)

    def run(self):
        # Reset the emitted_photon_cnt to be used for naming photons in IEmitPhoton
        self.node.qmemory.properties["emitted_photon_cnt"] = 0
        self.matter_qubit_index = 0
        clock = self.node.subcomponents["clock"]
        clock.start()
        qproc = self.node.qmemory
        for i in range(len(self.neighbor_node_dir_to)):
            # Waiting for clock signal at fixed time interval
            yield self.await_port_output(clock.ports["cout"])
            if self.end_dir == self.neighbor_node_dir_to[i]:
                # print(f"{ns.sim_time():.1f} Receive clock signal in end node {self.node.name}. Delay to emit photon at the same time as each leaf photon clock is emitted in ape node")
                yield self.await_timer(duration=self.leaf_photon_clock_time)
                # print(f"{ns.sim_time():.1f} After delay, ready to initialize in end node {self.node.name}.")

                # Initialize matter qubit
                qproc.execute_program(EndNodeEmitterInitProgram(), qubit_mapping=[self.matter_qubit_index])
                yield self.await_program(qproc)
                # print(self.node.name,"matter_qubit",qproc.peek([self.matter_qubit_index]))

                # Send clock message
                self.node.ports[f"cport_clock_to_{self.send_dir}"].tx_output("trigger_BSM")
                # print(f"{ns.sim_time():.1f}: End node {self.node.name} sends BSM clock message to {self.send_dir} measurement node")

                # Emission of one photon from emitter, output at "qout{i}" of quantum processor
                # print(f"{ns.sim_time():.1f}: Emitter {qproc.peek(self.matter_qubit_index)} at {self.node.name} is going to emit photon")
                qproc.execute_instruction(INSTR_EMIT_PHOTON, [self.matter_qubit_index])
                yield self.await_program(qproc)
                # print(f"{ns.sim_time():.1f}: one photon is emitted from emitter at {self.node.name}")
                qproc.execute_instruction(instr.INSTR_H, [self.matter_qubit_index])
                yield self.await_program(qproc)
                self.matter_qubit_index += 1
            # else:
                # print(f"{ns.sim_time():.1f}:No need to emit photon from end node {self.node.name}")
        # if self.node.name=='node_b':
            # print(f"{ns.sim_time():.1f}: node b waiting results output")
            # yield self.await_port_input(self.node.ports["cport_receive_result"])
            # print(f"{ns.sim_time():.1f}: results recieved in node_b from bsm0")
            # qproc.execute_instruction(instr.INSTR_MEASURE,[0])
            # qproc.execute_instruction(INSTR_EMIT_PHOTON, [0])

        # yield from self.recv_ctr_msg()
        clock.reset()

    def recv_ctr_msg(self):
        cport = self.node.ports[f"cport_from_control"]
        ev_expr = self.await_port_input(cport)
        yield ev_expr
        rport = ev_expr.triggered_events[0].source
        res = rport.rx_input()
        protocol, result = res.items[0]
        print('rport', rport, "res", res, "res.items[0]", res.items[0])


class GraphStateEmissionProtocol(NodeProtocol):
    """Protocol on apeqr node to emit the whole repeater graph state with 2-level tree encoded core qubits.
    """
    PostProcessingResult = {}

    def __init__(self, cfg, node, dir_to, b0, b1, name=None, is_manual_noise=False):
        self.cfg = cfg
        name = name if name else "EmissionProtocol{}".format(node.name)
        self.dir_seq = dir_to
        # self.measurement_outcome_ls = []
        self.b0 = b0
        self.b1 = b1
        self.is_manual_noise = is_manual_noise
        super().__init__(node=node, name=name)
        # print(f"{self.name} is initializing")

    def run(self):
        # print(f"{self.name} is running")
        # Reset the emitted_photon_cnt to be used for naming photons in IEmitPhoton
        self.node.qmemory.properties["emitted_photon_cnt"] = 0
        self.measurement_outcome_ls = []
        # Create Graph State source by quantum processor here, position[0,1]=[emitter, ancilla]
        clock = self.node.subcomponents["clock"]
        clock.start()
        switch = self.node.subcomponents["switch"]
        qproc = self.node.qmemory
        # print(f"{self.name}: dir_seq is {self.dir_seq}")

        for i in range(len(self.dir_seq)):  # len(self.dir_seq)=number of branches in RGS
            dir = self.dir_seq[i]
            # Waiting for clock signal at fixed time interval
            yield self.await_port_output(clock.ports["cout"])
            branch_size = 1+self.b0+self.b0*self.b1
            # print(f"{ns.sim_time():.1f}: (Photons {i*branch_size+1} to {(i+1)*branch_size} of RGS) Start GS gen process at {self.node.name}")
            for k in range(self.b0):
                emitter = qproc.peek(0)[0]
                # print(self.name, "before initialization,emitter is",emitter)
                # print(f'{ns.sim_time():.1f}:{k+1}-th subtree out of {self.b0} in 1st level')
                if k == 0:
                    # Start initialization of emitter and ancilla_1
                    qproc.execute_program(EmitterAncillaInitProgram(), qubit_mapping=[0, 1])
                    yield self.await_program(qproc)
                    # print(f'{ns.sim_time():.1f}:initialization of emitter in {self.node.name}')
                else:
                    qproc.execute_program(EmitterInitProgram(), qubit_mapping=[0, 1])
                    yield self.await_program(qproc)

                emitter = qproc.peek(0)[0]
                # print(self.name, "after initialization, emitter is",emitter)
                for j in range(self.b1+1):
                    if j == self.b1:  # Trigger optical switch for level1 core photon
                        switch.topology = {'switch_in': f'switch_out_{dir}_level1_core'}
                    else:
                        # Trigger optical switch for level2 core photon
                        switch.topology = {'switch_in': f'switch_out_{dir}_level2_core'}
                    # print(f'{ns.sim_time():.1f}:Trigger optical switch port switch_in to switch_out_{dir}_core in {self.node.name}')

                    # Send clock message to measurement node to trigger single-photon detector(SPD).
                    self.node.ports[f"cport_clock_to_{dir}"].tx_output("trigger_SPD")
                    # print(f"{ns.sim_time():.1f}: {self.node.name} sends SPD clock message to {dir} measurement node")

                    # if self.is_manual_noise: #Manual emitter noise for debugging purpose
                    #    if i==0 and k==0 and j==0:
                    #        #print(f'{ns.sim_time():.1f}:apply manual emitter Z error')
                    #        qproc.execute_instruction(instr.INSTR_Z, [0])
                    #        yield self.await_program(qproc)
                    #        #print(f"{ns.sim_time():.1f}: Emitter {qproc.peek(0)} at {self.node.name} is going to emit photon")

                    # Emission of one core photon from emitter, output at "qout0" of quantum processor
                    # print(f"{ns.sim_time():.1f}: Emitter {qproc.peek(0)} at {self.node.name} is going to emit photon")
                    qproc.execute_instruction(INSTR_EMIT_PHOTON, [0])

                    # Waiting for completed emission of core photon
                    yield self.await_program(qproc)
                    # print(f"{ns.sim_time():.1f}: one level-2 core photon is emitted from emitter at {self.node.name}")

                    # Add buffer time between each core photon emission
                    yield self.await_timer(duration=self.cfg.emitter.photon_emission_buffer)

                # Hadamard gate on emitter qubit
                qproc.execute_instruction(instr.INSTR_H, [0])
                yield self.await_program(qproc)
                # print(f"{ns.sim_time():.1f}:H on emitter is finished")

                # Measurement of emitter qubit
                # m0 = qproc.execute_instruction(instr.INSTR_MEASURE, [0], output_key="M0")
                m0 = qproc.execute_instruction(my_INSTR_MEASURE_Z, [0], output_key="M0")
                yield self.await_program(qproc)
                # print(f"{ns.sim_time():.1f}:Z-measurement result of emitter qubit= {m0[0]['M0']}. Need to send to measurement node for postprocessing, to be updated later.")
                self.measurement_outcome_ls.append(('z0', m0[0]['M0']))

            qproc.execute_program(EmitterInitProgram(), qubit_mapping=[0, 1])
            yield self.await_program(qproc)

            # Send clock message to measurement node to trigger BSM detector
            self.node.ports[f"cport_clock_to_{dir}"].tx_output("trigger_BSM")
            # print(f"{ns.sim_time():.1f}: {self.node.name} sends BSM clock message to {dir} measurement node")

            # Trigger optical switch for leaf photon
            switch.topology = {'switch_in': f'switch_out_{dir}_leaf'}
            # print(f'{ns.sim_time():.1f}:Trigger optical switch port switch_in to switch_out_{dir}_leaf in {self.node.name}')

            # Emission of one leaf photon from emitter, output at "qout0" of quantum processor
            # print(f"{ns.sim_time():.1f}: Emitter {qproc.peek(0)} at {self.node.name} is going to emit photon")
            qproc.execute_instruction(INSTR_EMIT_PHOTON, [0])
            yield self.await_program(qproc)
            # print(f"{ns.sim_time():.1f}: one leaf photon is emitted from emitter at {self.node.name}")

            if i == 0:
                qproc.execute_program(EndNodeEmitterInitProgram(), qubit_mapping=[2])
                yield self.await_program(qproc)
                # print(f"{ns.sim_time():.1f}: ancilla2 is initialized {self.node.name}")

            if self.is_manual_noise:  # Manual emitter noise for debugging purpose
                if i == 0:
                    print(f'{ns.sim_time():.1f}:apply manual emitter Z error before CZ between emitter and ancilla 2')
                    qproc.execute_instruction(instr.INSTR_Z, [0])
                    yield self.await_program(qproc)

            qproc.execute_instruction(instr.INSTR_CZ, [0, 2])
            yield self.await_program(qproc)
            # print(f"{ns.sim_time():.1f}: CZ between ancilla1 and ancilla2 {self.node.name}")

            m1 = qproc.execute_instruction(my_INSTR_MEASURE_X, [1], output_key="M1")
            yield self.await_program(qproc)
            # print(f"{ns.sim_time():.1f}:X-measurement result of ancilla1 qubit= {m1[0]['M1']}. Need to send to measurement node for postprocessing, to be updated later.")
            # Measurement
            m0 = qproc.execute_instruction(my_INSTR_MEASURE_X, [0], output_key="M0")
            yield self.await_program(qproc)
            # print(f"{ns.sim_time():.1f}:X-measurement result of emitter qubit= {m0[0]['M0']}. Need to send to measurement node for postprocessing, to be updated later.")
            self.measurement_outcome_ls.append(('x0', m0[0]['M0']))
            self.measurement_outcome_ls.append(('x1', m1[0]['M1']))

            # ancilla2=qproc.peek(2)[0]
            # plot_qubit_graph(ancilla2)

        # qproc.execute_instruction(INSTR_Rx, [2])
        # yield self.await_program(qproc)
        # print(f"{ns.sim_time():.1f}:Rx gate on ancilla2 qubit.")

        ancilla2 = qproc.peek(2)[0]
        # print("ancilla 2 state",ancilla2.qstate.qubits,ancilla2.qstate.indices_of(ancilla2.qstate.qubits),ancilla2.qstate.qrepr)
        # picked_qstate, picked_qubits = pick_entangled_qubits(ancilla2)
        # print("ancilla2",picked_qstate, picked_qubits)
        # plot_qubit_graph_without_split(ancilla2)
        m2 = qproc.execute_instruction(my_INSTR_MEASURE_Y, [2], output_key="M2")
        yield self.await_program(qproc)
        # print(f"{ns.sim_time():.1f}:Y-measurement result of ancilla2 qubit= {m2[0]['M2']}. Need to send to measurement node for postprocessing, to be updated later.")
        self.measurement_outcome_ls.append(('y2', m2[0]['M2']))
        # print(f"{ns.sim_time():.1f}: set another seed from here")
        # ns.set_random_state(seed=1)
        GraphStateEmissionProtocol.PostProcessingResult[f"{self.name}"] = self.measurement_outcome_ls
        clock.reset()


class ClockRecvProtocol(NodeProtocol):
    """Protocol on measurement node to receive clock message from ape node, and signal to leaf_recv_protocol or core_recv_protocol.
    Photon_table is stored in the protocol when the class instance is created. It allows the protocol to know whether the arriving 
    photon is a core or leaf photon in the repeater graph state depending on its clock arrival sequence.
    For instance, for 12 qubit repeater graph state, left_photon_table,right_photon_table=["core","leaf","core","leaf","core","leaf"]
    If one side is end node, left_photon_table=["leaf","leaf","leaf"]
    How do we keep it general even with end node as one side??
    """
    # seed_reset=True

    def __init__(self, node, left_photon_table, right_photon_table, name=None):
        # print(f"{self.name} is initializing")
        super().__init__(node, name)
        self.left_photon_table = left_photon_table
        self.right_photon_table = right_photon_table
        # self.left_clock_cnt = 0
        # self.right_clock_cnt = 0
        self.leaf_recv_label = "trigger_leaf_recv_protocol"
        self.add_signal(self.leaf_recv_label)
        self.left_core_recv_label = "trigger_left_core_recv_protocol"
        self.add_signal(self.left_core_recv_label)
        self.right_core_recv_label = "trigger_right_core_recv_protocol"
        self.add_signal(self.right_core_recv_label)

    def run(self):
        self.left_clock_cnt = 0
        self.right_clock_cnt = 0
        # print(f"{self.name} is running")
        left_port = self.node.ports["cport_clock_from_left"]
        right_port = self.node.ports["cport_clock_from_right"]
        left_clock_arrived = False
        right_clock_arrived = False
        wait_left_clock = self.await_port_input(left_port)
        wait_right_clock = self.await_port_input(right_port)

        while True:
            # print(f"{self.name} waiting for clock signal")
            evexpr = yield wait_left_clock | wait_right_clock
            # Delete this later
            # To set seed after the first clock signal(should be the core clock) arrived on each clock_receive_protocol
            # if ClockRecvProtocol.seed_reset:
            #    print(f"{ns.sim_time():.1f}: set another seed from here")
            #    ns.set_random_state(seed=ClockRecvProtocol.seed)
            #    ClockRecvProtocol.seed_reset=False
            if evexpr.first_term.value:
                # print(f"{ns.sim_time():.1f}: {self.node.name} received clock message from left ape node. According to photon table, {self.left_photon_table[self.left_clock_cnt]} photon would arrive soon")
                left_clock_arrived = True
                # left_clock_arrived_time = ns.sim_time()
                if self.left_photon_table[self.left_clock_cnt] == "level1_core" or self.left_photon_table[self.left_clock_cnt] == "level2_core":
                    self.send_signal(self.left_core_recv_label)
                    self.left_clock_cnt += 1
                    left_clock_arrived = False

            else:
                # print(f"{ns.sim_time():.1f}:{self.node.name} received clock message from right ape node. According to photon table, {self.right_photon_table[self.right_clock_cnt]} photon would arrive soon")
                right_clock_arrived = True
                # right_clock_arrived_time = ns.sim_time()
                if self.right_photon_table[self.right_clock_cnt] == "level1_core" or self.right_photon_table[self.right_clock_cnt] == "level2_core":
                    self.send_signal(self.right_core_recv_label)
                    self.right_clock_cnt += 1
                    right_clock_arrived = False

            if left_clock_arrived & right_clock_arrived:
                # print("left_clock_arrived & right_clock_arrived in clockrecvproto")
                # here we assume leaf clock signal from left and right arrive at the same time.
                if self.left_photon_table[self.left_clock_cnt] == "leaf" and self.right_photon_table[self.right_clock_cnt] == "leaf":
                    self.send_signal(self.leaf_recv_label)
                    # Iterate clock count and reset clock_arrived flags
                    self.left_clock_cnt += 1
                    self.right_clock_cnt += 1
                    left_clock_arrived = False
                    right_clock_arrived = False
                else:
                    raise Exception("Clock signal unmatched:arrived at the same time")


class LeafRecvProtocol(NodeProtocol):
    """ Protocol on measurement node to receive leaf photons for BSM
    """

    def __init__(self, cfg, node, clock_recv_protocol, name=None):
        self.cfg = cfg
        # print(f"{self.name} is initializing")
        super().__init__(node, name)
        # self.add_subprotocol(qubit_protocol, 'qprotocol')
        self.bsm_detector = self.node.subcomponents["bsm_detector"]
        self.bsm_result = []
        self.bsm_finished_label = "bsm_finished"
        self.add_signal(self.bsm_finished_label)
        # self.add_subprotocol(clock_recv_protocol,"clock_recv_protocol")
        self.clock_recv_protocol = clock_recv_protocol
        self.add_signal(self.clock_recv_protocol.leaf_recv_label)

    def run(self):
        # print(f"{self.name} is running")
        # clock_recv_protocol=self.subprotocols["clock_recv_protocol"]
        clock_recv_protocol = self.clock_recv_protocol

        while True:
            yield self.await_signal(clock_recv_protocol, clock_recv_protocol.leaf_recv_label)
            # Trigger switch
            self.node.subcomponents["switch_left"].topology = {"switch_in": "switch_out_leaf"}
            self.node.subcomponents["switch_right"].topology = {"switch_in": "switch_out_leaf"}
            # print(f"{ns.sim_time():.1f}: switch input is triggered for leaf photons in {self.node.name}")
            # Trigger BSMDetector to start detection window for Bell measurement:
            self.bsm_detector.ports['gate_trigger'].tx_input("trigger_detector")
            # print(f"{ns.sim_time():.1f}: bsm detector is triggered in {self.node.name}")
            wait_detector_dead = self.await_timer(duration=self.cfg.bsm.detection_window)
            port = self.bsm_detector.ports['cout0']
            wait_detected = self.await_port_output(port)
            evexpr = yield wait_detector_dead | wait_detected
            # Signal BSM result
            if evexpr.second_term.value:
                m = port.rx_output().items[0]
                self.bsm_result.append(m)
                # print(f"{ns.sim_time():.1f}: {self.name} Measurement outcome in BSM is {m}")
                # self.send_signal(self.bsm_finished_label,result=(m))
                self.send_signal(self.bsm_finished_label, result=(m))
            else:
                # print(f"{ns.sim_time():.1f}: {self.name} No photon is detected within BSM detection window")
                self.send_signal(self.bsm_finished_label, result=("No photon detected in BSM"))


class CoreRecvProtocol(NodeProtocol):
    """ Protocol on measurement node to receive core photons for single-photon measurement. 
    The measurement basis of each core photon depends on the BSM outcome of the corresponding leaf photons. 
    i.e. On each measurement node, if BSM is successful on any one of the leaf photons pair, 
         measure the corresponding core photon in X-basis, and all the other core photons in Z-basis.
    """
    PostProcessingResult = {}
    logical_z_fail_cnt = 0
    logical_z_cnt = 0
    logical_x_fail_cnt = 0
    logical_x_cnt = 0

    def __init__(self, cfg, node, leaf_recv_protocol, clock_recv_protocol, dir_from, rgs_size, b0, b1, name=None):
        self.cfg = cfg
        # print(f"{self.name} is initializing")
        super().__init__(node, name)
        self.add_subprotocol(leaf_recv_protocol, "leaf_recv_protocol")
        self.add_signal(leaf_recv_protocol.bsm_finished_label)
        self.single_detector_Z = self.node.subcomponents[f"single_detector_Z_{dir_from}"]  # Measurement basis is Z
        self.single_detector_X = self.node.subcomponents[f"single_detector_X_{dir_from}"]  # Measurement basis is X
        self.dir_from = dir_from
        self.rgs_size = rgs_size
        self.b0 = b0
        self.b1 = b1
        self.add_subprotocol(clock_recv_protocol, "clock_recv_protocol")
        if dir_from == "left":
            await_clock_label = clock_recv_protocol.left_core_recv_label
        else:
            await_clock_label = clock_recv_protocol.right_core_recv_label
        self.add_signal(await_clock_label)
        # self.bsm_result_ls = []
        # self.spd_result_ls = []
        # self.bsm_succeed = False

    def spd_z(self):
        self.node.subcomponents[f"switch_{self.dir_from}"].topology = {"switch_in": "switch_out_core_Z"}
        detector = self.node.subcomponents[f"single_detector_Z_{self.dir_from}"]
        # print(f"{ns.sim_time():.1f}: SPD_Z is triggered")
        detector.ports["gate_trigger"].tx_input("trigger_detector")
        return detector, "z"

    def spd_x(self):
        self.node.subcomponents[f"switch_{self.dir_from}"].topology = {"switch_in": "switch_out_core_X"}
        detector = self.node.subcomponents[f"single_detector_X_{self.dir_from}"]
        detector.ports["gate_trigger"].tx_input("trigger_detector")
        # print(f"{ns.sim_time():.1f}: SPD_X is triggered")
        return detector, "x"

    def spd_x_level1(self):
        self.node.subcomponents[f"switch_{self.dir_from}"].topology = {"switch_in": "switch_out_core_X_level1"}
        detector = self.node.subcomponents[f"single_detector_X_level1_{self.dir_from}"]
        detector.ports["gate_trigger"].tx_input("trigger_detector")
        # print(f"{ns.sim_time():.1f}: SPD_X_level1 is triggered")
        return detector, "x"

    def spd_operating(self, basis):
        assert basis == "X" or basis == "X_level1" or basis == "Z", "spd_operating() has unrecognized basis"
        if basis == "X":
            sp_detector, sp_detector_basis = self.spd_x()
        elif basis == "X_level1":
            sp_detector, sp_detector_basis = self.spd_x_level1()
        else:
            sp_detector, sp_detector_basis = self.spd_z()

        detector_dead = False
        detected = False
        wait_detector_dead = self.await_timer(
            duration=self.cfg.spd.detection_window + self.cfg.emitter.photon_emission_buffer)
        port = sp_detector.ports['cout0']
        wait_detected = self.await_port_output(port)
        while not detector_dead:
            evexpr_detector = yield wait_detector_dead | wait_detected
            # Store measurement result
            if evexpr_detector.second_term.value:
                spd_result = port.rx_output().items[0]
                # print(f"{ns.sim_time():.1f}:In node {self.node.name},Measurement outcome in SPD is {spd_result}")
                self.spd_tree_result_ls.append(spd_result)
                detected = True
            else:
                if not detected:
                    spd_result = "No photon detected in SPD"
                    # print(f"{ns.sim_time():.1f}:In node {self.node.name}, SPD doesn't detect any photon during detection window from direction {self.dir_from}")
                    self.spd_tree_result_ls.append(spd_result)
                    # self.spd_succeed=False
                # print(f"{ns.sim_time():.1f}:In node {self.node.name}, SPD dead now")
                detector_dead = True

    def logical_z_core(self):
        # print("Start doing logical_z_core")
        for i in range(self.b0):
            for j in range(self.b1):
                yield from self.spd_operating("X")
            yield from self.spd_operating("Z")
            yield self.await_timer(duration=APEParams.time_between_level1_subtrees(self.cfg))
        self.spd_result_ls.append(('z', self.cal_logical_z_outcome(self.spd_tree_result_ls)))

    def logical_x_core(self):
        # print("Start doing logical_x_core")
        for i in range(self.b0):
            for j in range(self.b1):
                yield from self.spd_operating("Z")
            yield from self.spd_operating("X_level1")
            yield self.await_timer(duration=APEParams.time_between_level1_subtrees(self.cfg))
        self.spd_result_ls.append(('x', self.cal_logical_x_outcome(self.spd_tree_result_ls)))

    def cal_logical_z_outcome(self, tree_ls):
        CoreRecvProtocol.logical_z_cnt += 1
        # print("tree_ls inside cal_logical_z_outcome()",tree_ls)
        level1_z_ls = []
        b0 = self.b0
        b1 = self.b1
        for i in range(b0):
            direct_z = tree_ls[(i+1)*(b1+1)-1]
            indirect_z_cnt0 = tree_ls[i*(b1+1):(i+1)*(b1+1)-1].count(0)
            indirect_z_cnt1 = tree_ls[i*(b1+1):(i+1)*(b1+1)-1].count(1)
            # Take majority vote
            if indirect_z_cnt0 > indirect_z_cnt1:
                indirect_z = 0
            elif indirect_z_cnt0 < indirect_z_cnt1:
                indirect_z = 1
            else:
                indirect_z = "undetermined"
            # Choose outcome of indirect_z over direct_z if both contain outcome
            if indirect_z == 0 or indirect_z == 1:
                level1_z_result = indirect_z
            elif indirect_z == "undetermined" and (direct_z == 0 or direct_z == 1):
                level1_z_result = direct_z
            else:
                level1_z_result = "failed"
                self.spd_succeed = False
                CoreRecvProtocol.logical_z_fail_cnt += 1
                return level1_z_result
            level1_z_ls.append(level1_z_result)
        logical_z = (sum(level1_z_ls)) % 2
        # if logical_z==1:
        #    print("tree_ls",tree_ls,"level1_z_ls",level1_z_ls,"logical_z",logical_z)
        return logical_z

    def cal_logical_x_outcome(self, tree_ls):
        CoreRecvProtocol.logical_x_cnt += 1
        # print("tree_ls inside cal_logical_x_outcome()",tree_ls)
        logical_x_ls = []
        b0 = self.b0
        b1 = self.b1
        for i in range(b0):
            subtree_ls = tree_ls[i*(b1+1):(i+1)*(b1+1)]
            # print("subtree_ls",subtree_ls)
            subtree_cnt0 = subtree_ls.count(0)
            subtree_cnt1 = subtree_ls.count(1)
            # Search for any photon loss in the whole subtree
            if (subtree_cnt0+subtree_cnt1) != len(subtree_ls):
                logical_x_ls.append("failed")
            else:
                logical_x_ls.append(subtree_cnt1 % 2)
        # print("logical_x_ls inside cal_logical_x_outcome()",logical_x_ls)
        logical_x_cnt0 = logical_x_ls.count(0)
        logical_x_cnt1 = logical_x_ls.count(1)
        if logical_x_cnt0 == 0 and logical_x_cnt1 == 0:
            logical_x = "failed"
            self.spd_succeed = False
            CoreRecvProtocol.logical_x_fail_cnt += 1
        # Take majority vote here
        elif logical_x_cnt0 > logical_x_cnt1:
            logical_x = 0
        elif logical_x_cnt0 < logical_x_cnt1:
            logical_x = 1
        else:  # when tie
            logical_x = "failed"
            self.spd_succeed = False
            CoreRecvProtocol.logical_x_fail_cnt += 1
            # index_0=logical_x_ls.index(0)
            # index_1=logical_x_ls.index(1)
            # if index_0<index_1:
            #    logical_x=0
            # else:
            #    logical_x=1
        # if logical_x==1:
        # print("tree_ls",tree_ls,"logical_x_ls",logical_x_ls,"logical_x",logical_x)
        # print("tree_ls",tree_ls,"logical_x",logical_x)
        return logical_x

    def run(self):
        # print(f"{self.name} is running")
        self.bsm_result_ls = []
        self.spd_result_ls = []  # for logical core result
        self.bsm_succeed = False
        self.spd_succeed = True
        leaf_recv_protocol = self.subprotocols["leaf_recv_protocol"]
        # leaf_recv_protocol.start()
        clock_recv_protocol = self.subprotocols["clock_recv_protocol"]
        # clock_recv_protocol.start()
        while True:
            for _ in range(int(self.rgs_size/2)):
                self.spd_tree_result_ls = []  # for physical qubits result
                if self.dir_from == "left":
                    yield self.await_signal(clock_recv_protocol, clock_recv_protocol.left_core_recv_label)
                else:
                    yield self.await_signal(clock_recv_protocol, clock_recv_protocol.right_core_recv_label)
                # print(f"{ns.sim_time():.1f}: In node {self.node.name}, core_recv_protocol_{self.dir_from} receives signal from clock_recv_protocol")
                core_delayed_flag = False
                bsm_result_flag = False
                core_delayed = self.await_timer(duration=APEParams.core_photon_delay(self.cfg) + 1)
                bsm_result = self.await_signal(leaf_recv_protocol, leaf_recv_protocol.bsm_finished_label)
                while True:
                    evexpr = yield bsm_result | core_delayed
                    if evexpr.first_term.value:
                        bsm_result_flag = True
                        # print(f"{ns.sim_time():.1f}: BSM result has arrived")
                        m = leaf_recv_protocol.get_signal_result(leaf_recv_protocol.bsm_finished_label, self)
                        # print(f"{ns.sim_time():.1f}:bsm_finished_label is received by {self.name} with outcome {m}")
                        self.bsm_result_ls.append(m)
                    elif evexpr.second_term.value:
                        core_delayed_flag = True
                        # print(f"{ns.sim_time():.1f}: core photon delay time has reached") ##NOT executed right now, need to fix!!

                    if bsm_result_flag & core_delayed_flag:
                        # After bsm result of leaf photons arrived and core photon delay time has reached, trigger single photon detector in Z or X basis
                        # depending on the bsm result:
                        if self.bsm_succeed:
                            yield from self.logical_z_core()
                            # print(f"{ns.sim_time():.1f}: BSM succeeded at previous leaf photon. SPD in Z basis is triggered for core photons arriving from {self.dir_from} in {self.node.name}")
                        elif m == 2 or m == 3:
                            yield from self.logical_z_core()
                            # print(f"{ns.sim_time():.1f}: BSM fails. SPD in Z basis is triggered for core photons arriving from {self.dir_from} in {self.node.name}")
                        # elif m == "No photon detected in BSM" or m == "One photon detected in BSM":  # Add here single photon detected
                        elif m == "No photon detected in BSM" or m in [4, 5, 6, 7]:
                            yield from self.logical_z_core()
                            # print(f"{ns.sim_time():.1f}: Fewer than 2 photons arrived at BSM. SPD in Z basis is triggered for core photons arriving from {self.dir_from} in {self.node.name}")
                        elif m == 0 or m == 1:
                            yield from self.logical_x_core()
                            self.bsm_succeed = True
                            # print(f"{ns.sim_time():.1f}: Since BSM succeeds for the leaf photon, SPD in X basis is triggered for the",
                            # f"corresponding core photons (which is connected to the leaf photon in GS) arriving from {self.dir_from} in {self.node.name}")
                        else:
                            raise ValueError(f'Unknown signal is received in {self.name}')
                        # print(f"{ns.sim_time():.1f}:self.spd_tree_result_ls after logical z/x core{self.spd_tree_result_ls}")
                        break
            result = (self.bsm_succeed, self.bsm_result_ls, self.spd_succeed,
                      self.spd_result_ls)  # Need to modify spd_succeed
            self.send_signal(Signals.SUCCESS, result=result)

            # Announce measurement results from the bsm node to the control node
            log.debug(f"{ns.sim_time():.1f}:sending results from bsm to control node, {self.name},{result}")
            self.node.ports[f"cport_to_control"].tx_output((self.name, result))
            CoreRecvProtocol.PostProcessingResult[f"{self.name}"] = result  # Need to handle majority vote later
            # Store logical results of core qubits of each CRP
            m_collector.core_logical_result[f"{self.name}"] = self.spd_result_ls
            # print(f"{ns.sim_time():.1f}: From {self.name}, bsm_result_ls {self.bsm_result_ls},spd_result_ls {self.spd_result_ls}")


def setup_repeater_protocol(cfg, network, bsm_nodes, ape_nodes, end_ape_nodes, rgs_size, num_repeater, is_manual_noise):
    """Setup repeater protocol on repeater chain network.

    Parameters
    ----------
    network : :class:`~netsquid.nodes.network.Network`
        Repeater chain network to put protocols on.

    Returns
    -------
    :class:`~netsquid.protocols.protocol.Protocol`
        Protocol holding all subprotocols used in the network.

    """
    b0 = cfg.rgs.b0
    b1 = cfg.rgs.b1
    protocol_name = f"local_protocol_for_{network.name}"
    protocol = LocalProtocol(nodes=network.nodes)
    num_matter_qubit = int(rgs_size/2)
    # Add SwapProtocol to all repeater nodes. Note: we use unique names,
    # since the subprotocols would otherwise overwrite each other in the main protocol.
    ape_photon_table = ((["level2_core"]*b1+["level1_core"])*b0+["leaf"])*int(rgs_size/2)
    end_photon_table = ["leaf"]*int(rgs_size/2)

    # Set up control node protocol
    control_protocol = ControlProtocol(cfg, network.get_node("node_c"), num_repeater)
    protocol.add_subprotocol(control_protocol)

    # Set up end node protocols
    end_node_emission_protocol_a = EndNodeEmissionProtocol(cfg, network.get_node(
        "node_a"), num_matter_qubit=num_matter_qubit, end_dir="left", neighbor_node_dir_to=["right", "left"]*int(rgs_size/2))
    if num_repeater % 2 == 1:
        end_node_emission_protocol_b = EndNodeEmissionProtocol(cfg, network.get_node(
            "node_b"), num_matter_qubit=num_matter_qubit, end_dir="right", neighbor_node_dir_to=["right", "left"]*int(rgs_size/2))
    else:
        end_node_emission_protocol_b = EndNodeEmissionProtocol(cfg, network.get_node(
            "node_b"), num_matter_qubit=num_matter_qubit, end_dir="right", neighbor_node_dir_to=["left", "right"]*int(rgs_size/2))
    protocol.add_subprotocol(end_node_emission_protocol_a)
    protocol.add_subprotocol(end_node_emission_protocol_b)

    # Set up ape node protocols
    for i in range(len(ape_nodes)):
        if i % 2 == 0:
            graph_state_emission_protocol = GraphStateEmissionProtocol(cfg, network.get_node(f"node_{ape_nodes[i]}"), dir_to=[
                                                                       "right", "left"]*int(rgs_size/2), b0=b0, b1=b1, name=f"GSEP_{ape_nodes[i]}", is_manual_noise=is_manual_noise)
        else:
            graph_state_emission_protocol = GraphStateEmissionProtocol(cfg, network.get_node(f"node_{ape_nodes[i]}"), dir_to=[
                                                                       "left", "right"]*int(rgs_size/2), b0=b0, b1=b1, name=f"GSEP_{ape_nodes[i]}", is_manual_noise=is_manual_noise)
        protocol.add_subprotocol(graph_state_emission_protocol)

    # Set up bsm node protocols
    for i in range(len(bsm_nodes)):
        bsm_node = network.get_node(f"node_{bsm_nodes[i]}")

        # Here assume ape_nodes>0,bsm_nodes>1
        if i == 0:
            clock_recv_protocol = ClockRecvProtocol(
                bsm_node, left_photon_table=end_photon_table, right_photon_table=ape_photon_table, name=f"ClRP_{bsm_nodes[i]}")
            leaf_recv_protocol = LeafRecvProtocol(cfg, bsm_node, clock_recv_protocol, name=f"LRP_{bsm_nodes[i]}")
            core_recv_protocol_right = CoreRecvProtocol(cfg, bsm_node, leaf_recv_protocol, clock_recv_protocol, dir_from="right",
                                                        rgs_size=rgs_size, b0=b0, b1=b1, name=f"CRPR_{bsm_nodes[i]}")  # don't need this for bsm node connected to right end node
            protocol.add_subprotocol(core_recv_protocol_right)
        elif i == len(bsm_nodes)-1:
            clock_recv_protocol = ClockRecvProtocol(
                bsm_node, left_photon_table=ape_photon_table, right_photon_table=end_photon_table, name=f"ClRP_{bsm_nodes[i]}")
            leaf_recv_protocol = LeafRecvProtocol(cfg, bsm_node, clock_recv_protocol, name=f"LRP_{bsm_nodes[i]}")
            core_recv_protocol_left = CoreRecvProtocol(cfg, bsm_node, leaf_recv_protocol, clock_recv_protocol, dir_from="left",
                                                       rgs_size=rgs_size, b0=b0, b1=b1, name=f"CRPL_{bsm_nodes[i]}")  # don't need this for bsm node connected to left end node
            protocol.add_subprotocol(core_recv_protocol_left)
        else:
            clock_recv_protocol = ClockRecvProtocol(
                bsm_node, left_photon_table=ape_photon_table, right_photon_table=ape_photon_table, name=f"ClRP_{bsm_nodes[i]}")
            leaf_recv_protocol = LeafRecvProtocol(cfg, bsm_node, clock_recv_protocol, name=f"LRP_{bsm_nodes[i]}")
            core_recv_protocol_left = CoreRecvProtocol(cfg, bsm_node, leaf_recv_protocol, clock_recv_protocol, dir_from="left",
                                                       rgs_size=rgs_size, b0=b0, b1=b1, name=f"CRPL_{bsm_nodes[i]}")  # don't need this for bsm node connected to left end node
            core_recv_protocol_right = CoreRecvProtocol(cfg, bsm_node, leaf_recv_protocol, clock_recv_protocol, dir_from="right",
                                                        rgs_size=rgs_size, b0=b0, b1=b1, name=f"CRPR_{bsm_nodes[i]}")  # don't need this for bsm node connected to right end node
            protocol.add_subprotocol(core_recv_protocol_left)
            protocol.add_subprotocol(core_recv_protocol_right)

        # Add as subprotocols
        protocol.add_subprotocol(clock_recv_protocol)
        protocol.add_subprotocol(leaf_recv_protocol)
    # print("all subprotocols:",protocol.subprotocols)

    return protocol
