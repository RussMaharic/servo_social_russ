"""SO-101 joint order and encoder units, derived from t2-BOTS."""

CANONICAL_REST_ANGLES = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -90.0,
    "elbow_flex": 90.0,
    "wrist_flex": 90.0,
    "wrist_roll": 0.0,
    "gripper": 0.0,
}

JOINT_ID_MAP = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

TICKS_PER_REV = 4096.0

DEGREES_PER_TICK = 360.0 / TICKS_PER_REV  # ~0.08789° per tick
