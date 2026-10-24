import json

import pytest
import websockets

from test_connect import FakeBus, profile
from t2_bots.connect.hardware import Hardware
from t2_bots.connect.sessions import Sessions, PROTOCOL


@pytest.mark.asyncio
@pytest.mark.parametrize("role,calibrated", [("follower", False), ("leader", True)])
async def test_remote_handshake_requires_calibrated_follower(role, calibrated):
    async def remote(ws):
        hello = json.loads(await ws.recv())
        assert hello["calibrated"] is True and "certificate" not in hello
        await ws.send(json.dumps({"protocol": PROTOCOL, "status": "connected",
                                  "role": role, "calibrated": calibrated}))
        await ws.wait_closed()
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    async with websockets.serve(remote, "127.0.0.1", 0) as server:
        try:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            with pytest.raises(ValueError, match="handshake"):
                await leader.connect("FAKE", profile(), url, "123456")
        finally:
            await leader.stop()
