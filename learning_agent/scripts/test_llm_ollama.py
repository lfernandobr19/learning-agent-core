#!/usr/bin/env python3
import traceback
from learning_agent.core import llm

msgs = [{"role": "user", "content": "diga ok"}]
try:
    r, m = llm.chat_complete(msgs, max_tokens=20)
    print("direct OK", m, r[:80])
except Exception as e:
    print("direct FAIL", e)
    traceback.print_exc()
try:
    r, m = llm.chat_with_fallback(msgs, max_tokens=20)
    print("fallback OK", m, r[:80])
except Exception as e:
    print("fallback FAIL", e)
