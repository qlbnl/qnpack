import os
import logging
from abc import ABC, abstractmethod
from qnpack.common.config import Config


log = logging.getLogger(__name__)


class Simulation(ABC):
    def __init__(self,
                 parameter_file=None,
                 fixed_params=None,
                 varying_params=None,
                 output_dir=None,
                 logfile=None,
                iterations: int = 1):

        self.param_file = parameter_file or Constants.DEFAULT_PARAM_FILE
        self.output_dir = output_dir or Constants.DEFAULT_OUTPUT_DIR
        self.cfg = Config(parameter_file)
        self.varying_params = varying_params
        self.fixed_params = fixed_params
        self.iterations = iterations

        os.makedirs(self.output_dir, exist_ok=True)

        res = self.cfg._apply_fixed_params(fixed_params)
        if res:
            log.debug("Updated self.cfg values")
            log.debug(f"New self.cfg:\n {self.cfg}")

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def finalize(self):
        pass
