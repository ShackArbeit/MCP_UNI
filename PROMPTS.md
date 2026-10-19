# Vorstellung｜各階段給 Claude Code 的 Prompt（依實際檔案改寫版）

## 開始前先確認（只需要做一次）

| 項目 | 現況 | 你要做的事 |
|---|---|---|
| 專案說明檔 | 目前叫 `basic.md` | **改名成 `CLAUDE.md`**，Claude Code 才會自動讀取（階段 0 的 prompt 會幫你改） |
| 規章 PDF | 7 份，直接放在 `kb/` | 不用動，階段 1 會處理 |
| Python | Anaconda 3.12.4，另外有 `uv` 0.9 | 不用動，階段 0 會用 uv 建立虛擬環境 |
| Claude Desktop | — | 確認已安裝並登入（階段 3 會用到） |

**每個階段的固定流程：**
1. 在 VS Code 開啟 `Vorstellung` 資料夾，然後打開 Claude Code
2. 貼上該階段的 prompt（整段 ``` 裡的內容）
3. Claude Code 做完後，**照「你要自己檢查」那一欄逐項驗證**
4. 驗證通過後，對 Claude Code 說：「請 git commit，訊息寫『階段 X 完成』」
5. 再進下一個階段

> 每個 prompt 的結尾都要求 Claude Code「做完停下來回報」，避免它一口氣做太多，你跟不上。

---

# Day 1

## 階段 0｜建立專案骨架（10 分鐘）

```
請幫我建立專案骨架。這是一個 Windows 11 環境，專案資料夾是 C:\Users\user\Desktop\Vorstellung。

【現況】
- basic.md：專案說明
- kb/：放了 7 份世新大學規章 PDF

【請依序做】
1. 把 basic.md 改名為 CLAUDE.md，並在檔案最上面加上「## 目前檔案結構」這一節（內容等第 4 步完成後再補）
2. 修改 CLAUDE.md 裡「知識來源」那一行，改成：
   kb/ 放原始 PDF（7 份：選課、抵免學分、轉系、輔系、雙主修、自主學習學分、專案服役彈性修業）；
   kb/md/ 放轉檔後的 Markdown；kb/chunks.json 放切好的條文
3. 用 uv 建立虛擬環境：uv venv --python 3.12
4. 建立以下資料夾與空檔案：
   core/__init__.py
   tests/__init__.py
   scripts/
   eval/
   docs/
   kb/md/
5. 建立 requirements.txt，內容固定為：
   mcp[cli]>=1.2
   rank_bm25
   pymupdf
   pyyaml
   pytest
   並執行 uv pip install -r requirements.txt
6. 建立 .gitignore：.venv/、__pycache__/、*.pyc、logs.db、.pytest_cache/
7. git init，先不要 commit

【不要做】
- 不要寫任何功能程式碼
- 不要移動 kb/ 裡的 PDF

【做完請回報】
- tree 結構（不含 .venv）
- 啟用虛擬環境的指令（PowerShell 版）
- 執行 python -c "import mcp, rank_bm25, fitz, yaml; print('ok')" 的結果
然後停下來等我。
```

**你要自己檢查：**
- [ ] `CLAUDE.md` 存在，`basic.md` 已經不見了
- [ ] 最後那行 import 測試印出 `ok`
- [ ] VS Code 右下角的 Python 直譯器選到 `.venv`（如果沒有，按 Ctrl+Shift+P →「Python: Select Interpreter」）

---

## 階段 1｜PDF 轉成條文切段（20 分鐘）

```
請寫 scripts/ingest.py，把 kb/*.pdf 轉成可以檢索的條文切段。

【已知的 PDF 格式問題，請務必處理】
1. 條號格式不統一，至少有這三種：
   - 「第一條」「第十三條」
   - 「第 九 條」（字之間有空格）
   - 「一、」「二、」（專案服役彈性修業辦法.pdf 用這種，整份沒有「第X條」）
2. 條文內文也會出現「第X條」，例如「依學則第二十九、三十條」，這種是引用，不是新條文。
   只有出現在「行首」的才算條號
3. 修讀輔系辦法.pdf、轉系辦法.pdf、雙主修辦法.pdf 用 pdftotext 抽出來時，會出現
   「第十條 第 十一 條 第 十二 條 第 十三 條」擠在同一行的情況，可能是表格排版。
   請先用 pymupdf 的 page.get_text("blocks") 或 "dict" 模式觀察實際結構，再決定切法
4. 每份 PDF 開頭都有一大段「XX 年 X 月 X 日教務會議修訂通過」的沿革，這段不是條文，
   請獨立存成 history 欄位，不要混進第一條
5. 條文內的「一、二、三、」是「款」，屬於該條的一部分，不要再切開
   （例外：專案服役那份的「一、」就是條）

【輸出】
1. kb/md/<原檔名>.md：每份一個檔，格式為
   # 辦法名稱
   > 沿革：...
   ## 第一條
   內文...
2. kb/chunks.json：list，每個元素格式為
   {
     "id": "選課辦法-第七條",
     "source": "選課辦法",
     "article": "第七條",
     "text": "條文全文（去除換行和多餘空白）"
   }
   專案服役那份的 article 寫成「第一點」「第二點」，並和其他份統一用中文數字

【完成標準】
- 執行 python scripts/ingest.py 時，印出每份文件切出幾條
- 選課辦法要切出 14 條（已人工確認有第一條到第十四條）
- 任何一份切出 0 條、或某條內文少於 10 個字，要印出警告
- 最後隨機印出 3 條讓我人工比對原 PDF

【不要做】
- 不要用 OCR
- 不要靜默略過任何錯誤

做完請回報上面的輸出結果，然後停下來等我。
```

**你要自己檢查：**
- [ ] 選課辦法切出 14 條
- [ ] 打開 `kb/md/轉系辦法.md`，和 PDF 對照一下，條號順序是否正確（這份最容易切錯）
- [ ] 打開 `kb/chunks.json`，搜尋「第七條」，確認停修規定那三款都在同一條裡
- [ ] 如果有切錯，直接跟 Claude Code 說「轉系辦法第 X 條的內容跑到第 Y 條去了，請修正」

---

## 階段 2｜三個核心函式加測試（45 分鐘）

> 這階段分成 2A、2B、2C 三次貼，每次做完都要跑測試。

### 2A：檢索

```
請寫 core/search.py 和 tests/test_search.py。

【函式簽名】
def search_regulations(query: str, top_k: int = 3) -> list[dict]:
    回傳格式：[{"id", "source", "article", "text", "score"}, ...]，依 score 由高到低排序

【實作規格】
- 模組載入時讀一次 kb/chunks.json，並建立 BM25Okapi 索引（不要每次查詢都重建）
- 中文斷詞：用「字元 bigram」，例如「停修課程」→ ["停修","修課","課程"]。
  英數字串（例如 16、GPA）整串當成一個 token。不要引入 jieba
- 索引內容 = source + article + text（讓「選課辦法」這種關鍵字也能命中）
- 設一個常數 MIN_SCORE = 1.0，低於這個分數的結果不回傳。
  如果全部都低於門檻，回傳空 list
- 路徑用 pathlib，以這個檔案的位置為基準，不要寫死絕對路徑

【測試案例（tests/test_search.py）】
1. query="停修" → 結果的第一筆要是 選課辦法-第七條
2. query="軍訓學分" → 前 3 筆要包含 選課辦法-第十條
3. query="專案服役 每學期學分" → 前 3 筆要包含專案服役那份的第四點
4. query="學生餐廳營業時間" → 回傳空 list
5. top_k=1 時，只回傳 1 筆

如果第 4 個測試失敗（亂查也有結果），請印出那筆的分數，並建議 MIN_SCORE 該調成多少，
先不要自己改，等我決定。

做完請執行 pytest tests/test_search.py -v，回報結果後停下來。
```

### 2B：個資遮蔽

```
請寫 core/pii.py 和 tests/test_pii.py。

【函式簽名】
def mask_pii(text: str) -> str

【遮蔽規則（依這個順序執行）】
1. Email → [EMAIL]
2. 台灣身分證字號（1 個英文字母 + 1 或 2 + 8 位數字，例如 A123456789）→ [ID]
3. 手機（09 開頭共 10 碼，允許 0912-345-678 和 0912 345 678 這兩種寫法）→ [PHONE]
4. 世新學號：先假設是「A 或 B 或 N 開頭 + 9 位數字」，或「純 9 位數字」→ [STUDENT_ID]
   regex 寫成模組常數 STUDENT_ID_PATTERN，並加註解：「待向校方確認實際學號格式」

【測試案例】
正例（要被遮蔽）：
- "我的信箱是 abc@mail.shu.edu.tw" → "我的信箱是 [EMAIL]"
- "身分證 A123456789" → "身分證 [ID]"
- "電話 0912-345-678" → "電話 [PHONE]"
- "學號 A110123456 想問停修" → "學號 [STUDENT_ID] 想問停修"
反例（不能被遮蔽）：
- "我這學期修了 16 學分"
- "110 學年度入學"
- "第十三條"
- "2026 年"

做完請執行 pytest tests/test_pii.py -v，回報結果後停下來。
```

### 2C：學分規則判斷

```
請寫 core/rules.py、rules.yaml 和 tests/test_rules.py。

【為什麼需要這個】
LLM 有時候會把數字比錯（例如答出「16 > 22」），所以學分門檻這類判斷一律交給程式算。

【rules.yaml 格式】
- rule_id: semester_min_credits_y1_3
  description: 學士班第一至三學年每學期最低修習學分
  operator: ">="
  threshold: 16
  unit: 學分
  source: 專案服役彈性修業辦法 第四點
  verified: true

請建立以下 4 條規則：
1. semester_min_credits_y1_3：>= 16，來源：專案服役彈性修業辦法 第四點，verified: true
2. semester_max_credits：<= 25，來源同上，verified: true
3. semester_min_credits_y4：>= 8，來源同上，verified: true
4. military_training_max_credits：在校期間軍訓至多採計 <= 2 學分，來源：選課辦法 第十條，verified: true

數字我已經從 PDF 原文確認過了。請你再到 kb/chunks.json 裡找到對應條文，
確認數字一致後再寫入。如果不一致，停下來告訴我，不要自己改數字。

【函式簽名】
def list_rules() -> list[dict]
def check_credit_rule(rule_id: str, value: float) -> dict
    回傳：{"rule_id", "passed": bool, "value", "operator", "threshold", "unit",
          "explanation": "你填的 14 學分低於最低 16 學分的規定", "source"}
    rule_id 不存在時：raise ValueError，訊息中列出所有可用的 rule_id
    verified 為 false 的規則：回傳結果加上 "warning": "此規則尚未經人工確認"

【測試案例】
- semester_min_credits_y1_3, 14 → passed=False
- semester_min_credits_y1_3, 16 → passed=True（邊界值）
- semester_max_credits, 26 → passed=False
- 不存在的 rule_id → 拋出 ValueError

做完請執行 pytest -v（全部測試），回報結果後停下來。
```

**你要自己檢查：**
- [ ] `pytest -v` 全部通過（應該有 15 個以上的測試）
- [ ] 打開 `rules.yaml`，親自對照 PDF 確認 4 個數字（面試時可以說「所有門檻都經過人工驗證」）

---

## 階段 3｜包成 MCP Server 並接上 Claude Desktop（30 分鐘）

```
請寫 server.py，用 FastMCP 把 core/ 的函式包成 MCP Server。

【基本設定】
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("shu-campus-assistant")
最後用 mcp.run()（預設是 stdio transport）

【要註冊的 tools】
1. search_regulations(query: str, top_k: int = 3)
   - 先對 query 執行 mask_pii，再進行檢索
   - 回傳時把結果整理成易讀格式，每筆都附「【出處】辦法名稱 第X條」
   - 結果為空時回傳：「知識庫中沒有找到相關規定。請呼叫 route_case 轉給承辦單位。」
2. list_credit_rules()：列出所有規則的 rule_id 和說明（讓 Claude 知道有哪些規則可以用）
3. check_credit_rule(rule_id: str, value: float)

每個 tool 的 docstring 都要寫清楚三件事：這個工具做什麼、什麼時候該用、什麼時候不該用。
Claude 會讀 docstring 決定要不要呼叫，所以要寫得具體。例如 check_credit_rule 的 docstring 要寫：
「當使用者的問題涉及學分數是否達到某個門檻時，一定要用這個工具計算，不要自己比較數字。」

【註冊一個 MCP prompt】
@mcp.prompt() 名稱叫 campus_assistant，內容是給 Claude 的行為準則：
- 你是世新大學校務諮詢助理，回答範圍限於知識庫內的規章
- 每個回答都必須附上出處（辦法名稱加條號）；沒有出處的內容不可以說
- 涉及學分數字比較時，必須呼叫 check_credit_rule，不可以自己判斷
- 找不到相關規定時，不可以只說「查無資料」，必須呼叫 route_case，並告訴學生承辦單位和下一步
- 不確定的時候就說不確定
- 使用繁體中文

【嚴格規定】
- 整個專案（包含 core/）在 import 時和執行時都不可以 print 到 stdout，
  因為 stdio 模式用 stdout 傳 JSON-RPC 訊息，任何 print 都會讓連線壞掉。
  需要除錯時，用 logging 寫到 stderr
- 請用 grep 檢查整個專案有沒有 print(，有的話改掉（scripts/ 和 tests/ 底下的除外）

【做完請提供】
1. 用 MCP Inspector 測試的指令：在 .venv 啟用的狀態下執行 mcp dev server.py
   並告訴我在 Inspector 網頁上要點哪裡來測試每個 tool
2. Claude Desktop 設定檔的完整內容，檔案位置是
   %APPDATA%\Claude\claude_desktop_config.json
   command 填 C:\\Users\\user\\Desktop\\Vorstellung\\.venv\\Scripts\\python.exe
   args 填 server.py 的絕對路徑
   如果設定檔已經存在，要說明怎麼「合併」，不要叫我整份覆蓋
3. 3 個我可以在 Claude Desktop 實際問的測試問題，以及每題預期 Claude 會呼叫哪個 tool

不要幫我修改 Claude Desktop 的設定檔，給我內容就好，我自己貼。做完停下來。
```

**你要自己做：**
1. 執行 `mcp dev server.py`，在瀏覽器打開的 Inspector 中：點 **Connect** → **Tools** → **List Tools** → 選一個 tool → 輸入參數 → **Run Tool**
2. 確認 3 個 tool 都能正常回傳結果後，按 Ctrl+C 關掉 Inspector
3. 把設定貼進 `claude_desktop_config.json`
4. **完全關閉 Claude Desktop**（工作列右下角的系統匣圖示也要按右鍵結束），再重新開啟
5. 在對話框附近找到工具（🔨/插頭）圖示，確認看得到 `shu-campus-assistant`
6. 問測試問題，例如：「我大二這學期只選了 14 學分，可以嗎？」

**卡住的時候：** Claude Desktop 的錯誤 log 在 `%APPDATA%\Claude\logs\mcp-server-shu-campus-assistant.log`，把內容貼給 Claude Code，請它修正。

---

## 階段 4｜案件分流加互動紀錄（20 分鐘）

```
請新增案件分流和紀錄功能。

【1. core/db.py】
- SQLite 檔案位置：專案根目錄的 logs.db（用 pathlib 計算路徑）
- 提供 get_conn() 和 init_db()，第一次連線時自動建立以下兩張表：
  interactions(id INTEGER PK, ts TEXT, question TEXT, answered INTEGER, sources TEXT, latency_ms INTEGER, is_demo INTEGER DEFAULT 0)
  cases(id INTEGER PK, case_no TEXT, ts TEXT, category TEXT, unit TEXT, summary TEXT, status TEXT DEFAULT 'open', is_demo INTEGER DEFAULT 0)

【2. routing.yaml】
categories:
  教務:
    unit: 教務處註冊課務組
    scope: 選課、加退選、停修、抵免、轉系、輔系、雙主修、學籍
    contact: TODO（待補分機與信箱）
  學務:
    unit: 學生事務處
    scope: 獎助學金、宿舍、社團、請假
    contact: TODO
  總務:
    unit: 總務處
    scope: 繳費、場地、設備報修
    contact: TODO
  綜合服務:
    unit: 學校總機轉接
    scope: 無法分類的問題
    contact: TODO
（「專案服役」相關問題歸在教務，因為該辦法寫明向教務處註冊課務組申請。請到 chunks.json 確認這點）

【3. core/routing.py】
def route_case(category: str, summary: str) -> dict
- category 不在 routing.yaml 時，歸到「綜合服務」
- summary 先經過 mask_pii 再存入資料庫
- case_no 格式為 A + 4 位流水號（A0001、A0002……）
- 回傳 {"case_no", "unit", "scope", "contact", "next_step": "給學生看的一句話說明"}

【4. core/logging_db.py】
def log_interaction(question: str, answered: bool, sources: list[str], latency_ms: int = 0) -> None
- question 先經過 mask_pii 再存入；sources 存成 JSON 字串

【5. 註冊到 server.py】
新增 route_case 和 log_interaction 兩個 tool。docstring 要寫清楚：
- route_case：search_regulations 查不到結果、或問題涉及個人特殊情況需要人工判斷時使用
- log_interaction：每次回答完使用者後都要呼叫一次
同時更新 campus_assistant prompt，加上「每次回答結束後呼叫 log_interaction」

【6. 測試 tests/test_routing.py】
- 測試時要用暫存的資料庫（pytest 的 tmp_path 加 monkeypatch 修改 DB 路徑），不可以寫入真正的 logs.db
- 測試案例：正常分流、未知類別歸到綜合服務、summary 中的手機號碼有被遮蔽、單號會遞增

做完請執行 pytest -v，回報結果，並提醒我要重新啟動 Claude Desktop。然後停下來。
```

**你要自己檢查：**
- [ ] `pytest -v` 全部通過
- [ ] 重啟 Claude Desktop 後問：「學校餐廳幾點開？」→ Claude 應該呼叫 `route_case`，並回覆單號和承辦單位，而不是「查無資料」
- [ ] 用 VS Code 的 SQLite 擴充套件（例如 SQLite Viewer）打開 `logs.db`，確認有紀錄寫進去

**Day 1 結束：** 請 Claude Code 執行 `git commit`。到這裡就已經有一個可以 demo 的版本了。

---

# Day 2

## 階段 5｜評估測試集（40 分鐘）

```
請建立評估機制，用來證明這個系統的準確度。

【1. eval/questions.yaml】
共 20 題，請以「學生會怎麼問」的口語寫法出題（不要直接抄條文用語）：
- answerable 12 題：每份辦法至少 1 題，選課辦法 3 題。
  每題附 expected_ids（預期命中的 chunk id，可以有多個）
  題目必須根據 kb/chunks.json 裡真的有的內容出題，出完後把每題對應的條文內容一起列給我確認
- calculation 4 題：例如「我大三選 15 學分可以嗎？」
  附 expected_rule_id 和 value（從題目中抽出的數字）
- should_route 4 題：規章沒有涵蓋的問題，例如宿舍、獎學金、學餐、停車
  附 expected_category

【2. eval/run_eval.py】
直接呼叫 core/ 的函式，不經過 LLM（這樣結果可以重現）：
- answerable：檢查 search_regulations(q, top_k=3) 的結果是否包含任一個 expected_ids → 命中率
- calculation：呼叫 check_credit_rule(expected_rule_id, value)，確認不會出錯，並輸出判斷結果
- should_route：檢查 search_regulations 是否回傳空 list → 正確分流率
輸出：
- 終端機表格：每題的題目、類型、通過或失敗、實際命中的 id
- 總結：三類各自的通過率
- docs/測試報告.md：上面的內容加上「失敗題目分析」一節

【完成標準】
answerable 命中率達到 80% 以上、should_route 達到 75% 以上。
沒達標時，分析失敗原因（斷詞、門檻、切段，或題目本身寫得太口語），
提出 2 到 3 個調整方案，以及每個方案的取捨，等我選擇後再修改。不要為了讓測試通過而改題目。

做完回報結果後停下來。
```

**你要自己檢查：**
- [ ] 逐題看過 answerable 題目和對應條文，確認 expected_ids 是對的（這是人工驗證，面試時可以講）
- [ ] 記下最後的命中率數字，面試時會用到

---

## 階段 6｜知識庫補洞報告加成效指標（20 分鐘）

```
請新增成效追蹤功能。

【1. scripts/seed_demo.py】
產生 30 筆擬真的 demo 紀錄寫入 logs.db，所有紀錄的 is_demo 都設為 1：
- 20 筆 answered=1（題目分散在各辦法）
- 10 筆 answered=0，其中刻意製造 3 群相似的問題：
  宿舍相關 4 筆、獎學金相關 3 筆、畢業門檻相關 3 筆（畢業門檻規定在學則，但 kb 裡沒有學則，正好是知識庫缺口）
- 時間平均分布在過去 7 天
- 執行前先刪除舊的 is_demo=1 紀錄，確保可以重複執行

【2. core/gap.py】
def kb_gap_report(days: int = 7) -> dict
- 撈出期間內 answered=0 的問題
- 用字元 bigram 計算 Jaccard 相似度，門檻 0.2，進行簡單分群（不要用機器學習套件）
- 回傳每一群的：代表問題、次數、所有問題、建議負責單位（用 routing.yaml 的 scope 關鍵字比對）、
  建議動作（例如「建議將《學則》納入知識庫」）
- 依次數由多到少排序
- 註冊成 MCP tool

【3. metrics.py（命令列執行：python metrics.py --days 7）】
輸出以下指標：
- 總問答數、自動解答數、自動解答率、分流數、分流率
- 各類別的分流數
- 估算省下的工時 = 自動解答數 × MINUTES_SAVED_PER_QUERY（預設 5 分鐘，可以用 --minutes 參數修改）
  輸出中必須註明「此為假設值，正式導入時應以實際作業時間調查校正」
- 如果有 is_demo 資料，在標題標示「（含 demo 資料）」
同時輸出 docs/成效指標.md

做完依序執行 seed_demo.py、metrics.py，並在 Python 中呼叫 kb_gap_report()，把三個結果都給我看。然後停下來。
```

**你要自己檢查：**
- [ ] gap report 有分出「宿舍、獎學金、畢業門檻」三群
- [ ] 在 Claude Desktop 問：「這週有哪些問題答不出來？」→ Claude 應該呼叫 `kb_gap_report`

---

## 階段 7｜文件（40 分鐘）

```
請撰寫三份文件，使用繁體中文，風格專業、簡潔、好懂。
請先讀完整個專案的程式碼和 docs/測試報告.md、docs/成效指標.md，文件內容必須和實際程式一致，
不可以寫出程式沒有實作的功能。

【1. README.md】
- 第一段：一句話說明解決什麼問題（AI 客服答不出、答錯 → 附出處、程式計算、自動轉單位、持續補洞）
- 架構圖（mermaid flowchart）：
  使用者 → Claude Desktop（MCP Host，內含 MCP Client）→ stdio / JSON-RPC → server.py（MCP Server）
  → 6 個 tools → kb/chunks.json、rules.yaml、routing.yaml、logs.db
- 設計原則（3 點）：
  1. LLM 只負責理解和措辭，事實、計算、權限交給確定性的工具
  2. 沒有出處就不回答，查不到就轉給真人
  3. 個資先遮蔽才寫入紀錄
- 6 個 tools 一覽表：名稱、用途、對應 JD 的哪一項職責
- 安裝步驟（Windows，使用 uv）
- Demo 腳本：3 個問題分別展示附出處回答、數字計算、轉單位，以及第 4 題「這週有哪些問題答不出來？」
- 測試結果摘要（引用 docs/測試報告.md 的數字）
- 限制與下一步：BM25 → 混合式檢索；接校務系統 API（需要唯讀帳號與權限分級）；
  導入 OpenClaw 等平台（因為使用 MCP 標準，server.py 可以直接重用）；
  正式上線前的個資衝擊評估；學號格式需要和校方確認

【2. docs/導入方案.md】（控制在 A4 一頁左右）
以「學生選課與學分相關諮詢」為例：
- 現況：學生提問 → 窗口人工查規章 → 回覆
- 痛點：重複性問題多、規章分散在多份辦法、回答標準不一致
- AI 介入點：條文查詢、學分計算、分流導引
- 人工保留點：個案判斷、例外申請、最終核定
- KPI：自動解答率、轉人工率、答對率（每週人工抽查 20 題）、省下的工時、知識庫補洞週期
- 分階段推動：PoC（本專案）→ 試辦 1 個單位 4 週 → 檢討 → 擴大
- 「如何避免 AI 客服答不出或答錯」：知識庫由各業務單位負責維護、每週補洞報告、轉人工機制、
  上線前必須通過測試集、規章修訂時同步更新

【3. docs/操作手冊.md】
讀者是完全不懂技術的行政同仁，不要出現程式碼術語。內容包含：
- 規章修訂時怎麼更新（把 PDF 放進 kb/ → 請資訊人員執行更新指令 → 用 3 個問題驗證）
- 怎麼看每週報表（metrics 和 gap report 各欄位的意思）
- 遇到 AI 答錯時怎麼回報

寫完後，請依照 README 的安裝步驟，在新的終端機中實際執行一次每個指令，確認都能正常運作。
做完停下來。
```

**你要自己檢查：**
- [ ] 在 VS Code 按 Ctrl+Shift+V 預覽 README，確認 mermaid 圖有正確顯示
- [ ] 把導入方案讀一遍，**用你自己的話改寫一兩句**（面試官可能會追問，要是你自己寫的語氣）

---

## 階段 8｜Demo 前檢查加面試準備（20 分鐘）

```
我明天要拿這個專案去世新大學「AI Agent 導入工程師」的面試。請幫我：

1. 健康檢查：依序執行 pytest -v、python eval/run_eval.py、python metrics.py，確認全部正常
2. 程式碼檢查：
   - 有沒有寫死的絕對路徑（server.py 以外）
   - 有沒有遺留在 core/ 或 server.py 裡的 print
   - logs.db 裡有沒有非 demo 的真實個資
   - .gitignore 有沒有把 logs.db 和 .venv 排除
3. 根據這份程式碼，列出面試官最可能追問的 6 個技術問題和回答要點，至少包含：
   - 為什麼用 BM25 而不是向量資料庫？
   - MCP 和直接呼叫 API 有什麼不同？
   - 如果要接到 OpenClaw 要改哪些地方？
   - 個資怎麼保護？還有哪些不足？
   - 怎麼知道 AI 答對了？
   - 如果規章改版怎麼辦？
4. 寫一份 2 分鐘的 demo 口述稿，結構為：問題（AI 客服答不出、答錯）→ 我的設計原則 → 實際操作 4 個問題 → 成效數字 → 下一步
5. 列出 demo 當天可能出錯的地方和備案（例如 Claude Desktop 連不上 MCP 時，改用 MCP Inspector 展示）

全部寫到 docs/面試準備.md。
```

**你要自己做：**
- [ ] 把口述稿大聲唸 2 次並計時
- [ ] 把 demo 過程錄成影片或截圖存起來，網路不穩時可以當備案
- [ ] 推上 GitHub（如果要放進履歷）：先確認 `logs.db` 沒有被 commit

---

## 時間不夠時的取捨

| 優先順序 | 一定要做 | 可以砍 |
|---|---|---|
| Day 1 | 階段 0–3（能夠 demo 附出處回答和學分計算） | 階段 4 可以移到 Day 2 |
| Day 2 | 階段 5（測試數字）、階段 7 的 README | 階段 6 的 gap report、操作手冊 |

**最低可以 demo 的版本**：Claude Desktop 接上 MCP Server，能附出處回答規章問題，能用程式判斷學分是否達標。光這樣就能把「LLM 加確定性工具」這個核心設計講清楚。
