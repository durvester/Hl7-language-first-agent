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
) -> str:
    """
    Async implementation of provider verification.
    """
    try:
        # Validate input
        if not first_name or not last_name:
            return "Both first name and last name are required for provider verification. Please provide complete information."
        
        client = NPPESClient()
        data = await client.search_providers(first_name, last_name, city, state)
        
        result_count = data.get("result_count", 0)
        results = data.get("results", [])
        
        # Process results based on count
        if result_count == 0:
            return (f"No healthcare providers found matching '{first_name} {last_name}'" +
                   (f" in {city}, {state}" if city or state else "") + 
                   ". Please verify the spelling or provide additional details like city or state.")
        
        elif result_count <= 3:
            # Process each provider to extract key information
            response_lines = []
            response_lines.append(f"Found {result_count} provider(s) matching '{first_name} {last_name}'" +
                                (f" in {city}, {state}" if city or state else "") + ":")
            response_lines.append("")
            
            npi_match_found = False
            
            for i, provider in enumerate(results, 1):
                basic = provider.get("basic", {})
                addresses = provider.get("addresses", [])
                provider_npi = provider.get("number", "")
                
                # Get primary address (usually first one)
                primary_address = addresses[0] if addresses else {}
                
                # Check if provider is active
                status = basic.get("status", "")
                is_active = status == "A"
                
                full_name = f"{basic.get('first_name', '')} {basic.get('middle_name', '')} {basic.get('last_name', '')}".strip()
                credentials = basic.get('credential', '')
                
                response_lines.append(f"{i}. {full_name}" + (f", {credentials}" if credentials else ""))
                response_lines.append(f"   NPI: {provider_npi}")
                response_lines.append(f"   Status: {'Active' if is_active else 'Inactive'}")
                response_lines.append(f"   Location: {primary_address.get('city', '')}, {primary_address.get('state', '')}")
                response_lines.append(f"   Enumeration Date: {basic.get('enumeration_date', '')}")
                response_lines.append("")
                
                # Check for NPI match if provided
                if npi and provider_npi == npi.strip():
                    npi_match_found = True
                    response_lines.append(f"✓ NPI {npi} matches this provider.")
                    response_lines.append("")
            
            # If NPI was provided but no match found, return validation failure
            if npi and not npi_match_found:
                response_lines.append(f"⚠️ NPI {npi} does not match any of the providers listed above. Please verify the NPI number or provider information.")
            
            if result_count > 1:
                response_lines.append("Your identity has been verified. Please confirm which provider above matches you for accurate referral processing.")
            else:
                response_lines.append("Your identity has been successfully verified for referrals to Dr Walter Reed.")
            
            return "\n".join(response_lines)
        
        else:
            # Too many results - need refinement, but check NPI first if provided
            if npi:
                # Check if any of the results match the provided NPI
                npi_match_found = False
                
                for provider in results:
                    provider_npi = provider.get("number", "")
                    if provider_npi == npi.strip():
                        npi_match_found = True
                        # Process the matching provider
                        basic = provider.get("basic", {})
                        addresses = provider.get("addresses", [])
                        primary_address = addresses[0] if addresses else {}
                        status = basic.get("status", "")
                        is_active = status == "A"
                        
                        full_name = f"{basic.get('first_name', '')} {basic.get('middle_name', '')} {basic.get('last_name', '')}".strip()
                        credentials = basic.get('credential', '')
                        
                        return (f"Identity verified: {full_name}" + (f", {credentials}" if credentials else "") + 
                               f"\nNPI: {npi}\nStatus: {'Active' if is_active else 'Inactive'}" +
                               f"\nLocation: {primary_address.get('city', '')}, {primary_address.get('state', '')}" +
                               f"\nYour identity has been successfully verified for referrals to Dr Walter Reed.")
                
                if not npi_match_found:
                    return (f"NPI {npi} does not match any provider named '{first_name} {last_name}'. " +
                           f"Found {result_count} provider(s) with that name but none have the provided NPI. " +
                           "Please verify the NPI number or provider name.")
            
            # No NPI provided - need more information
            refinement_params = []
            if not city:
                refinement_params.append("city")
            if not state:
                refinement_params.append("state")
            
            return (f"Found {result_count} providers matching '{first_name} {last_name}'" +
                   (f" in {city}, {state}" if city or state else "") + 
                   f". Please provide additional information to narrow the search: {', '.join(refinement_params)} or your NPI number.")
    
    except ProviderVerificationError as e:
        logger.error(f"Provider verification failed: {e}")
        return f"Unable to verify provider identity: {str(e)}. Please try again or contact support."
    
    except Exception as e:
        logger.error(f"Unexpected error in provider verification: {e}")
        return "An unexpected error occurred during provider verification. Please try again."


@tool
def get_referring_provider_identity(
    first_name: str,
    last_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    npi: Optional[str] = None
) -> str:
    """
    Verify a healthcare provider's identity using the NPPES NPI Registry.
    
    This is the primary tool for verifying referring providers to Dr Walter Reed.
    
    Args:
        first_name: Provider's first name (required)
        last_name: Provider's last name (required)  
        city: City to narrow search (optional)
        state: State to narrow search (optional)
        npi: NPI number to validate against found providers (optional)
        
    Returns:
        A formatted string with verification results suitable for the referring provider
    """
    return asyncio.run(_verify_provider_async(first_name, last_name, city, state, npi))



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