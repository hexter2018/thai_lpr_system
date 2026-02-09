#!/usr/bin/env python3
"""
Entry point for running: python -m alpr_worker.rtsp.frame_producer
"""

import sys
from .frame_producer import main

if __name__ == "__main__":
    sys.exit(main())
