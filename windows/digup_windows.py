"""DigUp Windows: local file search with optional llama.cpp text embeddings."""
import ctypes
import json
import math
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import urllib.request
import urllib.error
import zipfile
import xml.etree.ElementTree as ET

SKIP = {'.git', '.ssh', '.aws', 'node_modules', 'windows', '$recycle.bin', 'system volume information', 'appdata', '__pycache__'}
SECRET = {'.pem', '.key', '.pfx', '.p12', '.kdbx'}
TEXT = {'.txt', '.md', '.csv', '.log', '.html', '.rtf'}

def safe(path):
    return not any(p.lower().startswith('.') or p.lower() in SKIP for p in path.parts) and path.suffix.lower() not in SECRET and not any(s in path.name.lower() for s in ('password', 'credential', 'secret'))

def read_text(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        return ''
    if path.suffix.lower() in TEXT:
        return path.read_text(encoding='utf-8', errors='replace')[:32000]
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as z:
            if z.getinfo('word/document.xml').file_size > 8 * 1024 * 1024:
                return ''
            root = ET.fromstring(z.read('word/document.xml'))
            return ' '.join(root.itertext())[:32000]
    return ''

def cosine(a, b):
    if len(a) != len(b):
        return 0
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x,y in zip(a,b)) / norm if norm else 0

def command(settings):
    args = [settings['server'], '-m', settings['model'], '--embedding', '--host', '127.0.0.1', '--port', '8787', '-c', '2048', '--batch-size', '2048', '--ubatch-size', '2048', '--parallel', '1']
    if settings['mode'] == 'CPU / system RAM':
        args += ['--device', 'none', '--gpu-layers', '0']
    else:
        if not settings.get('device'):
            raise ValueError('Select a device identifier from List devices before starting GPU inference.')
        args += ['--device', settings['device'], '--gpu-layers', 'all']
    return args

def embedding_request(text):
    request = urllib.request.Request('http://127.0.0.1:8787/v1/embeddings', data=json.dumps({'input': text}).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            vector = json.load(response)['data'][0]['embedding']
        if not vector or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise RuntimeError('Model returned an invalid embedding')
        return vector
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')[:2000]
        # Only input-size failures can be recovered by splitting. Other server
        # failures must remain visible and preserve the previous index.
        lower = detail.lower()
        if error.code in (400, 500) and any(term in lower for term in
                ('too large', 'too long', 'batch size', 'context size', 'context length', 'exceeds')):
            raise InputTooLarge(detail) from error
        raise RuntimeError(f'Model HTTP {error.code}: {detail or error.reason}') from error


class InputTooLarge(RuntimeError):
    pass


def embed(text):
    """Embed all bounded extracted text, splitting oversized model requests.

    Character counts cannot predict token counts, especially for code and
    multilingual text. Let the runtime reject an oversized chunk, then bisect
    it without discarding any content. Pool the successful chunk vectors.
    """
    pending = [text[i:i+6000] for i in range(0, len(text), 6000)] or ['']
    vectors = []
    while pending:
        chunk = pending.pop()
        try:
            vectors.append((embedding_request(chunk), max(1, len(chunk))))
        except InputTooLarge:
            if len(chunk) <= 1:
                raise RuntimeError('Model cannot embed a minimal input; check its context/batch configuration')
            midpoint = len(chunk) // 2
            pending.extend((chunk[:midpoint], chunk[midpoint:]))
    dimensions = len(vectors[0][0])
    if any(len(vector) != dimensions for vector, _ in vectors):
        raise RuntimeError('Model embedding dimensions changed during indexing')
    total = sum(weight for _, weight in vectors)
    pooled = [sum(vector[i] * weight for vector, weight in vectors) / total for i in range(dimensions)]
    norm = math.sqrt(sum(x*x for x in pooled))
    return [x / norm for x in pooled] if norm else pooled

class App:
    def __init__(self, root):
        self.root = root
        root.title('DigUp — Windows')
        root.geometry('1000x700')
        self.home = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'DigUp'
        self.home.mkdir(parents=True, exist_ok=True)
        self.config = self.home / 'settings.json'
        self.settings = {'roots': [], 'mode': 'CPU / system RAM', 'server': '', 'model': '', 'device': '', 'semantic': False}
        if self.config.exists():
            self.settings.update(json.loads(self.config.read_text()))
        self.db = self.home / 'index.sqlite'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, text TEXT, vector TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT)')
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.process = None
        self.results = []
        tabs = ttk.Notebook(root)
        tabs.pack(fill='both', expand=True, padx=12, pady=12)
        search, sources, settings = (ttk.Frame(tabs, padding=12) for _ in range(3))
        for frame, title in ((search, 'Search'), (sources, 'Drives and folders'), (settings, 'Settings')):
            tabs.add(frame, text=title)
        self.query = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.query)
        entry.pack(fill='x')
        entry.bind('<Return>', lambda e: self.search())
        ttk.Button(search, text='Search', command=self.search).pack(anchor='w', pady=8)
        self.tree = ttk.Treeview(search, columns=('name', 'path', 'score'), show='headings')
        for col in ('name', 'path', 'score'):
            self.tree.heading(col, text=col.title())
        self.tree.column('path', width=550)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.open())
        actions = ttk.Frame(search)
        actions.pack(fill='x', pady=8)
        for title, callback in [('Open', self.open), ('Show in Explorer', self.reveal), ('Copy path', self.copy)]:
            ttk.Button(actions, text=title, command=callback).pack(side='left', padx=4)
        self.roots = tk.Listbox(sources)
        self.roots.pack(fill='both', expand=True)
        for path in self.settings['roots']:
            self.roots.insert('end', path)
        ttk.Button(sources, text='Add folder…', command=self.add_folder).pack(anchor='w', pady=4)
        self.drive = tk.StringVar()
        drives = [f'{chr(65+i)}:\\' for i in range(26) if ctypes.windll.kernel32.GetLogicalDrives() & (1 << i)] if os.name == 'nt' else ['/']
        ttk.Combobox(sources, values=drives, textvariable=self.drive, state='readonly').pack(anchor='w')
        ttk.Button(sources, text='Add selected drive', command=lambda: self.add(self.drive.get())).pack(anchor='w', pady=4)
        ttk.Button(sources, text='Remove selected source', command=self.remove).pack(anchor='w')
        ttk.Button(sources, text='Rebuild index', command=self.index).pack(anchor='w', pady=4)
        ttk.Button(sources, text='Stop indexing', command=self.cancel.set).pack(anchor='w')
        ttk.Label(sources, text='Only selected sources are read. Hidden folders, system folders, keys and common secrets are skipped.\nCloud placeholders and directory junctions are skipped. Rebuild after changing sources.').pack(anchor='w', pady=12)
        self.vars = {}
        for key, title in [('mode', 'Inference hardware'), ('device', 'llama.cpp device ID (GPU or iGPU)'), ('server', 'llama-server.exe path'), ('model', 'Embedding GGUF model path')]:
            ttk.Label(settings, text=title).pack(anchor='w', pady=(10, 2))
            var = tk.StringVar(value=self.settings[key])
            self.vars[key] = var
            if key == 'mode':
                ttk.Combobox(settings, textvariable=var, values=['CPU / system RAM', 'Dedicated GPU', 'Integrated GPU'], state='readonly').pack(fill='x')
            else:
                ttk.Entry(settings, textvariable=var).pack(fill='x')
            if key in ('server', 'model'):
                ttk.Button(settings, text='Browse…', command=lambda v=var: v.set(filedialog.askopenfilename() or v.get())).pack(anchor='w')
        self.semantic = tk.BooleanVar(value=self.settings['semantic'])
        ttk.Checkbutton(settings, text='Use local text embeddings (requires running model; rebuild index after changes)', variable=self.semantic).pack(anchor='w', pady=12)
        for title, callback in [('Save settings', self.save), ('List devices', self.devices), ('Start local model', self.start), ('Stop local model', self.stop)]:
            ttk.Button(settings, text=title, command=callback).pack(anchor='w', pady=3)
        ttk.Label(settings, text='GPU/iGPU requires a compatible llama.cpp build (Vulkan for Intel/AMD, CUDA for NVIDIA).\nChoose the exact device ID listed by your runtime. Filename/text search works without a model.\nThis version reads text and DOCX; other files are searchable by filename only.').pack(anchor='w', pady=12)
        self.status = tk.StringVar(value='Ready')
        ttk.Label(root, textvariable=self.status).pack(fill='x', padx=12, pady=8)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def save(self):
        self.settings.update({key: var.get() for key, var in self.vars.items()})
        self.settings['semantic'] = self.semantic.get()
        self.settings['roots'] = list(self.roots.get(0, 'end'))
        self.config.write_text(json.dumps(self.settings, indent=2))

    def add(self, path):
        if path and path not in self.roots.get(0, 'end'):
            self.roots.insert('end', str(Path(path).absolute()))
            self.save()

    def add_folder(self):
        self.add(filedialog.askdirectory())

    def remove(self):
        for index in reversed(self.roots.curselection()):
            self.roots.delete(index)
        self.save()

    def background(self, work):
        if self.busy:
            self.status.set('Wait for the current operation or stop indexing.')
            return
        self.busy = True
        def run():
            try:
                work()
            except Exception as e:
                self.events.put(('status', f'Failed: {e}'))
            finally:
                self.events.put(('done', None))
        threading.Thread(target=run, daemon=True).start()

    def index(self):
        self.save()
        settings = dict(self.settings)
        self.cancel.clear()
        def work():
            count, skipped = 0, 0
            with sqlite3.connect(self.db) as db:
                db.execute('CREATE TEMP TABLE replacement(path TEXT PRIMARY KEY, text TEXT, vector TEXT)')
                for source in settings['roots']:
                    if not Path(source).is_dir():
                        raise ValueError(f'Source unavailable: {source}; previous index retained')
                    for base, dirs, names in os.walk(source, followlinks=False):
                        dirs[:] = [d for d in dirs if safe(Path(base)/d) and not (Path(base)/d).is_junction() and not (Path(base)/d).is_symlink()]
                        for name in names:
                            if self.cancel.is_set():
                                self.events.put(('status', 'Stopped; previous index retained'))
                                return
                            path = Path(base)/name
                            try:
                                if not safe(path) or path.is_symlink() or path.stat().st_file_attributes & (0x1000 | 0x40000 | 0x400000):
                                    continue
                                text = read_text(path)
                                vector = []
                                if settings['semantic']:
                                    try:
                                        vector = embed(path.name + '\n' + text)
                                    except Exception as error:
                                        raise RuntimeError(f'Embedding failed for {path.name}; previous index retained: {error}') from error
                                db.execute('INSERT OR REPLACE INTO replacement VALUES(?,?,?)', (str(path), text, json.dumps(vector)))
                                count += 1
                                if count % 50 == 0:
                                    self.events.put(('status', f'Indexed {count}; skipped {skipped} unreadable files'))
                            except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError):
                                skipped += 1
                db.execute('DELETE FROM files')
                db.execute('INSERT INTO files SELECT * FROM replacement')
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('model', settings['model'] if settings['semantic'] else ''))
            self.events.put(('status', f'Indexed {count} files; skipped {skipped} unreadable files'))
        self.background(work)

    def search(self):
        query = self.query.get().strip()
        semantic = self.semantic.get()
        model = self.vars['model'].get()
        def work():
            if semantic:
                with sqlite3.connect(self.db) as db:
                    indexed = db.execute("SELECT value FROM metadata WHERE key='model'").fetchone()
                    if not indexed or indexed[0] != model or not model:
                        raise ValueError('Rebuild the index with the selected embedding model first.')
            vector = embed(query) if semantic else []
            tokens = query.casefold().split()
            results = []
            if tokens:
                with sqlite3.connect(self.db) as db:
                    for path, text, stored in db.execute('SELECT * FROM files'):
                        haystack = (path + '\n' + text).casefold()
                        lexical = sum(t in haystack for t in tokens) / len(tokens)
                        score = lexical + (cosine(vector, json.loads(stored)) if vector else 0)
                        if score > 0:
                            results.append((score, path))
            self.events.put(('results', sorted(results, reverse=True)[:200]))
        self.background(work)

    def selected(self):
        selection = self.tree.selection()
        return self.tree.item(selection[0], 'values')[1] if selection else None

    def open(self):
        if path := self.selected():
            try:
                os.startfile(path)
            except OSError as e:
                messagebox.showerror('Open file', str(e))

    def reveal(self):
        if path := self.selected():
            subprocess.Popen(['explorer.exe', '/select,', path])

    def copy(self):
        if path := self.selected():
            self.root.clipboard_clear()
            self.root.clipboard_append(path)

    def devices(self):
        self.save()
        def work():
            result = subprocess.run([self.settings['server'], '--list-devices'], capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.events.put(('devices', result.stdout + result.stderr))
        self.background(work)

    def start(self):
        self.save()
        if self.process and self.process.poll() is None:
            self.status.set('Model process already running')
            return
        try:
            self.log = open(self.home / 'model.log', 'w')
            self.process = subprocess.Popen(command(self.settings), stdout=self.log, stderr=self.log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.status.set('Model process launched; loading may take time. Logs: ' + str(self.home / 'model.log'))
        except (OSError, ValueError) as e:
            messagebox.showerror('Start model', str(e))

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if hasattr(self, 'log'):
            self.log.close()
        self.status.set('Model stopped')

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'done':
                    self.busy = False
                elif kind == 'status':
                    self.status.set(value)
                elif kind == 'devices':
                    messagebox.showinfo('Available inference devices', value or 'No devices reported')
                elif kind == 'results':
                    self.tree.delete(*self.tree.get_children())
                    for score, path in value:
                        self.tree.insert('', 'end', values=(Path(path).name, path, f'{score:.3f}'))
                    self.status.set(f'{len(value)} results')
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        self.cancel.set()
        self.stop()
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    ttk.Style().theme_use('vista' if os.name == 'nt' else 'clam')
    App(root)
    root.mainloop()
