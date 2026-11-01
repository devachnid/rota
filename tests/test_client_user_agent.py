"""The Shift Central reader names itself. The standard library's default agent
("Python-urllib/3.x") is refused by Cloudflare's bot checks in front of the
tunnel with a 403 that never reaches Shift Central."""

import io
import json
from datetime import date

from rota.services.shift_central.client import USER_AGENT, ShiftCentralClient


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_shift_central_client_sends_its_own_user_agent():
    seen = []

    def opener(req):
        seen.append(req)
        return _Resp(json.dumps({"leave": []}).encode())

    ShiftCentralClient("https://shifts.example", "t", opener=opener).leave(date(2027, 1, 1), date(2027, 1, 31))
    assert seen[0].get_header("User-agent") == USER_AGENT
    assert "urllib" not in USER_AGENT.lower()
