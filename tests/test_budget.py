import pytest

from app import llm, store


def test_over_budget_makes_no_llm_call(monkeypatch, users):
    user = users()
    over = llm.MONTHLY_CAP_USD + 0.01
    monkeypatch.setattr(store, "month_cost", lambda user_id: over)

    def boom(**kwargs):
        raise AssertionError("LLM must not be called over budget")

    monkeypatch.setattr(llm._client.chat.completions, "create", boom)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete(name="x", messages=[{"role": "user", "content": "hi"}], user_id=user.id)
