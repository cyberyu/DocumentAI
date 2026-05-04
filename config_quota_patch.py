# Config patch to add missing QUOTA_DEFAULT_IMAGE_RESERVE_MICROS
# This file patches app/config/__init__.py to add the missing attribute

import os
from typing import Optional

# Add to Config class
QUOTA_DEFAULT_IMAGE_RESERVE_MICROS: int = int(os.getenv("QUOTA_DEFAULT_IMAGE_RESERVE_MICROS", "100000"))
