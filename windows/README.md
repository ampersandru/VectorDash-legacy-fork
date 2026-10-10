# VectorDash for Windows 11

Search your local files by their meaning and exact words. VectorDash is a Windows
fork of [ARahim3/DigUp](https://github.com/ARahim3/DigUp), powered by
[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) and llama.cpp.
Your selected files and queries stay on your PC. Internet access is used for
runtime/model catalogs and downloads.

## Start

Open [windows/Setup-VectorDash.cmd](Setup-VectorDash.cmd) once, then
[windows/Run-VectorDash.cmd](Run-VectorDash.cmd). Python 3.12 or later is
required. This checkout already has its dependencies installed.

**Upgrading from the previous Windows port:** exit the old app from its tray,
open VectorDash, then use **Models & hardware → Load available downloads →
Encoder only**. Choose the quantization matching your existing EmbeddingGemma 2
model. Stop the old model server from the app that started it, and start it again
with the encoder selected. Enable semantic search, test the model, and use
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
model, encoder or content options cause reindexing. A failed embedding or a stopped
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
The server binds to loopback port 8787. VectorDash only stops servers it started.
An external server must be stopped from its original application before changing
its model/encoder.

**OCR:** install [Tesseract for Windows](https://tesseract-ocr.github.io/tessdoc/Installation.html).
VectorDash detects common installations; Sources also accepts an executable path.
English OCR is the default. For Bengali/Arabic screenshots, install the corresponding
Tesseract language packs and select `eng+ben+ara`. Multilingual text notes do not
need OCR language packs. Missing OCR produces a visible index warning. FFmpeg is
bundled by the Python dependency, or you can select an existing executable.

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
reuse `%LOCALAPPDATA%\DigUp` so settings, downloads and indexes remain intact.
The data folder contains `settings.json`, `index.sqlite` and `model.log`.

## Validation

The Windows suite has 50 regression checks. Native UI checks cover hotkeys,
settings, tray/taskbar behavior, scheduling and selectable devices. Real model
checks verified cellphone and dog-on-beach retrieval from numerically named photographs, a timed zebra
video, spoken sleep audio, OCR invoice/error identifiers, PDF page 2, English to
Arabic/Bengali notes, Bengali to English retrieval and a Python retry function.
Native previews were checked for page highlights, read-only source locations,
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
