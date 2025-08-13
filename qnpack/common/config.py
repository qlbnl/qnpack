import yaml
import munch
from qnpack.common.constants import Constants

class Config:
    def __init__(self, config_file=Constants.DEFAULT_PARAM_FILE):
        self._config = yaml.safe_load(open(config_file))
        self._munch = munch.munchify(self._config)

    def __getattr__(self, name):
        return getattr(self._munch, name)

    def __str__(self):
        return yaml.safe_dump(self._munch)

    def _apply_fixed_params(self, fixed_params: dict):
        if not fixed_params:
            return False
    
        updated = False
    
        for section_name, params in fixed_params.items():
            if hasattr(self._munch, section_name):
                section = getattr(self._munch, section_name)
                for key, value in params.items():
                    if hasattr(section, key):
                        old_val = getattr(section, key)
                        setattr(section, key, value)
                        print(f"Updated {section_name}.{key}: {old_val} -> {value}")
                        updated = True
    
        return updated

