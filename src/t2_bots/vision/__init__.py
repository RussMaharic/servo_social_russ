"""
t2-BOTS Multi-Track Vision & Action Pipeline.
Decouples real-time telepresence video from microsecond-synchronized RL dataset recording.
"""

from t2_bots.vision.sync_buffer import VisionActionSyncBuffer

__all__ = ["VisionActionSyncBuffer"]
