"""Persistent settings, incremental index, and search shared by the desktop UI."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from digup_windows import safe, read_text, embed, cosine, embedding_request

DEFAULTS = {
    'roots': [], 'mode': 'CPU / system RAM', 'server': '', 'model': '', 'device': '',
    'semantic': False, 'theme': 'System', 'hotkey': 'Ctrl+Shift+Space',
    'startup': False, 'start_hidden': True, 'close_behavior': 'Hide to tray',
    'minimize_behavior': 'Taskbar', 'auto_model': False,
    'schedule_mode': 'Manual', 'schedule_time': '02:00', 'schedule_days': [0,1,2,3,4,5,6],
    'idle_minutes': 5, 'cpu_limit': 25, 'gpu_limit': 20, 'check_cpu': True,
    'check_gpu': False, 'check_user_idle': True, 'ac_only': True, 'idle_interval': 60, 'last_success': '',
    'last_schedule_slot': '', 'schedule_history': [], 'max_run_minutes': 120
}

def data_home():
    return Path(os.environ.get('DIGUP_DATA_HOME', os.environ.get('LOCALAPPDATA', str(Path.home())) + '/DigUp'))

class Settings:
    def __init__(self, home=None):
        self.home = Path(home) if home else data_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home/'settings.json'
        self.values = dict(DEFAULTS)
        if self.path.exists():
            self.values.update(json.loads(self.path.read_text(encoding='utf-8-sig')))
    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.values, indent=2), encoding='utf-8')
        temp.replace(self.path)


def model_signature(settings):
    if not settings['semantic']:
        return ''
    path = Path(settings['model'])
    stat = path.stat()
    # Include the extraction/embedding algorithm version to invalidate old vectors.
    return json.dumps([str(path.resolve()), stat.st_size, stat.st_mtime_ns, 2])


def verify_server_model(settings):
    if not settings['semantic']:
        return
    with urllib.request.urlopen('http://127.0.0.1:8787/props',timeout=5) as response:
        running=json.load(response).get('model_path')
    if not running or os.path.normcase(str(Path(running).resolve())) != os.path.normcase(str(Path(settings['model']).resolve())):
        raise ValueError('The running server uses a different model. Stop it, then start the selected model before indexing/searching.')


class Engine:
    def __init__(self, home):
        self.db = Path(home)/'index.sqlite'
        self.cancel = threading.Event()
        self.paused = threading.Event()
        self.inference = threading.Lock()
        self.query_waiting = threading.Event()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, text TEXT, vector TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(files)')}
            for name in ('mtime', 'size'):
                if name not in columns:
                    db.execute(f'ALTER TABLE files ADD COLUMN {name} INTEGER DEFAULT -1')

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.db,timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def checkpoint(self, condition=lambda: True, wait_query=True):
        while True:
            if self.cancel.is_set():
                raise InterruptedError('Indexing stopped; previous index retained')
            available=condition()
            if available and not self.paused.is_set() and not (wait_query and self.query_waiting.is_set()):
                return
            self.cancel.wait(.25)

    def index(self, settings, progress=lambda text: None, condition=lambda: True, force=False):
        signature = model_signature(settings)
        verify_server_model(settings)
        count = reused = skipped = 0
        with self.connect() as db:
            metadata = dict(db.execute('SELECT key,value FROM metadata'))
            previous = {row[0]: row[1:] for row in db.execute('SELECT path,text,vector,mtime,size FROM files')}
            compatible = metadata.get('signature') == signature and not force
            db.execute('CREATE TEMP TABLE replacement(path TEXT PRIMARY KEY, text TEXT, vector TEXT, mtime INTEGER, size INTEGER)')
            for source in settings['roots']:
                if not Path(source).is_dir():
                    raise ValueError(f'Source unavailable: {source}; previous index retained')
                errors = []
                for base, dirs, names in os.walk(source, followlinks=False, onerror=errors.append):
                    self.checkpoint(condition)
                    allowed = []
                    for directory in dirs:
                        path = Path(base)/directory
                        try:
                            attrs = getattr(path.stat(), 'st_file_attributes', 0)
                            if safe(path) and not path.is_symlink() and not path.is_junction() and not attrs & (0x1000 | 0x40000 | 0x400000):
                                allowed.append(directory)
                        except OSError:
                            skipped += 1
                    dirs[:] = allowed
                    for name in names:
                        self.checkpoint(condition)
                        path = Path(base)/name
                        try:
                            stat = path.stat()
                            if not safe(path) or path.is_symlink() or getattr(stat, 'st_file_attributes', 0) & (0x1000 | 0x40000 | 0x400000):
                                continue
                            old = previous.get(str(path))
                            if compatible and old and old[2:] == (stat.st_mtime_ns, stat.st_size):
                                text, vector = old[:2]
                                reused += 1
                            else:
                                text = read_text(path)
                                vector = '[]'
                                if settings['semantic']:
                                    try:
                                        def infer_chunk(chunk):
                                            with self.inference:
                                                return embedding_request(chunk)
                                        vector = json.dumps(embed(path.name+'\n'+text, checkpoint=lambda: self.checkpoint(condition), request=infer_chunk))
                                    except InterruptedError:
                                        raise
                                    except Exception as error:
                                        raise RuntimeError(f'Embedding failed for {path.name}; previous index retained: {error}') from error
                            db.execute('INSERT OR REPLACE INTO replacement VALUES(?,?,?,?,?)', (str(path),text,vector,stat.st_mtime_ns,stat.st_size))
                            count += 1
                            if count % 10 == 0:
                                progress(f'{count} files checked · {reused} unchanged · {skipped} skipped')
                        except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as error:
                            if isinstance(error, InterruptedError):
                                raise
                            skipped += 1
                if errors:
                    raise OSError(f'Cannot read part of {source}; previous index retained: {errors[0]}')
            self.checkpoint(condition)
            db.execute('DELETE FROM files')
            db.execute('INSERT INTO files SELECT * FROM replacement')
            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('signature',signature))
            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('model',settings['model'] if settings['semantic'] else ''))
        return f'{count} files indexed · {reused} reused · {skipped} skipped'

    def search(self, query, settings):
        query = query.strip()
        if not query:
            return []
        vector = []
        if settings['semantic']:
            verify_server_model(settings)
            with self.connect() as db:
                signature = dict(db.execute('SELECT key,value FROM metadata')).get('signature')
            if signature != model_signature(settings):
                raise ValueError('Update the index with the selected model before semantic search.')
            self.query_waiting.set()
            try:
                with self.inference:
                    vector = embed(query)
            finally:
                self.query_waiting.clear()
        tokens = query.casefold().split()
        results = []
        with self.connect() as db:
            for path,text,stored in db.execute('SELECT path,text,vector FROM files'):
                haystack = (path+'\n'+text).casefold()
                lexical = sum(token in haystack for token in tokens)/len(tokens)
                score = lexical + (cosine(vector,json.loads(stored)) if vector else 0)
                if score > 0:
                    lower = text.casefold()
                    offset = min((lower.find(token) for token in tokens if token in lower), default=0)
                    snippet = ' '.join(text[max(0,offset-50):offset+180].split())
                    results.append((score,path,snippet))
        return sorted(results,reverse=True)[:100]
