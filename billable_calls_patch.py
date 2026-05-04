# Patch for billable_calls.py to handle missing QUOTA_DEFAULT_IMAGE_RESERVE_MICROS
# This file patches line 566 to use getattr with a default value

# All other imports and code from billable_calls.py would be here
# We're only patching the problematic line

# Original line 566:
# DEFAULT_IMAGE_RESERVE_MICROS = config.QUOTA_DEFAULT_IMAGE_RESERVE_MICROS

# Patched version:
# Import config (this would already be imported in the original file)
from app.config import config

# Use getattr with default value to avoid AttributeError
DEFAULT_IMAGE_RESERVE_MICROS = getattr(config, 'QUOTA_DEFAULT_IMAGE_RESERVE_MICROS', 100000)
