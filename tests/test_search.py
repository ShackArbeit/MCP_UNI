import pytest

from core.search import MIN_SCORE, query_terms, search_regulations, tokenize


def ids(results: list[dict]) -> list[str]:
    return [r["id"] for r in results]


def test_tokenize_bigram_and_alnum():
    assert tokenize("停修課程") == ["停修", "修課", "課程"]
    assert tokenize("GPA 達 16 學分") == ["gpa", "達", "16", "學分"]


def test_withdrawal_top1_is_course_selection_article_7():
    results = search_regulations("停修")
    assert results, "「停修」查不到任何結果"
    assert results[0]["id"] == "選課辦法-第七條", ids(results)


def test_military_training_credits():
    assert "選課辦法-第十條" in ids(search_regulations("軍訓學分", top_k=3))


def test_military_service_credits_per_semester():
    results = search_regulations("專案服役 每學期學分", top_k=3)
    assert "專案服役彈性修業辦法-第四點" in ids(results), ids(results)


def test_unrelated_query_returns_empty():
    results = search_regulations("學生餐廳營業時間")
    assert results == [], f"MIN_SCORE={MIN_SCORE}，但仍有結果：" + ", ".join(
        f"{r['id']}={r['score']}" for r in results
    )


def test_short_relevant_query_not_filtered():
    # 「轉系」只有 3 分左右，不能被門檻擋掉
    assert search_regulations("轉系")[0]["source"] == "轉系辦法"


def test_natural_language_questions():
    # 口語問句的疑問詞不能把覆蓋率拉低到被擋掉
    assert search_regulations("轉系要什麼條件")[0]["source"] == "轉系辦法"
    assert "選課辦法-第七條" in ids(search_regulations("停修可以退費嗎"))


def test_top_k_one():
    assert len(search_regulations("學分", top_k=1)) == 1


def test_results_sorted_and_have_fields():
    results = search_regulations("轉系 申請", top_k=5)
    assert results
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert set(r) == {"id", "source", "article", "text", "score"}


def test_query_terms_are_words_not_bigrams():
    # 跨詞的 bigram（「費會」「會退」）與單字詞不算覆蓋率
    assert query_terms("我想停修一門課，停修後學費會退嗎？") == [("停修",), ("一門",), ("學費",)]


def test_query_terms_traditional_segmentation():
    # 用繁體詞典：「申請」「學生宿舍」不能被切成單字
    assert ("申請",) in query_terms("學生宿舍什麼時候可以申請？")
    assert ("學生宿舍",) in query_terms("學生宿舍什麼時候可以申請？")


def test_synonyms():
    assert ("二年級", "第二學年") in query_terms("我已經大二了還能轉系嗎")
    assert ("服役", "入伍") in query_terms("我想先去當兵")


def test_colloquial_questions_hit():
    assert "選課辦法-第七條" in ids(search_regulations("我想停修一門課，停修後學費會退嗎？"))
    assert "轉系辦法-第四條" in ids(search_regulations("我已經大二了還能轉系嗎？"))


def test_out_of_scope_questions_return_empty():
    for q in ("學生宿舍什麼時候可以申請？", "圖書館開放時間", "學校有沒有游泳池"):
        assert search_regulations(q) == [], q


@pytest.mark.xfail(reason="已知限制：只有兩個詞、其中一個是常見詞（申請、退費）時，覆蓋率剛好 50%", strict=True)
@pytest.mark.parametrize("q", ["社團怎麼申請", "宿舍退費"])
def test_two_word_query_with_common_word(q):
    assert search_regulations(q) == []


@pytest.mark.parametrize("q, expected", [
    ("通識", "選課辦法-第四條"),
    ("超修", "專案服役彈性修業辦法-第四點"),
    ("驗退", "專案服役彈性修業辦法-第十點"),
    ("預士", "選課辦法-第十條"),
    ("編級", "抵免學分辦法-第五條"),
    ("先修", "選課辦法-第九條"),
])
def test_single_keyword_query(q, expected):
    # 這些詞若被 jieba 切成單字，query_terms 會是空的而直接查無；user_dict.txt 要讓它們保持完整
    assert query_terms(q) == [(q,)]
    assert expected in ids(search_regulations(q))
