#!/usr/bin/env python3
"""
Magnet Downloader - 支持断点续传的磁力链接下载工具
- 上传限速 100KB/s
- 下载不限速
- 动态调整下载连接数
"""

import argparse
import os
import sys
import time
import signal
from pathlib import Path

try:
    import libtorrent as lt
except ImportError:
    print("错误: 需要安装 libtorrent 库")
    print("安装方法: pip install libtorrent")
    sys.exit(1)

UPLOAD_LIMIT_KB = 100
MAX_CONNECTIONS = 300
MIN_CONNECTIONS = 10
CONNECTION_STEP = 20
OBSERVE_INTERVAL = 30
SPEED_HISTORY_SIZE = 6
SPEED_DROP_THRESHOLD = 0.05


class MagnetDownloader:
    def __init__(self, save_path: str, resume_dir: str = None, upload_limit_kb: int = UPLOAD_LIMIT_KB):
        self.save_path = os.path.abspath(save_path)
        self.resume_dir = resume_dir or os.path.join(self.save_path, ".resume")
        self.upload_limit_kb = upload_limit_kb
        self.session = None
        self.handle = None
        self.running = True
        self.info_hash = None
        self.current_max_connections = 50
        self.last_adjust_time = 0
        self.speed_history = []
        self.connection_history = {}
        self.best_connections = 50
        self.best_speed = 0
        self.direction = 1
        self.last_avg_speed = 0
        self.consecutive_same_direction = 0
        self.observing = False
        self.observe_start_time = 0
        
        os.makedirs(self.save_path, exist_ok=True)
        os.makedirs(self.resume_dir, exist_ok=True)
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print("\n收到中断信号，正在保存进度...")
        self.running = False
    
    def _get_resume_file(self) -> str:
        if self.info_hash:
            return os.path.join(self.resume_dir, f"{self.info_hash}.resume")
        return None
    
    def _load_resume_data(self) -> bytes:
        resume_file = self._get_resume_file()
        if resume_file and os.path.exists(resume_file):
            print(f"发现断点续传数据: {resume_file}")
            with open(resume_file, "rb") as f:
                return f.read()
        return None
    
    def _save_resume_data(self):
        if not self.handle or not self.handle.is_valid():
            return
        
        if self.handle.status().has_metadata:
            self.handle.save_resume_data()
    
    def _on_resume_data_saved(self, alert):
        resume_file = self._get_resume_file()
        if resume_file:
            data = lt.bencode(alert.params)
            with open(resume_file, "wb") as f:
                f.write(data)
            print(f"\n进度已保存: {resume_file}")
    
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
        settings['active_downloads'] = 10
        settings['active_seeds'] = 5
        settings['active_limit'] = 50
        settings['enable_dht'] = True
        settings['enable_lsd'] = True
        settings['enable_upnp'] = True
        settings['enable_natpmp'] = True
        settings['connections_limit'] = MAX_CONNECTIONS
        settings['max_peerlist_size'] = 4000
        settings['min_announce_interval'] = 60
        
        self.session = lt.session()
        self.session.apply_settings(settings)
    
    def _add_torrent(self, magnet_uri: str):
        params = lt.parse_magnet_uri(magnet_uri)
        self.info_hash = str(params.info_hashes.get_best())
        
        print(f"Info Hash: {self.info_hash}")
        
        params.save_path = self.save_path
        params.max_uploads = 4
        params.upload_limit = self.upload_limit_kb * 1024
        
        resume_data = self._load_resume_data()
        if resume_data:
            try:
                params = lt.read_resume_data(resume_data)
                params.save_path = self.save_path
                params.upload_limit = self.upload_limit_kb * 1024
                print("成功加载断点续传数据")
            except Exception as e:
                print(f"加载断点续传数据失败: {e}")
        
        self.handle = self.session.add_torrent(params)
        
        if not self.handle.status().has_metadata:
            print("正在获取元数据...")
    
    def _adjust_connections(self, status):
        current_time = time.time()
        download_rate = status.download_rate
        num_peers = status.num_peers
        
        self.speed_history.append(download_rate)
        if len(self.speed_history) > SPEED_HISTORY_SIZE:
            self.speed_history.pop(0)
        
        if len(self.speed_history) < SPEED_HISTORY_SIZE:
            return
        
        avg_speed = sum(self.speed_history) / len(self.speed_history)
        
        if self.observing:
            if current_time - self.observe_start_time < OBSERVE_INTERVAL:
                return
            self.observing = False
        
        if current_time - self.last_adjust_time < OBSERVE_INTERVAL:
            return
        
        self.last_adjust_time = current_time
        
        conn_key = self.current_max_connections
        if conn_key not in self.connection_history:
            self.connection_history[conn_key] = []
        self.connection_history[conn_key].append(avg_speed)
        
        if avg_speed > self.best_speed:
            self.best_speed = avg_speed
            self.best_connections = self.current_max_connections
        
        new_connections = self.current_max_connections
        
        if self.last_avg_speed > 0:
            speed_drop_ratio = (self.last_avg_speed - avg_speed) / self.last_avg_speed
            
            if speed_drop_ratio > SPEED_DROP_THRESHOLD:
                self.direction = -1
                self.consecutive_same_direction += 1
                
                step = min(CONNECTION_STEP, self.current_max_connections - MIN_CONNECTIONS)
                new_connections = max(self.current_max_connections - step, MIN_CONNECTIONS)
                print(f"\n[速度下降 {speed_drop_ratio*100:.1f}%] 减少连接数")
            else:
                self.direction = 1
                self.consecutive_same_direction += 1
                
                step = min(CONNECTION_STEP + self.consecutive_same_direction * 5, 50)
                new_connections = min(self.current_max_connections + step, MAX_CONNECTIONS)
        else:
            new_connections = min(self.current_max_connections + CONNECTION_STEP, MAX_CONNECTIONS)
        
        if new_connections != self.current_max_connections:
            self.current_max_connections = new_connections
            self.handle.set_max_connections(new_connections)
            self.observing = True
            self.observe_start_time = current_time
            self.speed_history = []
            print(f"\n[动态调整] 连接数: {new_connections} | "
                  f"速度: {self._format_speed(avg_speed)} | "
                  f"最优: {self.best_connections}@{self._format_speed(self.best_speed)} | "
                  f"观察 30 秒...")
        
        self.last_avg_speed = avg_speed
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    
    def _format_speed(self, speed: int) -> str:
        return f"{self._format_size(speed)}/s"
    
    def _format_time(self, seconds: int) -> str:
        if seconds < 0:
            return "计算中..."
        if seconds == 0:
            return "完成"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
    
    def _print_progress(self, status):
        progress = status.progress * 100
        download_rate = self._format_speed(status.download_rate)
        upload_rate = self._format_speed(status.upload_rate)
        
        if status.total_wanted > 0:
            downloaded = self._format_size(status.total_wanted_done)
            total = self._format_size(status.total_wanted)
            remaining = status.total_wanted - status.total_wanted_done
            if status.download_rate > 0:
                eta_seconds = remaining / status.download_rate
                eta = self._format_time(int(eta_seconds))
            else:
                eta = "计算中..."
        else:
            downloaded = "0 B"
            total = "未知"
            eta = "计算中..."
        
        state_map = {
            lt.torrent_status.queued_for_checking: "排队检查",
            lt.torrent_status.checking_files: "检查文件",
            lt.torrent_status.downloading_metadata: "获取元数据",
            lt.torrent_status.downloading: "下载中",
            lt.torrent_status.finished: "已完成",
            lt.torrent_status.seeding: "做种中",
            lt.torrent_status.allocating: "分配空间",
            lt.torrent_status.checking_resume_data: "检查断点数据",
        }
        
        state = state_map.get(status.state, "未知状态")
        
        peers = status.num_peers
        seeds = status.num_seeds
        
        bar_length = 40
        filled = int(bar_length * status.progress)
        bar = '█' * filled + '░' * (bar_length - filled)
        
        print(f"\r[{bar}] {progress:.1f}% | "
              f"↓{download_rate} ↑{upload_rate} | "
              f"{downloaded}/{total} | "
              f"种子:{seeds} 连接:{peers}/{self.current_max_connections} | "
              f"ETA:{eta} | {state}", end='', flush=True)
    
    def download(self, magnet_uri: str):
        print(f"保存路径: {self.save_path}")
        print(f"断点数据目录: {self.resume_dir}")
        print(f"上传限速: {self.upload_limit_kb} KB/s")
        print(f"下载限速: 无限制")
        print()
        
        self._create_session()
        self._add_torrent(magnet_uri)
        
        last_save_time = time.time()
        save_interval = 30
        
        print("开始下载...\n")
        
        try:
            while self.running:
                alerts = self.session.pop_alerts()
                
                for alert in alerts:
                    if isinstance(alert, lt.save_resume_data_alert):
                        self._on_resume_data_saved(alert)
                    elif isinstance(alert, lt.save_resume_data_failed_alert):
                        print(f"\n保存断点数据失败: {alert.error}")
                    elif isinstance(alert, lt.metadata_received_alert):
                        print("\n元数据获取成功!")
                        self._save_resume_data()
                    elif isinstance(alert, lt.torrent_error_alert):
                        print(f"\n下载错误: {alert.error}")
                    elif isinstance(alert, lt.torrent_finished_alert):
                        print("\n\n下载完成!")
                        self._save_resume_data()
                        self.running = False
                
                if self.handle and self.handle.is_valid():
                    status = self.handle.status()
                    self._print_progress(status)
                    self._adjust_connections(status)
                    
                    current_time = time.time()
                    if current_time - last_save_time >= save_interval:
                        self._save_resume_data()
                        last_save_time = current_time
                    
                    if status.is_finished:
                        print("\n\n下载完成!")
                        self._save_resume_data()
                        break
                
                time.sleep(1)
        
        finally:
            print("\n正在清理...")
            
            if self.handle and self.handle.is_valid():
                self.handle.pause()
                
                if self.handle.status().has_metadata:
                    print("保存断点数据...")
                    self.handle.save_resume_data()
                    
                    for _ in range(10):
                        alerts = self.session.pop_alerts()
                        for alert in alerts:
                            if isinstance(alert, lt.save_resume_data_alert):
                                self._on_resume_data_saved(alert)
                                break
                        time.sleep(0.5)
            
            print("退出下载器")


def main():
    parser = argparse.ArgumentParser(
        description="磁力链接下载工具 - 支持断点续传、上传限速、动态连接调整",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "magnet:?xt=urn:btih:..."
  %(prog)s -o /path/to/save "magnet:?xt=urn:btih:..."
  %(prog)s --upload-limit 50 "magnet:?xt=urn:btih:..."
        """
    )
    
    parser.add_argument(
        "magnet",
        help="磁力链接地址"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="./downloads",
        help="下载保存路径 (默认: ./downloads)"
    )
    
    parser.add_argument(
        "-r", "--resume-dir",
        default=None,
        help="断点续传数据保存目录 (默认: <保存路径>/.resume)"
    )
    
    parser.add_argument(
        "-u", "--upload-limit",
        type=int,
        default=UPLOAD_LIMIT_KB,
        help=f"上传限速 KB/s (默认: {UPLOAD_LIMIT_KB})"
    )
    
    args = parser.parse_args()
    
    if not args.magnet.startswith("magnet:"):
        print("错误: 请提供有效的磁力链接 (以 magnet: 开头)")
        sys.exit(1)
    
    downloader = MagnetDownloader(
        save_path=args.output,
        resume_dir=args.resume_dir,
        upload_limit_kb=args.upload_limit
    )
    
    downloader.download(args.magnet)


if __name__ == "__main__":
    main()
