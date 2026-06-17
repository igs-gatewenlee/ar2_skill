"""Tests for ai-toolkit log_parser (P3 coverage gaps train-1..train-4).

受測 module：skills/dgx-comfyui-train/scripts/log_parser.py（純 regex + 字串/浮點
邏輯，無 DGX / GPU / SSH / 網路 / 檔案 / env 依賴，hermetic by construction）。

覆蓋缺口：
- train-1: parse_step_line() — 單行 tqdm 解析（step/total 錨在 [elapsed 之前、
  lr/loss/epoch optional、科學記號 vs 純小數、缺欄位回 None、NaN loss 回 None）
- train-2: find_critical_errors() — 5 條 regex（\\bERROR\\b 唯一 case-sensitive、
  nan/inf \\b 詞界防誤判、per-line break 去重、保序、排除正常行）
- train-3: parse_full_log() — 多行聚合（valid/garbage 交錯靜默跳過、保序）
- train-4: is_complete() — best-effort 完成標記（字序敏感、行尾錨定 over-match）

所有 expected 值均對照 production code 實跑 ground-truth 後寫入（gap 註記指出原
test_sketch 數處期望值有誤，已校正：parse_step_line 對 'loss: nan' 回 None；
is_complete('finished training')==False；is_complete('not really done')==True）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# log_parser 不是 package，沿用 ref test 的 sys.path.insert 慣例。
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import log_parser  # noqa: E402


# ======================================================================
# train-1: parse_step_line()
# ======================================================================

def test_parse_step_line_real_aitoolkit_line():
    """train-1 案例1：真實 ai-toolkit tqdm 行 → 完整 StepMetric。

    loss/lr 解析成 Python float（0.3074 / 0.0001），非保留科學記號字串。
    description 文字（dreilin_smoke_20260515:）不污染 step/total。
    """
    line = ("dreilin_smoke_20260515:  10%|█         | "
            "5/50 [00:31<04:11, lr: 1.0e-04 loss: 3.074e-01]")
    m = log_parser.parse_step_line(line)
    assert m is not None
    assert m.step == 5
    assert m.total_steps == 50
    assert m.loss == pytest.approx(0.3074)
    assert m.lr == pytest.approx(0.0001)
    assert m.epoch is None
    assert m.total_epochs is None


def test_parse_step_line_missing_step_returns_none():
    """train-1 案例2：無 tqdm step/total（缺 [elapsed 錨點）→ None。"""
    assert log_parser.parse_step_line("lr: 1.0e-04 loss: 3.074e-01") is None


def test_parse_step_line_nan_loss_returns_none():
    """train-1 案例3：loss 為 'nan'（非數字）→ None。

    loss regex 要求數字 token；NaN 偵測屬 find_critical_errors 職責，
    parse_step_line 不負責（gap 指正原 sketch 此處期望有誤）。
    """
    assert log_parser.parse_step_line(
        "5/50 [00:31<04:11, lr: 1.0e-04 loss: nan]"
    ) is None


def test_parse_step_line_pure_decimal_variant():
    """train-1 案例4：純小數（非科學記號）lr/loss 也正確解析。"""
    m = log_parser.parse_step_line("5/50 [00:31, lr: 0.0001 loss: 0.3074]")
    assert m is not None
    assert m.step == 5
    assert m.total_steps == 50
    assert m.loss == pytest.approx(0.3074)
    assert m.lr == pytest.approx(0.0001)


def test_parse_step_line_missing_loss_postfix_returns_none():
    """train-1 案例5：有 lr 但缺 loss postfix → None（loss 為必要欄位）。"""
    assert log_parser.parse_step_line("5/50 [00:31, lr: 1.0e-04]") is None


def test_parse_step_line_future_kohya_epoch_line():
    """train-1 案例6：未來 kohya 風格含 Epoch 的行 → epoch/total_epochs 填入。

    step/total 仍錨在 [elapsed 之前的 5/50（非 description 中的 Epoch 2/10），
    epoch 由獨立 _EPOCH_PATTERN 補上。
    """
    m = log_parser.parse_step_line(
        "Epoch 2/10  5/50 [00:31, lr: 1.0e-04 loss: 3.074e-01]"
    )
    assert m is not None
    assert m.step == 5
    assert m.total_steps == 50
    assert m.loss == pytest.approx(0.3074)
    assert m.lr == pytest.approx(0.0001)
    assert m.epoch == 2
    assert m.total_epochs == 10


# ======================================================================
# train-2: find_critical_errors()
# ======================================================================

def test_find_critical_errors_all_markers_dedup_and_excludes_normal():
    """train-2 案例1：5 模式各命中、保序、排除正常行 / 正常 tqdm 進度行。

    'loading antelopev2 model' 與 'some normal line' 不命中；
    回傳順序即原行序。
    """
    log_text = "\n".join([
        "dreilin: 10%| | 5/50 [00:31<04:11, lr: 1.0e-04 loss: 3.074e-01]",
        "ERROR: out of memory",
        "loading antelopev2 model",
        "CUDA out of memory. Tried to allocate 2.00 GiB",
        "loss: nan",
        "Traceback (most recent call last)",
        "Loss is NaN",
        "some normal line",
    ])
    expected = [
        "ERROR: out of memory",
        "CUDA out of memory. Tried to allocate 2.00 GiB",
        "loss: nan",
        "Traceback (most recent call last)",
        "Loss is NaN",
    ]
    assert log_parser.find_critical_errors(log_text) == expected


@pytest.mark.parametrize("line,expected", [
    ("error: foo", []),           # 小寫不命中
    ("Error: foo", []),           # Title case 不命中
    ("ERROR: foo", ["ERROR: foo"]),  # 僅全大寫命中
])
def test_find_critical_errors_error_marker_is_case_sensitive(line, expected):
    """train-2 案例2：\\bERROR\\b 是 5 條中唯一 case-SENSITIVE 的（無 IGNORECASE）。

    這是承重邊界——改成 IGNORECASE 會把 'error' 字眼的正常 log 誤報成 critical。
    """
    assert log_parser.find_critical_errors(line) == expected


@pytest.mark.parametrize("line,expected", [
    ("loss: nanometer", []),          # \\b 詞界防 'nanometer' 誤判
    ("loss=nan", ["loss=nan"]),       # [:=] 接受 '=' 分隔
    ("loss is inf", ["loss is inf"]),  # 'loss is inf' 命中
])
def test_find_critical_errors_nan_inf_word_boundary(line, expected):
    """train-2 案例3：nan/inf 的 \\b 詞界——'nanometer' 不誤判為 NaN。"""
    assert log_parser.find_critical_errors(line) == expected


def test_find_critical_errors_single_line_multiple_patterns_dedup():
    """train-2 案例4：單行命中多模式只回一次（per-line break 去重）。"""
    assert log_parser.find_critical_errors("ERROR loss is nan") == [
        "ERROR loss is nan"
    ]


@pytest.mark.parametrize("text", ["", "   "])
def test_find_critical_errors_empty_or_whitespace_returns_empty(text):
    """train-2 案例5：空字串 / 純空白 → []。"""
    assert log_parser.find_critical_errors(text) == []


# ======================================================================
# train-3: parse_full_log()
# ======================================================================

def test_parse_full_log_mixed_valid_and_garbage():
    """train-3：多行 valid/garbage/空行交錯——只取合法 step 行、保序、靜默跳過。"""
    log_text = (
        "dreilin_smoke:  2%|  | 1/50 [00:05<04:00, lr: 1.0e-04 loss: 5.000e-01]\n"
        "starting training...\n"
        "dreilin_smoke:  4%|  | 2/50 [00:10<03:55, lr: 1.0e-04 loss: 4.800e-01]\n"
        "[garbage line no metrics]\n"
        "dreilin_smoke:  6%|  | 3/50 [00:15<03:50, lr: 9.0e-05 loss: 4.500e-01]\n"
        "\n"
        "Saving checkpoint\n"
        "dreilin_smoke: 10%|  | 5/50 [00:31<04:11, lr: 1.0e-04 loss: 3.074e-01]"
    )
    metrics = log_parser.parse_full_log(log_text)

    # 1. 4 個合法 step 行，garbage/空行/敘述行靜默跳過。
    assert len(metrics) == 4
    # 2. 保序（注意 4/50 不存在於輸入，故跳到 5）。
    assert [m.step for m in metrics] == [1, 2, 3, 5]
    # 3. total_steps 全 == 50。
    assert all(m.total_steps == 50 for m in metrics)
    # 4. 首尾 loss。
    assert metrics[0].loss == pytest.approx(0.5)
    assert metrics[-1].loss == pytest.approx(0.3074)
    # 5. 第三行 lr（9.0e-05）。
    assert metrics[2].lr == pytest.approx(9.0e-05)


@pytest.mark.parametrize("text", ["", "no\nmetrics\nhere"])
def test_parse_full_log_no_metrics_returns_empty(text):
    """train-3 案例6：全 garbage / 空字串 → 回空 list（不拋例外）。"""
    assert log_parser.parse_full_log(text) == []


def test_parse_full_log_nan_loss_line_silently_skipped():
    """train-3 案例7（邊界鎖定）：含 'loss: nan' 的行被靜默跳過。

    parse_step_line 對 nan loss 回 None（見 train-1 案例3），故聚合器不收該行，
    只保留前後合法行——固定此實際語意以防 regex 變更導致 NaN 行混入 metric 序列。
    """
    log_text = (
        "dreilin: 2%|  | 1/50 [00:05<04:00, lr: 1.0e-04 loss: 5.000e-01]\n"
        "dreilin: 4%|  | 2/50 [00:10<03:55, lr: 1.0e-04 loss: nan]\n"
        "dreilin: 6%|  | 3/50 [00:15<03:50, lr: 9.0e-05 loss: 4.500e-01]"
    )
    metrics = log_parser.parse_full_log(log_text)
    assert [m.step for m in metrics] == [1, 3]
    assert all(not math.isnan(m.loss) for m in metrics)


# ======================================================================
# train-4: is_complete()
# ======================================================================

@pytest.mark.parametrize("line,expected", [
    ("training completed successfully", True),   # 'training complete' 子串命中
    ("training complete", True),
    ("training finished", True),
    ("finished training", False),                # 字序敏感、反序不 match
    ("done", True),                              # \\bdone\\b\\s*$ 行尾命中
    ("all done", True),
    ("done loading checkpoint", False),          # 'done' 非行尾不 match
    ("not really done", True),                   # over-match：任何以 done 結尾的行
    ("still training, 50%", False),
])
def test_is_complete_behavior(line, expected):
    """train-4：完成標記判定（依實際行為鎖定）。

    承重語意陷阱：
    - 'training\\s+finished' 字序敏感——'finished training'(反序) → False。
    - '\\bdone\\b\\s*$' 行尾錨定——'not really done' over-match → True
      （記錄現況；若日後視為 bug 修正，此期望會翻轉，正是其守護價值）。
    gap 指正原 test_sketch 對 'finished training'(寫 True) 與
    'not really done'(寫 False) 兩處期望相反，此處已校正為實際行為。
    """
    assert log_parser.is_complete(line) is expected
