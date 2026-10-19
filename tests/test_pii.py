import pytest

from core.pii import mask_pii


@pytest.mark.parametrize("text, expected", [
    ("我的信箱是 abc@mail.shu.edu.tw", "我的信箱是 [EMAIL]"),
    ("身分證 A123456789", "身分證 [ID]"),
    ("電話 0912-345-678", "電話 [PHONE]"),
    ("學號 A110123456 想問停修", "學號 [STUDENT_ID] 想問停修"),
    # 寫法變化
    ("電話 0912 345 678", "電話 [PHONE]"),
    ("電話0912345678", "電話[PHONE]"),
    ("學號A110123456想問停修", "學號[STUDENT_ID]想問停修"),
    ("學號 110123456", "學號 [STUDENT_ID]"),
    ("身分證a123456789", "身分證[ID]"),
    # 一句話裡多種個資
    ("我是 B110123456，手機 0987-654-321，信箱 x.y@gmail.com",
     "我是 [STUDENT_ID]，手機 [PHONE]，信箱 [EMAIL]"),
])
def test_masks_pii(text, expected):
    assert mask_pii(text) == expected


@pytest.mark.parametrize("text", [
    "我這學期修了 16 學分",
    "110 學年度入學",
    "第十三條",
    "2026 年",
    "期限第一學期為11 月30 日",
    "抵免學分至多 6 學分",
])
def test_does_not_mask_normal_text(text):
    assert mask_pii(text) == text


def test_invalid_checksum_id_is_treated_as_student_id():
    # A110123456 格式像身分證，但檢查碼不對 → 當學號
    assert mask_pii("A110123456") == "[STUDENT_ID]"
