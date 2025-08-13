from netsquid.components.qprogram import QuantumProgram
from netsquid.components.instructions import INSTR_MEASURE_BELL, INSTR_X, INSTR_Z


class DBSM(QuantumProgram):

    default_num_qubits = 2

    def program(self):
        q1, q2 = self.get_qubit_indices()
        self.apply(instruction=INSTR_MEASURE_BELL, qubit_indices=[
                   q1, q2], inplace=False, output_key="BellStateIndex")

        yield self.run()


class CorrectionProgram(QuantumProgram):
    default_num_qubits = 1

    def set_DBSM_corrections(self, x_corr, z_corr):
        self.x_corr = x_corr % 2
        self.z_corr = z_corr % 2

    def set_BSM_corrections(self, x_corr, z_corr):
        # Set corrections based on the given flags
        self.x_corr = x_corr
        self.z_corr = z_corr

    def program(self):
        q1 = self.get_qubit_indices(1)
        if self.x_corr == 1:
            self.apply(instruction=INSTR_X, qubit_indices=q1)
        if self.z_corr == 1:
            self.apply(instruction=INSTR_Z, qubit_indices=q1)
        yield self.run()
