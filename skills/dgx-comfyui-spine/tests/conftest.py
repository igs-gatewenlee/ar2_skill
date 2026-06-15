"""讓 tests import scripts/ 下的模組（沿用家族 sibling 結構）。

被測模組（manifest_builder / spine_recompose / spine_qc）全為純函式（numpy/PIL/scipy），
不依賴 DGX / 不 sibling-import gen·transparent，故只需插入本 skill 的 scripts/。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
