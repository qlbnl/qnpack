class APEParams:
    @staticmethod
    def emitter_init_prog_period(cfg):
        return cfg.emitter.INIT_duration + cfg.emitter.H_duration + cfg.emitter.CZ_duration

    @staticmethod
    def level1_subtree_duration(cfg):
        return APEParams.emitter_init_prog_period(cfg) + \
            (cfg.emitter.EMIT_PHOTON_duration + cfg.emitter.photon_emission_buffer) * \
            (cfg.rgs.b1 + 1) + cfg.emitter.H_duration + cfg.emitter.MEASURE_duration

    @staticmethod
    def core_photon_delay(cfg): #in ns
        return APEParams.level1_subtree_duration(cfg) * cfg.rgs.b0 + 10
    
    @staticmethod
    def core_photon_delay_fibre_length(cfg): #in km
        return APEParams.core_photon_delay(cfg) * 2E5 * 1E-9

    @staticmethod
    def apeqr_clock_period(cfg):
        return (APEParams.level1_subtree_duration(cfg) * (cfg.rgs.b0 + 1) + cfg.emitter.CZ_duration +
                cfg.emitter.MEASURE_duration+1) * 1E-9

    @staticmethod
    def end_node_emitter_init_duration(cfg):
        return cfg.emitter.INIT_duration + cfg.emitter.H_duration

    @staticmethod
    def leaf_photon_clock_time(cfg):
        # change this to match end node with leaf photon of APE node
        # return cfg.emitter.INIT_duration + cfg.emitter.H_duration + cfg.emitter.CZ_duration + \
        #         cfg.emitter.EMIT_PHOTON_duration - cfg.emitter.INIT_duration - cfg.emitter.H_duration
        return APEParams.level1_subtree_duration(cfg) * cfg.rgs.b0 + \
            APEParams.emitter_init_prog_period(cfg) - APEParams.end_node_emitter_init_duration(cfg)

    @staticmethod
    def time_between_level1_subtrees(cfg):
        return cfg.emitter.H_duration + cfg.emitter.MEASURE_duration + \
            APEParams.emitter_init_prog_period(cfg)
    
    @staticmethod
    def p_loss_init(cfg):
        return 1 - cfg.emitter.collection_eff * (1 - cfg.emitter.QFC_loss) * cfg.emitter.detector_eff

