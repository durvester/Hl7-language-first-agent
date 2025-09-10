"""
Tools module for the A2A Agent.
This module contains all the tools that the agent can use.
Tools are isolated from the core agent logic for better modularity.
"""

import asyncio
import logging
from typing import Dict, Optional, Any
import httpx
from langchain_core.tools import tool
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProviderVerificationError(Exception):
    """Custom exception for provider verification errors."""
    pass


class NPPESClient:
    """Client for interacting with the NPPES NPI Registry API."""
    
    def __init__(self):
        """Initialize the NPPES client."""
        self.base_url = config.NPPES_BASE_URL
        self.version = config.NPPES_API_VERSION
        self.timeout = config.NPPES_REQUEST_TIMEOUT
        self.max_retries = config.NPPES_MAX_RETRIES
    
    async def search_providers(
        self,
        first_name: str,
        last_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Search for healthcare providers in the NPPES registry.
        
        Args:
            first_name: Provider's first name (required)
            last_name: Provider's last name (required)
            city: City to narrow search (optional)
            state: State abbreviation to narrow search (optional)
            limit: Maximum number of results (default 10)
            
        Returns:
            Dict containing search results and metadata
            
        Raises:
            ProviderVerificationError: If API request fails
        """
        params = {
            "version": self.version,
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "enumeration_type": "NPI-1",  # Individual providers
            "limit": limit,
            "pretty": "false"
        }
        
        # Add optional parameters if provided
        if city:
            params["city"] = city.strip()
        if state:
            params["state"] = state.strip().upper()
        
        logger.info(f"Searching NPPES for: {first_name} {last_name}" +
                   (f" in {city}, {state}" if city or state else ""))
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(self.base_url, params=params)
                    response.raise_for_status()
                    
                    data = response.json()
                    logger.info(f"NPPES search returned {data.get('result_count', 0)} results")
                    return data
                    
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:  # Rate limit
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"NPPES API HTTP error {e.response.status_code}: {e}")
                        raise ProviderVerificationError(f"NPPES API error: {e.response.status_code}")
                        
                except httpx.RequestError as e:
                    if attempt == self.max_retries - 1:
                        logger.error(f"NPPES API request failed after {self.max_retries} attempts: {e}")
                        raise ProviderVerificationError(f"Unable to connect to NPPES API: {e}")
                    
                    wait_time = 1 * (attempt + 1)
                    logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
        
        raise ProviderVerificationError("Max retries exceeded")


async def _verify_provider_async(
    first_name: str,
    last_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    npi: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for healthcare providers in the NPPES registry.
    Returns structured data for the LLM to interpret and respond to.
    """
    try:
        # Validate input
        if not first_name or not last_name:
            return {
                "success": False,
                "error": "Both first name and last name are required"
            }
        
        client = NPPESClient()
        data = await client.search_providers(first_name, last_name, city, state)
        
        result_count = data.get("result_count", 0)
        results = data.get("results", [])
        
        # Extract essential provider information
        providers = []
        for provider in results:
            basic = provider.get("basic", {})
            addresses = provider.get("addresses", [])
            provider_npi = provider.get("number", "")
            
            # Get location address (prefer LOCATION over MAILING)
            location_address = None
            for addr in addresses:
                if addr.get("address_purpose") == "LOCATION":
                    location_address = addr
                    break
            if not location_address and addresses:
                location_address = addresses[0]  # fallback to first address
            
            # Build provider info
            provider_info = {
                "npi": provider_npi,
                "first_name": basic.get("first_name", ""),
                "middle_name": basic.get("middle_name", ""),
                "last_name": basic.get("last_name", ""),
                "credential": basic.get("credential", ""),
                "name_prefix": basic.get("name_prefix", ""),
                "status": "Active" if basic.get("status") == "A" else "Inactive",
                "enumeration_date": basic.get("enumeration_date", ""),
                "city": location_address.get("city", "") if location_address else "",
                "state": location_address.get("state", "") if location_address else "",
                "matches_npi": provider_npi == npi.strip() if npi else None
            }
            providers.append(provider_info)
        
        return {
            "success": True,
            "result_count": result_count,
            "providers": providers,
            "search_criteria": {
                "first_name": first_name,
                "last_name": last_name,
                "city": city,
                "state": state,
                "npi": npi
            }
        }
    
    except ProviderVerificationError as e:
        logger.error(f"Provider verification failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    
    except Exception as e:
        logger.error(f"Unexpected error in provider verification: {e}")
        return {
            "success": False,
            "error": "An unexpected error occurred during provider verification"
        }


@tool
def get_referring_provider_identity(
    first_name: str,
    last_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    npi: Optional[str] = None
) -> str:
    """
    Search for healthcare providers in the NPPES NPI Registry.
    
    Use this tool to look up healthcare provider information for referral verification.
    The tool returns structured data - interpret the results and guide the conversation appropriately.
    
    Args:
        first_name: Provider's first name (required)
        last_name: Provider's last name (required)  
        city: City to narrow search (optional)
        state: State abbreviation to narrow search (optional)
        npi: NPI number to validate (optional)
        
    Returns:
        JSON string with provider search results
    """
    import json
    result = asyncio.run(_verify_provider_async(first_name, last_name, city, state, npi))
    return json.dumps(result, indent=2)



@tool
def verify_insurance_coverage(
    insurance_provider: str,
    patient_name: str,
    member_id: Optional[str] = None
) -> str:
    """
    Verify if patient insurance is accepted by Dr. Walter Reed's clinic.
    
    Accepted insurers: United Healthcare, Aetna, Cigna, Blue Cross Blue Shield (BCBS), Kaiser
    
    Args:
        insurance_provider: Name of the insurance company
        patient_name: Patient's full name
        member_id: Insurance member ID (optional)
        
    Returns:
        JSON string with insurance verification results
    """
    import json
    
    # Mock implementation - simulate insurance verification
    accepted_insurers = [
        "united healthcare", "united", "aetna", "cigna", 
        "blue cross blue shield", "bcbs", "kaiser"
    ]
    
    provider_lower = insurance_provider.lower().strip()
    is_accepted = any(accepted in provider_lower for accepted in accepted_insurers)
    
    if is_accepted:
        result = {
            "success": True,
            "insurance_accepted": True,
            "insurance_provider": insurance_provider,
            "patient_name": patient_name,
            "member_id": member_id,
            "verification_status": "Coverage verified - insurance accepted",
            "next_step": "Proceed to clinical validation"
        }
    else:
        result = {
            "success": True,
            "insurance_accepted": False,
            "insurance_provider": insurance_provider,
            "patient_name": patient_name,
            "member_id": member_id,
            "verification_status": "Insurance not accepted",
            "accepted_insurers": "United Healthcare, Aetna, Cigna, BCBS, Kaiser",
            "recommendation": "Contact Dr. Reed's office for self-pay options"
        }
    
    return json.dumps(result, indent=2)


@tool
def validate_clinical_criteria(
    referral_reason: str,
    patient_name: str,
    documentation_available: str = "Unknown"
) -> str:
    """
    Validate if referral meets Dr. Walter Reed's clinical criteria.
    
    Acceptable reasons: chest pain, abnormal stress test, arrhythmia, heart failure,
    valvular disease, syncope, resistant hypertension, congenital heart disease, 
    pulmonary hypertension.
    
    Args:
        referral_reason: Primary reason for cardiology referral
        patient_name: Patient's full name
        documentation_available: Description of available clinical documentation
        
    Returns:
        JSON string with clinical validation results
    """
    import json
    
    # Mock implementation - simulate clinical criteria validation
    valid_reasons = [
        "chest pain", "ischemia", "stress test", "arrhythmia", "heart failure", 
        "cardiomyopathy", "valvular", "syncope", "hypertension", "congenital", 
        "pulmonary hypertension", "cardiac", "heart"
    ]
    
    reason_lower = referral_reason.lower()
    is_valid_reason = any(valid in reason_lower for valid in valid_reasons)
    
    # Mock documentation check
    has_documentation = "ecg" in documentation_available.lower() or \
                       "ekg" in documentation_available.lower() or \
                       "echo" in documentation_available.lower() or \
                       "available" in documentation_available.lower()
    
    if is_valid_reason and has_documentation:
        result = {
            "success": True,
            "clinical_criteria_met": True,
            "referral_reason": referral_reason,
            "patient_name": patient_name,
            "documentation_status": "Adequate documentation provided",
            "validation_status": "Clinical criteria met - approved for scheduling",
            "next_step": "Proceed to appointment scheduling"
        }
    elif is_valid_reason and not has_documentation:
        result = {
            "success": True,
            "clinical_criteria_met": False,
            "referral_reason": referral_reason,
            "patient_name": patient_name,
            "documentation_status": "Missing required documentation",
            "required_docs": "ECG, recent echocardiogram (if performed), relevant labs, medication list, primary care summary",
            "recommendation": "Please provide required documentation before scheduling"
        }
    else:
        result = {
            "success": True,
            "clinical_criteria_met": False,
            "referral_reason": referral_reason,
            "patient_name": patient_name,
            "validation_status": "Referral reason does not meet criteria",
            "acceptable_reasons": "Chest pain, abnormal stress test, arrhythmia, heart failure, valvular disease, syncope, resistant hypertension",
            "recommendation": "Contact Dr. Reed's office to discuss referral appropriateness"
        }
    
    return json.dumps(result, indent=2)


@tool
def schedule_appointment(
    patient_name: str,
    patient_dob: str,
    patient_phone: str,
    preferred_date: Optional[str] = None
) -> str:
    """
    Schedule cardiology appointment with Dr. Walter Reed.
    
    Available: Mondays and Thursdays, 11:00 AM - 3:00 PM, 1-hour slots
    
    Args:
        patient_name: Patient's full name
        patient_dob: Patient's date of birth (MM/DD/YYYY)
        patient_phone: Patient's contact phone number
        preferred_date: Preferred appointment date (optional)
        
    Returns:
        JSON string with appointment scheduling results
    """
    import json
    from datetime import datetime, timedelta
    
    # Mock implementation - simulate appointment scheduling
    # Generate next available Monday or Thursday
    today = datetime.now()
    days_ahead = []
    
    # Find next Monday (weekday 0) and Thursday (weekday 3)
    for i in range(1, 15):  # Look ahead 2 weeks
        future_date = today + timedelta(days=i)
        if future_date.weekday() in [0, 3]:  # Monday or Thursday
            days_ahead.append(future_date)
        if len(days_ahead) >= 4:  # Get 4 available slots
            break
    
    if days_ahead:
        scheduled_date = days_ahead[0]  # Take first available
        appointment_time = "11:00 AM"
        
        result = {
            "success": True,
            "appointment_scheduled": True,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "patient_phone": patient_phone,
            "appointment_date": scheduled_date.strftime("%A, %B %d, %Y"),
            "appointment_time": appointment_time,
            "duration": "1 hour",
            "location": "Walter Reed Clinic, Manhattan",
            "confirmation_number": f"WR{scheduled_date.strftime('%m%d')}{patient_name[:2].upper()}",
            "instructions": "Please arrive 15 minutes early with insurance card and referral documentation",
            "contact": "Dr. Reed's office: (555) 123-CARD",
            "status": "APPOINTMENT CONFIRMED"
        }
    else:
        result = {
            "success": False,
            "appointment_scheduled": False,
            "patient_name": patient_name,
            "error": "No available appointments in the next 2 weeks",
            "recommendation": "Please contact Dr. Reed's office directly at (555) 123-CARD",
            "status": "SCHEDULING FAILED"
        }
    
    return json.dumps(result, indent=2)


# Export all available tools
TOOLS = [
    get_referring_provider_identity,
    verify_insurance_coverage,
    validate_clinical_criteria,
    schedule_appointment
]

# Optional: Tool metadata for introspection
TOOL_METADATA = {
    'get_referring_provider_identity': {
        'category': 'healthcare',
        'description': 'Healthcare provider identity verification for Dr Walter Reed referrals',
        'api_dependency': 'npiregistry.cms.hhs.gov',
        'rate_limited': True,
    },
    'verify_insurance_coverage': {
        'category': 'healthcare',
        'description': 'Insurance coverage verification for accepted payers',
        'api_dependency': 'mock',
        'rate_limited': False,
    },
    'validate_clinical_criteria': {
        'category': 'healthcare',
        'description': 'Clinical criteria validation for cardiology referrals',
        'api_dependency': 'mock',
        'rate_limited': False,
    },
    'schedule_appointment': {
        'category': 'healthcare',
        'description': 'Appointment scheduling for Dr Walter Reed clinic',
        'api_dependency': 'mock',
        'rate_limited': False,
    }
}