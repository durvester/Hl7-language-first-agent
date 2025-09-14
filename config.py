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

# Walter Reed Practice Configuration
WALTER_REED_USER_GUID = "3dbd230c-0b40-439b-8275-221c707df233"
WALTER_REED_FACILITY_GUID = "420d7e64-398b-4f28-8665-4e8c7f4dd38e"
PRACTICE_GUID = "b4ab304f-d1ac-4565-8dca-992b589422a7"
NEW_PATIENT_VISIT_TYPE_GUID = "2bb6b066-7f70-499f-8e63-d4942a79554a"

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')