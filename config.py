"""
Configuration module for the A2A Agent.
Contains API endpoints and settings for external services.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# NPPES API Configuration
NPPES_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
NPPES_API_VERSION = "2.1"
NPPES_REQUEST_TIMEOUT = 30.0  # seconds
NPPES_MAX_RETRIES = 3

# API Keys (from environment variables)
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')