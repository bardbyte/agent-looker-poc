#!/usr/bin/env python3
"""
Convenience script to run the V2 agent.

Usage:
    python run_v2.py
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import run

if __name__ == "__main__":
    run()
