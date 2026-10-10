"""Modern VectorDash Windows desktop, quick search, setup and scheduling."""
import ctypes
from ctypes import wintypes
from datetime import datetime
import hashlib
import socket as net_socket
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import psutil
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QTime, QAbstractNativeEventFilter, QFileInfo, QEvent
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QCursor, QPainter, QColor, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem, QStackedWidget, QComboBox, QCheckBox, QSpinBox, QTimeEdit, QFileDialog, QMessageBox, QFrame, QSystemTrayIcon, QMenu, QProgressBar, QScrollArea, QFileIconProvider, QAbstractItemView)
from engine import Engine, Settings, SearchResult, verify_server_model
from previews import Preview
from digup_windows import command, embed
from windows_integration import GlobalHotkey, HOTKEY_ID, set_startup, parse_devices, idle_seconds, gpu_utilization
from scheduling import schedule_due, idle_allowed, next_run
from setup_runtime import catalogs, install_runtime, install_model
from setup_tools import install_ocr, install_ffmpeg
from content import ocr_program, ffmpeg

class Events(QObject):
    status = Signal(str)
    indexed = Signal(str, str, bool, str)
    searched = Signal(int, object, str)
    devices = Signal(object, str)
    catalog = Signal(object, object, str)
    installed = Signal(str, str, str)
    progress = Signal(str, object, object)
    metrics = Signal(object)
    model = Signal(str)

def app_icon():
    pixmap=QPixmap(64,64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#6757e8'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2,2,60,60,17,17)
    painter.setPen(QPen(QColor('white'),5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(17,14,25,25)
    painter.drawLine(38,37,49,49)
    painter.end()
    return QIcon(pixmap)

def label(text, style=''):
    result=QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    if style:
        result.setObjectName(style)
    return result

def button(text, callback, primary=False):
    result=QPushButton(text)
    result.clicked.connect(callback)
    if primary:
        result.setObjectName('primary')
    return result

def row(*widgets):
    frame=QWidget()
    layout=QHBoxLayout(frame)
    layout.setContentsMargins(0,0,0,0)
    for widget in widgets:
        layout.addWidget(widget)
    return frame

def card(title, subtitle=''):
    frame=QFrame()
    frame.setObjectName('card')
    layout=QVBoxLayout(frame)
    layout.setContentsMargins(22,18,22,18)
    layout.setSpacing(12)
    layout.addWidget(label(title,'cardTitle'))
    if subtitle:
        layout.addWidget(label(subtitle,'muted'))
    return frame,layout

def scroll_settings(widget,event):
    event.ignore()
    parent=widget.parentWidget()
    while parent is not None and not isinstance(parent,QScrollArea):
        parent=parent.parentWidget()
    if parent is not None:
        QApplication.sendEvent(parent.viewport(),event)

class ScrollSafeSpinBox(QSpinBox):
    def wheelEvent(self,event):
        scroll_settings(self,event)

class ScrollSafeTimeEdit(QTimeEdit):
    def wheelEvent(self,event):
        scroll_settings(self,event)

class ScrollSafeComboBox(QComboBox):
    def wheelEvent(self,event):
        scroll_settings(self,event)

class SearchEdit(QLineEdit):
    def __init__(self, results):
        super().__init__()
        self.results=results
        self.setPlaceholderText('Describe a file, or search for exact words…')
        self.setObjectName('searchInput')
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Down and self.results.count():
            self.results.setCurrentRow(0)
            self.results.setFocus()
        else:
            super().keyPressEvent(event)

class Results(QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner=owner
        self.setObjectName('results')
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.icons=QFileIconProvider()
        self.itemActivated.connect(lambda item:owner.open_file(item.data(Qt.ItemDataRole.UserRole)))
    def populate(self, results):
        self.clear()
        for result in results:
            score,path,snippet = result
            item=QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,result if isinstance(result,SearchResult) else path)
            item.setToolTip(path)
            widget=QWidget()
            layout=QHBoxLayout(widget)
            layout.setContentsMargins(12,10,12,10)
            icon=QLabel()
            icon.setPixmap(self.icons.icon(QFileInfo(path)).pixmap(32,32))
            layout.addWidget(icon)
            content=QVBoxLayout()
            content.setSpacing(3)
            content.addWidget(label(Path(path).name,'resultTitle'))
            content.addWidget(label((result.location()+' · ' if isinstance(result,SearchResult) else '')+path,'muted'))
            if snippet:
                content.addWidget(label(snippet,'snippet'))
            layout.addLayout(content,1)
            item.setSizeHint(widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item,widget)
        if self.count():
            self.setCurrentRow(0)
    def selected_path(self):
        item=self.currentItem()
        value=item.data(Qt.ItemDataRole.UserRole) if item else None
        return value.path if isinstance(value,SearchResult) else value
    def selected_result(self):
        item=self.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback=callback
    def nativeEventFilter(self,event_type,message):
        if os.name=='nt':
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==0x0312 and msg.wParam==HOTKEY_ID:
                self.callback()
                return True,0
        return False,0

class QuickSearch(QWidget):
    def __init__(self, owner):
        super().__init__(None,Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.owner=owner
        self.setWindowTitle('VectorDash Quick Search')
        self.setWindowIcon(owner.windowIcon())
        self.setObjectName('quickSearch')
        self.resize(760,470)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(20,20,20,16)
        layout.addWidget(row(label('VectorDash','cardTitle'),button('Open full app',self.full)))
        self.results=Results(owner)
        self.input=SearchEdit(self.results)
        layout.addWidget(self.input)
        layout.addWidget(self.results,1)
        self.hint=label('↑ ↓ select     Enter open     Esc dismiss','muted')
        layout.addWidget(self.hint)
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(lambda:owner.request_search(self.input.text()))
        self.input.textChanged.connect(lambda:self.changed())
        self.input.returnPressed.connect(lambda:owner.open_file(self.results.selected_result()) if self.results.count() else owner.request_search(self.input.text()))
        QShortcut(QKeySequence('Escape'),self,activated=self.hide)
    def changed(self):
        self.results.clear()
        self.owner.search_sequence+=1
        self.timer.start()

    def full(self):
        self.owner.query.setText(self.input.text())
        self.hide()
        self.owner.show_main()
    def summon(self):
        screen=QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        self.move(area.center().x()-self.width()//2,area.top()+max(40,int(area.height()*.22)))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.input.selectAll()
        self.owner.request_search(self.input.text())
    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and self.isVisible():
            self.hide()
        return super().event(event)

class Desktop(QMainWindow):
    def __init__(self, settings, ipc=None):
        super().__init__()
        self.store=settings
        self.settings=settings.values
        self.engine=Engine(settings.home)
        self.events=Events()
        self.indexing=False
        self.automatic_active=False
        self.installing=False
        self.collecting=False
        self.metrics={'cpu':None,'gpu':None,'idle':None,'on_ac':None}
        self.metrics_time=0
        self.schedule_retry=0
        self.model_process=None
        self.model_log=None
        self.download_cancel=threading.Event()
        self.search_sequence=0
        self.pending_search=None
        self.search_running=False
        self.widgets={}
        self.runtimes=[]
        self.models=[]
        self.shutting_down=False
        self.setWindowTitle('VectorDash')
        self.setWindowIcon(app_icon())
        self.resize(1120,820)
        self.setMinimumSize(850,620)
        self.events.status.connect(self.set_status)
        self.events.indexed.connect(self.index_finished)
        self.events.searched.connect(self.search_finished)
        self.events.devices.connect(self.devices_finished)
        self.events.catalog.connect(self.catalog_finished)
        self.events.installed.connect(self.install_finished)
        self.events.progress.connect(self.download_progress)
        self.events.metrics.connect(self.metrics_finished)
        self.events.model.connect(self.model_status)
        self.build()
        self.quick=QuickSearch(self)
        self.hotkey=GlobalHotkey()
        self.hotkey_filter=HotkeyFilter(self.toggle_quick)
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)
        self.tray=QSystemTrayIcon(self.windowIcon(),self)
        menu=QMenu()
        menu.addAction('Quick search',self.toggle_quick)
        menu.addAction('Open VectorDash',lambda:self.show_main())
        menu.addSeparator()
        menu.addAction('Pause / resume indexing',self.pause_index)
        menu.addAction('Update index',lambda:self.start_index())
        menu.addAction('Settings',lambda:self.show_main(4))
        menu.addSeparator()
        menu.addAction('Exit VectorDash',self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('VectorDash • local file search')
        self.tray.activated.connect(lambda reason:self.toggle_quick() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        if ipc:
            ipc.newConnection.connect(lambda:self.accept_ipc(ipc))
        self.apply_theme()
        try:
            self.hotkey.register(self.settings['hotkey'])
            if self.settings['startup']:
                set_startup(True)
        except (OSError,ValueError) as error:
            self.set_status(str(error))
        self.clock=QTimer(self)
        self.clock.setInterval(15000)
        self.clock.timeout.connect(self.tick)
        self.clock.start()
        self.process_timer=QTimer(self)
        self.process_timer.setInterval(2000)
        self.process_timer.timeout.connect(self.check_model_exit)
        self.process_timer.start()
        QApplication.styleHints().colorSchemeChanged.connect(lambda:self.apply_theme() if self.settings['theme']=='System' else None)
        QTimer.singleShot(500,self.tick)
        if self.settings['auto_model']:
            QTimer.singleShot(800,self.start_model)

    def launch(self, work):
        threading.Thread(target=work,daemon=True).start()

    def build(self):
        central=QWidget()
        root=QHBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        sidebar=QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(205)
        nav=QVBoxLayout(sidebar)
        nav.setContentsMargins(20,30,16,18)
        nav.setSpacing(12)
        nav.addWidget(label('VectorDash','brand'))
        nav.addWidget(label('Find what you remember.','muted'))
        nav.addSpacing(28)
        self.navigation=QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.addItems(['Search','Sources','Models & hardware','Scheduling','Settings'])
        self.navigation.setSpacing(6)
        nav.addWidget(self.navigation,1)
        nav.addWidget(label('On your PC.\nYour files stay local.','muted'))
        root.addWidget(sidebar)
        body=QWidget()
        layout=QVBoxLayout(body)
        layout.setContentsMargins(28,26,28,16)
        layout.setSpacing(18)
        self.stack=QStackedWidget()
        layout.addWidget(self.stack,1)
        self.status=label('Ready','muted')
        layout.addWidget(self.status)
        root.addWidget(body,1)
        self.setCentralWidget(central)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.search_page()
        self.sources_page()
        self.models_page()
        self.schedule_page()
        self.settings_page()
        self.navigation.setCurrentRow(0)

    def page(self,title,description):
        page=QWidget()
        layout=QVBoxLayout(page)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(18)
        layout.addWidget(label(title,'heading'))
        layout.addWidget(label(description,'muted'))
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content=QWidget()
        inner=QVBoxLayout(content)
        inner.setContentsMargins(0,0,8,0)
        inner.setSpacing(18)
        scroll.setWidget(content)
        layout.addWidget(scroll,1)
        self.stack.addWidget(page)
        return inner

    def field(self,layout,key,title,kind='text',options=None,minimum=0,maximum=100):
        if kind!='check':
            layout.addWidget(label(title))
        value=self.settings.get(key)
        if kind=='combo':
            widget=ScrollSafeComboBox()
            widget.addItems(options)
            widget.setCurrentText(value)
        elif kind=='check':
            widget=QCheckBox(title)
            widget.setChecked(bool(value))
        elif kind=='spin':
            widget=ScrollSafeSpinBox()
            widget.setRange(minimum,maximum)
            widget.setValue(value)
        elif kind=='time':
            widget=ScrollSafeTimeEdit(QTime.fromString(value,'HH:mm'))
            widget.setDisplayFormat('hh:mm AP')
        else:
            widget=QLineEdit(str(value or ''))
        layout.addWidget(widget)
        self.widgets[key]=widget
        return widget

    def search_page(self):
        page=QWidget()
        layout=QVBoxLayout(page)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        layout.addWidget(label('What are you looking for?','heading'))
        self.shortcut_hint=label(f'Describe a file, or press {self.settings["hotkey"]} from any app.','muted')
        layout.addWidget(self.shortcut_hint)
        self.results=Results(self)
        self.query=SearchEdit(self.results)
        layout.addWidget(self.query)
        self.search_hint=label('Type to search your indexed files.','muted')
        layout.addWidget(self.search_hint)
        layout.addWidget(self.results,1)
        layout.addWidget(row(button('Open',lambda:self.open_file(self.results.selected_result()),True),button('Show in Explorer',self.reveal),button('Copy path',self.copy_path)))
        self.stack.addWidget(page)
        self.search_timer=QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(lambda:self.request_search(self.query.text()))
        self.query.textChanged.connect(self.query_changed)
        self.query.returnPressed.connect(lambda:self.open_file(self.results.selected_result()) if self.results.count() else self.request_search(self.query.text()))

    def sources_page(self):
        layout=self.page('Your sources','Choose the drives and folders VectorDash can read.')
        frame,inside=card('Drives and folders','Hidden/system folders, cloud placeholders and common secrets are skipped.')
        self.sources=QListWidget()
        self.sources.setMinimumHeight(180)
        self.sources.addItems(self.settings['roots'])
        inside.addWidget(self.sources)
        self.drives=ScrollSafeComboBox()
        if os.name=='nt':
            mask=ctypes.windll.kernel32.GetLogicalDrives()
            self.drives.addItems([f'{chr(65+i)}:\\' for i in range(26) if mask & (1<<i)])
        inside.addWidget(row(button('Add folder…',self.add_folder,True),self.drives,button('Add drive',lambda:self.add_source(self.drives.currentText())),button('Remove',self.remove_source)))
        layout.addWidget(frame)
        frame,inside=card('Search file contents','Photos, audio and video require semantic search and the matching vision + audio encoder. PDFs retain their page numbers.')
        for key,title in [('index_images','Photos and screenshots'),('index_audio','Audio and video soundtracks'),('index_video','Video frames')]:
            self.field(inside,key,title,'check')
        self.field(inside,'video_interval','Seconds between sampled video frames','spin',minimum=1,maximum=30)
        inside.addWidget(label('Scene changes are also sampled. A brief event between frames can be missed; use 1 second for finer coverage. Audio uses overlapping 30-second windows.','muted'))
        inside.addWidget(label('OCR, decoder and encoder setup are in Models & hardware.','muted'))
        layout.addWidget(frame)
        frame,inside=card('Code search','Opt in, choose project folders, then prefix your query with code:. Git ignored files are excluded.')
        self.field(inside,'code_enabled','Enable code search','check')
        self.code_sources=QListWidget()
        self.code_sources.addItems(self.settings.get('code_roots',[]))
        self.code_sources.setMinimumHeight(100)
        inside.addWidget(self.code_sources)
        inside.addWidget(row(button('Add project…',self.add_project),button('Remove project',lambda:self.code_sources.takeItem(self.code_sources.currentRow()))))
        inside.addWidget(button('Save content settings',self.save,True))
        layout.addWidget(frame)
        frame,inside=card('Indexing','Updates reuse unchanged files. A full rebuild recalculates every vector.')
        inside.addWidget(row(button('Update index',lambda:self.start_index(),True),button('Full rebuild',lambda:self.start_index(force=True)),button('Pause / resume',self.pause_index),button('Stop',self.engine.cancel.set)))
        self.index_status=label('No indexing task running.','muted')
        inside.addWidget(self.index_status)
        layout.addWidget(frame)
        layout.addStretch()

    def add_project(self):
        path=QFileDialog.getExistingDirectory(self,'Choose a project folder')
        if path and path not in [self.code_sources.item(i).text() for i in range(self.code_sources.count())]:
            self.code_sources.addItem(path)

    def models_page(self):
        layout=self.page('Models & hardware','Set up local semantic search, or keep using filename and text search.')
        frame,inside=card('Local inference','Keep your existing runtime and model, or download them below.')
        self.field(inside,'semantic','Use semantic search','check')
        self.field(inside,'mode','Run on','combo',['CPU / system RAM','Dedicated GPU','Integrated GPU'])
        self.devices=ScrollSafeComboBox()
        self.devices.addItem(self.settings['device'] or 'Select an adapter',self.settings['device'])
        inside.addWidget(label('Inference device'))
        inside.addWidget(row(self.devices,button('Refresh devices',self.refresh_devices)))
        for key,title in [('server','llama-server executable'),('model','Embedding model (GGUF)'),('projector','Vision + audio encoder (matching mmproj GGUF)')]:
            self.field(inside,key,title)
            inside.addWidget(button('Browse…',lambda checked=False,k=key:self.browse(k)))
        self.field(inside,'auto_model','Start model automatically when VectorDash starts','check')
        inside.addWidget(row(button('Save hardware settings',self.save,True),button('Start model',self.start_model),button('Stop model',self.stop_model),button('Test embedding',self.test_model)))
        self.model_state=label('Model readiness is checked when starting or testing.','muted')
        inside.addWidget(self.model_state)
        layout.addWidget(frame)
        frame,inside=card('Download and set up','Runtime: ggml-org/llama.cpp · Model: ggml-org/embeddinggemma-2-GGUF')
        inside.addWidget(button('Load available downloads',self.load_catalog))
        self.runtime_choice=ScrollSafeComboBox()
        self.quant_choice=ScrollSafeComboBox()
        self.quant_choice.addItem('Q8_0 (recommended)','Q8_0')
        self.quant_choice.addItem('BF16','BF16')
        if 'BF16' in Path(self.settings.get('model','')).name.upper():
            self.quant_choice.setCurrentIndex(1)
        inside.addWidget(label('Windows runtime'))
        inside.addWidget(self.runtime_choice)
        inside.addWidget(label('EmbeddingGemma 2 quantization'))
        inside.addWidget(self.quant_choice)
        self.download_summary=label('Choose a quantization and click download; catalogs load automatically. Load available downloads to choose a runtime build.','muted')
        inside.addWidget(self.download_summary)
        self.runtime_choice.currentIndexChanged.connect(self.catalog_summary)
        self.quant_choice.currentIndexChanged.connect(self.catalog_summary)
        self.download_bar=QProgressBar()
        self.download_bar.setValue(0)
        inside.addWidget(self.download_bar)
        inside.addWidget(row(button('Install runtime',lambda:self.install('server'),True),button('Download model + encoder',lambda:self.install('model'),True),button('Encoder only',lambda:self.install('projector')),button('Cancel download',self.download_cancel.set)))
        inside.addWidget(label('Downloads are resumable. Models are checked against SHA-256. Runtime checksums are verified when supplied by GitHub. Existing paths remain available.','muted'))
        layout.addWidget(frame)
        frame,inside=card('OCR and media tools','Optional OCR provides exact screenshot text. FFmpeg decodes audio/video and is included with VectorDash.')
        self.field(inside,'ocr_enabled','Extract exact text from screenshots and scanned PDFs','check')
        self.field(inside,'ocr_path','Tesseract executable (blank = detect installed copy)')
        inside.addWidget(button('Browse OCR executable…',lambda:self.browse('ocr_path')))
        self.field(inside,'ocr_languages','OCR language packs, e.g. eng+ben+ara')
        self.field(inside,'ocr_data','OCR language data folder (set automatically during setup)')
        inside.addWidget(button('Download and set up OCR + languages',lambda:self.install_tool('ocr'),True))
        self.field(inside,'ffmpeg_path','FFmpeg executable (blank = installed or included copy)')
        inside.addWidget(row(button('Browse FFmpeg…',lambda:self.browse('ffmpeg_path')),button('One-click FFmpeg setup',lambda:self.install_tool('ffmpeg'),True)))
        inside.addWidget(row(button('Save tool settings',self.save),button('Cancel remaining downloads',self.download_cancel.set)))
        self.tool_state=label('','muted')
        inside.addWidget(self.tool_state)
        inside.addWidget(label('The model GGUF handles text. Its mmproj file supplies EmbeddingGemma’s own image/audio encoders. Tesseract is optional for exact OCR; FFmpeg is only needed for audio/video.','muted'))
        layout.addWidget(frame)
        self.update_tool_state()
        layout.addStretch()

    def schedule_page(self):
        layout=self.page('Scheduling','Keep your index current while VectorDash runs in the background.')
        frame,inside=card('When to update','Scheduled updates reuse unchanged files and never overlap.')
        self.field(inside,'schedule_mode','Schedule','combo',['Manual','At selected time','When idle','Time + idle'])
        self.field(inside,'schedule_time','Time (this PC’s local time)','time')
        dayrow=QWidget()
        days=QHBoxLayout(dayrow)
        days.setContentsMargins(0,0,0,0)
        self.day_checks=[]
        for i,name in enumerate(['Mon','Tue','Wed','Thu','Fri','Sat','Sun']):
            check=QCheckBox(name)
            check.setChecked(i in self.settings['schedule_days'])
            self.day_checks.append(check)
            days.addWidget(check)
        inside.addWidget(dayrow)
        self.field(inside,'idle_interval','Minimum minutes between idle updates','spin',minimum=5,maximum=1440)
        inside.addWidget(button('Save schedule',self.save,True))
        layout.addWidget(frame)
        frame,inside=card('Idle and power conditions','Idle conditions apply to When idle and Time + idle. AC power applies to every automatic run.')
        self.field(inside,'check_user_idle','Require keyboard and mouse inactivity','check')
        self.field(inside,'idle_minutes','Keyboard/mouse inactive for minutes','spin',minimum=1,maximum=120)
        self.field(inside,'check_cpu','Require low CPU usage','check')
        self.field(inside,'cpu_limit','CPU usage below (%)','spin',minimum=1,maximum=100)
        self.field(inside,'check_gpu','Require low GPU usage (all monitored GPU engines)','check')
        self.field(inside,'gpu_limit','GPU usage below (%)','spin',minimum=1,maximum=100)
        self.field(inside,'ac_only','Automatic indexing only on AC power','check')
        self.field(inside,'max_run_minutes','Maximum automatic run duration (minutes)','spin',minimum=5,maximum=1440)
        inside.addWidget(label('GPU monitoring depends on Windows performance counters. If unavailable, a GPU-conditioned schedule waits and explains why. Idle jobs pause between chunks when activity resumes.','muted'))
        inside.addWidget(button('Save conditions',self.save,True))
        layout.addWidget(frame)
        frame,inside=card('Schedule status')
        self.schedule_status=label('Checking conditions…','muted')
        self.telemetry=label('Collecting usage…','muted')
        self.next_status=label('Next run: manual only','muted')
        self.last_status=label('Last successful update: '+(self.settings['last_success'] or 'Never'),'muted')
        inside.addWidget(self.schedule_status)
        inside.addWidget(self.telemetry)
        inside.addWidget(self.next_status)
        inside.addWidget(self.last_status)
        self.history=QListWidget()
        self.history.setMinimumHeight(100)
        self.history.addItems(self.settings.get('schedule_history',[]))
        inside.addWidget(self.history)
        inside.addWidget(button('Update now',lambda:self.start_index()))
        inside.addWidget(label('Missed runs are handled once after resume. VectorDash must be running; it does not wake a sleeping PC.','muted'))
        layout.addWidget(frame)
        layout.addStretch()

    def settings_page(self):
        layout=self.page('Settings','Make VectorDash fit the way you use Windows.')
        frame,inside=card('Appearance and shortcut')
        self.field(inside,'theme','Appearance','combo',['System','Light','Dark'])
        self.field(inside,'hotkey','Global quick-search shortcut')
        inside.addWidget(label('Use Ctrl, Alt, Shift or Win plus Space, a letter, digit or function key. Conflicts are reported.','muted'))
        layout.addWidget(frame)
        frame,inside=card('Startup and window behavior')
        self.field(inside,'startup','Start VectorDash when I sign in to Windows','check')
        self.field(inside,'start_hidden','Start hidden in the system tray at sign-in','check')
        self.field(inside,'close_behavior','When I close the window','combo',['Hide to tray','Minimize to taskbar','Exit'])
        self.field(inside,'minimize_behavior','When I minimize the window','combo',['Taskbar','Tray'])
        inside.addWidget(label('The tray icon provides Search, Pause/resume, Settings and Exit. Closing to tray keeps schedules and the hotkey available.','muted'))
        layout.addWidget(frame)
        layout.addWidget(button('Apply settings',self.save,True))
        frame,inside=card('Local data')
        inside.addWidget(label(str(self.store.home),'muted'))
        inside.addWidget(button('Open data folder',lambda:self.open_file(str(self.store.home))))
        inside.addWidget(button('Exit VectorDash',self.exit_app))
        layout.addWidget(frame)
        layout.addStretch()

    def read_widgets(self):
        values=dict(self.settings)
        for key,widget in self.widgets.items():
            if isinstance(widget,QCheckBox):
                values[key]=widget.isChecked()
            elif isinstance(widget,QComboBox):
                values[key]=widget.currentText()
            elif isinstance(widget,QSpinBox):
                values[key]=widget.value()
            elif isinstance(widget,QTimeEdit):
                values[key]=widget.time().toString('HH:mm')
            else:
                values[key]=widget.text().strip()
        values['roots']=[self.sources.item(i).text() for i in range(self.sources.count())]
        values['code_roots']=[self.code_sources.item(i).text() for i in range(self.code_sources.count())]
        values['device']=self.devices.currentData() or ''
        values['schedule_days']=[i for i,check in enumerate(self.day_checks) if check.isChecked()]
        return values

    def save(self, quiet=False):
        values=self.read_widgets()
        if values['schedule_mode'] in ('At selected time','Time + idle') and not values['schedule_days']:
            self.error('Select at least one scheduling day.')
            return False
        old_shortcut=self.settings['hotkey']
        try:
            if values['hotkey']!=self.hotkey.current:
                self.hotkey.register(values['hotkey'])
            if values['startup']!=self.settings['startup']:
                set_startup(values['startup'])
        except (ValueError,OSError) as error:
            if self.hotkey.current!=old_shortcut:
                try:
                    self.hotkey.register(old_shortcut)
                except (OSError,ValueError):
                    pass
            self.error(str(error))
            return False
        schedule_keys=['schedule_mode','schedule_time','schedule_days']
        if any(values[key]!=self.settings[key] for key in schedule_keys):
            values['schedule_enabled_at']=datetime.now().isoformat()
            values['last_schedule_slot']=''
            self.schedule_retry=0
            if self.automatic_active:
                self.engine.cancel.set()
        self.settings=values
        self.store.values=values
        self.store.save()
        self.apply_theme()
        self.update_tool_state()
        self.shortcut_hint.setText(f'Describe a file, or press {values["hotkey"]} from any app.')
        if not quiet:
            self.set_status('Settings saved')
        return True

    def apply_theme(self):
        theme=self.settings['theme']
        dark=theme=='Dark' or (theme=='System' and QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark)
        bg='#14151d' if dark else '#f5f6fa'
        surface='#20212c' if dark else '#ffffff'
        side='#191a24' if dark else '#eceef6'
        text='#eceef8' if dark else '#202239'
        muted='#a8acc2' if dark else '#646b85'
        border='#35384b' if dark else '#dfe3ef'
        hover='#2c2f42' if dark else '#e8e7fd'
        tick_icon=(Path(__file__).parent/'assets'/'check.png').as_posix()
        css=f'''
            QWidget {{font-family: 'Segoe UI'; font-size: 13px; color: {text};}}
            QMainWindow, QScrollArea, QStackedWidget {{background: {bg};}}
            QScrollArea > QWidget > QWidget {{background: {bg};}}
            #sidebar {{background: {side}; border-right: 1px solid {border};}}
            #brand {{font-size: 29px; font-weight: 700; color: #8573ff;}}
            #heading {{font-size: 28px; font-weight: 600;}}
            #cardTitle {{font-size: 17px; font-weight: 600;}}
            #muted {{color: {muted}; font-size: 12px;}}
            #card {{background: {surface}; border: 1px solid {border}; border-radius: 12px;}}
            #card QWidget {{background: transparent;}}
            QPushButton {{background: {surface}; border: 1px solid {border}; padding: 9px 14px; border-radius: 7px;}}
            QPushButton:hover {{background: {hover};}}
            QPushButton#primary {{background: #6757e8; color: white; border-color: #6757e8;}}
            QPushButton#primary:hover {{background: #7868f2;}}
            QLineEdit, QComboBox, QSpinBox, QTimeEdit {{background: {surface}; border: 1px solid {border}; border-radius: 7px; padding: 8px; selection-background-color: #6757e8;}}
            QLineEdit:focus {{border-color: #8573ff;}}
            QComboBox QAbstractItemView {{background: {surface}; color: {text}; selection-background-color: {hover}; border: 1px solid {border};}}
            #searchInput {{font-size: 18px; padding: 16px; border-radius: 11px;}}
            QListWidget {{background: {surface}; border: 1px solid {border}; border-radius: 8px; outline: none;}}
            QListWidget::item {{padding: 7px; border-radius: 6px;}}
            QListWidget::item:selected {{background: {hover}; color: {text};}}
            #navigation {{background: transparent; border: none; font-size: 14px;}}
            #navigation::item {{padding: 13px 10px;}}
            #navigation::item:selected {{background: {hover}; color: #8573ff;}}
            #results {{background: transparent; border: none;}}
            #results::item {{background: {surface}; border: 1px solid {border}; padding: 0;}}
            #results::item:selected {{border-color: #8573ff; background: {hover};}}
            #resultTitle {{font-weight: 600; font-size: 14px;}}
            #snippet {{color: {muted}; font-size: 12px;}}
            #quickSearch {{background: {surface}; border: 2px solid #8573ff; border-radius: 14px;}}
            QCheckBox {{spacing: 8px; padding: 3px;}}
            QCheckBox::indicator {{width: 16px; height: 16px; border: 1px solid {border}; border-radius: 4px; background: {surface};}}
            QCheckBox::indicator:checked {{background: #6757e8; border-color: #6757e8; image: url("{tick_icon}");}}
            QProgressBar {{border: 1px solid {border}; border-radius: 6px; text-align: center; height: 18px;}}
            QProgressBar::chunk {{background: #6757e8; border-radius: 5px;}}
            QMenu {{background: {surface}; border: 1px solid {border}; padding: 6px;}}
            QMenu::item {{padding: 8px 20px;}}
            QMenu::item:selected {{background: {hover};}}
        '''
        QApplication.instance().setStyleSheet(css)

    def error(self,text):
        self.set_status(text)
        QMessageBox.warning(self,'VectorDash',text)

    def set_status(self,text):
        self.status.setText(text)
        if self.indexing:
            self.index_status.setText(text)

    def show_main(self,index=None):
        if index is not None:
            self.navigation.setCurrentRow(index)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if index in (None,0):
            self.query.setFocus()

    def toggle_quick(self):
        if self.quick.isVisible():
            self.quick.hide()
        else:
            self.quick.summon()

    def accept_ipc(self,server):
        socket=server.nextPendingConnection()
        if socket:
            def received():
                if socket.readAll().data()!=b'startup':
                    self.quick.summon()
                socket.disconnectFromServer()
            socket.readyRead.connect(received)
            if socket.bytesAvailable():
                received()
            socket.disconnected.connect(socket.deleteLater)

    def add_folder(self):
        self.add_source(QFileDialog.getExistingDirectory(self,'Choose a folder'))

    def add_source(self,path):
        if path and path.casefold() not in [self.sources.item(i).text().casefold() for i in range(self.sources.count())]:
            self.sources.addItem(str(Path(path).absolute()))
            self.settings['roots']=[self.sources.item(i).text() for i in range(self.sources.count())]
            self.store.save()

    def remove_source(self):
        index=self.sources.currentRow()
        if index>=0:
            self.sources.takeItem(index)
            self.settings['roots']=[self.sources.item(i).text() for i in range(self.sources.count())]
            self.store.save()
            self.set_status('Source removed. Update the index to remove its results.')

    def start_index(self,force=False,scheduled=False,slot=''):
        if self.indexing:
            self.set_status('An indexing task is already running')
            return
        if not scheduled and not self.save(quiet=True):
            return
        if not self.settings['roots'] and not (self.settings.get('code_enabled') and self.settings.get('code_roots')):
            self.set_status('Add a folder, drive or enabled code project before indexing')
            return
        self.engine.cancel.clear()
        self.engine.paused.clear()
        self.indexing=True
        self.automatic_active=scheduled
        snapshot=dict(self.settings)
        self.set_status('Checking selected sources…')
        started=time.monotonic()
        def condition():
            if scheduled:
                rules=self.settings
                if rules['schedule_mode']=='Manual':
                    raise InterruptedError('Automatic schedule disabled; previous index retained')
                if time.monotonic()-started>rules['max_run_minutes']*60:
                    raise InterruptedError('Automatic run reached its time limit; previous index retained')
                if time.monotonic()-self.metrics_time>45:
                    return False
                if rules['schedule_mode'] in ('When idle','Time + idle'):
                    return idle_allowed(rules,self.metrics)[0]
                if rules['ac_only']:
                    return self.metrics.get('on_ac') is True
            return True
        def work():
            try:
                result=self.engine.index(snapshot,self.events.status.emit,condition,force)
                self.events.indexed.emit(result,slot,True,'Scheduled' if scheduled else 'Manual')
            except Exception as error:
                self.events.indexed.emit(str(error),slot,False,'Scheduled' if scheduled else 'Manual')
        self.launch(work)

    def index_finished(self,message,slot,success,origin):
        self.indexing=False
        self.automatic_active=False
        self.engine.paused.clear()
        self.index_status.setText(message)
        self.set_status(message)
        now=datetime.now().isoformat(timespec='seconds')
        if success:
            self.settings['last_success']=now
            if slot:
                self.settings['last_schedule_slot']=slot
            self.last_status.setText('Last successful update: '+now)
        else:
            self.schedule_retry=time.monotonic()+300
        entry=f'{now} · {origin} · {"Complete" if success else "Stopped/failed"} · {message}'
        self.settings['schedule_history']=[entry]+self.settings.get('schedule_history',[])[:19]
        self.history.clear()
        self.history.addItems(self.settings['schedule_history'])
        self.store.save()
        if self.query.text():
            self.request_search(self.query.text())

    def pause_index(self):
        if not self.indexing:
            self.set_status('No indexing task running')
            return
        if self.engine.paused.is_set():
            self.engine.paused.clear()
            self.set_status('Indexing resumed')
        else:
            self.engine.paused.set()
            self.set_status('Indexing paused; search remains available')

    def query_changed(self):
        self.results.clear()
        self.search_sequence+=1
        self.search_timer.start()

    def request_search(self,query):
        self.search_sequence+=1
        self.pending_search=(self.search_sequence,query,dict(self.settings))
        if not self.search_running:
            self.run_search()

    def run_search(self):
        if not self.pending_search:
            return
        sequence,query,settings=self.pending_search
        self.pending_search=None
        self.search_running=True
        self.search_hint.setText('Searching…')
        self.quick.hint.setText('Searching…')
        def work():
            try:
                self.events.searched.emit(sequence,self.engine.search(query,settings),'')
            except Exception as error:
                self.events.searched.emit(sequence,[],str(error))
        self.launch(work)

    def search_finished(self,sequence,results,error):
        self.search_running=False
        if sequence==self.search_sequence:
            self.results.populate(results)
            self.quick.results.populate(results)
            self.search_hint.setText(error or f'{len(results)} results · Enter to open')
            self.quick.hint.setText(error or f'{len(results)} results · ↑ ↓ select · Enter open · Esc dismiss')
            if error:
                self.set_status(error)
        self.run_search()

    def open_file(self,path):
        if not path:
            return
        try:
            if isinstance(path,SearchResult):
                result=path
                from content import CODE
                if Path(result.path).suffix.lower() in CODE and result.kind!='code':
                    result.kind='code'
                    result.line=result.end_line=1
                if result.page or result.seconds>=0 or result.kind in ('image','code'):
                    preview=Preview(result,self)
                    preview.show()
                    self.quick.hide()
                    return
                path=result.path
            os.startfile(path)
            self.quick.hide()
        except Exception as error:
            self.error(str(error))

    def reveal(self):
        if path:=self.results.selected_path():
            subprocess.Popen(['explorer.exe',f'/select,{path}'])

    def copy_path(self):
        if path:=self.results.selected_path():
            QApplication.clipboard().setText(path)
            self.set_status('Path copied')

    def browse(self,key):
        path,_=QFileDialog.getOpenFileName(self,'Choose '+key,'','Executable (*.exe)' if key in ('server','ocr_path','ffmpeg_path') else 'GGUF model (*.gguf)')
        if path:
            self.widgets[key].setText(path)

    def refresh_devices(self):
        path=self.widgets['server'].text().strip()
        self.set_status('Detecting inference devices…')
        def work():
            try:
                result=subprocess.run([path,'--list-devices'],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode:
                    raise RuntimeError((result.stderr or result.stdout)[-1500:])
                output=result.stdout+'\n'+result.stderr
                self.events.devices.emit(parse_devices(output),output)
            except Exception as error:
                self.events.devices.emit([],str(error))
        self.launch(work)

    def devices_finished(self,devices,output):
        previous=self.devices.currentData()
        self.devices.clear()
        self.devices.addItem('CPU / system RAM (no GPU offload)','')
        for identifier,description in devices:
            self.devices.addItem(f'{identifier} — {description}',identifier)
        index=self.devices.findData(previous)
        self.devices.setCurrentIndex(max(0,index))
        self.set_status(f'{len(devices)} device(s) detected. Select an adapter and save.' if devices else 'No GPU devices detected: '+output[-500:])

    def start_model(self):
        if self.indexing:
            self.set_status('Stop indexing before changing the running model')
            return
        if not self.save(quiet=True):
            return
        if self.model_process and self.model_process.poll() is None:
            self.set_status('The model is already running')
            return
        try:
            if not Path(self.settings['server']).is_file() or not Path(self.settings['model']).is_file():
                raise ValueError('Choose or download a runtime and model first.')
            if self.settings.get('projector') and not Path(self.settings['projector']).is_file():
                raise ValueError('The selected vision/audio encoder does not exist. Download it or choose its mmproj GGUF file.')
            with net_socket.socket() as probe:
                occupied=probe.connect_ex(('127.0.0.1',8787))==0
            if occupied:
                try:
                    verify_server_model(dict(self.settings,semantic=True))
                    self.model_status('Connected to the existing local server. Stop it from its original app before changing models.')
                    return
                except Exception as error:
                    raise ValueError('Port 8787 is already occupied. Stop the existing server before starting a new model. '+str(error)) from error
            self.model_log=open(self.store.home/'model.log','w',encoding='utf-8')
            self.model_process=subprocess.Popen(command(self.settings),stdout=self.model_log,stderr=self.model_log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.model_state.setText('Loading the model…')
            process=self.model_process
            def wait_ready():
                for _ in range(90):
                    if self.model_process is not process:
                        return
                    if process.poll() is not None:
                        self.events.model.emit('Model exited. Open the data folder and inspect model.log.')
                        return
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=1) as response:
                            if json.load(response).get('status')=='ok':
                                self.events.model.emit('Local embedding server is ready')
                                return
                    except Exception:
                        pass
                    time.sleep(1)
                self.events.model.emit('Model still loading or port unavailable. Inspect model.log.')
            self.launch(wait_ready)
        except (OSError,ValueError) as error:
            self.error(str(error))

    def model_status(self,message):
        self.model_state.setText(message)
        self.set_status(message)

    def check_model_exit(self):
        if self.model_process and self.model_process.poll() is not None:
            code=self.model_process.returncode
            self.model_process=None
            if self.model_log:
                self.model_log.close()
                self.model_log=None
            self.model_status(f'Model process exited ({code}). See model.log for details.')

    def stop_model(self):
        process=self.model_process
        self.model_process=None
        if process and process.poll() is None:
            process.terminate()
            def finish():
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            self.launch(finish)
        if self.model_log:
            self.model_log.close()
            self.model_log=None
        self.model_status('Local model stopped' if process else 'No model owned by this app. An external server must be stopped from its original app.')

    def test_model(self):
        if not self.save(quiet=True):
            return
        snapshot=dict(self.settings,semantic=True)
        self.model_state.setText('Testing a local embedding request…')
        def work():
            try:
                verify_server_model(snapshot)
                with self.engine.inference:
                    vector=embed('task: search result | query: A document about Windows desktop search')
                with urllib.request.urlopen('http://127.0.0.1:8787/props',timeout=5) as response:
                    modalities=json.load(response).get('modalities',{})
                ready=modalities.get('vision') and modalities.get('audio')
                if snapshot.get('projector') and not ready:
                    raise ValueError('The running server has no vision/audio encoder. Stop it and start the model with the selected encoder.')
                self.events.model.emit(f'Embedding test passed · {len(vector)} dimensions · '+('text + vision + audio ready' if ready else 'text only; download/select an encoder and restart for media search'))
            except Exception as error:
                self.events.model.emit('Embedding test failed: '+str(error))
        self.launch(work)

    def load_catalog(self):
        self.set_status('Loading official runtime and model catalogs…')
        def work():
            try:
                runtimes,models=catalogs()
                self.events.catalog.emit(runtimes,models,'')
            except Exception as error:
                self.events.catalog.emit([],[],str(error))
        self.launch(work)

    def catalog_finished(self,runtimes,models,error):
        if error:
            self.error('Catalog unavailable: '+error)
            return
        selected_quant=self.quant_choice.currentData() or 'Q8_0'
        self.runtimes,self.models=runtimes,models
        self.runtime_choice.clear()
        self.quant_choice.clear()
        for item in runtimes:
            self.runtime_choice.addItem(f'{item["label"]} · {item["size"]/1024**2:.0f} MB')
        for item in models:
            self.quant_choice.addItem(f'{item["label"]} · {item["size"]/1024**2:.0f} MB',item['label'])
        self.quant_choice.setCurrentIndex(next((i for i,item in enumerate(models) if item['label']==selected_quant),0))
        preferred=next((i for i,item in enumerate(runtimes) if item['backend']=='vulkan'),0)
        if self.settings['mode']=='Dedicated GPU' and self.settings['device'].upper().startswith('CUDA'):
            preferred=next((i for i,item in enumerate(runtimes) if item['backend'].startswith('cuda-12')),preferred)
        elif self.settings['mode']=='CPU / system RAM':
            preferred=next((i for i,item in enumerate(runtimes) if item['backend']=='cpu'),preferred)
        self.runtime_choice.setCurrentIndex(preferred)
        self.catalog_summary()
        self.set_status('Downloads available. Select a runtime and quantization.')

    def catalog_summary(self):
        r=self.runtime_choice.currentIndex()
        q=self.quant_choice.currentIndex()
        if 0<=r<len(self.runtimes) and 0<=q<len(self.models):
            total=self.runtimes[r]['size']+self.models[q]['size']+self.models[q].get('projector',{}).get('size',0)
            self.download_summary.setText(f'Total download: {total/1024**2:.0f} MB. Model SHA-256 verified. Choose the runtime for your hardware; existing installations are retained.')

    def update_tool_state(self):
        try:
            engine=ocr_program(self.settings)
            decoder=ffmpeg(self.settings)
            self.tool_state.setText(('OCR detected' if engine else 'OCR not installed; image meaning search still works')+' · '+('Media decoder available' if Path(decoder).is_file() else 'Media decoder needs setup'))
        except Exception as error:
            self.tool_state.setText(str(error))

    def install_tool(self,key):
        if self.installing or self.indexing:
            self.set_status('Finish the current download/indexing task before setting up tools')
            return
        if not self.save(quiet=True):
            return
        snapshot=dict(self.settings)
        self.download_cancel.clear()
        self.installing=True
        self.download_bar.setValue(0)
        self.set_status('Setting up '+('OCR and selected languages' if key=='ocr' else 'included FFmpeg'))
        def work():
            try:
                paths=install_ocr(snapshot,self.store.home,self.download_cancel,self.events.progress.emit) if key=='ocr' else install_ffmpeg(self.store.home,self.download_cancel,self.events.progress.emit)
                self.events.installed.emit('tools',json.dumps(paths),'')
            except Exception as error:
                self.events.installed.emit('tools','',str(error))
        self.launch(work)

    def install(self,key):
        if self.installing:
            self.set_status('A download is already running')
            return
        quant=self.quant_choice.currentData() or 'Q8_0'
        runtime_index=self.runtime_choice.currentIndex()
        model_index=self.quant_choice.currentIndex()
        available_runtimes=list(self.runtimes)
        available_models=list(self.models)
        mode=self.widgets['mode'].currentText()
        device=self.devices.currentData() or ''
        self.download_cancel.clear()
        self.installing=True
        self.download_bar.setValue(0)
        self.set_status('Preparing '+('vision/audio encoder' if key=='projector' else 'download'))
        def work():
            try:
                runtimes,models=available_runtimes,available_models
                if not runtimes or not models:
                    runtimes,models=catalogs()
                    self.events.catalog.emit(runtimes,models,'')
                    preferred='cpu' if mode=='CPU / system RAM' else ('cuda-' if str(device).upper().startswith('CUDA') else 'vulkan')
                    runtime_index_local=next((i for i,item in enumerate(runtimes) if item['backend'].startswith(preferred)),0)
                    model_index_local=next((i for i,item in enumerate(models) if item['label']==quant),-1)
                    if model_index_local<0:
                        raise ValueError('The selected quantization is unavailable. Load the catalog and select an available model.')
                else:
                    runtime_index_local=runtime_index
                    model_index_local=model_index
                item=runtimes[runtime_index_local] if key=='server' else models[model_index_local]
                if key=='projector':
                    item=item.get('projector')
                    if not item:
                        raise ValueError('No matching vision/audio encoder is available for this model.')
                function=install_runtime if key=='server' else install_model
                path=function(item,self.store.home,self.download_cancel,self.events.progress.emit)
                if key=='model' and item.get('projector'):
                    encoder=install_model(item['projector'],self.store.home,self.download_cancel,self.events.progress.emit)
                    path=json.dumps({'model':path,'projector':encoder})
                self.events.installed.emit(key,path,'')
            except Exception as error:
                self.events.installed.emit(key,'',str(error))
        self.launch(work)

    def download_progress(self,title,done,total):
        self.download_bar.setValue(round(done/total*100) if total else 0)
        self.set_status(f'{title}: {done/1024**2:.0f} / {total/1024**2:.0f} MB' if total else title)

    def install_finished(self,key,path,error):
        self.installing=False
        if error:
            self.set_status(error)
            return
        paths=json.loads(path) if path.startswith('{') else {key:path}
        for name,value in paths.items():
            self.widgets[name].setText(value)
            self.settings[name]=value
        self.store.save()
        self.download_bar.setValue(100)
        self.set_status('Installed. Refresh devices, select hardware, then start/test the model.' if key=='server' else 'Model downloaded and verified. Start/test the model, then update your index.')
        self.update_tool_state()
        if key=='tools':
            self.set_status('Tools installed, verified and configured. Update the index to apply OCR changes.')
        if key=='server':
            self.refresh_devices()

    def tick(self):
        self.next_status.setText('Next run: '+next_run(self.settings,datetime.now()))
        if self.collecting:
            return
        self.collecting=True
        check_gpu=self.settings['check_gpu']
        def work():
            try:
                cpu=psutil.cpu_percent(interval=.2)
                battery=psutil.sensors_battery()
                metrics={'cpu':cpu,'gpu':gpu_utilization() if check_gpu else None,'idle':idle_seconds(),'on_ac':battery is None or battery.power_plugged}
            except Exception:
                metrics={'cpu':None,'gpu':None,'idle':None,'on_ac':None}
            self.events.metrics.emit(metrics)
        self.launch(work)

    def metrics_finished(self,metrics):
        self.collecting=False
        self.metrics=metrics
        self.metrics_time=time.monotonic()
        def number(value,suffix):
            return f'{value:.0f}{suffix}' if value is not None else 'unavailable'
        self.telemetry.setText(f'CPU {number(metrics["cpu"],"%")} · GPU {number(metrics["gpu"],"%") if self.settings["check_gpu"] else "not required"} · User idle {number(metrics["idle"],"s")} · Power {"AC" if metrics["on_ac"] else "battery/unknown"}')
        due,slot,reason=schedule_due(self.settings,datetime.now(),metrics)
        if self.indexing:
            allowed,condition=idle_allowed(self.settings,metrics)
            self.schedule_status.setText('Indexing in progress · '+(condition if self.settings['schedule_mode'] in ('When idle','Time + idle') else 'running'))
        else:
            self.schedule_status.setText(reason)
        if due and not self.indexing and time.monotonic()>=self.schedule_retry and self.settings['roots']:
            self.start_index(scheduled=True,slot=slot)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.Type.WindowStateChange and self.isMinimized() and self.settings['minimize_behavior']=='Tray' and QSystemTrayIcon.isSystemTrayAvailable():
            QTimer.singleShot(0,self.hide)

    def closeEvent(self,event):
        if self.shutting_down:
            event.accept()
            return
        behavior=self.settings['close_behavior']
        if behavior=='Exit':
            event.ignore()
            self.exit_app()
        elif behavior=='Hide to tray' and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            self.showMinimized()
            event.ignore()

    def exit_app(self):
        self.shutting_down=True
        self.engine.cancel.set()
        self.download_cancel.set()
        self.hotkey.unregister()
        self.stop_model()
        self.tray.hide()
        self.quick.hide()
        self.close()
        QApplication.instance().quit()


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('VectorDash')
    app.setOrganizationName('VectorDash')
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    settings=Settings()
    name='DigUp-'+hashlib.sha256(str(settings.home.resolve()).encode()).hexdigest()[:16]
    socket=QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(400):
        socket.write(b'startup' if '--startup' in sys.argv else b'show')
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return 0
    QLocalServer.removeServer(name)
    server=QLocalServer()
    if not server.listen(name):
        QMessageBox.critical(None,'VectorDash','Could not establish single-instance communication.')
        return 1
    window=Desktop(settings,server)
    hidden='--startup' in sys.argv and settings.values['start_hidden'] and QSystemTrayIcon.isSystemTrayAvailable()
    if not hidden:
        window.show()
    return app.exec()

if __name__=='__main__':
    raise SystemExit(main())
