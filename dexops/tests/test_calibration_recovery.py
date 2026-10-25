"""Faults remain visible; a recoverable status no longer discards a sweep."""
import time
import pytest

from test_companion import FakeBus, assign, local
from t2_bots.connect.hardware import Hardware
from t2_bots_so101.driver.registers import Register


@pytest.mark.parametrize("status", [1, 4, 16, 32])
def test_motor_status_preserves_ranges_and_requires_a_healthy_recheck(status):
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    hardware.reference()
    for mid in range(1, 7):
        bus.values[mid][Register.PRESENT_POSITION] = 2200
    before = hardware.sample()
    bus.values[2][Register.STATUS_ERROR] = status
    bus.values[1][Register.PRESENT_POSITION] = 2400
    paused = hardware.sample()
    assert f"status 0x{status:02X}" in paused["paused_error"]
    assert "Motor 2 (shoulder lift)" in paused["paused_error"]
    assert "12.0 V, 30 °C" in paused["paused_error"]
    assert paused["ranges"] == before["ranges"]  # No partial unhealthy sample.
    assert paused["reference_set"] and not bus.closed
    with pytest.raises(ValueError, match="paused"):
        hardware.finish()
    with pytest.raises(ValueError, match="paused"):
        hardware.reference()
    with pytest.raises(ValueError, match="Recheck failed"):
        hardware.resume()
    assert hardware.sample()["ranges"] == paused["ranges"]
    bus.values[2][Register.STATUS_ERROR] = 0
    resumed = hardware.resume()
    assert not resumed["paused_error"] and resumed["reference_set"]
    assert resumed["ranges"][0]["travel"] == 400
    assert len(hardware.finish()) == 6
    assert all(reg == Register.TORQUE_ENABLE and value == 0 for _, reg, value in bus.writes)
    hardware.cancel()


def test_pause_cannot_resume_with_low_voltage_or_external_torque():
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    bus.values[3][Register.STATUS_ERROR] = 1
    hardware.sample()
    bus.values[3][Register.STATUS_ERROR] = 0
    bus.values[3][Register.PRESENT_VOLTAGE] = 40
    with pytest.raises(ValueError, match="4.8 V"):
        hardware.resume()
    assert hardware.capture["paused_error"]
    bus.values[3][Register.PRESENT_VOLTAGE] = 120
    bus.values[3][Register.TORQUE_ENABLE] = 1
    with pytest.raises(ValueError, match="enabled externally"):
        hardware.resume()
    assert not hardware.capture and bus.closed


def test_reference_is_not_recorded_during_fault():
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    bus.values[2][Register.STATUS_ERROR] = 16
    with pytest.raises(ValueError, match="Recheck before recording"):
        hardware.reference()
    assert hardware.capture["reference"] is None
    hardware.cancel()


def test_api_pauses_rechecks_and_continues_without_starting_over(local):
    client, station, bus, _ = local
    assign(client)
    client.post("/api/calibration/start", json={"supported": True})
    client.post("/api/calibration/reference", json={})
    for mid in range(1, 7):
        bus.values[mid][Register.PRESENT_POSITION] = 2200
    client.get("/api/state")
    bus.values[2][Register.STATUS_ERROR] = 16
    state = client.get("/api/state").json()
    assert state["capture"]["paused_error"]
    assert client.post("/api/calibration/save", json={"reviewed": True}).status_code == 400
    assert client.post("/api/calibration/resume", json={}).status_code == 400
    assert not station.store.profile_path("leader").exists()
    bus.values[2][Register.STATUS_ERROR] = 0
    resumed = client.post("/api/calibration/resume", json={})
    assert resumed.status_code == 200 and not resumed.json()["paused_error"]
    assert client.post("/api/calibration/save", json={"reviewed": True}).status_code == 200


def test_passive_capture_tolerates_a_short_browser_pause_but_still_times_out(local):
    client, station, _, _ = local
    assign(client)
    client.post("/api/calibration/start", json={"supported": True})
    station.last_browser = time.monotonic() - 8
    time.sleep(1.1)
    assert station.hardware.capture is not None
    station.last_browser = time.monotonic() - 21
    deadline = time.monotonic() + 2
    while station.hardware.capture and time.monotonic() < deadline:
        time.sleep(.01)
    assert station.hardware.capture is None
    assert "browser stopped responding" in station.capture_error


def test_external_torque_during_pause_still_cancels():
    bus = FakeBus()
    hardware = Hardware(lambda **kwargs: bus)
    hardware.begin("FAKE", "leader")
    bus.values[2][Register.STATUS_ERROR] = 16
    hardware.sample()
    bus.values[5][Register.TORQUE_ENABLE] = 1
    with pytest.raises(ValueError, match="Motor 5 torque was enabled externally"):
        hardware.sample()
    assert not hardware.capture and bus.closed
