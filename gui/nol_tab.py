"""NOLTab — Novel Object Location screen: NORTab with NOLExperiment."""
from gui.nor_tab import NORTab
from gui.experiment_batch_tab import ExperimentBatchTab
from experiments.nol import NOLExperiment


class NOLTab(NORTab):
    def __init__(self, config):
        super().__init__(config, experiment=NOLExperiment())


class NOLBatchTab(ExperimentBatchTab):
    embedded_tab_class = NOLTab
