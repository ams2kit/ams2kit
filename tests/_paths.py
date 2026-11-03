"""Where the tests find the game and the extracted research data (both outside this repository).

  AMS2KIT_GAME        AMS2 install folder (default: ams2kit's configured / auto-detected game folder)
  AMS2KIT_TEST_WORK   workspace with extracted game files (phys/, research/, donor/, kit_projects/ ...);
                      default: the folder that contains this repository
Tests whose data is missing are skipped.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ams2kit import game  # noqa: E402

WORK = Path(os.environ.get("AMS2KIT_TEST_WORK") or ROOT.parent)
GAME = Path(os.environ.get("AMS2KIT_GAME") or game.find_game() or "AMS2_not_found")
VEHICLE_PAKS = GAME / "Pakfiles" / "Vehicles"
