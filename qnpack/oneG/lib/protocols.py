import logging
import netsquid as ns
from pydynaa import ExpressionHandler
from enum import IntEnum, auto
from netsquid.qubits import ketstates as ks
from netsquid.protocols.nodeprotocols import NodeProtocol, LocalProtocol
from netsquid.components.component import Message
from netsquid.protocols.protocol import Signals
from qnpack.oneG.advanced_ion_trap import AdvRetryEmitProgram, AdvIonTrapSwapProgram
from qnpack.oneG.lib.programs import CorrectionProgram
from qnpack.common.utils import calculate_distances
from qnpack.common.logging import setup_logging
import re


log = logging.getLogger(__name__)
# setup_logging(name=__name__,
#                       level=logging.DEBUG,
#                       logfile=None)

BSM_SUCCESS = [[2], [3]]


class DetectorStatus(IntEnum):
    SUCCESS = auto()
    NOT_DETECTED = auto()
    DETECTOR_FAILURE = auto()


class BSMControlMessage:
    def __str__(self):
        return (f"node: {self.node}, status: {self.status.name}, data: {self.data}, "
                f"retries: {self.retries}, sim_time: {self.ts}")

    def __repr__(self):
        return self.__str__()

    def __init__(self, node, status, data, retries):
        self.node = node
        self.status = status
        self.data = data
        self.retries = retries
        self.ts = ns.sim_time()


class PhotonEmissionProtocol(NodeProtocol):

    def __init__(self, cfg, node, max_emission_retries, num_repeaters=None, name=None):
        super().__init__(node, name=name)
        self.cfg = cfg
        self.max_emission_retries = max_emission_retries
        self.num_repeaters = num_repeaters
        self.ion_trap = self.node.subcomponents['ion_trap_quantum_communication_device']
        self._x_corr = 0
        self._z_corr = 0
        self._program = CorrectionProgram()
        self._counter = 0
        self.result = []
        self.retries = 0
        if self.node.name == 'node_q1':
            self.cport = self.node.ports["clock_from_right"]
            self.res_port = self.node.ports["BSM_res_from_right"]
        else:
            self.cport = self.node.ports["clock_from_left"]
            self.res_port = self.node.ports["BSM_res_from_left"]

    def _handle_success(self, node, data):
        if self.num_repeaters == 0 and self.node.name == "node_q2":
            log.debug("BSM corrections for 0 repeater case")
            if res.items[0]["data"] == [2]:
                self._x_corr = 1
            elif res.items[0]["data"] == [3]:
                self._x_corr = 1
                self._z_corr = 1
            if self._x_corr or self._z_corr:
                self._program.set_BSM_corrections(
                    self._x_corr, self._z_corr)
                log.debug(
                    f"Applying BSM corrections at {self.node.name}")
                yield self.node.qmemory.execute_program(
                    self._program, qubit_mapping=[0])
                log.debug(
                    f">>>>>> Finished BSM corrections at {self.node.name}")
                self._x_corr = 0
                self._z_corr = 0

    def _handle_failure(self, node, data):
        pass

    def _handle_corrections(self):
        # If this is a repeater chain, wait for control result
        if self.num_repeaters != 0:
            ctrl_port = self.node.ports["from_control"]
            log.debug(f" >>> {self.node.name} waiting for result")
            yield self.await_port_input(ctrl_port)
            log.debug(
                f"Received all repeater DBSM results from control node at {self.node.name}")
            # self.send_ctrl_msg("q1_c", "Entanglement is established")
            if self.node.name == "node_q2":
                log.debug("Starting DBSM corrections at node_q2")
                # message = self.node.ports["q2_c"].rx_input()
                message = ctrl_port.rx_input()
                log.debug(message.items)
                for m in message.items:
                    if m.items[0]['bell_index'] == ks.BellIndex.B01 or m.items[0]['bell_index'] == ks.BellIndex.B11:
                        log.debug(
                            f"Incremented x_corr because BellIndex was {m.items[0]['bell_index']}")
                        self._x_corr += 1
                    if m.items[0]['bell_index'] == ks.BellIndex.B10 or m.items[0]['bell_index'] == ks.BellIndex.B11:
                        self._z_corr += 1
                        log.debug(
                            f"Incremented x_corr because BellIndex was {m.items[0]['bell_index']}")
                    self._counter += 1
                    if self._counter == self.num_repeaters:
                        if self._x_corr or self._z_corr:
                            self._program.set_DBSM_corrections(
                                self._x_corr, self._z_corr)
                            yield self.node.qmemory.execute_program(
                                self._program, qubit_mapping=[0])
                            log.debug(
                                "Finished DBSM corrections at node_q2")
                        self._x_corr = 0
                        self._z_corr = 0
                        self._counter = 0
            log.debug(
                f"Sending Success signal to node_c from {self.node.name}")
            info_port = self.node.ports["from_qnode"]
            info_port.tx_output(self.retries)

    def run(self):
        ctrl_port = self.node.ports["from_control"]
        yield self.await_port_input(ctrl_port)
        log.debug(
            f"{ns.sim_time():.1f}: Received init trigger at {self.node.name}, performing init sequence")
        self.ion_trap.doppler_cooling(doppler_sim_time=self.cfg.ion_trap.doppler_sim_time)
        self.ion_trap.raman_excitation(raman_ex_sim_time=self.cfg.ion_trap.raman_ex_sim_time)
        self.ion_trap.doppler_cooling(doppler_sim_time=50)
        self.ion_trap.optical_pumping(pump_sim_time=self.cfg.ion_trap.pump_sim_time)
        self.ion_trap.sideband_cooling(sideband_sim_time=self.cfg.ion_trap.sideband_sim_time)
        self.ion_trap.create_qubits(node_name=self.node.name)
        yield self.await_timer(duration=self.cfg.ion_trap.emission_duration)
        log.debug(
            f"{ns.sim_time():.1f}: Initialization sequence completed at {self.node.name}")
        while True:
            # Wait for clock tick from BSM
            yield self.await_port_input(self.cport)
            log.debug(
                f"{ns.sim_time():.1f}: Received tick at {self.node.name}, sending qubit...")
            # Emit up to allowed retries
            self.retries = 0
            while self.retries <= self.max_emission_retries:
                log.debug(
                    f"Emission attempt {self.retries} at {self.node.name} (time={ns.sim_time()})")

                # Emit photon
                self.ion_trap.optical_pumping(pump_sim_time=self.cfg.ion_trap.pump_sim_time)
                self.ion_trap.raman_excitation(raman_ex_sim_time=self.cfg.ion_trap.raman_ex_sim_time)
                if self.retries % 5 == 0:
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    yield self.await_timer(duration=3*self.cfg.ion_trap.spin_echo_sim_time*1e3)
                if self.retries != 0:
                    self.ion_trap.state_initialization(node_name=self.node.name)
                self.node.qmemory.execute_program(
                    AdvRetryEmitProgram(), qubit_mapping=[0, 1])
                yield self.await_program(self.node.qmemory)
                log.debug(f"Matter qubit state in {self.node.name} after emission, {self.node.qmemory.peek(positions=[0])[0].qstate.qrepr} {ns.sim_time()}")
                # Wait for BSM result
                yield self.await_port_input(self.res_port)
                res = self.res_port.rx_input()
                node = res.items[0].node
                data = res.items[0].data
                log.debug(
                    f"BSM result arrived at {self.node.name}: {data}")

                # Handle result as needed
                if data in BSM_SUCCESS:
                    yield from self._handle_success(node, data)
                    break
                else:
                    self._handle_failure(node, data)
                self.retries += 1
            # do corrections before returning to top control loop
            yield from self._handle_corrections()


class BSMProtocol(NodeProtocol):
    def __init__(self, cfg, node, num_repeaters, node_distance, max_emission_retries, node_c_pos, name=None):
        super().__init__(node,  name=name)
        self.cfg = cfg
        self.node_c_pos = node_c_pos
        self.node_distance = node_distance
        self.max_emission_retries = max_emission_retries
        self.num_repeaters = num_repeaters
        self.detector = self.node.subcomponents["BSMDETECTOR"]
        # self.bsm_result = []
        self.clk = self.node.subcomponents["BSMCLK"]

    def send_ctrl_msg(self, pname, msg=""):
        self.node.ports[pname].tx_output(msg)

    def run(self):
        while True:
            if self.num_repeaters != 0:
                yield self.await_port_input(self.node.ports["to_bsm"])
            retries = 0
            msg_travel_time = (self.node_distance/self.cfg.network.q_lightspeed)*1e9
            distances = calculate_distances(self.node_c_pos, self.num_repeaters, self.node_distance)
            max_distance = max(distances.values())
            trigger_travel_time = (max_distance/self.cfg.network.q_lightspeed)*1e9
            if retries == 0:
                match = re.search(r"(\d+)$", self.node.name)
                if match:
                    node_num = int(match.group(1))
                if node_num % 2 != 0:
                    yield self.await_timer(duration=self.cfg.ion_trap.emission_duration)
                    yield self.await_timer(duration=trigger_travel_time)
            if self.clk.is_running is not True:
                self.clk.start()
            log.debug(
                f"{ns.sim_time()}BSM: Clock running: {self.clk.is_running}, num_ticks: {self.clk.num_ticks} at {self.node.name}")
            log.debug(
                f"{ns.sim_time():.1f}: Start BSM gen process at {self.node.name}")
            yield self.await_port_output(self.clk.ports["cout"])
            msg = self.clk.ports["cout"].rx_output()
            self.node.ports["clock_to_left"].tx_output(msg)
            self.node.ports["clock_to_right"].tx_output(msg)
            # Try detecting up to retry limit
            while retries <= self.max_emission_retries:
                log.debug(f"Qubit and clock travel time one side: {msg_travel_time}")
                # if retries != 0:
                wait_duration = self.cfg.ion_trap.retry_duration + msg_travel_time
                yield self.await_timer(duration=self.cfg.ion_trap.retry_duration)
                yield self.await_timer(duration=msg_travel_time)
                if retries % 5 == 0:
                    yield self.await_timer(duration=3*self.cfg.ion_trap.spin_echo_sim_time*1e3)
                # Trigger BSMDetector to start detection window for Bell measurement:
                # yield self.await_timer(duration=wait_duration)
                log.debug(f"{ns.sim_time()} Triggering at {self.node.name}")  # trigger based on travel time
                self.detector.ports["gate_trigger"].tx_input("Triggering BSM")
                # if
                wait_detector_dead = self.await_timer(
                    duration=(self.cfg.bsm.detector_wait_factor*msg_travel_time))
                wait_detected = self.await_port_output(
                    self.detector.ports["cout0"])
                evexpr = yield wait_detector_dead | wait_detected
                if evexpr.second_term.value:
                    m = self.detector.ports["cout0"].rx_output()
                    log.debug(
                        f"{ns.sim_time():.1f}: For {self.num_repeaters} repeater/s, BSM result at {self.node.name}: {m.items}")

                    if m.items in BSM_SUCCESS:
                        if self.num_repeaters != 0:
                            log.debug(
                                f"{self.node.name} Sending success to controller")
                            msg = BSMControlMessage(node=self.node.name,
                                                    status=DetectorStatus.SUCCESS,
                                                    data=m.items,
                                                    retries=retries)
                            self.send_ctrl_msg("to_control", msg)
                            self.send_ctrl_msg("BSM_res_to_left", msg)
                            self.send_ctrl_msg("BSM_res_to_right", msg)
                        log.debug(
                            f"{ns.sim_time()} Photon-mediated entanglement successful at {self.node.name}")
                        break
                    else:
                        msg = BSMControlMessage(node=self.node.name,
                                                status=DetectorStatus.NOT_DETECTED,
                                                data=m.items,
                                                retries=retries)
                        self.send_ctrl_msg("BSM_res_to_left", msg)
                        self.send_ctrl_msg("BSM_res_to_right", msg)
                else:
                    log.debug(f"{ns.sim_time()} BSM detector failed at {self.node.name}")
                    msg = BSMControlMessage(node=self.node.name,
                                            status=DetectorStatus.DETECTOR_FAILURE,
                                            data=None,
                                            retries=retries)
                    self.send_ctrl_msg("BSM_res_to_left", msg)
                    self.send_ctrl_msg("BSM_res_to_right", msg)

                log.debug(
                    f"Retries at BSM: (retries = {retries}) (time={ns.sim_time()})")
                retries += 1

            # Tell CP we have failed if retries exceeded
            if retries > self.max_emission_retries:
                self.send_ctrl_msg("to_control", msg)
            # Stop clock until next CP start message
            log.debug("BSM stopping clock")
            self.clk.stop()


class RepeaterEmissionProtocol(NodeProtocol):

    def __init__(self, cfg, node, max_emission_retries, num_repeaters=None, name=None):
        super().__init__(node, name=name)
        self.cfg = cfg
        self.max_emission_retries = max_emission_retries
        self.ion_trap = self.node.subcomponents['ion_trap_quantum_communication_device']
        self.num_repeaters = num_repeaters
        self.left_flag = False
        self.right_flag = False
        self._program = CorrectionProgram()
        self._x_corr = 0
        self._z_corr = 0
        self.initport = self.node.ports["from_control"]
        self.bsm_result = []

    def _handle_success(self, node, data, res_port):
        self._x_corr = 0
        self._z_corr = 0
        if res_port == self.node.ports["BSM_res_from_left"]:
            self.left_flag = True
            log.debug(f"Left flag is true for {self.node.name}")
        else:
            self.right_flag = True
            log.debug(f"Right flag is true for {self.node.name}")
        # Determine corrections based on result items
        # Result is `na`, apply X correction only
        if data == [2]:
            self._x_corr = 1
        # Result is `nb`, apply XZ correction
        elif data == [3]:
            self._x_corr = 1
            self._z_corr = 1
        # all repeaters perform bsm corrections for corresponding bsm nodes
        if int(node[-1]) == int(self.node.name[-1]):
            log.debug(
                f"Repeater {self.node.name} received success message {data} from {node}")
            mapping = [0]
        # last repeater to perform bsm corrections for last bsm node as well
        elif (int(self.node.name[-1]) == self.num_repeaters
                and int(node[-1]) == int(self.node.name[-1]) + 1):
            log.debug(
                f"Last repeater {self.node.name} received success message {data} from last bsm {node}")
            mapping = [1]
        else:
            return
        # Execute the correction program on the specified qubit
        log.debug(
            f"Performing BSM corrections at {self.node.name} with mapping: {mapping}")
        if self._x_corr or self._z_corr:
            self._program.set_BSM_corrections(
                self._x_corr, self._z_corr)
            log.debug(
                f"Applying BSM corrections at {self.node.name}")
            yield self.node.qmemory.execute_program(
                self._program, qubit_mapping=mapping)
            log.debug(
                f">>>>>> Finished BSM corrections at {self.node.name}")
            self._x_corr = 0
            self._z_corr = 0

    def _handle_failure(self, node, data):
        pass

    def run(self):
        self.left_flag = self.right_flag = False
        yield self.await_port_input(self.initport)
        log.debug(
            f"{ns.sim_time():.1f}: Received init trigger at {self.node.name}, performing init sequence")
        self.ion_trap.doppler_cooling(doppler_sim_time=self.cfg.ion_trap.doppler_sim_time)
        self.ion_trap.raman_excitation(raman_ex_sim_time=self.cfg.ion_trap.raman_ex_sim_time)
        self.ion_trap.doppler_cooling(doppler_sim_time=50)
        self.ion_trap.optical_pumping(pump_sim_time=self.cfg.ion_trap.pump_sim_time)
        self.ion_trap.sideband_cooling(sideband_sim_time=self.cfg.ion_trap.sideband_sim_time)
        self.ion_trap.create_qubits(node_name=self.node.name)
        yield self.await_timer(duration=self.cfg.ion_trap.emission_duration)
        log.debug(
            f"{ns.sim_time():.1f}: Initialization sequence completed at {self.node.name}")
        while True:
            cport1 = self.node.ports["clock_from_left"]
            cport2 = self.node.ports["clock_from_right"]
            eve1 = self.await_port_input(cport1)
            eve2 = self.await_port_input(cport2)
            eveexpr = yield eve1 | eve2
            if eveexpr.first_term.value:
                emission_map = [0, 2]
                res_port = self.node.ports["BSM_res_from_left"]
            else:
                emission_map = [1, 2]
                res_port = self.node.ports["BSM_res_from_right"]
            log.debug(
                f"{ns.sim_time():.1f}: Received tick at {self.node.name}, sending qubit...")
            retries = 0
            while retries <= self.max_emission_retries:
                log.debug(
                    f"Emission attempt {retries} at {self.node.name} (time={ns.sim_time()})")

                # Emit qubit
                self.ion_trap.optical_pumping(pump_sim_time=self.cfg.ion_trap.pump_sim_time)
                self.ion_trap.raman_excitation(raman_ex_sim_time=self.cfg.ion_trap.raman_ex_sim_time)
                if retries % 5 == 0:
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    self.ion_trap.spin_echo(spin_echo_sim_time=self.cfg.ion_trap.spin_echo_sim_time)
                    yield self.await_timer(duration=3*self.cfg.ion_trap.spin_echo_sim_time*1e3)
                if retries != 0:
                    self.ion_trap.state_initialization(
                        node_name=self.node.name, topo=[emission_map[0]])
                self.node.qmemory.execute_program(
                    AdvRetryEmitProgram(), qubit_mapping=[emission_map[0], 2])
                yield self.await_program(self.node.qmemory)
                log.debug(
                    f"Matter qubit state in {self.node.name} after emission, {self.node.qmemory.peek(positions=emission_map[0])[0].qstate.qrepr} {ns.sim_time()}")

                # Wait on BSM result
                yield self.await_port_input(res_port)
                res = res_port.rx_input()
                node = res.items[0].node
                data = res.items[0].data
                log.debug(
                    f"BSM result arrived at {self.node.name}: {data} from {node}")
                # log.debug(
                #     f"Matter qubit state in {self.node.name} after BSM, {self.node.qmemory.peek(positions=emission_map[0])[0].qstate.qrepr} {ns.sim_time()}")
                # Handle result as necessary
                if data in BSM_SUCCESS:
                    yield from self._handle_success(node, data, res_port)
                    break
                else:
                    self._handle_failure(node, data)
                retries += 1

            # start DBSM
            if self.left_flag and self.right_flag:
                swap_program = AdvIonTrapSwapProgram()
                # Perform Bell measurement
                yield self.node.qmemory.execute_program(swap_program, qubit_mapping=[0, 1])
                log.debug(
                    f"DBSM result at {self.node.name}:{swap_program.output}")
                # Send result to the control node
                log.debug(
                    f"Sending DBSM result from {self.node.name} to node_c")
                self.node.ports["to_control"].tx_output(
                    Message(swap_program.output))
                self.left_flag = self.right_flag = False


class ControlProtocol(NodeProtocol):
    def __init__(self, cfg, node, node_q1, node_q2, r_nodes, bsm_nodes, num_repeaters, max_emission_retries,
                 z_gate_duration, x_gate_duration, proto_sched, name=None):
        super().__init__(node, name=name)
        self.cfg = cfg
        self.proto_sched = proto_sched
        self.max_emission_retries = max_emission_retries
        self.z_gate_duration = z_gate_duration
        self.x_gate_duration = x_gate_duration
        self.node_q1 = node_q1
        self.node_q2 = node_q2
        self.r_nodes = r_nodes
        self.bsm_nodes = bsm_nodes
        self.num_repeaters = num_repeaters
        self.num_bsm_nodes = len(self.bsm_nodes)
        self.bsm_results = dict()
        self.end_result = list()
        self.repeater_results = list()
        self.retries = list()
        self.both_ends_proto_flag = False
        self.single_bsm_proto_flag = False
        self.shared_repeater_proto_flag = False
        self.odd_bsm_proto_flag = False
        self.even_bsm_proto_flag = False
        self.end_time = 0
        # setup an expression handler that persists for the duration
        # of the protocol instance
        ev_expr = None
        for i in range(0, len(self.r_nodes)):
            cport = self.node.ports[f"from_{self.r_nodes[i]}"]
            if ev_expr is None:
                ev_expr = self.await_port_input(cport)
            else:
                ev_expr |= self.await_port_input(cport)
        self._wait(ExpressionHandler(self.handle_dbsm), expression=ev_expr)
        ev_expr1 = None
        for i in range(0, 2):
            cport1 = self.node.ports[f"to_q{i+1}"]
            if ev_expr1 is None:
                ev_expr1 = self.await_port_input(cport1)
            else:
                ev_expr1 |= self.await_port_input(cport1)
        self._wait(ExpressionHandler(self.handle_endres), expression=ev_expr1)

    def send_ctrl_msg(self, nname, msg=""):
        self.node.ports[f"control_to_{nname}"].tx_output(msg)

    def recv_ctrl_msg(self, *nodes):
        ev_expr = None
        for n in nodes:
            cport = self.node.ports[f"from_{n}"]
            if ev_expr is None:
                ev_expr = self.await_port_input(cport)
            else:
                ev_expr |= self.await_port_input(cport)
        waiting = len(nodes)
        while waiting:
            yield ev_expr
            rport = ev_expr.triggered_events[0].source
            res = rport.rx_input()
            self.retries.append(res.items[0].retries)
            self.bsm_results[res.items[0].node] = res.items
            waiting -= 1

    def _single_bsm_proto(self, idx):
        first_node = f"{self.bsm_nodes[idx]}"
        self.send_ctrl_msg(first_node, "Start")
        yield from self.recv_ctrl_msg(first_node)
        self.pending_bsm -= 1

    def _both_ends_proto(self, idx):
        first_node = f"{self.bsm_nodes[idx]}"
        last_node = f"{self.bsm_nodes[-(idx+1)]}"
        self.send_ctrl_msg(first_node, "Start")
        self.send_ctrl_msg(last_node, "Start")
        yield from self.recv_ctrl_msg(first_node, last_node)
        self.pending_bsm -= 2

    def _odd_proto(self, idx):
        odd_bsm_nodes = [f"{self.bsm_nodes[i]}" for i in range(idx, len(self.bsm_nodes), 2)]
        for node in odd_bsm_nodes:
            self.send_ctrl_msg(node, "Start")
        yield from self.recv_ctrl_msg(*odd_bsm_nodes)
        self.pending_bsm = (len(self.bsm_nodes)-len(odd_bsm_nodes))

    def _even_proto(self, idx):
        even_bsm_nodes = [f"{self.bsm_nodes[i]}" for i in range(idx + 1, len(self.bsm_nodes), 2)]
        for node in even_bsm_nodes:
            self.send_ctrl_msg(node, "Start")

        yield from self.recv_ctrl_msg(*even_bsm_nodes)
        self.pending_bsm -= len(even_bsm_nodes)

    def _shared_repeater_proto(self, idx):
        first_node = f"{self.bsm_nodes[idx]}"
        last_node = f"{self.bsm_nodes[-(idx+1)]}"
        self.send_ctrl_msg(first_node, "Start")
        yield from self.recv_ctrl_msg(first_node)
        yield self.await_timer(
            duration=(self.z_gate_duration + self.x_gate_duration))

        self.send_ctrl_msg(last_node, "Start")
        yield from self.recv_ctrl_msg(last_node)
        self.pending_bsm -= 2

    def handle_dbsm(self, ev_expr):
        cport = ev_expr.triggered_events[0].source
        res = cport.rx_input()
        self.repeater_results.append(res)
        log.debug(
            f"{ns.sim_time():.1f}: Received DBSM result at {self.node.name}, from {cport}")

        if (len(self.repeater_results) == len(self.r_nodes)):
            self.send_ctrl_msg(self.node_q1, self.repeater_results)
            self.send_ctrl_msg(self.node_q2, self.repeater_results)
            self.repeater_results = []

    def handle_endres(self, ev_expr):
        cport = ev_expr.triggered_events[0].source
        res1 = cport.rx_input()
        self.end_result.append(res1)
        log.debug(
            f"{ns.sim_time():.1f}: Received entanglement success result at {self.node.name}, from {cport}")

        if len(self.end_result) == 2:
            self.end_time = ns.sim_time()
            log.debug(f"Sending Success signal at {self.node.name}")
            self.send_signal(Signals.SUCCESS)
            log.debug(f"{ns.sim_time()}: Control Protocol finished")

    def restart_protocol(self):
        # Reset protocol state
        log.info("Restarting protocol from the beginning.")
        self.pending_bsm = self.num_bsm_nodes
        self.bsm_results.clear()
        self.repeater_results.clear()
        self.run()

    def run(self):
        self.end_time = 0
        self.start_time = ns.sim_time()
        log.debug(f"Control starting time: {self.start_time}")
        self.bsm_results = dict()
        self.repeater_results = list()
        self.end_result = list()
        self.retries = list()
        self.single_bsm_proto_flag = False
        self.both_ends_proto_flag = False
        self.shared_repeater_proto_flag = False
        self.odd_bsm_proto_flag = False
        self.even_bsm_proto_flag = False
        # Send trigger message to all qnodes and repeater nodes to start initialization process
        for node in self.r_nodes:
            self.send_ctrl_msg(node, "Start")
        self.send_ctrl_msg(self.node_q1, "Start")
        self.send_ctrl_msg(self.node_q2, "Start")
        log.debug("Triggered initialization sequence at all Q-nodes and QR-nodes")
        # how many BSMs to wait for
        self.pending_bsm = self.num_bsm_nodes
        # track our iterations as we process our bsm list
        i = 0
        while (self.pending_bsm):
            if self.proto_sched == 2:
                if (self.pending_bsm == 1):
                    # handle middle bsm node
                    if self.single_bsm_proto_flag is True or self.shared_repeater_proto_flag is True or self.both_ends_proto_flag is True:
                        yield self.await_timer(
                            duration=(self.z_gate_duration + self.x_gate_duration))
                    yield from self._single_bsm_proto(i)
                    self.single_bsm_proto_flag = True
                elif (self.pending_bsm == 2):
                    if self.single_bsm_proto_flag is True or self.shared_repeater_proto_flag is True or self.both_ends_proto_flag is True:
                        yield self.await_timer(
                            duration=(self.z_gate_duration + self.x_gate_duration))
                    # Two BSM left means we have a shared repeater in the middle
                    yield from self._shared_repeater_proto(i)
                    self.shared_repeater_proto_flag = True
                else:
                    if self.single_bsm_proto_flag is True or self.shared_repeater_proto_flag is True or self.both_ends_proto_flag is True:
                        yield self.await_timer(
                            duration=(self.z_gate_duration + self.x_gate_duration))
                    # otherwise continue along the chain
                    yield from self._both_ends_proto(i)
                    self.both_ends_proto_flag = True
            elif self.proto_sched == 1:
                if (self.pending_bsm < self.num_bsm_nodes) and self.even_bsm_proto_flag is False:
                    # log.info("Starting even bsm nodes")
                    yield self.await_timer(
                        duration=(self.z_gate_duration + self.x_gate_duration))
                    yield from self._even_proto(0)
                    self.even_bsm_proto_flag = True
                else:
                    # log.info("Starting odd bsm nodes")
                    yield from self._odd_proto(i)
                    self.odd_bsm_proto_flag = True
            else:
                if self.single_bsm_proto_flag is True:
                    yield self.await_timer(
                        duration=(self.z_gate_duration + self.x_gate_duration))
                yield from self._single_bsm_proto(i)
                self.single_bsm_proto_flag = True
            for node in self.bsm_results:
                if self.bsm_results[node][0].status != DetectorStatus.SUCCESS:
                    self.single_bsm_proto_flag = False
                    self.both_ends_proto_flag = False
                    self.shared_repeater_proto_flag = False
                    self.odd_bsm_proto_flag = False
                    self.even_bsm_proto_flag = False
                    log.warning(
                        f"CP: BSM detection was not successful within {self.max_emission_retries} retries for {node}")
                    self.end_time = ns.sim_time()
                    return
            i += 1


class RepeaterProtocol(LocalProtocol):
    def __init__(self, cfg, network, bsm_nodes, r_nodes, num_repeaters, max_emission_retries,
                 z_gate_duration, x_gate_duration, node_distance, proto_sched, node_c_pos):
        """Setup protocols on repeater chain network."""
        super().__init__(nodes=network.nodes)
        self.cfg = cfg
        self.node_c_pos = node_c_pos
        self.proto_sched = proto_sched
        self.node_distance = node_distance
        self.z_gate_duration = z_gate_duration
        self.x_gate_duration = x_gate_duration
        self.retries = max_emission_retries
        print(f"RP: self.retries: {self.retries}")
        self.network = network
        self.num_repeaters = num_repeaters
        self.bsm_nodes = bsm_nodes
        self.r_nodes = r_nodes
        self.node_q1 = self.network.get_node("node_q1")
        self.node_q2 = self.network.get_node("node_q2")
        self.node_c = self.network.get_node("node_c")
        self.num_bsm_nodes = len(self.bsm_nodes)
        self.num_bsm = self.bsm_nodes[-1].split("node_bsm")[1]
        log.debug("---------------------------------------------------------------")
        log.debug(f"Num Repeaters: {self.num_repeaters}")
        log.debug(f"List of BSM Nodes: {self.bsm_nodes}")
        log.debug(f"List of Repeater Nodes: {self.r_nodes}")
        log.debug(f"Number of BSM nodes: {self.num_bsm_nodes}")
        self._add_subprotocols()

    def scheduling(self):
        if self.num_repeaters == 0:
            # BSM1, Q1, and Q2 start at signal-> WAITING.
            bsm_node = self.network.get_node("node_bsm1")

    def _add_subprotocols(self):
        """Setup all of the subprotocols"""

        for i in range(self.num_bsm_nodes):
            node = self.network.get_node(f"node_bsm{i+1}")
            subprotocol_bsm = BSMProtocol(
                self.cfg, node=node, num_repeaters=self.num_repeaters, name=node.name,
                max_emission_retries=self.retries, node_distance=self.node_distance,
                node_c_pos=self.node_c_pos)
            self.add_subprotocol(subprotocol_bsm)

        for i in range(1, self.num_bsm_nodes):
            if self.num_repeaters != 0:
                node = self.network.get_node(f"node_r{i}")
                repeater_emission_protocol = RepeaterEmissionProtocol(
                    self.cfg, node, num_repeaters=self.num_repeaters, name=f"{node.name}",
                    max_emission_retries=self.retries)
                self.add_subprotocol(repeater_emission_protocol)

        photon_emission_protocol1 = PhotonEmissionProtocol(
            self.cfg, node=self.node_q1, num_repeaters=self.num_repeaters, name=self.node_q1.name,
            max_emission_retries=self.retries)
        self.add_subprotocol(photon_emission_protocol1)

        photon_emission_protocol2 = PhotonEmissionProtocol(
            self.cfg, node=self.node_q2, num_repeaters=self.num_repeaters, name=self.node_q2.name,
            max_emission_retries=self.retries)
        self.add_subprotocol(photon_emission_protocol2)

        if self.num_repeaters != 0:
            control_protocol = ControlProtocol(
                self.cfg, node=self.node_c, node_q1=self.node_q1, node_q2=self.node_q2, r_nodes=self.r_nodes,
                bsm_nodes=self.bsm_nodes, num_repeaters=self.num_repeaters,
                name=self.node_c.name, max_emission_retries=self.retries,
                z_gate_duration=self.z_gate_duration, x_gate_duration=self.x_gate_duration,
                proto_sched=self.proto_sched)
            self.add_subprotocol(control_protocol)

        log.debug("Added all sub-protocols")

    def init(self):
        if self.num_repeaters == 0:
            self.scheduling()

    def run(self):
        self.init()
        self.start_subprotocols()
