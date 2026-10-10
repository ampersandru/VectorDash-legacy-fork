# VectorDash for Windows 11

Search your local files by their meaning and exact words. VectorDash is a Windows
fork of [ARahim3/DigUp](https://github.com/ARahim3/DigUp), powered by
[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) and llama.cpp.
In local mode your selected files and queries stay on your PC. Remote mode
sends them to the server you configure. Internet access also supplies setup downloads.

## Start

Open [windows/Setup-VectorDash.cmd](windows/Setup-VectorDash.cmd) once, then
[windows/Run-VectorDash.cmd](windows/Run-VectorDash.cmd). Python 3.12 or later is
required. This checkout already has its dependencies installed.

**Upgrading from the previous Windows port:** exit the old app from its tray,
open VectorDash, then use **Models & hardware → Load available downloads →
Encoder only**. Choose the quantization matching your existing EmbeddingGemma 2
model. Stop the old model server from the app that started it, and start it again
with the encoder selected. Semantic search is always enabled. Test the model, and use
**Sources → Full rebuild**. Old filename/text vectors cannot identify photos.
Existing settings and downloads are reused automatically.

## Find the content

| Search | Result |
| --- | --- |
| `zebra in a video` | A sampled video frame; opens the original clip at that timestamp |
| `where they talk about sleep` | An audio window; opens playback at the matching moment |
| `the clause about pets in the lease` | The PDF page with matching words highlighted |
| `a dog on the beach` | A photo matched by its image content |
| `payment declined error` | A screenshot matched by image meaning and OCR text |
| English, Bengali or Arabic descriptions | Matching notes across the model's supported languages |
| `code: retry a failed call with backoff` | A source function or passage with its line numbers |
| Invoice numbers, error codes and names | Literal matches in paths, documents and screenshot OCR |

Search combines local semantic vectors, Unicode full-text matches and literal
identifier matching. Each result shows its page, timestamp or source location.
PDF/image highlights are preview overlays; original files are never annotated.
Code opens in a read-only preview rather than running a script.

Images and audio use the model's actual vision/audio encoders. Audio is embedded
directly; no cloud transcription or image captions are required. The model
supports 100+ languages; retrieval quality varies with language and content.

## Choose what to index

Add drives/folders in **Sources**. Select photos, audio, video and OCR individually.
PDF text is split by page and passage; scanned pages use OCR and visual embeddings.
Code content is excluded from ordinary file search. To enable it, opt in and add
project folders, then use the `code:` prefix. Git ignored files, hidden folders,
common credential files and generated dependency/build folders are excluded.
Python functions and common brace-based language functions retain their names and
line ranges; other languages use source passages. Notebook outputs are excluded.

An update reuses unchanged content and removes deleted files. Changes to the
model, encoder or content options cause reindexing. A stopped
update preserves the previous committed index. Search remains available during
indexing; interactive requests get priority between embedding requests.

## Model setup and hardware

In **Models & hardware**, load the official catalogs, install a CPU/CUDA/Vulkan
Windows runtime, then choose a model quantization. **Download model + encoder**
installs and verifies both files; **Encoder only** keeps your existing model.
Manual paths also work. A model GGUF alone only supports text: the matching
`mmproj-embeddinggemma-2-*.gguf` is required for vision and audio.

Select CPU/system RAM, Dedicated GPU or Integrated GPU. Refresh devices and select
the exact adapter. CUDA needs NVIDIA hardware/drivers; Vulkan supports compatible
Intel/AMD/NVIDIA adapters. The model test reports text-only versus vision/audio
readiness. CPU mode disables both language-model and encoder GPU offload.

Downloads resume and are pinned to the catalog revision/release. Model and encoder
SHA-256 hashes are checked. Runtime hashes are checked when supplied by GitHub.
Local servers bind to loopback port 8787. Exit stops owned helpers and a verified
matching local server; remote hosts continue running.
An external server must be stopped from its original application before changing
its model/encoder.

**OCR and media tools:** all paths, OCR language choices and one-click setup are
in **Models & hardware**. **Download and set up OCR + languages** reuses an installed
Tesseract or installs it with Windows App Installer (WinGet), downloads the selected
official language packs, verifies them, and saves the paths. Windows may show an
installer permission prompt. **One-click FFmpeg setup** configures the decoder
already included with VectorDash; no separate media-tool download is required.
**Encoder only** automatically loads the catalog and downloads/configures the mmproj
for the selected quantization without requiring a separate catalog-loading step.

The model contains its own vision/audio encoders; mmproj is how the GGUF runtime
packages those components. It is required for image/audio embeddings, and is not a
second image recognition model. Tesseract is optional for semantic photo/screenshot
search; it extracts literal OCR words, identifiers and highlight positions. Plain
text/PDF text needs neither Tesseract nor FFmpeg. FFmpeg only decodes audio/video.
Google documents the independent encoders in its
[model card](https://huggingface.co/google/embeddinggemma-2#2-selective-encoder-loading);
[GGUF files](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/tree/main) contain
the separate mmproj weights.

For Bengali/Arabic screenshots select `eng+ben+ara` and click OCR setup. Language
packs live in VectorDash's managed tools folder without modifying an existing
Tesseract installation. Multilingual text notes do not need OCR packs. Missing OCR
produces a visible index warning. Numeric/time fields and closed dropdowns forward
wheel gestures to the settings page; deliberate typing and arrow keys still work.

## Windows conveniences

- Ctrl+Shift+Space opens quick search from any application; the shortcut is configurable.
- System, light and dark appearances, file previews, Explorer reveal and copy path.
- Start with Windows, optional hidden startup, close to tray/taskbar/exit, minimize to tray/taskbar.
- A Scheduling tab supports selected times/weekdays, idle CPU/GPU/user conditions,
  AC power and maximum run duration. Jobs do not overlap. Missed runs run once after
  resume; VectorDash must remain running and does not wake a sleeping PC.
- Tray search, pause/resume, index update and Exit; reopening activates the existing instance.

## Accuracy and current limits

Video samples every three seconds plus scene changes. Select a one-second interval
for finer coverage; a very brief event between samples can be missed. Audio uses
30-second windows overlapping by five seconds and seeks to the window start, so it
can begin slightly before the spoken match. Silent windows are skipped. This is
semantic audio retrieval, not a word-by-word transcript.

OCR can misread tiny/blurry text; installed language packs control OCR coverage.
PDF highlights use matching words, falling back to the retrieved passage for
semantic queries. Protected/corrupt documents are reported as skipped. Plain text
and DOCX extraction are bounded to 8 MiB of text; unsupported files remain
searchable by filename. HTML/RTF retain markup. Animated images use their first frame.
Function detection outside Python is a best-effort source parser.

New installations use `%LOCALAPPDATA%\VectorDash`. Existing Windows installations
automatically move `%LOCALAPPDATA%\DigUp` to `%LOCALAPPDATA%\VectorDash`, updating managed paths and preserving settings, downloads and indexes. Exit the previous app before upgrading.
The data folder contains `settings.json`, `index.sqlite` and `model.log`.

## Validation

The Windows suite has 57 regression checks. Native UI checks cover hotkeys,
settings, tray/taskbar behavior, scheduling and selectable devices. Real model
checks verified cellphone and dog-on-beach retrieval from numerically named photographs, a timed zebra
video, spoken sleep audio, OCR invoice/error identifiers, PDF page 2, English to
Arabic/Bengali notes, Bengali to English retrieval and a Python retry function.
Tool setup was checked with real English/Bengali/Arabic packs and the included
FFmpeg decoder; native tests verify wheel scrolling preserves field values and
keyboard editing still works. Native previews were checked for page highlights, read-only source locations,
video/audio seeking and clean closing. Run the unit suite with:

```powershell
.venv/Scripts/python.exe -m unittest discover -s . -p 'test_*.py'
```

`qa_multimedia.py` and `qa_previews.py` are opt-in integration checks requiring
isolated local test fixtures and a model server on port 8788. They do not read your
personal sources. The Windows implementation is in [windows](.); retained
Swift/macOS sources come from the upstream project.

## Credits and license

Based on [DigUp](https://github.com/ARahim3/DigUp). Original code/license notices
are retained; see [LICENSE](../LICENSE). Model/runtime/OCR dependencies carry their
own licenses.


## Guided setup, connection status and logs

The first card in **Models & hardware** is **One-click setup**. Choose hardware
and quantization below it, then click **Download, install and start**. It installs
missing llama-server, the selected EmbeddingGemma 2 GGUF and matching encoder,
managed FFmpeg, and (when enabled) Tesseract plus your chosen OCR languages.
Use the feature checkboxes to choose which components to install. Installed
components are reused, and the button becomes **Start** when the selected
components are present. Right-aligned statuses are green for loaded/ready, yellow
for installed but not loaded/verified, and red for missing. The checklist and Settings report model/feature
readiness, and model status is checked periodically. Downloads can be cancelled.

Choose **Remote** in Server connection to use an existing EmbeddingGemma 2
llama-server. Enter its full HTTP(S) URL, optional API key and model identifier
reported by `/props`, then save and connect. The remote server needs embedding
mode and a matching encoder for images/audio. Remote mode sends selected file
content and queries to that host. Its model identity must match the configured
identifier; changing the server or identifier requires reindexing. VectorDash
does not download models onto or stop a remote machine.

**Sources** has live indexing activity, Pause/resume and Cancel. Its progress
indicator remains active until the traversal finishes because the file count is
not known beforehand. During active indexing the tray/window magnifying glass
animates in red; it becomes static purple while paused or stopped. File-specific
failures, including Pillow's oversized-image protection, are logged and skipped;
partial segments for a failed file are removed, while its filename stays searchable.
Cancellation and database/source configuration failures retain the completed index.

**Logs** filters All, Verbose, Info, Warning and Error and opens the persistent
`vectordash.log`. The separate `model.log` contains llama-server output.
**Exit VectorDash** stops its local model and helper process tree (OCR, decoder,
installer and device probes), and blocks new helpers during shutdown. A matching
existing local llama-server is also stopped on exit only after its configured
executable, model and listening port have been verified. Closing to tray continues
background work according to your window settings.

The Windows application is newly written Python/Qt code. It does not compile or
import the original macOS Swift application; the fork retains the original source,
resources and MIT attribution. A standalone Windows repository is a reasonable
future home for VectorDash if the macOS implementation will not be maintained here.


## Result previews and picture queries

Selecting a result displays its image, PDF page with highlights, text, source
passage, or audio/video moment in the right-hand pane. The hotkey search window
has the same preview. Media previews wait for Play instead of starting sound as
selection changes, and switching results releases the previous media player.
**Show in Explorer** selects the actual file using the Windows Shell API.

Semantic search is always enabled in the desktop app. If an earlier index was
built with semantic search disabled, start the model and run **Sources → Full
rebuild** once to add the missing image/audio/text embeddings. Picture queries
such as “images of dogs” match the subject; generic words describing file types
do not add lexical score when another subject is present. Exact IDs and error
codes retain their stronger literal-match score.
