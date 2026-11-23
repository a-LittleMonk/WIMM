"""One list of every experiment the app offers — used by the launcher,
the main window, the Help window and the graph-style store, so adding a
test means adding one line here.

(key, title, gui module, batch-tab class, tab class)
"""
EXPERIMENTS = (
    ("open_field",    "Open Field",           "gui.openfield_batch_tab", "OpenFieldBatchTab",      "OpenFieldTab"),
    ("y_maze",        "Y-Maze",               "gui.y_maze_tab",          "YMazeBatchTab",          "YMazeTab"),
    ("nor",           "Novel Object",         "gui.nor_tab",             "NORBatchTab",            "NORTab"),
    ("epm",           "Elevated Plus",        "gui.epm_tab",             "EPMBatchTab",            "EPMTab"),
    ("nol",           "Object Location",      "gui.nol_tab",             "NOLBatchTab",            "NOLTab"),
    ("three_chamber", "Three Chamber",        "gui.box_tab",             "ThreeChamberBatchTab",   "ThreeChamberTab"),
    ("cpp",           "Place Preference",     "gui.box_tab",             "PlacePreferenceBatchTab", "PlacePreferenceTab"),
    ("light_dark",    "Light–Dark Box",       "gui.box_tab",             "LightDarkBatchTab",      "LightDarkTab"),
    ("zero_maze",     "Zero Maze",            "gui.box_tab",             "ZeroMazeBatchTab",       "ZeroMazeTab"),
    ("t_maze",        "T-Maze",               "gui.box_tab",             "TMazeBatchTab",          "TMazeTab"),
    ("radial_maze",   "Radial Arm Maze",      "gui.box_tab",             "RadialMazeBatchTab",     "RadialMazeTab"),
    ("water_maze",    "Water Maze",           "gui.box_tab",             "WaterMazeBatchTab",      "WaterMazeTab"),
)

KEYS = tuple(e[0] for e in EXPERIMENTS)
TITLES = {e[0]: e[1] for e in EXPERIMENTS}


def tab_class(key, which="batch"):
    import importlib
    for k, _title, module, batch, tab in EXPERIMENTS:
        if k == key:
            mod = importlib.import_module(module)
            return getattr(mod, batch if which == "batch" else tab)
    raise KeyError(key)
