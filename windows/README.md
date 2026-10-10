# DigUp for Windows 11 — initial port

Run `windows\Run-DigUp.cmd` with Python 3.12+ installed (including Tcl/Tk).
No Python packages are required. Settings and the SQLite index live in
`%LOCALAPPDATA%\DigUp`. The original macOS application remains available.

1. Add folders or choose drive letters under Drives and folders.
2. Click Rebuild index, then search in the Search tab.
3. Double-click a result to open it, or use Show in Explorer / Copy path.

Text, Markdown, CSV, logs, HTML, RTF and DOCX get bounded text extraction.
Other files get filename search. RTF/HTML currently retain markup. Hidden
folders, common system/cache folders, credentials, junctions and cloud-only
placeholders are skipped. Only selected sources are indexed; sources are
read without modifying files. Rebuild removes deleted files and removed
sources. Cancelling retains the previous index. No automatic watcher yet.

## Local semantic search and hardware

Install a Windows llama.cpp `llama-server.exe` build and obtain a compatible
text embedding GGUF model separately. No model is downloaded automatically.
Set both paths in Settings. List devices displays the runtime's identifiers.
Select CPU / system RAM, Dedicated GPU or Integrated GPU. For either GPU
mode, enter the exact device ID corresponding to the intended adapter.
Vulkan builds can support Intel/AMD integrated GPUs; CUDA builds support
compatible NVIDIA devices. Availability depends on hardware and runtime.
CPU mode explicitly disables GPU offload. iGPU typically shares system RAM.

Start local model; inspect `%LOCALAPPDATA%\DigUp\model.log` if loading fails.
The server binds only to loopback, port 8787. Enable embeddings and rebuild.
Search combines literal matches with text vector similarity. Switching model
requires rebuilding the index. This prototype does not implement multimodal
embedding parity with the upstream macOS implementation. Model/server
compatibility and GPU execution require testing on your actual hardware.

## Plan and next milestones

Implemented: standalone Windows UI, drive/folder selection, saved settings,
SQLite index, cancellable rebuild, filename/content search, local embedding
API integration, explicit device launch arguments, Explorer actions.

Next: PDF extraction and OCR; image/audio/video embedding pipeline; model
identity tracking and passage indexing; incremental file watching; automatic
adapter discovery/health checks; battery-aware scheduling; tray/global
hotkey; signed standalone installer and Windows CI. Validate cloud hydration
behavior on OneDrive and removable-drive disconnection before broad release.

Tests: `python -m unittest discover -s windows -v`.

Source pulled from https://github.com/ARahim3/DigUp on branch windows-11.
GitHub fork: https://github.com/ampersandru/DigUp (Windows work on windows-11).

## Embedding input-size fix

The launcher now sets context, logical batch and physical batch to 2048,
with one server slot. Oversized inputs are split and their vectors pooled,
including when connected to an older server still using a 512-token batch.
All extracted text up to the existing 32,000-character extraction bound is
considered, rather than silently cutting embedding input at 6,000 characters.
Other HTTP errors report the server response and preserve the previous index.

After updating: close and reopen DigUp, stop/start the local model, then
Rebuild index. Existing settings and source selections are retained.
