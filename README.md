# rlpanel

**A local dashboard that lets you watch and compare RL training runs in the browser with live charts, instead of in the terminal.**

Adding a single line (`PanelCallback`) to your training code opens a dashboard in the browser. It shows the
progress percentage, the current reward, a chart of **every** logged metric, and a live console. Finished runs
can be loaded later, seeds can be overlaid for comparison, and every chart can be downloaded as PNG / SVG / CSV.
The goal is a shared monitoring tool for the RL projects at the MTA Artificial Intelligence Center
(DroneTrackingRL, LunarRocket …). The interface is currently in Turkish.

![rlpanel live training view](assets/demo.gif)

*The dashboard while a Demo-CartPole PPO run is training: progress goes from 6% to 85%, and the reward curve and cards update live.*

## Overview

| | |
|---|---|
| **Problem** | RL training output scrolls past in the terminal and is lost; seeds and earlier experiments are hard to view side by side. |
| **Method** | A small client inside the training process sends metrics over HTTP to a local FastAPI server. The server writes them to SQLite and broadcasts them to the browser over WebSocket. If the server is down, data are written to a local buffer and sent later. |
| **Simulation / hardware** | Environment-agnostic (Gymnasium / Stable-Baselines3 or your own loop). No GPU needed; tested on Windows 11 with Python 3.12. |
| **Paper** | None (tool project). |

### System architecture

![rlpanel block diagram](assets/architecture.png)

The training process contains only an HTTP client and knows nothing about the server's internals.
`rlpanel serve` is a separate process and can listen to several runs at once. Finished logs (`progress.csv`,
tfevents, `results.json`) are brought into the same database with `rlpanel watch` / `rlpanel import`.

## Selected results

### Result 1: Live training page

A run's top cards (progress, current / best reward, success rate, learning rate, elapsed time) and its metric
charts. Every chart has PNG / SVG / CSV download buttons; the console tab streams `print`/`logging` output.

![Live run page](plots/canli_run.png)

### Result 2: Seed comparison

Three seeds of the same experiment (`ppo/seed_0..2`) drawn on top of each other. The "mean ± σ" option shows them as a single band.

![Comparison page](plots/karsilastirma.png)

### Result 3: Run list

All projects and runs with their status (live, finished, crashed, stopped, not responding) in one list.

![Home page](plots/ana_sayfa.png)

*All screenshots use the data from `scripts/demo.py` and are in `plots/`.*

## Installation

### Requirements

- Windows 10/11, Linux or macOS
- Python ≥ 3.10 (tested with 3.12)
- No GPU needed; optional: `stable-baselines3` (`[sb3]`), `tensorboard` (`[tb]`)

### Steps

To add it as a dependency of another project, put this in its `pyproject.toml`:

```toml
dependencies = ["rlpanel[sb3] @ git+https://github.com/BalBaZeuR0/RLpanel"]
```

For development, on a clean machine:

```bash
git clone https://github.com/BalBaZeuR0/RLpanel.git
cd RLpanel
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q -m "not slow and not e2e"           # installation check
```

Expected output:

```
90 passed, 18 deselected in 21.14s
```

## Usage

### In your own training

```python
from rlpanel import Panel, PanelCallback

panel = Panel(project="MyProject", run="seed0", config=cfg)   # starts the dashboard if needed, opens the browser
model.learn(total_timesteps=100_000, callback=PanelCallback(panel))
panel.log({"eval/success": 0.93}, step=model.num_timesteps)   # your own metric
panel.result({"final": 0.93})                                 # Results tab
panel.finish()
```

One-line shortcut: `model.learn(..., callback=PanelCallback(project="MyProject", run="seed0"))`.
If you don't use SB3, `panel.log({...}, step=t)` and `panel.progress(t, total)` are enough.

### Run the bundled demo

```bash
python scripts/demo.py
```

Expected output (the dashboard opens in the browser: first 3 finished seeds, then a 4th run streaming live;
the script prints in Turkish, "adım" = step):

```
Canlı demo: http://127.0.0.1:8765/#/run/4
adım 0: reward -6.3
adım 8192: reward 161.3
adım 16384: reward 289.6
...
```

### Commands

| Command | What it does |
|---|---|
| `rlpanel serve` | Opens the dashboard (http://127.0.0.1:8765) |
| `rlpanel serve --host 0.0.0.0` | Makes it reachable from remote machines |
| `rlpanel watch <folder>` | Watches SB3 `progress.csv` / tfevents / `results.json` files live |
| `rlpanel import <file> --project P --run r` | Loads the log of a finished run |

If an error occurs the run is marked **crashed**, and on Ctrl+C **stopped**. If no data arrive for 30 s it becomes **not responding**.
If the server is down, data pile up in `.rlpanel/<project>-<run>/.rlpanel_buffer.jsonl` and are sent automatically once the server is up.

### Environment variables

| Variable | Effect |
|---|---|
| `RLPANEL_SERVER=http://ip:8765` | Send to a dashboard on another machine |
| `RLPANEL_NO_BROWSER=1` | Don't open the browser |
| `RLPANEL_DISABLE=1` | Turn the dashboard off completely (tests, CI) |
| `RLPANEL_HOME` / `RLPANEL_DB` | Data folder / database path (default `~/.rlpanel/panel.db`) |

## Reproducing the results

| Figure | Command |
|---|---|
| `assets/demo.gif`, `plots/canli_run.png`, `plots/karsilastirma.png`, `plots/ana_sayfa.png` | `python -m playwright install chromium && python scripts/readme_gorselleri.py` |
| `assets/architecture.png` | `python scripts/flowchart.py assets/architecture.json` |

The image script uses a temporary database and does not touch the files in `~/.rlpanel`.

## Project structure

```
RLpanel/
├── assets/              # README images (demo.gif, architecture.png + .json source)
├── docs/                # design and implementation plan
├── plots/               # README screenshots
├── scripts/
│   ├── demo.py          # demo data: 3 finished seeds + a live run
│   ├── readme_gorselleri.py  # produces the assets/ and plots/ images
│   └── flowchart.py     # draws the architecture diagram from JSON
├── src/rlpanel/
│   ├── client.py        # Panel: start a run, send metrics/logs, buffer
│   ├── sb3.py           # PanelCallback (Stable-Baselines3)
│   ├── server/          # FastAPI app, SQLite store, import/export, folder watching
│   └── web/             # build-free interface (uPlot)
├── tests/               # unit + e2e (Playwright) tests
├── pyproject.toml
└── README.md
```

## Citation, license, contact

```bibtex
@misc{rlpanel2026,
  title  = {rlpanel: A local, live monitoring dashboard for RL training},
  author = {Öztürk, Emir},
  year   = {2026},
  howpublished = {\url{https://github.com/BalBaZeuR0/RLpanel}}
}
```

No license file has been added yet; please get in touch before reusing the code.
Contact: [@BalBaZeuR0](https://github.com/BalBaZeuR0), MTA Artificial Intelligence Center.
