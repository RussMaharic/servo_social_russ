import json

import pytest
import websockets

from test_connect import FakeBus, cert, profile
from t2_bots.connect.hardware import Hardware
from t2_bots.connect.sessions import Sessions, PROTOCOL
from t2_bots.core.certification import HardwareCertificate


@pytest.mark.asyncio
async def test_remote_handshake_requires_a_passing_follower_grade():
    certificate = HardwareCertificate(arm_id="TEST-NON-PASSING", role="follower",
                                     grade="B", readiness_score=80, diagnostics={})
    certificate.sign()
    async def remote(ws):
        await ws.recv()
        await ws.send(json.dumps({"protocol":PROTOCOL,"status":"connected",
                                  "certificate":certificate.to_dict()}))
        await ws.wait_closed()
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    async with websockets.serve(remote, "127.0.0.1", 0) as server:
        try:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            with pytest.raises(ValueError, match="certificate"):
                await leader.connect("FAKE", profile(), cert("leader"), url, "123456")
        finally:
            await leader.stop()
