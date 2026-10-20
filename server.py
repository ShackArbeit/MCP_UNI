"""世新大學校務諮詢助理 MCP Server（stdio）。

注意：stdio 模式用 stdout 傳 JSON-RPC 訊息，整個專案在 import 與執行時都不可以 print 到 stdout。
需要除錯請用 logging（預設寫到 stderr）。
"""
from __future__ import annotations

import logging
import re
import sys

from mcp.server.fastmcp import FastMCP

from core import db
from core.logging_db import log_interaction as _log_interaction
from core.pii import mask_pii
from core.routing import route_case as _route_case
from core.rules import check_credit_rule as _check_credit_rule
from core.rules import list_rules
from core.search import search_regulations as _search_regulations

# Windows 的 stderr 預設是 cp950，中文日誌會變亂碼
sys.stderr.reconfigure(encoding="utf-8")
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("shu-campus-assistant")

# 啟動時就建立 logs.db 與資料表，不必等到第一次寫入
db.get_conn().close()
logger.info("logs.db：%s", db.DB_PATH)

# dependencies 讓 `mcp dev` / `mcp install` 建臨時環境時也會裝上這些套件
mcp = FastMCP("shu-campus-assistant", dependencies=["rank_bm25", "pyyaml", "jieba"])

NOT_FOUND_MESSAGE = "知識庫中沒有找到相關規定。請呼叫 route_case 轉給承辦單位。"
# mask_pii 產生的 [STUDENT_ID] 等標記，檢索前拿掉，避免 student、id 被當成查詢詞
_PII_TAG_RE = re.compile(r"\[(?:EMAIL|ID|PHONE|STUDENT_ID)\]")


@mcp.tool()
def search_regulations(query: str, top_k: int = 3) -> str:
    """搜尋世新大學的教務規章條文，回傳條文全文與出處（辦法名稱＋條號）。

    知識庫目前收錄 7 份規章：選課辦法、抵免學分辦法、轉系辦法、修讀輔系辦法、
    雙主修辦法、自主學習學分實施辦法、專案服役彈性修業辦法。

    什麼時候該用：
    - 使用者問到選課、加退選、停修、學分上下限、抵免、轉系、輔系、雙主修、
      自主學習學分、軍訓、體育、專案服役等教務規定時，回答前一定要先用這個工具查條文。
    - 回答中引用的每一條規定，都必須來自這個工具回傳的條文，並附上【出處】。

    什麼時候不該用：
    - 學分數是否達到門檻的「比大小」判斷：請改用 check_credit_rule。
    - 明顯不屬於教務規章的問題（宿舍、餐廳、獎學金申請、個人成績查詢等）：
      直接呼叫 route_case 轉給承辦單位。

    查詢技巧：用規章裡的用語當關鍵字效果最好，例如「每學期 學分上限」比「最多可以修幾學分」準；
    多個關鍵字用空白隔開。查詢內容的個資（學號、身分證、手機、Email）會先自動遮蔽。

    Args:
        query: 查詢關鍵字，例如「停修 退費」「轉系 申請條件」。
        top_k: 最多回傳幾筆條文，預設 3。

    Returns:
        易讀格式的條文清單；找不到相關條文時回傳提示訊息，此時請改呼叫 route_case。
    """
    masked = mask_pii(query)
    results = _search_regulations(_PII_TAG_RE.sub(" ", masked), top_k=top_k)
    logger.info("search_regulations query=%r hits=%s", masked, [r["id"] for r in results])
    if not results:
        return NOT_FOUND_MESSAGE
    blocks = [
        f"{i}. {r['text']}\n【出處】{r['source']} {r['article']}"
        for i, r in enumerate(results, 1)
    ]
    return "\n\n".join(blocks)


@mcp.tool()
def list_credit_rules() -> str:
    """列出所有可用的學分門檻規則，依分類分組，每條附適用對象、value 要填什麼、條件與出處。

    分類：每學期修課學分（學士班／研究生）、專案役男、軍訓與體育、輔系與雙主修、
    自主學習、抵免學分、提高編級。

    什麼時候該用：
    - 準備呼叫 check_credit_rule 之前，不確定該用哪個 rule_id 時，先呼叫這個工具查。
    - 注意區分適用對象，先確認學生身分再選規則：例如每學期學分上限，一般學生用
      semester_max_credits（22），法律系、輔系生、雙主修或成績優異者、專案役男、
      研究生各有自己的規則。
    - 注意 value 的意思：有些規則是「每學期」學分，有些是「在校期間累計」學分或分數，
      依每條規則的「value 填」說明傳值。

    什麼時候不該用：
    - 查規章條文內容：請用 search_regulations。
    - 已經知道正確的 rule_id 時，直接呼叫 check_credit_rule 即可。
    - 學生同時有多種身分、條文沒寫清楚怎麼合併（例如法律系又是輔系生）時，
      不要自己挑一條硬套，請呼叫 route_case。
    """
    groups: dict[str, list[str]] = {}
    for r in list_rules():
        status = "" if r["verified"] else "（尚未經人工確認）"
        groups.setdefault(r["category"], []).append(
            f"- {r['rule_id']}：{r['description']}；value 填：{r['input']}；"
            f"條件 {r['operator']} {r['threshold']} {r['unit']}；出處 {r['source']}{status}"
        )
    return "\n\n".join(f"【{cat}】\n" + "\n".join(lines) for cat, lines in groups.items())


@mcp.tool()
def check_credit_rule(rule_id: str, value: float) -> dict:
    """用程式判斷一個學分數是否符合某條學分門檻規則，回傳是否通過、說明與出處。

    什麼時候該用：
    - 當使用者的問題涉及數字是否達到某個門檻時（例如「我修 14 學分會不會太少」
      「修 24 學分有沒有超過上限」「輔系修了 18 學分夠不夠」「抵免 40 學分能不能升二年級」
      「軍訓平均 68 分能報考預官嗎」），一定要用這個工具計算，不要自己比較數字。
    - 回答時引用回傳的 explanation 與 source（出處）。

    什麼時候不該用：
    - 使用者沒有提供具體數字，只是問規定內容：請用 search_regulations。
    - 找不到適用的 rule_id 時，不要硬套其他規則；請先用 list_credit_rules 確認，
      仍然沒有就說明無法判斷，並呼叫 route_case 轉給承辦單位。

    Args:
        rule_id: 規則代號，可用 list_credit_rules 查詢，例如 "semester_min_credits_y1_3"。
        value: 要檢查的數值，例如使用者這學期修的學分數。

    Returns:
        {"rule_id", "passed", "value", "operator", "threshold", "unit", "explanation", "source"}；
        規則尚未經人工確認時多一個 "warning"，回答時必須告知使用者。
    """
    result = _check_credit_rule(rule_id, value)
    logger.info("check_credit_rule %s value=%s passed=%s", rule_id, value, result["passed"])
    return result


@mcp.tool()
def route_case(category: str, summary: str) -> dict:
    """開立分流單，找出負責的承辦窗口，回傳單號、承辦單位、聯絡方式（分機／Email）與給學生的下一步說明。

    什麼時候該用：
    - search_regulations 查不到相關條文時（回傳「知識庫中沒有找到相關規定」）。
    - 問題涉及個人特殊情況、需要人工判斷時（例如申請例外、個人成績或學籍狀態、
      找不到適用的 check_credit_rule 規則）。
    - 明顯不屬於教務規章的問題（宿舍、獎學金、繳費、設備報修、停車等）。

    什麼時候不該用：
    - search_regulations 已經查到條文、可以直接回答的一般規定問題。

    Args:
        category: 分流類別，只能是下列其中之一（填其他值會自動歸到「綜合服務」）：
            教務：選課、加退選、停修、抵免、轉系、輔系、雙主修、學籍、休復學、成績、畢業資格、
                  專案服役、研究生學位考試、招生；
            學務：獎助學金、就學貸款、學雜費減免、兵役（緩徵、役期折抵）、請假、社團、職涯、
                  諮商、衛保與保險、宿舍、申訴與霸凌、失物招領；
            總務：停車、門禁、設備報修（空調、水電、宿舍設施）、註冊費繳費、冷氣卡儲值、學位服；
            國際兩岸：僑生、外國學生、港澳生、陸生、居留證、出國交換；
            綜合服務：無法分類的問題、校外實習、推廣教育。
        summary: 一兩句話的問題摘要，請包含關鍵業務詞（例如「宿舍」「停車」「休學」），
            系統會依關鍵詞找出具體窗口。個資會自動遮蔽，但仍請不要刻意寫入學號、身分證、手機、Email。

    Returns:
        {"case_no", "category", "window", "unit", "scope", "contact", "next_step"}；
        window 是對到的業務窗口名稱，沒對到時為 null（unit、contact 改用類別的總機）。
        分流單只記錄在本系統、不會自動通知承辦單位，回答時要告訴學生單號、承辦單位、
        contact 裡的分機或 Email，請學生自行聯絡。
    """
    result = _route_case(category, summary)
    logger.info("route_case category=%s window=%s case_no=%s unit=%s",
                category, result["window"], result["case_no"], result["unit"])
    return result


@mcp.tool()
def log_interaction(question: str, answered: bool, sources: list[str], latency_ms: int = 0) -> str:
    """記錄這次問答，供成效指標與知識庫補洞報告使用。每次回答完使用者後都要呼叫一次。

    什麼時候該用：
    - 每一輪回答使用者之後（不論有沒有答出來、有沒有分流），都呼叫一次。

    Args:
        question: 使用者的原始問題；存入前會自動遮蔽個資。
        answered: 有根據條文或規則回答就填 true；查不到、轉 route_case 分流就填 false。
        sources: 回答引用的出處清單，例如 ["選課辦法 第七條"]；沒有引用就填 []。
        latency_ms: 回答耗時（毫秒），不知道就填 0。
    """
    _log_interaction(question, answered, sources, latency_ms)
    logger.info("log_interaction answered=%s sources=%s", answered, sources)
    return "已記錄"


@mcp.prompt()
def campus_assistant() -> str:
    """世新大學校務諮詢助理的行為準則。"""
    return """你是世新大學校務諮詢助理，回答範圍限於知識庫內的規章。

行為準則：
1. 每個回答都必須附上出處（辦法名稱加條號，例如「選課辦法 第七條」）。沒有出處的內容不可以說。
2. 回答規章問題前，先呼叫 search_regulations 查條文；只根據工具回傳的條文回答，不要憑記憶補充。
3. 涉及學分數字比較時（是否達到最低學分、是否超過上限等），必須呼叫 check_credit_rule，不可以自己判斷。
   不確定該用哪條規則時，先呼叫 list_credit_rules；先確認學生身分（年級、是否法律系、輔系生、雙主修、
   專案役男、研究生），再選對應的規則。學生有多種身分、找不到明確適用的規則時，改呼叫 route_case。
   回傳結果有 warning（尚未經人工確認）時，回答要告訴學生這點，並建議向承辦單位確認。
4. 找不到相關規定、或問題涉及個人特殊情況需要人工判斷時，不可以只說「查無資料」，
   必須呼叫 route_case，並告訴學生分流單號、承辦單位、分機或 Email，請學生自行聯絡
   （分流單只記錄在本系統，不會自動通知承辦單位，不可以說「已轉交」或「會有人聯絡你」）。
5. 不確定的時候就說不確定，並建議學生向哪個單位確認。
6. 每次回答結束後呼叫 log_interaction，記錄問題、是否有回答、引用的出處。
7. 使用繁體中文回答。"""


if __name__ == "__main__":
    mcp.run()
