from learning_agent.core.deepseek_balance import _balance_url


def test_balance_url_strips_v1():
    # uses module config; just ensure helper shape
    url = _balance_url()
    assert url.endswith("/user/balance")
    assert "/v1/user/balance" not in url
