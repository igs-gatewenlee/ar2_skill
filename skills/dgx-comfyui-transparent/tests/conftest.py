"""讓 tests import scripts/ 下的模組（沿用既有 ar2 skill 的 sibling 結構）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
