# WIMM synthetic benchmark

Synthetic validation recordings for WIMM (Where Is My Mouse?) version 1.0.0, with every
measure known in advance, and the results of analyzing them with WIMM. These are the data
behind Section 3.4, Figure 2, Supplementary Figure S1 and Supplementary Table S1 of the paper
*From Natural Language to Laboratory Tool: AI-Assisted Development of WIMM, an Open-Source
Mouse Tracking Platform*.

**Where the files are.** The `benchmark/` folder of the WIMM repository holds the scripts,
this README and the summary workbook. The full benchmark, including the videos, ground
truth, WIMM exports, graphs and figures, is attached to the
[WIMM 1.0.0 release](https://github.com/a-LittleMonk/WIMM/releases/tag/v1.0.0) as
`WIMM-1.0.0-synthetic-benchmark.zip` (about 250 MB). Unzip it into this folder to get the
layout described below.

## What the benchmark is

There is one recording for each of the 12 standard WIMM paradigms; the user-defined
experiment was not tested. In each recording, a top-view image of a mouse follows a scripted
path over a rendered arena:

- **Recording format:** 30.000 s, 900 frames, 30 frames per second, 1280 × 720 pixels, with
  fresh sensor noise on every frame.
- **Paths:** straight runs, arcs and stationary periods.
- **Ground truth:** the animal's position on every frame is known exactly, so every measure
  is calculated from the script rather than from WIMM. The body point is the center of the
  drawn body without tail and shadow. The nose point is the tip of the snout.

Each recording was then analyzed with WIMM 1.0.0 through the application's own Run path,
using its default detection and smoothing settings. The movement threshold was 2 cm/s, the
minimum dwell time 0 s and the time bins 5 s. Every exported value was compared with its
true value.

## Contents

| Path | What it is |
|---|---|
| `NN_<Paradigm>/NN_<Paradigm>.mp4` | The synthetic recording |
| `NN_<Paradigm>/NN_<Paradigm>_benchmark.xlsx` | Ground truth. The `Benchmark` sheet holds every measure with how it was calculated; `Per frame` holds the true body, nose and tail-base position on every frame; zones and settings are listed alongside |
| `NN_<Paradigm>/Output graphs/` | Graphs drawn from the true path |
| `NN_<Paradigm>/NN_<Paradigm>_APP_results.xlsx` | WIMM 1.0.0's own Excel export, unchanged. It includes raw per-frame positions and the version and all parameters used |
| `NN_<Paradigm>/App graphs/` | The graphs WIMM produced |
| `NN_<Paradigm>/NN_<Paradigm>_APP_comparison.xlsx` | Every benchmark measure next to the WIMM value, with difference, % difference and status |
| `APP_vs_benchmark_summary.xlsx` | All 12 comparisons in one workbook: an overview, one sheet per paradigm, the values that differ, the trajectories and the values grouped by type |
| `All trajectories - benchmark vs app.png` | The true and the tracked path of all 12 recordings (Supplementary Figure S1) |
| `figures/` | Figure 2, Supplementary Figure S1, `Supplementary Information.docx` (Table S1) and the scripts that make them |
| `make_arenas.py` | Draws the synthetic arenas |
| `make_validation_videos.py` | Makes the recordings and their ground truth |
| `run_app_on_benchmarks.py` | Runs every recording through the WIMM application and writes the comparison files and the summary |
| `run_wimm_on_benchmarks.py` | Zone shapes, measure-name mapping and comparison rules used by `run_app_on_benchmarks.py` |

The status column in the comparison files means the following:
- **exact:** identical when rounded to two decimals.
- **close:** within 0.1 units or 5%.
- **differs:** outside both limits. Counts and text values must match exactly.
- **not reported by WIMM:** a benchmark measure that WIMM does not export.

Overall, the 12 paradigms give 445 benchmark measures. Of the 402 that WIMM exports, 241 are
exact, 141 close and 20 differ. In five rows, one WIMM value is listed under two benchmark
names, for example entries into an object zone and exploration bouts at that object.

Known limitation: in the light–dark box, the dark animal cannot be separated from the dark
floor of the dark compartment, and only 38.6% of frames were detected. Zone measures are
correct, but distance, speed, mobility, immobility and pauses are not.

## Reproducing

You need Python 3.12 with numpy, pillow, opencv-python, openpyxl, pandas and matplotlib. You
also need the WIMM 1.0.0 source and its requirements, including PyQt5.

```
# 1. recordings and ground truth. Writes the NN_<Paradigm> folders next to the script and
#    overwrites existing ones, so run it from a copy of the two scripts in an empty folder.
#    Output is deterministic: it reproduces the published videos and Excel files.
python make_validation_videos.py --all

# 2. analyze every recording with WIMM and compare
#    (uses the WIMM source this folder sits in; set WIMM_DIR to use another copy)
set WIMM_DIR=C:\path\to\WIMM
python run_app_on_benchmarks.py

# 3. figures and Supplementary Table S1
python figures/make_figure2.py
python figures/make_supplementary.py
```

`run_app_on_benchmarks.py` reads WIMM's settings file but never writes to it. WIMM's own
backup copies go to a temporary folder. Running one paradigm only:
`python run_app_on_benchmarks.py open_field`.

## License

MIT, as the rest of the WIMM repository.
