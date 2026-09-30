#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极趣墨水屏同步 — 快捷入口 (eink_sync.py)

本文件为 tools/eink_push.py 的根目录快捷包装，
方便在 CI 或本地直接调用：

  python3 eink_sync.py --mode report --dry-run
  python3 eink_sync.py --mode news --dry-run

接口来源：k-macao/10_sync (tools/zectrix_client.py)
功能：自动运行任务 yml 时，推送去极趣墨水屏同步
"""

import sys
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.eink_push import main

if __name__ == "__main__":
    sys.exit(main())
