#!/usr/bin/env python3
"""
MagnetDonkey - 磁力下载工具图形界面
一只帮你干活儿的毛驴 🫏
"""

import sys
import os
import time
import threading
import queue
import json
import subprocess
import platform
from dataclasses import dataclass
from typing import Dict, Optional

try:
    import libtorrent as lt
except ImportError:
    print("错误: 需要安装 libtorrent 库")
    print("安装方法: pip install libtorrent")
    sys.exit(1)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QFileDialog, QSpinBox, QProgressBar,
    QMessageBox, QAbstractItemView, QFrame, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt5.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPen, QBrush
from PyQt5.QtSvg import QSvgRenderer

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_CONFIG = {
    "download_path": os.path.expanduser("~/Downloads/MagnetDonkey"),
    "upload_limit_kb": 100,
    "max_connections": 200,
    "window_geometry": "1000x700"
}


def create_donkey_icon():
    svg_data = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
      <defs>
        <linearGradient id="bodyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#8B7355"/>
          <stop offset="100%" style="stop-color:#6B5344"/>
        </linearGradient>
        <linearGradient id="noseGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#D4C4B0"/>
          <stop offset="100%" style="stop-color:#B8A898"/>
        </linearGradient>
      </defs>
      <circle cx="128" cy="128" r="120" fill="#4A90D9"/>
      <circle cx="128" cy="128" r="110" fill="#5BA0E9"/>
      <ellipse cx="75" cy="55" rx="22" ry="38" fill="url(#bodyGrad)" transform="rotate(-20, 75, 55)"/>
      <ellipse cx="75" cy="55" rx="12" ry="25" fill="#FFB6C1" transform="rotate(-20, 75, 55)"/>
      <ellipse cx="181" cy="55" rx="22" ry="38" fill="url(#bodyGrad)" transform="rotate(20, 181, 55)"/>
      <ellipse cx="181" cy="55" rx="12" ry="25" fill="#FFB6C1" transform="rotate(20, 181, 55)"/>
      <ellipse cx="128" cy="130" rx="70" ry="65" fill="url(#bodyGrad)"/>
      <path d="M90 70 Q100 50, 110 70 Q120 50, 130 70 Q140 50, 150 70 Q160 50, 166 70" stroke="#4A3728" stroke-width="8" fill="none" stroke-linecap="round"/>
      <ellipse cx="100" cy="115" rx="12" ry="14" fill="white"/>
      <circle cx="103" cy="117" r="7" fill="#2C1810"/>
      <circle cx="105" cy="114" r="3" fill="white"/>
      <ellipse cx="156" cy="115" rx="12" ry="14" fill="white"/>
      <circle cx="159" cy="117" r="7" fill="#2C1810"/>
      <circle cx="161" cy="114" r="3" fill="white"/>
      <path d="M88 98 L112 105" stroke="#4A3728" stroke-width="3" stroke-linecap="round"/>
      <path d="M168 98 L144 105" stroke="#4A3728" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="128" cy="165" rx="35" ry="28" fill="url(#noseGrad)"/>
      <ellipse cx="115" cy="168" rx="6" ry="8" fill="#5A4A3A"/>
      <ellipse cx="141" cy="168" rx="6" ry="8" fill="#5A4A3A"/>
      <path d="M110 185 Q128 195, 146 185" stroke="#5A4A3A" stroke-width="3" fill="none" stroke-linecap="round"/>
      <ellipse cx="75" cy="145" rx="12" ry="8" fill="#FFB6C1" opacity="0.6"/>
      <ellipse cx="181" cy="145" rx="12" ry="8" fill="#FFB6C1" opacity="0.6"/>
      <circle cx="128" cy="75" r="18" fill="#FFD700"/>
      <path d="M128 60 L128 82 M118 72 L128 82 L138 72" stroke="#B8860B" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </svg>'''
    
    renderer = QSvgRenderer(svg_data.encode())
    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


@dataclass
class DownloadTask:
    id: str
    magnet_uri: str
    name: str = "获取中..."
    save_path: str = ""
    progress: float = 0.0
    download_speed: int = 0
    upload_speed: int = 0
    size_total: int = 0
    size_downloaded: int = 0
    seeds: int = 0
    peers: int = 0
    status: str = "准备中"
    handle = None
    running: bool = True
    paused: bool = False
    info_hash: str = ""


class DownloadWorker(QThread):
    progress_updated = pyqtSignal(str, str, float, int, int, int, int, int, int, str)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str, str)
    
    def __init__(self, task: DownloadTask, config: dict):
        super().__init__()
        self.task = task
        self.config = config
        self.session = None
        self.handle = None
        
    def run(self):
        try:
            self._create_session()
            self._add_torrent()
            self._download_loop()
        except Exception as e:
            self.error_signal.emit(self.task.id, str(e))
    
    def _create_session(self):
        settings = lt.default_settings()
        settings['alert_mask'] = (
            lt.alert_category.error | lt.alert_category.status | 
            lt.alert_category.storage | lt.alert_category.piece_progress
        )
        settings['dht_bootstrap_nodes'] = (
            "router.bittorrent.com:6881,"
            "router.utorrent.com:6881,"
            "dht.transmissionbt.com:6881"
        )
        settings['enable_dht'] = True
        settings['enable_lsd'] = True
        settings['enable_upnp'] = True
        settings['enable_natpmp'] = True
        settings['connections_limit'] = self.config.get("max_connections", 200)
        
        self.session = lt.session()
        self.session.apply_settings(settings)
    
    def _add_torrent(self):
        params = lt.parse_magnet_uri(self.task.magnet_uri)
        self.task.info_hash = str(params.info_hashes.get_best())
        params.save_path = self.task.save_path
        params.upload_limit = self.config.get("upload_limit_kb", 100) * 1024
        params.max_uploads = 4
        
        resume_file = os.path.join(self.task.save_path, ".resume", f"{self.task.info_hash}.resume")
        if os.path.exists(resume_file):
            try:
                with open(resume_file, "rb") as f:
                    params = lt.read_resume_data(f.read())
                    params.save_path = self.task.save_path
            except:
                pass
        
        self.handle = self.session.add_torrent(params)
        self.task.handle = self
    
    def _download_loop(self):
        last_save_time = time.time()
        
        while self.task.running:
            if self.task.paused:
                time.sleep(0.5)
                continue
                
            alerts = self.session.pop_alerts()
            
            for alert in alerts:
                if isinstance(alert, lt.torrent_finished_alert):
                    self.finished_signal.emit(self.task.id)
            
            if self.handle and self.handle.is_valid():
                status = self.handle.status()
                
                self.progress_updated.emit(
                    self.task.id,
                    status.name if status.name else self.task.name,
                    status.progress * 100,
                    status.download_rate,
                    status.upload_rate,
                    status.total_wanted,
                    status.total_wanted_done,
                    status.num_seeds,
                    status.num_peers,
                    self._get_status_text(status)
                )
                
                current_time = time.time()
                if current_time - last_save_time >= 30:
                    if status.has_metadata:
                        self.handle.save_resume_data()
                        last_save_time = current_time
            
            time.sleep(1)
    
    def _get_status_text(self, status) -> str:
        state_map = {
            lt.torrent_status.queued_for_checking: "检查中",
            lt.torrent_status.checking_files: "检查文件",
            lt.torrent_status.downloading_metadata: "获取元数据",
            lt.torrent_status.downloading: "下载中",
            lt.torrent_status.finished: "已完成",
            lt.torrent_status.seeding: "做种中",
            lt.torrent_status.allocating: "分配空间",
            lt.torrent_status.checking_resume_data: "检查断点",
        }
        return state_map.get(status.state, "未知")
    
    def pause(self):
        if self.handle:
            self.handle.pause()
            self.task.paused = True
    
    def resume(self):
        if self.handle:
            self.handle.resume()
            self.task.paused = False
    
    def stop(self):
        self.task.running = False
        if self.handle and self.handle.is_valid():
            self.handle.pause()
            if self.handle.status().has_metadata:
                self.handle.save_resume_data()


class AddTaskDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("新建下载任务")
        self.setMinimumWidth(550)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        label = QLabel("磁力链接:")
        label.setFont(QFont("SF Pro Display", 12))
        layout.addWidget(label)
        
        self.magnet_input = QLineEdit()
        self.magnet_input.setPlaceholderText("magnet:?xt=urn:btih:...")
        self.magnet_input.setFont(QFont("SF Pro Display", 11))
        self.magnet_input.setMinimumHeight(36)
        layout.addWidget(self.magnet_input)
        
        label2 = QLabel("保存路径:")
        label2.setFont(QFont("SF Pro Display", 12))
        layout.addWidget(label2)
        
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.config.get("download_path", ""))
        self.path_input.setFont(QFont("SF Pro Display", 11))
        self.path_input.setMinimumHeight(36)
        path_layout.addWidget(self.path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.setMinimumHeight(36)
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("开始下载")
        ok_btn.setMinimumWidth(100)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
        
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存路径", self.path_input.text())
        if path:
            self.path_input.setText(path)
    
    def get_data(self):
        return self.magnet_input.text().strip(), self.path_input.text().strip()


class SettingsDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        label1 = QLabel("默认下载路径:")
        label1.setFont(QFont("SF Pro Display", 11))
        layout.addWidget(label1)
        
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.config.get("download_path", ""))
        self.path_input.setMinimumHeight(32)
        path_layout.addWidget(self.path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)
        
        label2 = QLabel("上传限速 (KB/s):")
        label2.setFont(QFont("SF Pro Display", 11))
        layout.addWidget(label2)
        
        self.upload_spin = QSpinBox()
        self.upload_spin.setRange(0, 100000)
        self.upload_spin.setValue(self.config.get("upload_limit_kb", 100))
        self.upload_spin.setMinimumHeight(32)
        layout.addWidget(self.upload_spin)
        
        label3 = QLabel("最大连接数:")
        label3.setFont(QFont("SF Pro Display", 11))
        layout.addWidget(label3)
        
        self.conn_spin = QSpinBox()
        self.conn_spin.setRange(10, 500)
        self.conn_spin.setValue(self.config.get("max_connections", 200))
        self.conn_spin.setMinimumHeight(32)
        layout.addWidget(self.conn_spin)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
        
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载路径", self.path_input.text())
        if path:
            self.path_input.setText(path)
    
    def get_config(self):
        return {
            "download_path": self.path_input.text(),
            "upload_limit_kb": self.upload_spin.value(),
            "max_connections": self.conn_spin.value()
        }


class MagnetDonkeyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MagnetDonkey - 磁力下载工具")
        self.setMinimumSize(900, 600)
        
        self.config = self._load_config()
        self.tasks: Dict[str, DownloadTask] = {}
        self.workers: Dict[str, DownloadWorker] = {}
        self.task_id_counter = 0
        
        self.setWindowIcon(create_donkey_icon())
        self.setup_ui()
        self.setup_timer()
        
    def _load_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    
    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        header = self._create_header()
        layout.addWidget(header)
        
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        self.table = self._create_table()
        layout.addWidget(self.table)
        
        status_bar = self._create_status_bar()
        layout.addWidget(status_bar)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QWidget { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; }
            QLineEdit { 
                background-color: #3c3c3c; 
                border: 1px solid #555; 
                border-radius: 4px; 
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:focus { border: 1px solid #4A90D9; }
            QPushButton { 
                background-color: #4A90D9; 
                border: none; 
                border-radius: 4px; 
                padding: 8px 16px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5BA0E9; }
            QPushButton:pressed { background-color: #3A80C9; }
            QPushButton:disabled { background-color: #555; color: #888; }
            QTableWidget { 
                background-color: #3c3c3c; 
                border: none;
                gridline-color: #555;
            }
            QTableWidget::item { padding: 5px; }
            QTableWidget::item:selected { background-color: #4A90D9; }
            QHeaderView::section { 
                background-color: #4a4a4a; 
                padding: 8px;
                border: none;
                border-bottom: 1px solid #555;
                font-weight: bold;
            }
            QSpinBox {
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QDialog { background-color: #2b2b2b; }
        """)
        
    def _create_header(self):
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 10)
        
        icon_label = QLabel()
        icon_label.setPixmap(create_donkey_icon().pixmap(48, 48))
        layout.addWidget(icon_label)
        
        title_layout = QVBoxLayout()
        title = QLabel("MagnetDonkey")
        title.setFont(QFont("SF Pro Display", 20, QFont.Bold))
        title_layout.addWidget(title)
        
        subtitle = QLabel("一只帮你干活儿的毛驴")
        subtitle.setFont(QFont("SF Pro Display", 11))
        subtitle.setStyleSheet("color: #888;")
        title_layout.addWidget(subtitle)
        layout.addLayout(title_layout)
        
        layout.addStretch()
        
        speed_layout = QVBoxLayout()
        self.download_speed_label = QLabel("↓ 0 KB/s")
        self.download_speed_label.setFont(QFont("SF Pro Display", 14, QFont.Bold))
        self.download_speed_label.setStyleSheet("color: #4A90D9;")
        self.download_speed_label.setAlignment(Qt.AlignRight)
        speed_layout.addWidget(self.download_speed_label)
        
        self.upload_speed_label = QLabel("↑ 0 KB/s")
        self.upload_speed_label.setFont(QFont("SF Pro Display", 11))
        self.upload_speed_label.setStyleSheet("color: #888;")
        self.upload_speed_label.setAlignment(Qt.AlignRight)
        speed_layout.addWidget(self.upload_speed_label)
        layout.addLayout(speed_layout)
        
        return frame
    
    def _create_toolbar(self):
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 10)
        
        add_btn = QPushButton("➕ 新建下载")
        add_btn.clicked.connect(self.add_task)
        layout.addWidget(add_btn)
        
        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.clicked.connect(self.pause_selected)
        self.pause_btn.setEnabled(False)
        layout.addWidget(self.pause_btn)
        
        self.resume_btn = QPushButton("▶ 继续")
        self.resume_btn.clicked.connect(self.resume_selected)
        self.resume_btn.setEnabled(False)
        layout.addWidget(self.resume_btn)
        
        self.delete_btn = QPushButton("🗑 删除")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.delete_btn.setEnabled(False)
        layout.addWidget(self.delete_btn)
        
        layout.addStretch()
        
        open_btn = QPushButton("📂 打开目录")
        open_btn.clicked.connect(self.open_download_dir)
        layout.addWidget(open_btn)
        
        settings_btn = QPushButton("⚙ 设置")
        settings_btn.clicked.connect(self.show_settings)
        layout.addWidget(settings_btn)
        
        return frame
    
    def _create_table(self):
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["文件名", "大小", "进度", "速度", "连接", "状态"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 150)
        table.setColumnWidth(3, 120)
        table.setColumnWidth(4, 80)
        table.setColumnWidth(5, 80)
        
        table.itemSelectionChanged.connect(self.on_selection_changed)
        table.doubleClicked.connect(self.on_double_click)
        
        return table
    
    def _create_status_bar(self):
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 10, 0, 0)
        
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        self.task_count_label = QLabel("任务: 0")
        self.task_count_label.setStyleSheet("color: #888;")
        layout.addWidget(self.task_count_label)
        
        return frame
    
    def setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_total_speed)
        self.timer.start(500)
    
    def format_size(self, size: int) -> str:
        if size <= 0:
            return "未知"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    
    def format_speed(self, speed: int) -> str:
        return f"{self.format_size(speed)}/s"
    
    def add_task(self):
        dialog = AddTaskDialog(self, self.config)
        if dialog.exec_() == QDialog.Accepted:
            magnet, path = dialog.get_data()
            if not magnet.startswith("magnet:"):
                QMessageBox.warning(self, "错误", "请输入有效的磁力链接")
                return
            if not path:
                QMessageBox.warning(self, "错误", "请选择保存路径")
                return
            
            self._add_task(magnet, path)
    
    def _add_task(self, magnet_uri: str, save_path: str):
        self.task_id_counter += 1
        task_id = f"task_{self.task_id_counter}"
        
        os.makedirs(save_path, exist_ok=True)
        os.makedirs(os.path.join(save_path, ".resume"), exist_ok=True)
        
        task = DownloadTask(
            id=task_id,
            magnet_uri=magnet_uri,
            save_path=save_path
        )
        self.tasks[task_id] = task
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("获取中..."))
        self.table.setItem(row, 1, QTableWidgetItem("未知"))
        self.table.setItem(row, 2, QTableWidgetItem("0%"))
        self.table.setItem(row, 3, QTableWidgetItem("0 KB/s"))
        self.table.setItem(row, 4, QTableWidgetItem("0/0"))
        self.table.setItem(row, 5, QTableWidgetItem("准备中"))
        self.table.setItem(row, 0, QTableWidgetItem(task_id))
        self.table.item(row, 0).setData(Qt.UserRole, task_id)
        
        worker = DownloadWorker(task, self.config)
        worker.progress_updated.connect(self.on_progress_updated)
        worker.finished_signal.connect(self.on_task_finished)
        worker.error_signal.connect(self.on_task_error)
        self.workers[task_id] = worker
        worker.start()
        
        self._update_task_count()
        self.status_label.setText(f"已添加任务")
    
    def on_progress_updated(self, task_id, name, progress, dl_speed, ul_speed, total, done, seeds, peers, status):
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        task.name = name
        task.progress = progress
        task.download_speed = dl_speed
        task.upload_speed = ul_speed
        task.size_total = total
        task.size_downloaded = done
        task.seeds = seeds
        task.peers = peers
        task.status = status
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == task_id:
                self.table.item(row, 0).setText(name[:40] + "..." if len(name) > 40 else name)
                self.table.item(row, 1).setText(self.format_size(total))
                self.table.item(row, 2).setText(f"{progress:.1f}%")
                self.table.item(row, 3).setText(f"↓ {self.format_speed(dl_speed)}")
                self.table.item(row, 4).setText(f"{seeds}/{peers}")
                self.table.item(row, 5).setText(status)
                break
    
    def on_task_finished(self, task_id):
        if task_id in self.tasks:
            self.status_label.setText(f"下载完成: {self.tasks[task_id].name}")
    
    def on_task_error(self, task_id, error):
        self.status_label.setText(f"错误: {error}")
    
    def update_total_speed(self):
        total_dl = sum(t.download_speed for t in self.tasks.values())
        total_ul = sum(t.upload_speed for t in self.tasks.values())
        self.download_speed_label.setText(f"↓ {self.format_speed(total_dl)}")
        self.upload_speed_label.setText(f"↑ {self.format_speed(total_ul)}")
    
    def on_selection_changed(self):
        selected = self.table.selectedItems()
        has_selection = len(selected) > 0
        self.pause_btn.setEnabled(has_selection)
        self.resume_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
    
    def get_selected_task_id(self):
        selected = self.table.selectedItems()
        if selected:
            return selected[0].data(Qt.UserRole)
        return None
    
    def pause_selected(self):
        task_id = self.get_selected_task_id()
        if task_id and task_id in self.workers:
            self.workers[task_id].pause()
            self.status_label.setText("已暂停")
    
    def resume_selected(self):
        task_id = self.get_selected_task_id()
        if task_id and task_id in self.workers:
            self.workers[task_id].resume()
            self.status_label.setText("已继续")
    
    def delete_selected(self):
        task_id = self.get_selected_task_id()
        if task_id and task_id in self.tasks:
            reply = QMessageBox.question(self, "确认删除", 
                f"确定要删除任务吗？\n{self.tasks[task_id].name}",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                if task_id in self.workers:
                    self.workers[task_id].stop()
                    self.workers[task_id].wait()
                    del self.workers[task_id]
                del self.tasks[task_id]
                
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.data(Qt.UserRole) == task_id:
                        self.table.removeRow(row)
                        break
                
                self._update_task_count()
                self.status_label.setText("已删除任务")
    
    def on_double_click(self):
        task_id = self.get_selected_task_id()
        if task_id and task_id in self.tasks:
            path = self.tasks[task_id].save_path
            if path and os.path.exists(path):
                self.open_path(path)
    
    def open_download_dir(self):
        path = self.config.get("download_path", "")
        if path and os.path.exists(path):
            self.open_path(path)
    
    def open_path(self, path):
        if platform.system() == "Darwin":
            subprocess.run(["open", path])
        elif platform.system() == "Windows":
            subprocess.run(["explorer", path])
        else:
            subprocess.run(["xdg-open", path])
    
    def show_settings(self):
        dialog = SettingsDialog(self, self.config)
        if dialog.exec_() == QDialog.Accepted:
            self.config.update(dialog.get_config())
            self._save_config()
    
    def _update_task_count(self):
        self.task_count_label.setText(f"任务: {len(self.tasks)}")
    
    def closeEvent(self, event):
        self.config["window_geometry"] = f"{self.width()}x{self.height()}"
        self._save_config()
        
        for worker in self.workers.values():
            worker.stop()
            worker.wait()
        
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MagnetDonkeyApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
