## 目前檔案結構
```
Vorstellung/
├── CLAUDE.md            # 專案說明（本檔）
├── PROMPTS.md           # 分階段開發指令（階段 0–8）
├── requirements.txt     # mcp[cli]>=1.2,<2、rank_bm25、pymupdf、pyyaml、pytest
├── .gitignore
├── .venv/               # uv 虛擬環境（Python 3.12.4，不進版控）
├── server.py            # MCP Server（FastMCP，stdio）
├── rules.yaml           # 門檻規則 34 條（8 個分類，全部 verified，核對紀錄見 docs/規則核對表.md）
├── routing.yaml         # 分流 5 類 → 業務窗口（分機／Email 取自世新官網 2026-10-20，demo 前再核對）
├── logs.db              # SQLite 互動紀錄與分流單（啟動時自動建立，不進版控）
├── core/                # 純函式，各模組說明見下方「core/ 模組說明」
│   ├── __init__.py      # 空檔，讓 core 成為套件
│   ├── search.py        # 條文檢索（BM25 排序 + jieba 覆蓋率門檻）
│   ├── pii.py           # 個資遮蔽
│   ├── rules.py         # 學分門檻判斷
│   ├── routing.py       # 案件分流（開分流單）
│   ├── db.py            # SQLite 連線與建表
│   └── logging_db.py    # 互動紀錄寫入
├── tests/               # test_search/pii/rules/routing.py（141 passed、2 xfailed）
├── scripts/ingest.py    # PDF → kb/md/*.md + kb/chunks.json
├── eval/                # questions.yaml（20 題）、run_eval.py（跑 eval＋pytest，寫入 docs/測試報告.md）
├── docs/                # 測試報告.md、規則核對表.md、面試準備.md
└── kb/
    ├── *.pdf            # 7 份原始規章
    ├── md/              # 7 份轉檔後的 Markdown
    ├── dict/            # jieba 繁體詞典 dict.txt.big + 自訂詞 user_dict.txt（49 個規章用語，避免被切成單字）
    └── chunks.json      # 81 條切好的條文
```

## core/ 模組說明
`core/` 只放純函式，不依賴 MCP；`server.py` 把它們包成 MCP tool。所有路徑都用
`Path(__file__).resolve().parent.parent` 推算，不寫死絕對路徑；模組內不可以 `print`（會污染 stdio）。

| 檔案 | 功能 | 對外函式 | 讀寫的檔案 |
|---|---|---|---|
| `search.py` | 規章條文檢索。字元 bigram + BM25 排序；jieba（繁體詞典、關 HMM）斷詞算**覆蓋率**，條文要含 ≥ 50% 查詢詞（`MIN_COVERAGE`）且分數 ≥ `MIN_SCORE` 才回傳。查詢先去掉疑問詞（`QUERY_STOPWORDS`），口語詞用 `QUERY_SYNONYMS` 對應規章用語（大二→第二學年、當兵→服役）。模組載入時建一次索引 | `search_regulations(query, top_k)`、`tokenize`、`query_terms`、`coverage` | 讀 `kb/chunks.json`、`kb/dict/*` |
| `pii.py` | 個資遮蔽：Email→`[EMAIL]`、身分證→`[ID]`、手機→`[PHONE]`、學號→`[STUDENT_ID]`。身分證要通過檢查碼才算，不通過的交給學號規則（學號格式是假設的，待校方確認） | `mask_pii(text)` | 無 |
| `rules.py` | 門檻判斷：規則寫在 `rules.yaml`（必填 category、input 等欄位；選填 `derivation` 如 `"22 + 4"`），用 Python `operator` 比大小，回傳是否通過、中文說明與出處；載入時檢查欄位、運算子、重複 rule_id、derivation 算式是否等於 threshold；`verified: false` 的規則會附 warning | `check_credit_rule(rule_id, value)`、`list_rules()` | 讀 `rules.yaml` |
| `routing.py` | 案件分流：依類別（教務／學務／總務／國際兩岸／綜合服務）查 `routing.yaml`，再依摘要關鍵字對到具體業務窗口（例如宿舍→學務處宿管中心 分機 82076），沒對到就用類別總機；摘要先遮蔽個資再寫入 `cases` 表，產生單號 `A0001`…；未知類別一律歸「綜合服務」；載入時檢查缺欄位與 TODO。分流單不會自動送出，next_step 請學生自行聯絡 | `route_case(category, summary)`、`list_categories()` | 讀 `routing.yaml`，寫 `logs.db` |
| `logging_db.py` | 互動紀錄：每次問答寫入 `interactions` 表（問題先遮蔽個資、出處存 JSON），供成效指標與補洞報告使用 | `log_interaction(question, answered, sources, latency_ms)` | 寫 `logs.db` |
| `db.py` | SQLite 共用層：定義 `interactions`、`cases` 兩張表（含 `is_demo` 欄位），`get_conn()` 開連線並自動建表。測試用 monkeypatch 把 `DB_PATH` 換成暫存檔 | `get_conn()`、`init_db(conn)`、`DB_PATH` | `logs.db` |
| `__init__.py` | 空檔，讓 `core` 可以被 `from core import ...` 匯入 | — | — |

呼叫關係：`server.py` → `search` / `rules` / `routing` / `logging_db` / `pii`；`routing`、`logging_db` → `pii`（遮蔽）+ `db`（寫入）。

## 目前進度（2026-10-20 更新）

### 已完成：階段 0～5
- **階段 0 專案骨架**：venv、資料夾、requirements、.gitignore、git（已有 4 個 commit，最新為 `SecondCommit`；
  之後的規則擴充、routing 窗口、註解等修改**尚未 commit**）
- **階段 1 PDF 切段**：`python scripts/ingest.py` → 7 份文件共 81 條，選課辦法 14 條、0 個警告
- **階段 2 核心函式**：search / pii / rules 三個模組 + 測試
- **階段 3 MCP Server**：`server.py` 註冊 5 個 tools（`search_regulations`、`list_credit_rules`、
  `check_credit_rule`、`route_case`、`log_interaction`）和 1 個 prompt（`campus_assistant`）
- **階段 4 分流與紀錄**：`route_case` 依類別＋摘要關鍵字對到具體業務窗口（分機／Email 取自世新官網）；
  `log_interaction` 寫入 logs.db，個資先遮蔽
- **階段 5 評估**：`eval/run_eval.py`（2026-10-20 執行）→ 可回答 **10/12 = 83%**（目標 80%）、
  計算 **4/4 = 100%**、應分流 **3/4 = 75%**（目標 75%），報告在 `docs/測試報告.md`
- **規則擴充**：`rules.yaml` 34 條，全部對照 PDF 原文核對（`docs/規則核對表.md`），pytest 141 passed、2 xfailed

### 手動驗證（使用者自己做）
- [ ] `mcp dev server.py` 開 MCP Inspector 測 5 個 tools
- [x] Claude Desktop 已連上 `shu-campus-assistant`：logs.db 有 2 筆 2026-10-19 的真實問答紀錄
  （停修退費 → 選課辦法第七條；一年級 25 學分 → 選課辦法第三條），表示工具與 `log_interaction` 都有被呼叫
- [ ] 改完規則與 routing 後**重新啟動** Claude Desktop，再問 3 題確認：
  1.「我想停修一門課，停修後學費會退嗎？」→ `search_regulations`，回答選課辦法第七條（不退費）
  2.「我大二，這學期只選了 14 學分，這樣可以嗎？」→ `check_credit_rule(semester_min_credits_y1_3, 14)`，不通過
  3.「學生宿舍什麼時候可以申請？」→ 查無條文 → `route_case(學務, …)`，分到「宿舍服務」窗口
     （學務處宿管中心 分機 82076、dorm@mail.shu.edu.tw），並請學生自行聯絡
- 連不上時看 `%APPDATA%\Claude\logs\mcp-server-shu-campus-assistant.log`

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
| 學分下限規則出處寫成「專案服役彈性修業辦法 第四點」 | 該點雖然也寫 16／8 學分，但那是專案役男的辦法；一般學生的下限在選課辦法第三條 | `semester_min_credits_y1_3`、`semester_min_credits_y4` 出處改為選課辦法第三條，測試加上斷言 |
| 找不到 `logs.db` | SQLite 第一次連線才建檔，測試又用暫存資料庫 | server.py 啟動時就呼叫 `db.get_conn()` 建檔建表 |
| eval 口語題命中率只有 17%（正確條文多半排第 1，卻被覆蓋率擋掉） | 字元 bigram 把口語切出「費會」「會退」等跨詞雜訊，拉低覆蓋率 | 覆蓋率改用 jieba 斷詞（繁體詞典 `kb/dict/dict.txt.big` + `user_dict.txt`，關 HMM）+ `QUERY_SYNONYMS`（大二→第二學年、當兵→服役），BM25 排序仍用 bigram → 83% |
| jieba 內建詞典切繁體全變單字 | 內建是簡體詞典 | 改用官方繁體詞典 dict.txt.big |
| 單一關鍵字查詢（「通識」「超修」「驗退」）直接查無 | 這些詞被 jieba 切成單字，`query_terms` 丟掉單字後變成空的 | `user_dict.txt` 補到 49 個規章用語（只收規章原文有、且會被切成單字的詞）；模擬確認 eval 不變，17 個單詞查詢從查無變成命中 |
| server 日誌中文亂碼 | Windows stderr 預設 cp950 | server.py 將 stderr 改成 UTF-8 |

### 已知限制（還沒處理）
- 口語和規章用語不同時查不到，例如「一學期最多可以修幾學分」（條文寫「學分數上限」）。
  打算在 system prompt 要求 LLM 用規章用語的關鍵字查詢，不再放寬門檻
- 規則有兩處條文解讀待確認（見 docs/規則核對表.md 標「解讀」的列）：「雙主修與前學期平均八十分以上之學生」解讀為兩種學生；大四修碩士班「二門」未寫明每學期或累計
- 多重身分（例如法律系又是輔系生）條文沒寫怎麼合併，沒有對應規則，交給 route_case
- 沒做成規則的數字：輔系／雙主修延長修業「9 學分以下繳學分費、10 學分以上繳全額學雜費」（是收費分級，不是通過與否）、日期期限（放棄輔系 11/30、4/30 等）、比例（抵免不超過畢業學分 1/2、轉系名額二成）
- eval 仍失敗：A03「電腦課」（條文是「電腦及語言教室課程」，長詞整詞比對不到）、A12「念到一半先去當兵」、
  R02「清寒獎學金」誤命中抵免學分辦法第一條；「社團怎麼申請」「宿舍退費」這類兩詞且含常見詞的查詢也會誤命中（xfail 測試）
- 載入 jieba 繁體詞典讓 server 啟動多約 2～3 秒
- routing.yaml：學生餐廳、場地借用在官方業務聯絡窗口查不到承辦組別，目前只給總務處總機；教務各窗口官網只列 Email 與統一分機 #82044
- `STUDENT_ID_PATTERN` 是假設的格式，待向校方確認實際學號格式
- Markdown 分段：段落最後一行剛好寫滿又以「。」結尾時無法判斷，會併成同一段（只影響閱讀）

## 待辦事項

### 下次進來的第一步
1. 開 PowerShell，啟用環境並確認測試還是全過：
   ```powershell
   cd C:\Users\user\Desktop\Vorstellung
   conda deactivate                 # 如果提示字元前面有 (base)
   .\.venv\Scripts\Activate.ps1
   python -m pytest -q              # 預期 141 passed、2 xfailed
   python eval/run_eval.py          # 預期 83% / 100% / 75%
   ```
2. 重新啟動 Claude Desktop，完成上面「手動驗證」的 3 題
3. 驗證沒問題後 commit 目前的修改（規則擴充、routing 窗口、註解都還沒 commit）

### 後續階段（詳見 PROMPTS.md）
- [x] 階段 4：案件分流（`route_case`）+ 互動紀錄（`log_interaction`、logs.db）
- [x] 階段 5：評估測試集（`eval/questions.yaml`、`eval/run_eval.py`）
      —— 可改進：應分流題目前只檢查「查不到」，還沒檢查 route_case 是否對到正確窗口
- [ ] 階段 6：知識庫補洞報告（`kb_gap_report`）+ 成效指標（`metrics.py`）
- [ ] 階段 7：文件（README、docs/導入方案、操作手冊；測試報告已由 run_eval.py 產生）
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
- `docs/測試報告.md`：單元測試（各測試檔 passed／failed／xfailed）＋ eval 結果與失敗分析，執行 `eval/run_eval.py` 自動產生

## 開發規則
- Python 3.11+，相依套件用 `uv` 或 `pip` 管理，寫在 `requirements.txt`
- 每個 tool 都要有 docstring（MCP 會拿 docstring 當工具描述）
- 先把 tool 的純函式寫好並測過，再包成 MCP tool
