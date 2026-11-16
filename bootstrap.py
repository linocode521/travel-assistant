# -*- coding: utf-8 -*-
"""依赖路径引导：把项目自带的 vendor/ 目录放进 sys.path。

为什么要这个文件：本机 Python 的 site-packages 不可写，
所以 flask / reportlab / pillow 装在了项目内的 vendor/ 里。
任何入口（server.py、planner.py、exporter.py、测试脚本）只要先 import bootstrap，
就能找到这些依赖，不用改环境变量、不用管理员权限。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")

if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
