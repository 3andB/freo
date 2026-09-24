"""Installed client version. Change this value when publishing a release."""

import logging

VERSION = '0.3.0'

# Keep the wire value nonempty without inventing a release if build metadata is bad.
if not isinstance(VERSION, str) or not VERSION.strip() or len(VERSION) > 128:
    logging.getLogger(__name__).error('Installed Freo version metadata is invalid')
    VERSION = 'unknown'
