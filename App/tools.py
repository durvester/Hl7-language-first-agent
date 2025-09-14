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


class PracticeFusionError(Exception):
    """Custom exception for Practice Fusion API errors."""
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


class PracticeFusionClient:
    """Client for interacting with the Practice Fusion EHR API."""

    def __init__(self):
        """Initialize the Practice Fusion client."""
        self.base_url = config.PRACTICE_FUSION_BASE_URL
        self.timeout = config.PRACTICE_FUSION_REQUEST_TIMEOUT
        self.max_retries = config.PRACTICE_FUSION_MAX_RETRIES
        self.refresh_token = config.PRACTICE_FUSION_REFRESH_TOKEN
        self.client_id = config.PRACTICE_FUSION_CLIENT_ID
        self.client_secret = config.PRACTICE_FUSION_CLIENT_SECRET
        self.redirect_uri = config.PRACTICE_FUSION_REDIRECT_URI

    async def get_access_token(self) -> str:
        """
        Get a fresh access token using the refresh token.
        This is called for every API request (stateless approach).

        Returns:
            Access token string

        Raises:
            PracticeFusionError: If token refresh fails
        """
        token_url = f"{self.base_url}/ehr/oauth2/token"

        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'redirect_uri': self.redirect_uri,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(token_url, data=data, headers=headers)
                    response.raise_for_status()

                    token_data = response.json()
                    access_token = token_data.get('access_token')

                    if not access_token:
                        raise PracticeFusionError("No access token in response")

                    logger.info("Successfully obtained fresh access token")
                    return access_token

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:  # Rate limit
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Practice Fusion token API HTTP error {e.response.status_code}: {e}")
                        raise PracticeFusionError(f"Token API error: {e.response.status_code}")

                except httpx.RequestError as e:
                    if attempt == self.max_retries - 1:
                        logger.error(f"Practice Fusion token API request failed after {self.max_retries} attempts: {e}")
                        raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                    wait_time = 1 * (attempt + 1)
                    logger.warning(f"Token request failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)

        raise PracticeFusionError("Max retries exceeded for token refresh")

    async def create_patient(self, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new patient in Practice Fusion EHR.

        Args:
            patient_data: Dictionary containing patient information

        Returns:
            Dictionary containing patient creation response

        Raises:
            PracticeFusionError: If patient creation fails
        """
        try:
            # Get fresh access token for this request
            access_token = await self.get_access_token()

            # Create patient endpoint
            patient_url = f"{self.base_url}/ehr/v4/patients/"

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }

            logger.info(f"Creating patient in Practice Fusion: {patient_data.get('profile', {}).get('firstName', '')} {patient_data.get('profile', {}).get('lastName', '')}")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.post(patient_url, json=patient_data, headers=headers)
                        response.raise_for_status()

                        patient_response = response.json()
                        logger.info(f"Successfully created patient with MRN: {patient_response.get('profile', {}).get('patientRecordNumber', 'Unknown')}")
                        return patient_response

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:  # Rate limit
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Practice Fusion patient API HTTP error {e.response.status_code}: {e}")
                            raise PracticeFusionError(f"Patient creation API error: {e.response.status_code}")

                    except httpx.RequestError as e:
                        if attempt == self.max_retries - 1:
                            logger.error(f"Practice Fusion patient API request failed after {self.max_retries} attempts: {e}")
                            raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                        wait_time = 1 * (attempt + 1)
                        logger.warning(f"Patient creation request failed, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)

            raise PracticeFusionError("Max retries exceeded for patient creation")

        except PracticeFusionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in patient creation: {e}")
            raise PracticeFusionError(f"Unexpected error: {e}")

    async def get_users(self) -> Dict[str, Any]:
        """
        Get all users in the practice to find Dr. Walter Reed's user details.

        Returns:
            Dictionary containing users list

        Raises:
            PracticeFusionError: If users fetch fails
        """
        try:
            access_token = await self.get_access_token()
            users_url = f"{self.base_url}/ehr/v2/users"

            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.get(users_url, headers=headers)
                        response.raise_for_status()

                        users_data = response.json()
                        logger.info(f"Successfully retrieved {len(users_data.get('Users', []))} users")
                        return users_data

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:  # Rate limit
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Practice Fusion users API HTTP error {e.response.status_code}: {e}")
                            raise PracticeFusionError(f"Users API error: {e.response.status_code}")

                    except httpx.RequestError as e:
                        if attempt == self.max_retries - 1:
                            logger.error(f"Practice Fusion users API request failed after {self.max_retries} attempts: {e}")
                            raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                        wait_time = 1 * (attempt + 1)
                        logger.warning(f"Users request failed, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)

            raise PracticeFusionError("Max retries exceeded for users fetch")

        except PracticeFusionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in users fetch: {e}")
            raise PracticeFusionError(f"Unexpected error: {e}")

    async def get_facilities(self) -> Dict[str, Any]:
        """
        Get all facilities in the practice to find Walter Reed Cardiology Clinic details.

        Returns:
            Dictionary containing facilities list

        Raises:
            PracticeFusionError: If facilities fetch fails
        """
        try:
            access_token = await self.get_access_token()
            facilities_url = f"{self.base_url}/ehr/v2/facilities"

            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.get(facilities_url, headers=headers)
                        response.raise_for_status()

                        facilities_data = response.json()
                        logger.info(f"Successfully retrieved {len(facilities_data.get('facilities', []))} facilities")
                        return facilities_data

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:  # Rate limit
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Practice Fusion facilities API HTTP error {e.response.status_code}: {e}")
                            raise PracticeFusionError(f"Facilities API error: {e.response.status_code}")

                    except httpx.RequestError as e:
                        if attempt == self.max_retries - 1:
                            logger.error(f"Practice Fusion facilities API request failed after {self.max_retries} attempts: {e}")
                            raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                        wait_time = 1 * (attempt + 1)
                        logger.warning(f"Facilities request failed, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)

            raise PracticeFusionError("Max retries exceeded for facilities fetch")

        except PracticeFusionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in facilities fetch: {e}")
            raise PracticeFusionError(f"Unexpected error: {e}")

    async def check_calendar_availability(
        self,
        ehr_user_guid: str,
        facility_guid: str,
        start_date_utc: str,
        end_date_utc: str
    ) -> Dict[str, Any]:
        """
        Check for existing appointments in the specified time window.

        Args:
            ehr_user_guid: Provider's EHR user GUID
            facility_guid: Facility GUID
            start_date_utc: Start date in UTC (YYYY-MM-DDTHH:MM:SSZ)
            end_date_utc: End date in UTC (YYYY-MM-DDTHH:MM:SSZ)

        Returns:
            Dictionary containing calendar events

        Raises:
            PracticeFusionError: If calendar query fails
        """
        try:
            access_token = await self.get_access_token()

            params = {
                "eventTypeCategory": "Appointment",
                "ehrUserGuid": ehr_user_guid,
                "facilityGuid": facility_guid,
                "minimumStartDateTimeUtc": start_date_utc,
                "maximumStartDateTimeUtc": end_date_utc
            }

            calendar_url = f"{self.base_url}/ehr/v1/calendar/events/query"

            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.get(calendar_url, params=params, headers=headers)
                        response.raise_for_status()

                        calendar_data = response.json()
                        logger.info(f"Successfully retrieved {len(calendar_data.get('events', []))} calendar events")
                        return calendar_data

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:  # Rate limit
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Practice Fusion calendar API HTTP error {e.response.status_code}: {e}")
                            raise PracticeFusionError(f"Calendar API error: {e.response.status_code}")

                    except httpx.RequestError as e:
                        if attempt == self.max_retries - 1:
                            logger.error(f"Practice Fusion calendar API request failed after {self.max_retries} attempts: {e}")
                            raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                        wait_time = 1 * (attempt + 1)
                        logger.warning(f"Calendar request failed, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)

            raise PracticeFusionError("Max retries exceeded for calendar query")

        except PracticeFusionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in calendar query: {e}")
            raise PracticeFusionError(f"Unexpected error: {e}")

    async def create_appointment(self, appointment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new appointment in Practice Fusion EHR.

        Args:
            appointment_data: Dictionary containing appointment information

        Returns:
            Dictionary containing appointment creation response

        Raises:
            PracticeFusionError: If appointment creation fails
        """
        try:
            access_token = await self.get_access_token()
            appointment_url = f"{self.base_url}/ehr/v1/calendar/events"

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }

            logger.info(f"Creating appointment for patient: {appointment_data.get('event', {}).get('patientPracticeGuid', 'Unknown')}")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.post(appointment_url, json=appointment_data, headers=headers)
                        response.raise_for_status()

                        appointment_response = response.json()
                        logger.info(f"Successfully created appointment with ID: {appointment_response.get('event', {}).get('eventId', 'Unknown')}")
                        return appointment_response

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:  # Rate limit
                            wait_time = 2 ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            # Log detailed error information for debugging
                            error_details = ""
                            try:
                                error_response = e.response.json()
                                error_details = f" - Response: {error_response}"
                            except:
                                error_details = f" - Response text: {e.response.text}"

                            logger.error(f"Practice Fusion appointment API HTTP error {e.response.status_code}: {e}{error_details}")
                            logger.error(f"Request payload was: {appointment_data}")
                            raise PracticeFusionError(f"Appointment creation API error: {e.response.status_code}{error_details}")

                    except httpx.RequestError as e:
                        if attempt == self.max_retries - 1:
                            logger.error(f"Practice Fusion appointment API request failed after {self.max_retries} attempts: {e}")
                            raise PracticeFusionError(f"Unable to connect to Practice Fusion API: {e}")

                        wait_time = 1 * (attempt + 1)
                        logger.warning(f"Appointment creation request failed, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)

            raise PracticeFusionError("Max retries exceeded for appointment creation")

        except PracticeFusionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in appointment creation: {e}")
            raise PracticeFusionError(f"Unexpected error: {e}")


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


async def _create_patient_async(
    first_name: str,
    last_name: str,
    sex: str,
    birth_date: str,
    email_address: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    street_address1: Optional[str] = None,
    street_address2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a patient in Practice Fusion EHR.
    Returns structured data for the LLM to interpret and respond to.
    """
    try:
        # Validate required input
        if not first_name or not last_name or not sex or not birth_date:
            return {
                "success": False,
                "error": "First name, last name, sex, and birth date are required"
            }

        # Build patient data structure matching Practice Fusion API
        patient_data = {
            "profile": {
                "sex": sex,
                "firstName": first_name.strip(),
                "lastName": last_name.strip(),
                "birthDate": birth_date
            }
        }

        # Add contact information if provided
        if email_address or mobile_phone or street_address1:
            contact_info = {}

            if email_address:
                contact_info["emailAddress"] = email_address.strip()
                contact_info["doesNotHaveEmail"] = False
            else:
                contact_info["doesNotHaveEmail"] = True

            if mobile_phone:
                contact_info["mobilePhone"] = mobile_phone.strip()
                contact_info["doesNotHaveMobilePhone"] = False
            else:
                contact_info["doesNotHaveMobilePhone"] = True

            # Add address if provided
            if street_address1 or city or state or postal_code:
                address_info = {}
                if street_address1:
                    address_info["streetAddress1"] = street_address1.strip()
                if street_address2:
                    address_info["streetAddress2"] = street_address2.strip()
                if city:
                    address_info["city"] = city.strip()
                if state:
                    address_info["state"] = state.strip()
                if postal_code:
                    address_info["postalCode"] = postal_code.strip()

                # Set effective dates (required by API)
                from datetime import datetime, timedelta
                today = datetime.now()
                address_info["effectiveStartDate"] = today.strftime("%Y-%m-%dT00:00:00Z")
                address_info["effectiveEndDate"] = (today + timedelta(days=365*30)).strftime("%Y-%m-%dT00:00:00Z")  # 30 years

                contact_info["address"] = address_info

            patient_data["contact"] = contact_info

        # Create patient using Practice Fusion client
        client = PracticeFusionClient()
        response_data = await client.create_patient(patient_data)

        # Extract patient information from response
        profile = response_data.get("profile", {})
        contact = response_data.get("contact", {})

        return {
            "success": True,
            "patient_created": True,
            "patient_mrn": profile.get("patientRecordNumber", ""),
            "patient_practice_guid": profile.get("patientPracticeGuid", ""),
            "practice_guid": profile.get("practiceGuid", ""),
            "patient_name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}",
            "birth_date": profile.get("birthDate", ""),
            "sex": profile.get("sex", ""),
            "is_active": profile.get("isActive", False),
            "email_address": contact.get("emailAddress", ""),
            "mobile_phone": contact.get("mobilePhone", ""),
            "creation_status": "Patient successfully created in Practice Fusion EHR"
        }

    except PracticeFusionError as e:
        logger.error(f"Practice Fusion patient creation failed: {e}")
        return {
            "success": False,
            "error": f"Practice Fusion API error: {str(e)}"
        }

    except Exception as e:
        logger.error(f"Unexpected error in patient creation: {e}")
        return {
            "success": False,
            "error": "An unexpected error occurred during patient creation"
        }


async def _schedule_appointment_async(
    patient_name: str,
    patient_dob: str,
    patient_phone: str,
    patient_practice_guid: str,
    preferred_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Schedule a real appointment using Practice Fusion API.
    Returns structured data for the LLM to interpret and respond to.
    """
    try:
        from datetime import datetime, timedelta, timezone
        try:
            import pytz
        except ImportError:
            logger.warning("pytz not available, using datetime timezone instead")
            # Fallback to built-in timezone for Eastern Time
            from datetime import timezone, timedelta
            eastern = timezone(timedelta(hours=-5))  # EST (simplified)
            utc = timezone.utc

        # Validate required input
        if not patient_name or not patient_dob or not patient_phone or not patient_practice_guid:
            return {
                "success": False,
                "error": "Patient name, date of birth, phone number, and patient practice GUID are required"
            }

        # Create Practice Fusion client
        client = PracticeFusionClient()

        # Use configuration constants
        walter_reed_user_guid = config.WALTER_REED_USER_GUID
        walter_reed_facility_guid = config.WALTER_REED_FACILITY_GUID
        practice_guid = config.PRACTICE_GUID
        event_type_guid = config.NEW_PATIENT_VISIT_TYPE_GUID

        # Find available appointment slots
        # Walter Reed Cardiology Clinic hours: Mon-Fri 9AM-5PM Eastern
        if 'pytz' in locals():
            eastern = pytz.timezone('America/New_York')
            utc = pytz.UTC
        # eastern and utc already set in fallback above if pytz not available

        # Find next available weekday (Monday-Friday)
        today = datetime.now(eastern)
        available_slots = []

        for days_ahead in range(1, 15):  # Look ahead 2 weeks
            candidate_date = today + timedelta(days=days_ahead)

            # Skip weekends (Saturday=5, Sunday=6)
            if candidate_date.weekday() >= 5:
                continue

            # Generate hourly slots from 9AM to 4PM (last 1-hour slot starts at 4PM)
            for hour in range(9, 17):  # 9AM to 4PM
                slot_time = candidate_date.replace(hour=hour, minute=0, second=0, microsecond=0)

                # Convert to UTC for API calls
                slot_time_utc = slot_time.astimezone(utc)
                available_slots.append({
                    'local_time': slot_time,
                    'utc_time': slot_time_utc,
                    'date_str': slot_time.strftime("%A, %B %d, %Y"),
                    'time_str': slot_time.strftime("%I:%M %p")
                })

        if not available_slots:
            return {
                "success": False,
                "error": "No available slots found in the next 2 weeks"
            }

        # Check for conflicts with existing appointments
        # We need to check availability in 7-day windows due to API limitation
        selected_slot = None

        for slot in available_slots:
            # Create 7-day window around this slot for conflict checking
            window_start = slot['utc_time'] - timedelta(days=3)
            window_end = slot['utc_time'] + timedelta(days=4)

            try:
                # Check for existing appointments in this window
                calendar_data = await client.check_calendar_availability(
                    walter_reed_user_guid,
                    walter_reed_facility_guid,
                    window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
                )

                # Check if this specific slot conflicts with existing appointments
                slot_conflicts = False
                existing_events = calendar_data.get('events', [])

                for event in existing_events:
                    if event.get('isCancelled', False):
                        continue

                    event_start_utc = datetime.fromisoformat(
                        event['startDateTimeUtc'].replace('Z', '+00:00')
                    )

                    # Parse duration (format: "HH:MM:SS")
                    duration_str = event.get('duration', '01:00:00')
                    duration_parts = duration_str.split(':')
                    duration_hours = int(duration_parts[0])
                    duration_minutes = int(duration_parts[1]) if len(duration_parts) > 1 else 0

                    event_end_utc = event_start_utc + timedelta(hours=duration_hours, minutes=duration_minutes)

                    # Check if our 1-hour slot overlaps with this event
                    slot_end_utc = slot['utc_time'] + timedelta(hours=1)

                    if (slot['utc_time'] < event_end_utc and slot_end_utc > event_start_utc):
                        slot_conflicts = True
                        break

                if not slot_conflicts:
                    selected_slot = slot
                    break

            except PracticeFusionError as e:
                logger.warning(f"Could not check availability for slot {slot['time_str']}: {e}")
                continue

        if not selected_slot:
            return {
                "success": False,
                "error": "No available slots found without conflicts"
            }

        # Create the appointment
        appointment_data = {
            "event": {
                "practiceGuid": practice_guid,
                "ehrUserGuid": walter_reed_user_guid,
                "facilityGuid": walter_reed_facility_guid,
                "patientPracticeGuid": patient_practice_guid,
                "chiefComplaint": "",
                "eventType": {
                    "eventTypeGuid": event_type_guid,
                    "eventTypeName": "New Patient Visit",
                    "eventCategory": "Appointment"
                },
                "startDateTimeUtc": selected_slot['utc_time'].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "startDateTimeFlt": selected_slot['local_time'].strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "duration": "01:00:00"  # 1 hour appointment
            }
        }

        # Create the appointment
        appointment_response = await client.create_appointment(appointment_data)

        # Extract appointment details from response
        event_data = appointment_response.get("event", {})
        event_id = event_data.get("eventId", "")

        return {
            "success": True,
            "appointment_scheduled": True,
            "appointment_id": event_id,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "patient_phone": patient_phone,
            "patient_practice_guid": patient_practice_guid,
            "appointment_date": selected_slot['date_str'],
            "appointment_time": selected_slot['time_str'],
            "duration": "1 hour",
            "location": "Walter Reed Cardiology Clinic, New York, NY",
            "facility_address": "351 Bowling Green, Ste 200, New York, NY 10001",
            "confirmation_number": event_id,
            "instructions": "Please arrive 15 minutes early with insurance card and referral documentation",
            "contact": "Walter Reed Cardiology Clinic: (555) 555-0001",
            "status": "APPOINTMENT CONFIRMED",
            "provider": "Dr. Walter Reed",
            "appointment_type": "New Patient Visit",
            "is_cancelled": False
        }

    except PracticeFusionError as e:
        logger.error(f"Practice Fusion appointment scheduling failed: {e}")
        return {
            "success": False,
            "error": f"Appointment scheduling API error: {str(e)}"
        }

    except Exception as e:
        logger.error(f"Unexpected error in appointment scheduling: {e}")
        return {
            "success": False,
            "error": "An unexpected error occurred during appointment scheduling"
        }


@tool
def create_patient_in_ehr(
    first_name: str,
    last_name: str,
    sex: str,
    birth_date: str,
    email_address: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    street_address1: Optional[str] = None,
    street_address2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None
) -> str:
    """
    Create a new patient record in Practice Fusion EHR system.

    Use this tool to register a patient in the EHR after successful appointment scheduling.
    This establishes the patient record needed for clinical documentation.

    Args:
        first_name: Patient's first name (required)
        last_name: Patient's last name (required)
        sex: Patient's sex (Male/Female) (required)
        birth_date: Patient's birth date in YYYY-MM-DDTHH:MM:SSZ format (required)
        email_address: Patient's email address (optional)
        mobile_phone: Patient's mobile phone number (optional)
        street_address1: Street address line 1 (optional)
        street_address2: Street address line 2 (optional)
        city: City (optional)
        state: State abbreviation (optional)
        postal_code: ZIP/postal code (optional)

    Returns:
        JSON string with patient creation results including MRN
    """
    import json
    result = asyncio.run(_create_patient_async(
        first_name, last_name, sex, birth_date, email_address, mobile_phone,
        street_address1, street_address2, city, state, postal_code
    ))
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
    patient_practice_guid: str,
    preferred_date: Optional[str] = None,
    patient_mrn: Optional[str] = None
) -> str:
    """
    Schedule cardiology appointment with Dr. Walter Reed using real Practice Fusion API.

    Available: Monday-Friday, 9:00 AM - 5:00 PM Eastern, 1-hour slots

    Args:
        patient_name: Patient's full name
        patient_dob: Patient's date of birth (MM/DD/YYYY)
        patient_phone: Patient's contact phone number
        patient_practice_guid: Patient's Practice GUID from EHR creation (required)
        preferred_date: Preferred appointment date (optional)
        patient_mrn: Patient's MRN from EHR registration (optional)

    Returns:
        JSON string with appointment scheduling results
    """
    import json
    result = asyncio.run(_schedule_appointment_async(
        patient_name, patient_dob, patient_phone, patient_practice_guid, preferred_date
    ))
    return json.dumps(result, indent=2)


# Export all available tools
TOOLS = [
    get_referring_provider_identity,
    verify_insurance_coverage,
    validate_clinical_criteria,
    schedule_appointment,
    create_patient_in_ehr
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
        'description': 'Real appointment scheduling for Dr Walter Reed clinic using Practice Fusion API',
        'api_dependency': 'Practice Fusion API',
        'rate_limited': True,
    },
    'create_patient_in_ehr': {
        'category': 'healthcare',
        'description': 'Patient record creation in Practice Fusion EHR system',
        'api_dependency': 'Practice Fusion API',
        'rate_limited': True,
    }
}