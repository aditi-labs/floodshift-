"""
Test Configuration

API tests run against the real WorldService (the scripted mock world was removed).
Pin the bundle so a developer's FLOODSHIFT_SCENARIO cannot change expectations.
"""
import os

os.environ.pop("FLOODSHIFT_USE_MOCK", None)
os.environ["FLOODSHIFT_SCENARIO"] = "nepal_rasuwa_hot_v1"
os.environ.pop("FLOODSHIFT_SESSION", None)
