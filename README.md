# MagnetDonkey 🫏

一只帮你干活儿的毛驴 - 磁力下载工具

## 功能特点

- 🧲 支持磁力链接下载
- 💾 断点续传
- ⬆️ 上传限速 (默认 100KB/s)
- 🔀 动态连接数调整
- 🖥️ PyQt5 图形界面
- 🌍 跨平台支持 (macOS/Windows/Linux)

## 安装

### 依赖

```bash
pip install PyQt5 libtorrent
```

### macOS

```bash
# 运行 GUI 版本
python magnet_donkey.py

# 或运行命令行版本
python magnet_download.py "magnet:?xt=urn:btih:..."
```

### Windows

```powershell
# 安装 Python 3.9+ 从 python.org

# 安装依赖
pip install PyQt5 libtorrent

# 运行
python magnet_donkey.py
```

## 使用方法

### GUI 版本

双击运行 `MagnetDonkey.app` (macOS) 或执行 `python magnet_donkey.py`

### 命令行版本

```bash
python magnet_download.py "magnet:?xt=urn:btih:..." -o /path/to/save
```

#### 参数说明

| 参数 | 说明 |
|------|------|
| `magnet` | 磁力链接地址 |
| `-o, --output` | 下载保存路径 (默认: ./downloads) |
| `-r, --resume-dir` | 断点续传数据目录 |
| `-u, --upload-limit` | 上传限速 KB/s (默认: 100) |

## 打包

```bash
# macOS 打包成 .app
pip install pyinstaller
pyinstaller --name "MagnetDonkey" --windowed --onefile --icon icon.icns magnet_donkey.py
```

## 技术栈

- **Python 3.9+**
- **PyQt5** - GUI 框架
- **libtorrent** - BitTorrent 协议实现

## 许可证

MIT License
