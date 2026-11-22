"""让 tests 在 ``python -m pytest`` 之外也能从仓库根目录导入 hit 包。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
