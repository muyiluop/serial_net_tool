"""PyInstaller 入口 — 从包外正确导入，避免冻结后相对导入报错。"""
import os
import sys

# 将项目根目录的父目录加入 sys.path，使 serial_net_tool 包可被发现
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from serial_net_tool.main import main

if __name__ == "__main__":
    main()
