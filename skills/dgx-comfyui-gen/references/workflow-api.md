# ComfyUI HTTP API 用法

`ar2:dgx-comfyui-gen` 透過本機 SSH tunnel 把 `localhost:8199` 轉到 DGX 的 ComfyUI。所有 API 呼叫都是 `http://localhost:8199/...`。

## client_id 規約

每次呼叫 `-gen` 生成一個 UUID 當 `client_id`：

```python
import uuid
client_id = str(uuid.uuid4())
```

`client_id` 主要用途：
- POST `/prompt` 時送進 body，讓伺服器在 WebSocket 通道綁定該 client
- v1 不用 WebSocket（HTTP polling 為主），但仍要附 client_id 以與 ComfyUI 慣例相容

## POST /prompt（提交工作流）

```python
import json, urllib.request

payload = {
    "prompt": workflow_dict,
    "client_id": client_id,
}
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    "http://localhost:8199/prompt",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
# result = {"prompt_id": "...", "number": N, "node_errors": {...}}
```

關鍵欄位：
- `prompt_id` — 用來 poll `/history/{id}`
- `number` — queue 位置；> 0 表示前面還有任務在跑
- `node_errors` — 若非空，工作流驗證失敗（如缺 model），不會排程

## GET /history/{prompt_id}（查詢狀態）

```python
with urllib.request.urlopen(
    f"http://localhost:8199/history/{prompt_id}", timeout=10
) as resp:
    history = json.loads(resp.read())
```

- 任務未完成 → `history == {}`
- 任務完成 → `history[prompt_id]["outputs"]` 是 `{node_id: {"images": [{"filename", "subfolder", "type"}, ...]}}`

Poll 流程：sleep 1 秒、查 history、若空就再 sleep；以此循環直到 outputs 出現或 timeout。

## GET /queue（看誰在排隊）

不在 v1 主流程使用，可手動 debug。

```python
with urllib.request.urlopen("http://localhost:8199/queue", timeout=5) as resp:
    queue = json.loads(resp.read())
# queue["queue_running"] = 跑中的任務 list
# queue["queue_pending"] = 等待中的任務 list
```

## 取得圖（兩種方式）

### 方式 A：直接 SCP（v1 用這個）

ComfyUI 把輸出寫到 `OUTPUT_DIR + subfolder + filename`，本 skill 把 `filename_prefix` 鎖在 `{date}_{tag}/img`，所以圖固定落在 `/root/ComfyUI/output/{date}_{tag}/`。SCP 整個目錄拉回。

### 方式 B：透過 ComfyUI 的 /view（v1 不用）

```
GET /view?filename=XXX&subfolder=YYY&type=output
```

回傳是 raw 圖檔。要透過 tunnel 才能訪問。比 SCP 多一層、無優勢。

## 錯誤處理

| HTTP 狀態 | 含意 | 處置 |
|---|---|---|
| 200 + `node_errors` 非空 | 工作流驗證失敗 | 印 errors、不繼續 |
| Connection refused | tunnel 沒開或 ComfyUI 沒跑 | 跑 `-check`、看 connection.md |
| Timeout | ComfyUI hang / OOM | 看 DGX log、看 connection.md |
| 4xx / 5xx | API 用法錯 / 伺服器爆 | dump response body 給人 debug |

## 與 SSH tunnel 的依賴

`/prompt`、`/history` 都要先有 tunnel：

```
ssh -fN -L 8199:localhost:8199 ... -p 7915 root@192.168.5.27
```

`scripts/ssh_client.py` 的 `ensure_tunnel()` 在第一次呼叫時建立、之後 reuse。家族其他 skill 開過後不主動 kill，本 skill 可直接 reuse。
