"""Reproduce hand movements that the browser-paced capture used to reject/miss."""
import time

import pytest

from test_connect import FakeBus, assign, local
from t2_bots.connect.hardware import Hardware
from t2_bots_so101.driver.registers import Register


def test_positioning_reference_allows_large_movement_and_resets_sweep():
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    try:
        bus.values[1][Register.PRESENT_POSITION] = 100
        hardware.sample()
        bus.values[1][Register.PRESENT_POSITION] = 3100
        hardware.sample()
        result = hardware.reference()
        assert result["reference_set"]
        assert all(row["travel"] == 0 for row in result["ranges"])
    finally:
        hardware.cancel()


def test_normal_1700_tick_sweep_is_not_an_encoder_fault():
    bus = FakeBus()
    bus.values[1][Register.PRESENT_POSITION] = 700
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    try:
        hardware.reference()
        bus.values[1][Register.PRESENT_POSITION] = 2400
        result = hardware.sample()
        assert result["ranges"][0]["travel"] == 1700
        # Calibration only releases torque, never writes a motion target.
        assert all(reg == Register.TORQUE_ENABLE and value == 0 for _, reg, value in bus.writes)
    finally:
        hardware.cancel()


def test_local_sampler_captures_sweep_between_browser_polls(local):
    client, station, bus, _ = local
    assign(client)
    assert client.post("/api/calibration/start", json={"supported": True}).status_code == 200
    assert client.post("/api/calibration/reference", json={}).status_code == 200
    # The browser sends no state requests during this outward-and-return sweep.
    bus.values[1][Register.PRESENT_POSITION] = 2700
    time.sleep(.3)
    bus.values[1][Register.PRESENT_POSITION] = 2000
    time.sleep(.15)
    result = client.get("/api/state").json()
    assert not result["capture_error"]
    assert result["capture"]["ranges"][0]["travel"] == 700
    assert result["capture"]["samples"] > 3
    assert not bus.closed


def test_wrapped_encoder_cannot_be_saved_as_a_full_turn_range():
    bus = FakeBus()
    bus.values[5][Register.PRESENT_POSITION] = 4050
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    hardware.reference()
    bus.values[5][Register.PRESENT_POSITION] = 30
    with pytest.raises(ValueError, match="wrist roll.*boundary"):
        hardware.sample()
    assert hardware.capture is None and bus.closed


def test_wide_sweep_of_all_six_joints_saves_without_browser_sampling(local):
    client, station, bus, _ = local
    assign(client)
    assert client.post("/api/calibration/start", json={"supported": True}).status_code == 200
    assert client.post("/api/calibration/reference", json={}).status_code == 200
    # A 2400-tick working interval exceeds both the old 1500 guard and half
    # a turn, but each continuously observed hand movement is small.
    for position in (1400, 800, 1400, 2000, 2600, 3200, 2600, 2000):
        for mid in range(1, 7):
            bus.values[mid][Register.PRESENT_POSITION] = position
        deadline = time.monotonic() + 1
        while station.hardware.capture and station.hardware.capture["last"][6] != position and time.monotonic() < deadline:
            time.sleep(.01)
        assert station.hardware.capture is not None
        assert station.hardware.capture["last"][6] == position
    assert client.post("/api/calibration/save", json={"reviewed": True}).status_code == 200
    assert all(joint["range_min"] == 860 and joint["range_max"] == 3140 for joint in station.profile().values())
    assert all(reg == Register.TORQUE_ENABLE and value == 0 for _, reg, value in bus.writes)


def test_background_fault_stays_visible_across_browser_polls(local):
    client, station, bus, _ = local
    assign(client)
    client.post("/api/calibration/start", json={"supported": True})
    bus.values[2][Register.STATUS_ERROR] = 1
    deadline = time.monotonic() + 1
    while station.hardware.capture and not station.hardware.capture["paused_error"] and time.monotonic() < deadline:
        time.sleep(.01)
    assert station.hardware.capture and not bus.closed
    for _ in range(2):
        state = client.get("/api/state").json()
        assert "Motor 2 (shoulder lift)" in state["capture"]["paused_error"]
        assert "0x01" in state["capture"]["paused_error"]


@pytest.mark.parametrize("register,value", [
    (Register.PRESENT_POSITION, None),
    (Register.PRESENT_POSITION, 4096),
    (Register.TORQUE_ENABLE, 1),
])
def test_capture_still_stops_for_unreadable_or_faulted_motors(register, value):
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    bus.values[3][register] = value
    with pytest.raises(ValueError):
        hardware.sample()
    assert hardware.capture is None and bus.closed
