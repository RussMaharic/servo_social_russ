"""
High-Speed Half-Duplex UART Serial Bus Transport for Feetech STS3215 Servos.
Zero heavy dependencies (pure pyserial).
"""

import time
import serial
from typing import Dict, List, Optional, Tuple
from t2_bots_so101.driver.registers import (
    BAUDRATE_1M,
    HEADER_BYTE_1,
    HEADER_BYTE_2,
    Instruction,
    Register,
)

class FeetechBus:
    """Half-duplex serial bus interface for Feetech STS series actuators."""

    def __init__(self, port: str, baudrate: int = BAUDRATE_1M, timeout: float = 0.05):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        self.last_errors: Dict[int, int] = {}

    def open(self) -> None:
        if self.ser is not None and self.ser.is_open:
            return
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        if self.ser is not None:
            if self.ser.is_open:
                self.ser.close()
            self.ser = None

    @staticmethod
    def _checksum(payload: bytes) -> int:
        """Calculates Feetech bitwise inverted modulo-256 checksum."""
        return (~sum(payload)) & 0xFF

    def _send_packet(self, servo_id: int, instruction: int, params: bytes = b"") -> None:
        length = len(params) + 2
        header = bytes([HEADER_BYTE_1, HEADER_BYTE_2, servo_id, length, instruction])
        body = header[2:] + params
        chk = self._checksum(body)
        packet = header + params + bytes([chk])
        self.ser.reset_input_buffer()
        self.ser.write(packet)
        self.ser.flush()

    def _read_response(self, servo_id: int, expected_data_len: int) -> bytes:
        expected_len = 6 + expected_data_len
        raw = self.ser.read(expected_len)
        if len(raw) < expected_len:
            raise TimeoutError(f"Serial read timeout on Servo {servo_id}: got {len(raw)}/{expected_len} bytes")

        idx = raw.find(bytes([HEADER_BYTE_1, HEADER_BYTE_2]))
        if idx == -1:
            raise ValueError(f"Packet header mismatch from Servo {servo_id}: {raw.hex()}")

        msg = raw[idx:]
        if len(msg) < expected_len:
            msg += self.ser.read(expected_len - len(msg))

        resp_id = msg[2]
        length = msg[3]
        err = msg[4]
        data = msg[5 : 5 + length - 2]
        chk = msg[-1]

        calc_chk = self._checksum(msg[2:-1])
        if chk != calc_chk:
            raise ValueError(f"Checksum error from Servo {servo_id}: {chk} != {calc_chk}")
        
        # Track hardware status flags (e.g. angle limit 0x10, overheat 0x04) without discarding payload
        self.last_errors[servo_id] = err

        return data

    def ping(self, servo_id: int, retries: int = 2) -> bool:
        """Pings a servo to verify presence on the bus."""
        for _ in range(retries):
            try:
                self._send_packet(servo_id, Instruction.PING)
                self._read_response(servo_id, 0)
                return True
            except Exception:
                time.sleep(0.003)
        return False

    def read_byte(self, servo_id: int, register: Register, retries: int = 3) -> int:
        """Reads a 1-byte unsigned 8-bit integer."""
        for attempt in range(retries):
            try:
                self._send_packet(servo_id, Instruction.READ, bytes([register, 1]))
                data = self._read_response(servo_id, 1)
                return data[0]
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(0.002)
        raise RuntimeError("Unreachable")

    def read_word(self, servo_id: int, register: Register, retries: int = 3) -> int:
        """Reads a 2-byte unsigned 16-bit integer (little endian)."""
        for attempt in range(retries):
            try:
                self._send_packet(servo_id, Instruction.READ, bytes([register, 2]))
                data = self._read_response(servo_id, 2)
                return int.from_bytes(data, byteorder="little", signed=False)
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(0.002)
        raise RuntimeError("Unreachable")

    def read_signed_word(self, servo_id: int, register: Register, retries: int = 3) -> int:
        """Reads a 2-byte signed 16-bit integer (little endian)."""
        val = self.read_word(servo_id, register, retries)
        if val >= 0x8000:
            val -= 0x10000
        return val

    def write_byte(self, servo_id: int, register: Register, value: int, retries: int = 3) -> None:
        """Writes a single byte to register and consumes the ACK response packet."""
        for attempt in range(retries):
            try:
                self._send_packet(servo_id, Instruction.WRITE, bytes([register, value & 0xFF]))
                self._read_response(servo_id, 0)
                return
            except Exception:
                if attempt == retries - 1:
                    # Non-fatal if servo configured with RESPONSE_LEVEL=0
                    pass
                time.sleep(0.002)

    def write_word(self, servo_id: int, register: Register, value: int, retries: int = 3) -> None:
        """Writes a 2-byte integer (little endian) and consumes the ACK response packet."""
        data = bytes([register, value & 0xFF, (value >> 8) & 0xFF])
        for attempt in range(retries):
            try:
                self._send_packet(servo_id, Instruction.WRITE, data)
                self._read_response(servo_id, 0)
                return
            except Exception:
                if attempt == retries - 1:
                    pass
                time.sleep(0.002)

    def write_byte_verified(self, servo_id: int, register: Register, value: int, retries: int = 3) -> None:
        """
        Writes a single byte to register, consumes the ACK, and performs an explicit
        readback assertion to guarantee that the hardware register latched the value.
        """
        for attempt in range(retries):
            self.write_byte(servo_id, register, value)
            time.sleep(0.002)
            try:
                actual = self.read_byte(servo_id, register)
                if actual == (value & 0xFF):
                    return
            except Exception:
                pass
        raise RuntimeError(
            f"Actuator ID {servo_id} register 0x{register:02X} failed to latch value {value} after {retries} attempts!"
        )

    def write_signed_word(self, servo_id: int, register: Register, value: int) -> None:
        """Writes a 2-byte signed integer to register."""
        if value < 0:
            value = (value + 0x10000) & 0xFFFF
        self.write_word(servo_id, register, value)

    def sync_read_positions(self, servo_ids: List[int], retries: int = 3) -> Dict[int, int]:
        """
        Fast batch read of Present_Position across all specified servos.
        Uses single SYNC_READ instruction.
        """
        params = bytes([Register.PRESENT_POSITION, 2]) + bytes(servo_ids)
        for attempt in range(retries):
            try:
                self._send_packet(0xFE, Instruction.SYNC_READ, params)
                res = {}
                for sid in servo_ids:
                    data = self._read_response(sid, 2)
                    res[sid] = int.from_bytes(data, byteorder="little", signed=False)
                return res
            except Exception:
                if attempt == retries - 1:
                    # Fallback to sequential read on failure
                    res = {}
                    for sid in servo_ids:
                        res[sid] = self.read_word(sid, Register.PRESENT_POSITION, retries=1)
                    return res
                time.sleep(0.002)
        return {}

    def sync_write_positions(self, targets: Dict[int, int]) -> None:
        """
        Fast batch write of Goal_Position across all servos simultaneously.
        """
        payload = bytearray([Register.GOAL_POSITION, 2])
        for sid, pos in targets.items():
            payload.extend([sid, pos & 0xFF, (pos >> 8) & 0xFF])
        self._send_packet(0xFE, Instruction.SYNC_WRITE, bytes(payload))
