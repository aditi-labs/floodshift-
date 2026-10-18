"""
Test Configuration
Sets up mock mode for API tests.
"""
import os

# Force mock mode for all tests - this must happen before any imports
os.environ["FLOODSHIFT_USE_MOCK"] = "true"
