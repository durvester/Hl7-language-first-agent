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



# Export all available tools
TOOLS = [get_referring_provider_identity]

# Optional: Tool metadata for introspection
TOOL_METADATA = {
    'get_referring_provider_identity': {
        'category': 'healthcare',
        'description': 'Healthcare provider identity verification for Dr Walter Reed referrals',
        'api_dependency': 'npiregistry.cms.hhs.gov',
        'rate_limited': True,
    }
}