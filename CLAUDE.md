## 目前檔案結構
```
Vorstellung/
├── CLAUDE.md            # 專案說明（本檔）
├── PROMPTS.md           # 分階段開發指令（階段 0–8）
├── requirements.txt     # mcp[cli]>=1.2,<2、rank_bm25、pymupdf、pyyaml、pytest
├── .gitignore
├── .venv/               # uv 虛擬環境（Python 3.12.4，不進版控）
├── server.py            # MCP Server（FastMCP，stdio）
├── rules.yaml           # 學分門檻規則（5 條）
├── core/
│   ├── search.py        # BM25 + 字元 bigram 檢索
│   ├── pii.py           # 個資遮蔽
│   └── rules.py         # 學分規則判斷
├── tests/               # test_search.py、test_pii.py、test_rules.py（共 39 個測試）
├── scripts/ingest.py    # PDF → kb/md/*.md + kb/chunks.json
├── eval/                # （尚未建立內容）
├── docs/                # （尚未建立內容）
└── kb/
    ├── *.pdf            # 7 份原始規章
    ├── md/              # 7 份轉檔後的 Markdown
    └── chunks.json      # 81 條切好的條文
```

## 目前進度（2026-10-19 更新）

### 已完成：階段 0～3（程式碼部分）
- **階段 0 專案骨架**：venv、資料夾、requirements、.gitignore、`git init`（**尚未 commit**）
- **階段 1 PDF 切段**：`python scripts/ingest.py` → 7 份文件共 81 條，選課辦法 14 條、0 個警告
- **階段 2 核心函式**：search / pii / rules 三個模組 + 測試，`pytest` 39 個全過
- **階段 3 MCP Server**：`server.py` 註冊 3 個 tools（`search_regulations`、`list_credit_rules`、
  `check_credit_rule`）和 1 個 prompt（`campus_assistant`）。已用 Python MCP client 透過 stdio
  實測（從 `C:\Windows` 啟動，模擬 Claude Desktop），全部正常、stdout 沒有被污染

### 進行到一半：階段 3 的手動驗證（使用者自己做）
- [ ] `mcp dev server.py` 開 MCP Inspector 測 3 個 tools（Claude 還沒親眼確認 Inspector 網頁能正常運作）
- [ ] 修改 `%APPDATA%\Claude\claude_desktop_config.json`：**只把第 2 行 `"mcpServers": {},` 換成**
  ```json
    "mcpServers": {
      "shu-campus-assistant": {
        "command": "C:\\Users\\user\\Desktop\\Vorstellung\\.venv\\Scripts\\python.exe",
        "args": ["C:\\Users\\user\\Desktop\\Vorstellung\\server.py"]
      }
    },
  ```
  其他內容（coworkUserFilesPath、preferences）不要動；結尾逗號要保留
- [ ] 從系統匣完全結束 Claude Desktop 再重開，確認工具清單看得到 `shu-campus-assistant`
- [ ] 在 Claude Desktop 問 3 題測試：
  1.「我想停修一門課，停修後學費會退嗎？」→ 預期呼叫 `search_regulations`，回答選課辦法第七條（不退費）
  2.「我大二，這學期只選了 14 學分，這樣可以嗎？」→ 預期呼叫 `check_credit_rule(semester_min_credits_y1_3, 14)`
  3.「學生宿舍什麼時候可以申請？」→ 預期查無資料；因為 `route_case` 還沒寫，Claude 應該說不確定、建議洽學務單位

### 遇到的問題與處理方式（下次不要重踩）
| 問題 | 原因 | 處理 |
|---|---|---|
| `from mcp.server.fastmcp import FastMCP` 失敗 | `mcp[cli]>=1.2` 裝到 2.x，FastMCP 在 2.x 改名為 MCPServer | requirements 改成 `mcp[cli]>=1.2,<2`（目前 mcp 1.30.0） |
| 在終端機跑 `pytest` 出現 `No module named 'rank_bm25'` | 終端機是 conda `(base)`，用到 Anaconda 的 pytest，不是 .venv 的 | 一律用 `.\.venv\Scripts\python.exe -m pytest`，或先 `.\.venv\Scripts\Activate.ps1` 再 `python -m pytest` |
| PDF 文字重複或漏字（例如「以四、五年級」少了「五年」） | PDF 含 CJK 相容字（如「年」U+F98E），pymupdf dict 模式會漏字、text 模式會重複 | ingest.py 改用 text 模式，同列重疊 ≥4 字或緊鄰相容字才去重（每次去重都會印出 `[去重]`），相容字轉回標準字 |
| Markdown 段落黏在一起（款之後的「項」併到最後一款） | text 模式沒有座標 | 從 dict 模式取每行右緣 x1，前一行以「。」「：」結尾且沒寫滿才分段；chunks.json 內容不受影響 |
| 「學生餐廳營業時間」也查得到結果（4.94 分） | 只命中「學生」「時間」常見詞，單靠分數門檻擋不住（「轉系」才 3.02 分） | search.py 加 `MIN_COVERAGE = 0.5`（條文要含一半以上查詢詞）+ 查詢疑問詞清單 `QUERY_STOPWORDS` |
| 「學號 A110123456」被當成身分證 | 格式和身分證完全相同 | pii.py 身分證要通過檢查碼才算，不通過的交給學號規則 |
| `semester_max_credits` 原本 ≤ 25 | 25 是專案服役辦法給專案役男的；選課辦法第三條一般學生上限是 22 | 拆成 `semester_max_credits`（≤22，選課辦法第三條）和 `semester_max_credits_military`（≤25） |
| MCP 查詢「學號 [STUDENT_ID] 想問停修」查不到 | 遮蔽標記被斷成 student、id 當查詢詞 | server.py 檢索前拿掉遮蔽標記；「想問」加入疑問詞清單 |
| server 日誌中文亂碼 | Windows stderr 預設 cp950 | server.py 將 stderr 改成 UTF-8 |

### 已知限制（還沒處理）
- 口語和規章用語不同時查不到，例如「一學期最多可以修幾學分」（條文寫「學分數上限」）。
  打算在 system prompt 要求 LLM 用規章用語的關鍵字查詢，不再放寬門檻
- 法律系上限 25 學分、輔系生加 4、雙主修／成績優異加 6 的例外，目前沒有對應規則
- `STUDENT_ID_PATTERN` 是假設的格式，待向校方確認實際學號格式
- Markdown 分段：段落最後一行剛好寫滿又以「。」結尾時無法判斷，會併成同一段（只影響閱讀）

## 待辦事項

### 下次進來的第一步
1. 開 PowerShell，啟用環境並確認測試還是全過：
   ```powershell
   cd C:\Users\user\Desktop\Vorstellung
   conda deactivate                 # 如果提示字元前面有 (base)
   .\.venv\Scripts\Activate.ps1
   python -m pytest -q              # 預期 39 passed
   ```
2. 接著完成上面「進行到一半」的 Claude Desktop 驗證。
   連不上時看 `%APPDATA%\Claude\logs\mcp-server-shu-campus-assistant.log`
3. 驗證沒問題後，建議先做第一次 git commit（目前完全沒有 commit）

### 後續階段（詳見 PROMPTS.md）
- [ ] 階段 4：案件分流（`route_case`）+ 互動紀錄（`log_interaction`、logs.db）
      —— prompt 和 `search_regulations` 已經會叫 Claude 呼叫 `route_case`，做完才算閉環
- [ ] 階段 5：評估測試集（`eval/questions.yaml`、`eval/run_eval.py`）
- [ ] 階段 6：知識庫補洞報告（`kb_gap_report`）+ 成效指標（`metrics.py`）
- [ ] 階段 7：文件（README、docs/導入方案、操作手冊、測試報告）
- [ ] 階段 8：Demo 前檢查 + 面試準備
- [ ] 寫 system prompt 時要寫進去：先判斷學生是否為專案役男，再選學分上限規則；查詢要用規章用語的關鍵字

# 校務行政 AI Agent PoC：「不會說『查無此題』的校務助理」

> 把這份檔案放在 VS Code 專案根目錄，Claude Code 會自動讀它當作專案說明。

## 目標
做一個 4 小時內可以 demo 的 PoC，證明我能做到 JD 列的這幾件事：
部署 Agent → 串接知識文件 → 設計防呆 → 案件分流 → 用指標追成效 → 寫文件。

核心概念：**LLM 只負責理解和措辭，事實、計算、權限交給確定性的工具。**

## 架構（MCP Server + Claude Desktop 當 Host）
- 用 Python + 官方 `mcp` SDK（FastMCP）寫一個 MCP Server：`server.py`
- Host 用 Claude Desktop（不需要 API key）；之後也可以接到 OpenClaw 這類 Agent 平台
- 知識來源：`kb/` 放原始 PDF（7 份：選課、抵免學分、轉系、輔系、雙主修、自主學習學分、專案服役彈性修業）；`kb/md/` 放轉檔後的 Markdown；`kb/chunks.json` 放切好的條文
- 檢索：先用 BM25（`rank_bm25`）+ 依條文切段，不做向量資料庫（時間不夠，而且條文用關鍵字就夠準）
- 紀錄：SQLite `logs.db`（只當儲存用，面試不考 SQL）

## MCP Tools
1. `search_regulations(query, top_k=3)`：回傳條文段落 + 來源檔名 + 條號。回答**一定要附出處**
2. `check_credit_rule(rule_id, value)`：學分、門檻這類數字判斷用 Python 算，不讓 LLM 自己比大小（避免「16>22」這種錯）
3. `route_case(category, summary)`：查不到或屬於例外的情況 → 依類別（教務/學務/總務/…）開分流單，回傳承辦單位和單號；summary 先遮蔽個資
4. `mask_pii(text)`：用 regex 遮蔽學號、身分證字號、手機、Email
5. `log_interaction(question, answered, sources, latency)`：每次問答都記下來
6. `kb_gap_report()`：列出答不出來的問題並分群 → 每週給知識庫維護者的補洞清單

## 防呆與合規（參考台大計中 MCP 文章的做法）
- 回答沒有引用來源 → 不回答，改走 `route_case`
- 遇到敏感操作（例如修改資料）只產生草稿，必須經人工確認
- 個資在寫進 log 或分流單之前先遮蔽
- System prompt 寫明：不確定就說不確定，並告訴使用者「該找哪個單位、怎麼找」

## 成效評估
- `eval/questions.yaml`：20 題（12 題可以回答、4 題要計算、4 題應該分流）
- `eval/run_eval.py`：算答對率、引用正確率、分流正確率
- `metrics.py`：使用次數、自動解答率、分流率，以及估算省下的工時（每題省幾分鐘 × 自動解答次數）

## 交付物
- `README.md`：架構圖、安裝步驟、demo 腳本
- `docs/導入方案.md`：一頁的流程盤點 → 痛點 → AI 介入點 → KPI → 推動步驟
- `docs/操作手冊.md`：寫給非技術同仁看的（附截圖）
- `docs/測試報告.md`：eval 結果

## 開發規則
- Python 3.11+，相依套件用 `uv` 或 `pip` 管理，寫在 `requirements.txt`
- 每個 tool 都要有 docstring（MCP 會拿 docstring 當工具描述）
- 先把 tool 的純函式寫好並測過，再包成 MCP tool
