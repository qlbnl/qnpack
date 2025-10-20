import os
import pytest
from qnpack.APE.allphotonic import APESimulation
from qnpack.oneG.theo_rate import TheoRateSimulation
from qnpack.oneG.iontrap import IonTrapSimulation

CWD = os.path.normpath(os.path.join(os.path.dirname(__file__)))
output_dir = os.path.join(CWD, "output")


class TestParameters():

    def _run_ion_simulation(self, fixed_params={}):
        sim = IonTrapSimulation(
            fixed_params=fixed_params,
            varying_params={
                "num_repeaters": [1],
                "distance": [10]
            },
            iterations=10,
            parameter_file=os.path.join(CWD, "parameters/ion_baseline.yml"),
            output_dir=output_dir,
        )
        return sim.start()

    @pytest.fixture(autouse=True)
    def baseline(self):
        return self._run_ion_simulation()

    def test_collection_efficiency(self, baseline):
        fixed_params = {"ion_trap": {"collection_efficiency": 0.7}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        assert result[0]["rate"] < baseline[0]["rate"]
        assert result[0]["fidelity"] == baseline[0]["fidelity"]

    def test_emission_fidelity(self, baseline):
        fixed_params = {"ion_trap": {"emission_fidelity": 0.69}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        #assert int(result[0]["rate"]) == int(baseline[0]["rate"])
        assert result[0]["fidelity"] < baseline[0]["fidelity"] 

    def test_coherence_time(self, baseline):
        fixed_params = {"ion_trap": {"coherence_time": 60000000}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        #assert int(result[0]["rate"]) == int(baseline[0]["rate"])
        assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_coupling_efficiency(self, baseline):
        fixed_params = {"bsm": {"coupling_efficiency": 0.9}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        assert int(result[0]["rate"]) < int(baseline[0]["rate"])
        # assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_ms_depolar_prob(self, baseline):
        fixed_params = {"ion_trap": {"ms_depolar_prob": 0.01}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        #assert int(result[0]["rate"]) == int(baseline[0]["rate"])
        assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_z_depolar_prob(self, baseline):
        fixed_params = {"ion_trap": {"z_depolar_prob": 0.001}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        #assert int(result[0]["rate"]) == int(baseline[0]["rate"])
        assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_x_depolar_prob(self, baseline):
        fixed_params = {"ion_trap": {"x_depolar_prob": 0.001}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        #assert int(result[0]["rate"]) == int(baseline[0]["rate"])
        assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_photon_loss(self, baseline):
        fixed_params = {"network": {"photon_loss": 0.2}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        assert int(result[0]["rate"]) < int(baseline[0]["rate"])
        # assert result[0]["fidelity"] < baseline[0]["fidelity"]

    def test_init_photon_loss(self, baseline):
        fixed_params = {"network": {"init_photon_loss": 0.7}}
        result = self._run_ion_simulation(fixed_params=fixed_params)
        assert int(result[0]["rate"]) < int(baseline[0]["rate"])
        # assert result[0]["fidelity"] < baseline[0]["fidelity"]