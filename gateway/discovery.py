"""Compatibility import for the shared HACS library."""
import sys
from pathlib import Path
source = Path(__file__).resolve().parents[1] / 'custom_components' / 'tuya_beacon'
if source.is_dir():
    sys.path.insert(0, str(source))
from beacon.discovery import *
