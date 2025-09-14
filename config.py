"""
Configuration module for the A2A Agent.
Contains API endpoints and settings for external services.
"""

import os
from dotenv import load_dotenv

# Load environment variables from App/.env
load_dotenv("App/.env")

# NPPES API Configuration
NPPES_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
NPPES_API_VERSION = "2.1"
NPPES_REQUEST_TIMEOUT = 30.0  # seconds
NPPES_MAX_RETRIES = 3

# Practice Fusion API Configuration
PRACTICE_FUSION_BASE_URL = "https://qa-api.practicefusion.com"
PRACTICE_FUSION_REQUEST_TIMEOUT = 30.0  # seconds
PRACTICE_FUSION_MAX_RETRIES = 3

# API Keys (from environment variables)
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Practice Fusion credentials (from environment variables)
PRACTICE_FUSION_REFRESH_TOKEN = os.getenv('REFRESH_TOKEN')
PRACTICE_FUSION_CLIENT_ID = os.getenv('PRACTICE_FUSION_CLIENT_ID')
PRACTICE_FUSION_CLIENT_SECRET = os.getenv('PRACTICE_FUSION_CLIENT_SECRET')
PRACTICE_FUSION_REDIRECT_URI = os.getenv('PRACTICE_FUSION_REDIRECT_URI')

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')