# DigUp for Windows 11

A local Windows desktop app with a floating search panel, drive/folder selection,
local semantic search, guided model setup, and background indexing schedules.

## Run

Install Python 3.12 or later. Run `Setup-DigUp.cmd` once, then open
`Run-DigUp.cmd`. Setup creates a local virtual environment with PySide6
Essentials and psutil. The launcher opens the desktop without a console.
This checkout already has its dependencies installed.

Close the previous DigUp window before opening this version. Existing settings,
source selections, model paths and index entries are retained in
`%LOCALAPPDATA%\DigUp`. Click **Sources → Update index** once after upgrading
so the index gains file fingerprints and a model signature. Schema migration
retains existing records; a failed/cancelled update retains the previous index.

## Search and background behavior

- **Ctrl+Shift+Space** opens quick search from any app. Change the shortcut in
  Settings. Registration conflicts are reported rather than silently ignored.
- Search while typing; arrows select, Enter opens, Escape dismisses quick search.
- The full app shows file icons, matching snippets, Explorer reveal and copy path.
- Choose System, Light or Dark appearance.
- Choose close behavior: Hide to tray, Minimize to taskbar, or Exit.
- Choose minimize behavior: Taskbar or Tray.
- Enable Start with Windows to register a per-user sign-in entry (no admin needed).
  Optionally start hidden in the tray. This setting does not enable itself.
- The tray provides quick search, main app, pause/resume, update, settings and Exit.
- Reopening the app communicates with the existing instance.

## Sources and index

Add folders or select drive letters. Only selected sources are read. Updates
reuse unchanged content/vectors and remove entries for deleted files/removed
sources. Full rebuild recalculates everything. Pause or stop from Sources or
the tray. Search can continue while indexing; interactive embedding requests
get priority at chunk boundaries. Missing roots and failed embeddings preserve
the previous index.

Text, Markdown, CSV, logs, HTML, RTF and DOCX have content extraction bounded to
32,000 characters and 8 MiB per input file. HTML/RTF currently retain markup.
Other files have filename search. Hidden/system folders, common credentials,
cloud placeholders and directory junctions are skipped. This is a text-search
port; PDF OCR and image/audio/video content understanding remain future work.

## Models and hardware

Keep manual executable/GGUF paths, or use the built-in download flow:

1. Open Models & hardware → Load available downloads.
2. Choose a CPU, CUDA or Vulkan Windows runtime and install it. CUDA runtime
   companion DLL archives are installed when provided in the same release.
3. Choose the EmbeddingGemma 2 quantization and download it. The official model
   catalog currently offers Q8_0 and BF16; the list comes from the repository.
4. Refresh devices and select the actual adapter from the dropdown.
5. Choose CPU/system RAM, Dedicated GPU or Integrated GPU. Save, start the
   model, and click Test embedding. Enable semantic search and update the index.

Runtime catalog: https://github.com/ggml-org/llama.cpp/releases
Model catalog: https://huggingface.co/ggml-org/embeddinggemma-2-GGUF

Downloads show sizes/progress and support cancel/resume. Models are verified
against repository SHA-256; runtime asset digests are verified when supplied by
GitHub. Runtime downloads are pinned to their release; models to their repository
revision. Failed/corrupt downloads do not replace the selected path. Managed
copies live in the data folder under models/runtimes; manual installations remain
available. Catalog access/downloads require internet; file search stays local.

Device IDs are taken from the selected executable. Vulkan can expose compatible
Intel/AMD integrated devices; CUDA requires compatible NVIDIA hardware/drivers.
Hardware classification is chosen explicitly rather than guessed from a name.
CPU mode disables GPU offload. GPU availability depends on the runtime and drivers.

The model server binds to loopback port 8787. Start checks for an existing server;
an existing compatible server can be used, and a conflicting server is reported.
The app only stops server processes it owns. To replace an external model, stop
it from its original app first. Model identity is checked before semantic indexing
and searching to avoid mixing embeddings. Changed model fingerprints require an
index update. Oversized inputs split into chunks with pooled vectors; launch uses
matching context/logical/physical batch sizes of 2048 and one slot.

## Scheduling

Choose Manual, At selected time, When idle, or Time + idle.

- Time schedules support selected weekdays and the PC's local time.
- Idle rules independently require keyboard/mouse inactivity, low CPU usage,
  and/or low system-wide GPU-engine usage. User inactivity can be disabled for
  a resources-only idle schedule.
- Configure idle duration, usage thresholds and the minimum interval between
  idle updates. Optionally require AC power for all automatic runs.
- Automatic runs pause between chunks when their conditions cease to hold.
  Configure a maximum automatic-run duration; reaching it retains the old index.
- Jobs never overlap. Missed time slots are handled once after resume; failures
  back off for five minutes. Next run, waiting reason, telemetry, last success and
  a bounded history are shown.
- GPU telemetry uses Windows performance counters across all GPU engines,
  summed conservatively and capped at 100%. Unsupported/localized counters are
  shown as unavailable; a GPU-conditioned job waits until monitoring is available
  or that condition is disabled. It does not silently assume an idle GPU.

DigUp must remain running (the tray is sufficient). It does not wake a sleeping
PC or run as a Windows service. Start with Windows and automatic model startup
are separate settings. There is no filesystem watcher yet; updates happen manually
or on the saved schedule. A signed standalone installer is still future work.

## Validation

`windows\.venv\Scripts\python.exe -m unittest discover -s windows -v`

`windows\.venv\Scripts\python.exe windows\qa_desktop.py`

The second command needs an interactive Windows desktop and briefly opens test
windows. It uses isolated settings and mocks startup writes. Tests cover index
migration/reuse, cancellation, scheduling, device/hotkey parsing, download
checksums/resume, native hotkey delivery, tray/taskbar and keyboard behavior.
Real CPU runtime/Q8_0 downloads, CPU embeddings and the existing CUDA server's
index/query path were also verified locally. Actual sign-in launch and Intel/AMD
GPU execution still require machine-specific validation.

Source: https://github.com/ARahim3/DigUp
Fork / Windows branch: https://github.com/ampersandru/DigUp/tree/windows-11
