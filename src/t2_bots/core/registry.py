"""
Dynamic Robot Driver Registry & Discovery.
"""

import sys
from typing import Dict, Type, Optional, List
from t2_bots.core.base import BaseRobot, RobotRole

if sys.version_info >= (3, 10):
    from importlib.metadata import entry_points
else:
    from importlib_metadata import entry_points

_DRIVERS: Dict[str, Type[BaseRobot]] = {}

def register_driver(name: str, driver_cls: Type[BaseRobot]) -> None:
    """Manually registers a driver class."""
    _DRIVERS[name.lower()] = driver_cls

def list_available_drivers() -> List[str]:
    """Discovers all drivers installed via entry points or direct registry."""
    discovered = list(_DRIVERS.keys())
    try:
        eps = entry_points(group="t2_bots.drivers")
        for ep in eps:
            if ep.name not in discovered:
                discovered.append(ep.name)
    except Exception:
        pass
    return discovered

def get_robot(name: str, role: RobotRole = RobotRole.FOLLOWER, port: Optional[str] = None, **kwargs) -> BaseRobot:
    """Factory function to instantiate any registered robot driver."""
    key = name.lower()
    
    # 1. Check in-memory registry
    if key in _DRIVERS:
        return _DRIVERS[key](name=name, role=role, port=port, **kwargs)

    # 2. Check installed entry-points
    try:
        eps = entry_points(group="t2_bots.drivers")
        for ep in eps:
            if ep.name == key:
                cls = ep.load()
                return cls(name=name, role=role, port=port, **kwargs)
    except Exception as e:
        raise RuntimeError(f"Failed to load entry point for '{name}': {e}")

    # 3. Fallback direct imports for built-in packages
    if key in ["so101", "so101_follower", "so101_leader"]:
        try:
            from t2_bots_so101.arm import SO101Manipulator, SO101Teleoperator
            if key == "so101_leader" or role == RobotRole.LEADER:
                return SO101Teleoperator(name=name, port=port, **kwargs)
            return SO101Manipulator(name=name, role=role, port=port, **kwargs)
        except ImportError as e:
            raise ImportError(f"Driver '{name}' requires 't2-bots-so101': {e}")

    raise ValueError(f"Unknown robot driver '{name}'. Available: {list_available_drivers()}")
