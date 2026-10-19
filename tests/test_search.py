from core.search import MIN_SCORE, search_regulations, tokenize


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
