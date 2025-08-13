import streamlit as st
import requests
import re
import json
import time
import random
from typing import List, Optional, Dict, Any
from utils.logger import logger
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

class APIKeyPool:
    """Manages multiple Google API keys with rotation and error handling."""
    
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.failed_keys = set()
        self.rate_limited_keys = {}  # key -> timestamp when rate limit expires
        self.usage_counts = {key: 0 for key in api_keys}
        
    def get_next_available_key(self) -> Optional[str]:
        """Gets the next available API key, skipping failed or rate-limited ones."""
        current_time = time.time()
        
        # Clean up expired rate limits
        expired_keys = [key for key, expire_time in self.rate_limited_keys.items() 
                       if current_time > expire_time]
        for key in expired_keys:
            del self.rate_limited_keys[key]
            logger.info(f"API key {key[:8]}... rate limit expired, marking as available")
        
        # Try to find an available key
        attempts = 0
        while attempts < len(self.api_keys):
            key = self.api_keys[self.current_index]
            
            # Skip failed or rate-limited keys
            if (key not in self.failed_keys and 
                key not in self.rate_limited_keys):
                return key
            
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            attempts += 1
            
        
        
        return None
    
    def mark_key_used(self, api_key: str):
        """Marks a key as successfully used and moves to next key."""
        self.usage_counts[api_key] += 1
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        logger.debug(f"API key {api_key[:8]}... used successfully (total uses: {self.usage_counts[api_key]})")
    
    def mark_key_rate_limited(self, api_key: str, retry_after: int = 3600):
        """Marks a key as rate limited with retry time."""
        expire_time = time.time() + retry_after
        self.rate_limited_keys[api_key] = expire_time
        logger.warning(f"API key {api_key[:8]}... rate limited until {time.ctime(expire_time)}")
    
    def mark_key_failed(self, api_key: str):
        """Marks a key as permanently failed."""
        self.failed_keys.add(api_key)
        logger.error(f"API key {api_key[:8]}... marked as failed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Returns usage statistics for all keys."""
        available_keys = len([k for k in self.api_keys 
                            if k not in self.failed_keys and k not in self.rate_limited_keys])
        
        # Add individual key statuses to the stats dict for detailed monitoring
        key_statuses = {}
        for key in self.api_keys:
            if key in self.failed_keys:
                key_statuses[key] = "Failed"
            elif key in self.rate_limited_keys:
                key_statuses[key] = "Rate Limited"
            else:
                key_statuses[key] = "Available"

        return {
            "total_keys": len(self.api_keys),
            "available_keys": available_keys,
            "failed_keys": len(self.failed_keys),
            "rate_limited_keys": len(self.rate_limited_keys),
            "usage_counts": self.usage_counts.copy(),
            "key_statuses": key_statuses
        }


class AIClassifier:
    def __init__(self):
        """Initializes the classifier with API key pool."""
        # Load API keys from Streamlit secrets
        self.api_key_pool = self._initialize_api_key_pool()
        
        # Classification retry settings
        self.max_retries = 3
        self.base_delay = 2  # Base delay between retries in seconds
        self.max_delay = 30  # Maximum delay between retries
        
    def _initialize_api_key_pool(self) -> APIKeyPool:
        """Initialize API key pool from Streamlit secrets."""
        api_keys = []
        
        
        for i in range(1, 17):  
            key_name = f"GOOGLE_API_KEY_{i}"
            api_key = st.secrets.get(key_name)
            if api_key:
                api_keys.append(api_key)
                logger.info(f"Loaded API key {i}: {api_key[:8]}...")
        
        # Fallback to single key if numbered keys don't exist
        if not api_keys:
            main_key = st.secrets.get("GOOGLE_API_KEY")
            if main_key:
                api_keys.append(main_key)
                logger.info(f"Using single API key: {main_key[:8]}...")
        
        if not api_keys:
            logger.error("No Google API keys found in secrets!")
            raise ValueError("No Google API keys configured")
        
        # Shuffle keys to distribute load randomly
        random.shuffle(api_keys)
        
        logger.info(f"Initialized API key pool with {len(api_keys)} keys")
        return APIKeyPool(api_keys)
    
    def _extract_with_google_gemini_retry(self, combined_text: str, company_roles: List[str]) -> Optional[Dict]:
        """Extract using Google's Gemini Pro API with retry logic and key rotation."""
        logger.info("Starting extraction with Google Gemini Pro (with retry logic)...")
        
        for attempt in range(self.max_retries):
            api_key = self.api_key_pool.get_next_available_key()
            
            if not api_key:
                logger.error("No available API keys remaining!")
                return None
            
            try:
                # Configure the API key
                genai.configure(api_key=api_key)
                
                # Craft a prompt for Gemini
                prompt = f"""
                You are an expert HR data extraction system. Your task is to analyze the following text from a job application.
                Extract the information and return ONLY a single, valid JSON object with these exact keys:

                "Name": Full name of applicant
                "Email": Email address
                "Phone": 10-digit mobile number (remove country codes like +91)
                "Education": A brief summary of their educational background
                "JobHistory": Markdown bullet list of jobs including the job title, company, duration, and a 1-2 line summary of their responsibilities or achievements in that role
                "Domain": Their primary role, chosen from these options: {', '.join(company_roles)}

                Text to analyze:
                ---
                {combined_text[:30000]}
                ---

                Return only the raw JSON object. Do not include any other text, explanations, or ```json markers.
                """

                # Set up the model and generate content
                model = genai.GenerativeModel('gemini-2.5-flash-lite')
                response = model.generate_content(prompt)

                # Clean and parse the response
                if response and response.text:
                    result = self._parse_and_clean_response(response.text)
                    if result:
                        # Mark key as successfully used
                        self.api_key_pool.mark_key_used(api_key)
                        logger.info(f"Successfully extracted data using API key {api_key[:8]}...")
                        return result
                    else:
                        logger.warning(f"Failed to parse response from API key {api_key[:8]}...")
                else:
                    logger.warning(f"Empty response from API key {api_key[:8]}...")
                
            except google_exceptions.ResourceExhausted as e:
                logger.warning(f"API key {api_key[:8]}... exceeded quota: {str(e)}")
                # Parse retry-after from error message if available
                retry_after = self._extract_retry_after(str(e))
                self.api_key_pool.mark_key_rate_limited(api_key, retry_after)
                
            except google_exceptions.InvalidArgument as e:
                logger.error(f"Invalid argument error with API key {api_key[:8]}...: {str(e)}")
                self.api_key_pool.mark_key_failed(api_key)
                
            except google_exceptions.Unauthenticated as e:
                logger.error(f"Authentication error with API key {api_key[:8]}...: {str(e)}")
                self.api_key_pool.mark_key_failed(api_key)
                
            except Exception as e:
                logger.error(f"Unexpected error with API key {api_key[:8]}...: {str(e)}")
                # Don't mark as failed for unexpected errors, just try next key
                
            # Calculate delay for next retry (exponential backoff with jitter)
            if attempt < self.max_retries - 1:
                delay = min(60, self.max_delay)
                jitter = random.uniform(0, 0.1 * delay)  # Add up to 10% jitter
                total_delay = delay + jitter
                
                logger.info(f"Retry attempt {attempt + 1} failed, waiting {total_delay:.1f}s before next attempt")
                time.sleep(total_delay)
        
        logger.error("All retry attempts exhausted")
        return None
    
    def _extract_retry_after(self, error_message: str) -> int:
        """Extract retry-after time from error message, default to 1 hour."""
        # Try to parse retry-after time from error message
        # Google API often includes quota reset information
        try:
            # Look for patterns like "Quota exceeded. Try again in 3600 seconds"
            import re
            match = re.search(r'try again in (\d+) seconds?', error_message.lower())
            if match:
                return int(match.group(1))
            
            match = re.search(r'quota.*?(\d+)\s*hour', error_message.lower())
            if match:
                return int(match.group(1)) * 3600
                
            match = re.search(r'quota.*?(\d+)\s*minute', error_message.lower())
            if match:
                return int(match.group(1)) * 60
        except Exception:
            pass
        
        # Default to 1 hour if we can't parse
        return 3600
    
    def _normalize_domain(self, domain_text: str) -> str:
        """Normalizes different variations of a role into a standard name."""
        if not domain_text:
            return "Other"

        domain_lower = domain_text.lower()

        # Define mappings from keywords to a standard role name
        role_map = {
            "DevOps Engineer": ['devops', 'aws cloud engineer'],
            "Full Stack Developer": ['full stack', 'fullstack'],
            "AI/ML Engineer": ['ai/ml', 'machine learning', 'ml engineer'],
            "QA Engineer": ['qa', 'quality assurance', 'testing'],
            "Software Developer": ['software developer', 'software engineer'],
            "Digital Marketing": ['digital marketing', 'ppc'],
            "Content": ["content writing", "content creation", "copywriting"],
            "UI/UX": ["ui/ux", "ui", "ux", "designer"]
        }

        for standard_role, keywords in role_map.items():
            for keyword in keywords:
                if keyword in domain_lower:
                    return standard_role
        
        # If no keyword matches, return the original text capitalized
        return domain_text.title()

    def extract_info(self, email_subject: str, email_body: str, resume_text: str) -> Optional[Dict]:
        """Extract and normalize structured data using AI API with key rotation."""
        try:
            combined_text = (
                f"EMAIL SUBJECT: {email_subject}\n\n"
                f"EMAIL BODY: {email_body}\n\n"
                f"RESUME CONTENT: {resume_text}"
            )

            # Consolidate company roles to a single source of truth
            company_roles = [
                "LLM engineer", "AI/ML Engineer", "SEO", "Full Stack Developer",
                "Project manager", "Content", "Digital Marketing", "QA Engineer",
                "Software Developer", "UI/UX", "App developer", "graphic designer",
                "videographer", "BDE", "HR", "DevOps Engineer"
            ]

            # Try Google Gemini API with retry logic
            result = self._extract_with_google_gemini_retry(combined_text, company_roles)
            
            if result:
                # Normalize the domain from the AI output
                if 'Domain' in result:
                    result['Domain'] = self._normalize_domain(result['Domain'])
                
                logger.info("Successfully extracted applicant information using AI classification")
                return result
            else:
                # Log API key pool statistics for debugging
                stats = self.api_key_pool.get_stats()
                logger.error(f"AI classification completely failed. API Key Pool Stats: {stats}")
                return None
            
        except Exception as e:
            logger.error(f"AI processing failed with exception: {str(e)}", exc_info=True)
            return None

    def _parse_and_clean_response(self, text: str) -> Optional[Dict]:
        """Parse and clean the response from LLM."""
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
                # Clean phone number if present
                if 'Phone' in data and data['Phone']:
                    phone_digits = re.sub(r'\D', '', str(data['Phone']))
                    if len(phone_digits) == 12 and phone_digits.startswith('91'):
                        phone_digits = phone_digits[2:]
                    data['Phone'] = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
                
                return data
            else:
                logger.warning("No JSON found in LLM response")
                return None
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from LLM: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing LLM response: {str(e)}")
            return None

    def get_api_pool_status(self) -> Dict[str, Any]:
        """Get current status of the API key pool for monitoring."""
        return self.api_key_pool.get_stats()


