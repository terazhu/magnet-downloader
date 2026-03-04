#!/bin/bash
# 打包脚本 - 将 MagnetDonkey 打包成独立应用

# 安装 pyinstaller
pip install pyinstaller

# macOS 打包成 .app
if [[ "$OSTYPE" == "darwin"* ]]; then
    pyinstaller --name "MagnetDonkey" \
                --windowed \
                --onefile \
                --icon icon.svg \
                --add-data "icon.svg:." \
                magnet_donkey.py
    echo "macOS .app 已生成: dist/MagnetDonkey.app"
fi

# Windows 打包成 .exe (在 Windows 上运行)
if [[ "$OSTYPE" == "msys"* ]] || [[ "$OSTYPE" == "win32"* ]]; then
    pyinstaller --name "MagnetDonkey" \
                --windowed \
                --onefile \
                --icon icon.ico \
                magnet_donkey.py
    echo "Windows .exe 已生成: dist/MagnetDonkey.exe"
fi

# Linux 打包成可执行文件
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    pyinstaller --name "MagnetDonkey" \
                --onefile \
                magnet_donkey.py
    echo "Linux 可执行文件已生成: dist/MagnetDonkey"
fi
