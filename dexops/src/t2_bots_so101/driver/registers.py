"""
Feetech STS3215 Control Table Register Map & Protocol Constants.
"""

from enum import IntEnum

# Baud rate constants
BAUDRATE_1M = 1_000_000

# Protocol packet bytes
HEADER_BYTE_1 = 0xFF
HEADER_BYTE_2 = 0xFF

class Instruction(IntEnum):
    PING = 0x01
    READ = 0x02
    WRITE = 0x03
    REG_WRITE = 0x04
    ACTION = 0x05
    SYNC_READ = 0x82
    SYNC_WRITE = 0x83

class Register(IntEnum):
    # EEPROM Area (Non-volatile, persists across power cycles)
    FIRMWARE_MAJOR = 0x00
    FIRMWARE_MINOR = 0x01
    SERVO_ID = 0x05
    BAUD_RATE = 0x06
    MIN_ANGLE_LIMIT = 0x09   # 2 bytes
    MAX_ANGLE_LIMIT = 0x0B   # 2 bytes
    MAX_TEMPERATURE = 0x0D
    MAX_VOLTAGE = 0x0E
    MIN_VOLTAGE = 0x0F
    HOMING_OFFSET = 0x18     # 2 bytes (Signed)
    OPERATING_MODE = 0x21
    PROTECTIVE_TORQUE = 0x22

    # RAM Area (Volatile, resets on reboot)
    TORQUE_ENABLE = 0x28
    ACCELERATION = 0x29
    GOAL_POSITION = 0x2A     # 2 bytes (0-4095)
    GOAL_TIME = 0x2C         # 2 bytes
    GOAL_SPEED = 0x2E        # 2 bytes
    LOCK = 0x37
    PRESENT_POSITION = 0x38  # 2 bytes (0-4095)
    PRESENT_SPEED = 0x3A     # 2 bytes
    PRESENT_LOAD = 0x3C      # 2 bytes
    PRESENT_VOLTAGE = 0x3E   # 1 byte (0.1V units)
    PRESENT_TEMPERATURE = 0x3F # 1 byte (°C)
    STATUS_ERROR = 0x41

class OperatingMode(IntEnum):
    POSITION = 0
    CONTINUOUS_ROTATION = 1
    PWM = 2
    STEP = 3
