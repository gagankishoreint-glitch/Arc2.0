import os
import sys
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arc.contracts import trigger_holds, validate_contract_dict
from arc.events import BatteryInfo
from arc.monitors import RealMonitor

FakeBattery = namedtuple("sbattery", "percent secsleft power_plugged")


def sample_with(battery):
    with mock.patch("psutil.sensors_battery", return_value=battery):
        return RealMonitor().sample()


class TestBatteryPortability:
    """Regression tests: battery sampling must work on every psutil version
    and on machines with real batteries (macOS/Windows laptops)."""

    def test_battery_present(self):
        s = sample_with(FakeBattery(76.5, 3600.0, True))
        assert s.battery.percent == 76.5
        assert s.battery.plugged is True
        assert s.battery.secs_left == 3600.0

    def test_battery_unknown_secsleft_sentinel(self):
        # psutil uses negative sentinels (POWER_TIME_UNKNOWN/UNLIMITED).
        s = sample_with(FakeBattery(55.0, -1, False))
        assert s.battery.percent == 55.0
        assert s.battery.plugged is False
        assert s.battery.secs_left is None

    def test_no_battery_desktop(self):
        s = sample_with(None)
        assert s.battery == BatteryInfo(None, None)

    def test_battery_trigger_end_to_end(self):
        d = {"name": "bat", "trigger": {"type": "battery_below", "threshold": 25},
             "actions": [{"type": "log", "message": "low"}]}
        t = validate_contract_dict(d).trigger
        assert trigger_holds(t, sample_with(FakeBattery(18.0, 1800.0, False))) is True
        assert trigger_holds(t, sample_with(FakeBattery(18.0, 1800.0, True))) is False  # charging
        assert trigger_holds(t, sample_with(None)) is False
