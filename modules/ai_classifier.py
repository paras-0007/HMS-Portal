import requests
import json
from utils.logger import logger

class AIClassifier:
    def __init__(self):
        # The IP address of your GPU server.
        self.api_endpoint = "http://43.204.254.233:8503/extract"

    def _normalize_domain(self, domain_text):
        """
        Normalizes different variations of a role into a standard name.
        This function is restored to improve data consistency.
        """
        if not domain_text:
            return "Other"

        domain_lower = domain_text.lower()
        role_map = {
            "DevOps Engineer": ['devops', 'aws cloud engineer'],
            "Full Stack Developer": ['full stack', 'fullstack'],
            "AI/ML Engineer": ['ai/ml', 'machine learning', 'ml engineer', 'llm engineer'],
            "QA Engineer": ['qa', 'quality assurance', 'testing'],
            "Software Developer": ['software developer', 'software engineer'],
            "Digital Marketing": ['digital marketing', 'ppc', 'seo'],
            "Content": ["content writing", "content creation", "copywriting"],
            "UI/UX": ["ui/ux", "ui", "ux", "designer", "graphic designer"],
            "Project Manager": ["project manager", "project management"],
            "Business Development": ["bde", "business development", "sales"],
            "HR": ["hr", "human resources", "recruitment"]
        }

        for standard_role, keywords in role_map.items():
            for keyword in keywords:
                if keyword in domain_lower:
                    return standard_role
        
        return domain_text.title()

    def extract_info(self, email_subject, email_body, resume_text):
        """
        Extracts structured data by calling the self-hosted LLM API.
        If the server is down, it raises a ConnectionError to halt the process.
        """
        logger.info(f"Sending text to self-hosted LLM at: {self.api_endpoint}")

        combined_text = (
            f"EMAIL SUBJECT: {email_subject}\n\n"
            f"EMAIL BODY: {email_body}\n\n"
            f"RESUME CONTENT: {resume_text}"
        )

        company_roles = [
            "LLM engineer", "AI/ML Engineer", "SEO", "Full Stack Developer",
            "Project manager", "Content", "Digital Marketing", "QA Engineer",
            "Software Developer", "UI/UX", "App developer", "graphic designer",
            "videographer", "BDE", "HR", "DevOps Engineer", "Other"
        ]
        
        payload = {
            "text": combined_text,
            "roles": company_roles
        }

        try:
            response = requests.post(self.api_endpoint, json=payload, timeout=120)
            response.raise_for_status()
            
            extracted_data = response.json()
            logger.info(f"Successfully received data from LLM: {extracted_data.get('Name')}")

            # --- ADDED: Normalize the domain after successful extraction ---
            if 'Domain' in extracted_data:
                extracted_data['Domain'] = self._normalize_domain(extracted_data['Domain'])

            return extracted_data

        except requests.exceptions.RequestException as e:
            logger.error(f"Could not connect to the LLM server: {e}", exc_info=True)
            # --- MODIFIED: Raise an error instead of returning a failed dictionary ---
            raise ConnectionError("LLM server is not reachable. Please ensure it's running and the port is open.")
        
        except Exception as e:
            logger.error(f"An unexpected error occurred during AI classification: {e}", exc_info=True)
            # Also raise an error for other unexpected issues
            raise


# import streamlit as st
# import requests
# import re
# import json
# import time
# from typing import Dict, Optional, List, Any
# from utils.logger import logger
# from collections import deque # MODIFIED: Imported deque for efficient timestamp tracking

# class AIClassifier:
#     def __init__(self):
#         """Initialize the classifier with Groq LLM backend support."""
#         self.company_roles = [
#             "LLM Engineer", "AI/ML Engineer", "SEO", "Full Stack Developer",
#             "Project Manager", "Content", "Digital Marketing", "QA Engineer",
#             "Software Developer", "UI/UX", "App Developer", "Graphic Designer",
#             "Videographer", "BDE", "HR", "DevOps Engineer"
#         ]
        
#         self.llm_config = self._load_llm_config()
        
#         # --- NEW: Rate Limiting Attributes ---
#         # Set a safe limit of 25 requests per 60 seconds to avoid edge cases.
#         self.rate_limit_requests = 25
#         self.rate_limit_period = 60  # seconds
#         # Use a deque to store the timestamps of recent requests.
#         self.request_timestamps = deque()
#         # --- END NEW ---
        
#     def _load_llm_config(self) -> Dict[str, Any]:
#         """Load Groq LLM configuration from Streamlit secrets."""
#         config = {
#             'groq': {
#                 'api_key': st.secrets.get('GROQ_API_KEY'),
#                 'model': 'llama-3.1-8b-instant',
#                 'base_url': 'https://api.groq.com/openai/v1'
#             }
#         }
#         return config
        
#     # --- NEW: Rate Limiting Method ---
#     def _wait_for_rate_limit(self):
#         """
#         Checks if a new request is allowed. If the rate limit has been reached,
#         it pauses execution until the oldest request expires from the 60-second window.
#         """
#         while True:
#             current_time = time.monotonic()
#             # Remove any timestamps from the left of the deque that are older than the defined period.
#             while self.request_timestamps and self.request_timestamps[0] <= current_time - self.rate_limit_period:
#                 self.request_timestamps.popleft()

#             # If the number of requests in the current window is less than our limit, we can proceed.
#             if len(self.request_timestamps) < self.rate_limit_requests:
#                 break
            
#             # Otherwise, we must wait. The wait time is calculated based on when the
#             # oldest request in the queue will expire.
#             time_to_wait = self.request_timestamps[0] + self.rate_limit_period - current_time
#             logger.warning(f"Groq RPM limit reached. Waiting for {time_to_wait:.2f} seconds to avoid exceeding the limit.")
#             time.sleep(time_to_wait)
#     # --- END NEW ---

#     def _create_extraction_prompt(self, combined_text: str) -> str:
#         """Create an optimized prompt for data extraction."""
#         return f"""You are an expert HR data extraction system. Extract information from the job application text and return ONLY a valid JSON object.

# IMPORTANT: Return only raw JSON, no markdown, no explanations, no ```json markers.

# Required JSON structure:
# {{
#     "Name": "Full name of applicant",
#     "Email": "Email address",  
#     "Phone": "10-digit mobile number (remove country codes like +91)",
#     "Education": "Brief summary of educational background",
#     "JobHistory": "Markdown bullet list of jobs with title, company, duration, and 1-2 line summary",
#     "Domain": "Primary role from these options: {', '.join(self.company_roles)}"
# }}

# Text to analyze:
# {combined_text[:25000]}

# JSON Response:"""

#     def extract_info(self, email_subject: str, email_body: str, resume_text: str) -> Optional[Dict[str, Any]]:
#         """Extract structured data using the Groq LLM, respecting API rate limits."""
#         try:
#             if not self.llm_config['groq'].get('api_key') or self.llm_config['groq']['api_key'] == "your_api_key_here":
#                 logger.error("Groq API key is not configured in Streamlit secrets.")
#                 return None
            
#             # --- MODIFIED: Call the rate limiter before every API request ---
#             self._wait_for_rate_limit()
#             # --- END MODIFIED ---

#             combined_text = (
#                 f"EMAIL SUBJECT: {email_subject}\n\n"
#                 f"EMAIL BODY: {email_body}\n\n"
#                 f"RESUME CONTENT: {resume_text}"
#             )
            
#             logger.info("Attempting extraction with Groq")
#             result = self._extract_with_groq(combined_text)
            
#             if result and self._validate_extraction(result):
#                 logger.info("Successfully extracted data using Groq")
#                 return self._post_process_result(result)
#             else:
#                 logger.warning("Groq extraction failed or returned invalid data")
#                 return None
            
#         except Exception as e:
#             logger.error(f"AI processing failed: {str(e)}", exc_info=True)
#             return None

#     def _extract_with_groq(self, combined_text: str) -> Optional[Dict[str, Any]]:
#         """Extract using the Groq API."""
#         config = self.llm_config['groq']
        
#         headers = {
#             "Authorization": f"Bearer {config['api_key']}",
#             "Content-Type": "application/json"
#         }
        
#         payload = {
#             "model": config['model'],
#             "messages": [{"role": "user", "content": self._create_extraction_prompt(combined_text)}],
#             "temperature": 0.1,
#             "max_tokens": 1000
#         }
        
#         try:
#             # --- MODIFIED: Add a timestamp just before the request is made ---
#             self.request_timestamps.append(time.monotonic())
#             # --- END MODIFIED ---
#             response = requests.post(
#                 f"{config['base_url']}/chat/completions",
#                 headers=headers,
#                 json=payload,
#                 timeout=30
#             )
#             response.raise_for_status()
            
#             result = response.json()
#             content = result['choices'][0]['message']['content']
#             return self._parse_json_response(content)
#         except Exception as e:
#             logger.error(f"Error with Groq backend: {str(e)}")
#             # --- MODIFIED: If the request fails, remove the timestamp we just added ---
#             if self.request_timestamps:
#                 self.request_timestamps.pop()
#             # --- END MODIFIED ---
#             return None


#     def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
#         """Safely parse JSON from an LLM response text."""
#         try:
#             text = re.sub(r'```json\s*', '', text)
#             text = re.sub(r'```\s*', '', text)
            
#             json_match = re.search(r'\{.*\}', text, re.DOTALL)
#             if json_match:
#                 json_str = json_match.group(0)
#                 return json.loads(json_str)
#             else:
#                 logger.warning("No JSON found in LLM response")
#                 return None
                
#         except json.JSONDecodeError as e:
#             logger.error(f"Failed to parse JSON: {str(e)}")
#             return None

#     def _validate_extraction(self, data: Dict[str, Any]) -> bool:
#         """Validate the essential fields of the extracted data."""
#         if not isinstance(data, dict):
#             return False
            
#         required_fields = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Domain']
#         for field in required_fields:
#             if field not in data:
#                 logger.warning(f"Missing required field: {field}")
#                 return False
                
#         if not data.get('Name') or not data['Name'].strip():
#             logger.warning("Name field is empty")
#             return False
            
#         return True

#     def _post_process_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
#         """Post-process and normalize the extracted data."""
#         if data.get('Phone'):
#             phone_digits = re.sub(r'\D', '', str(data['Phone']))
#             if len(phone_digits) == 12 and phone_digits.startswith('91'):
#                 phone_digits = phone_digits[2:]
#             data['Phone'] = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
        
#         if data.get('Domain'):
#             data['Domain'] = self._normalize_domain(data['Domain'])
        
#         defaults = {
#             'Name': 'Unknown Applicant', 'Email': '', 'Phone': '',
#             'Education': 'Not specified', 'JobHistory': 'No work experience specified',
#             'Domain': 'Other'
#         }
        
#         for key, default_value in defaults.items():
#             if not data.get(key):
#                 data[key] = default_value
                
#         return data

#     def _normalize_domain(self, domain_text: str) -> str:
#         """Normalize the extracted domain to align with standard company roles."""
#         if not domain_text:
#             return "Other"

#         domain_lower = domain_text.lower()

#         role_map = {
#             "DevOps Engineer": ['devops', 'aws cloud engineer', 'cloud engineer'],
#             "Full Stack Developer": ['full stack', 'fullstack', 'full-stack'],
#             "AI/ML Engineer": ['ai/ml', 'machine learning', 'ml engineer', 'ai engineer', 'data scientist'],
#             "QA Engineer": ['qa', 'quality assurance', 'testing', 'tester'],
#             "Software Developer": ['software developer', 'software engineer', 'backend developer', 'frontend developer'],
#             "Digital Marketing": ['digital marketing', 'ppc', 'marketing', 'social media marketing'],
#             "Content": ["content writing", "content creation", "copywriting", "content writer"],
#             "UI/UX": ["ui/ux", "ui", "ux", "designer", "product designer"],
#             "App Developer": ["mobile developer", "android developer", "ios developer", "app developer"],
#             "Graphic Designer": ["graphic designer", "visual designer", "graphic artist"],
#             "Project Manager": ["project manager", "product manager", "scrum master"],
#             "LLM Engineer": ["llm engineer", "nlp engineer", "language model"],
#             "HR": ["hr", "human resources", "talent acquisition", "recruiter"],
#             "BDE": ["business development", "bde", "sales", "business analyst"],
#             "SEO": ["seo", "search engine optimization", "seo specialist"]
#         }

#         for standard_role, keywords in role_map.items():
#             if any(keyword in domain_lower for keyword in keywords):
#                 return standard_role
        
#         for role in self.company_roles:
#             if role.lower() in domain_lower or domain_lower in role.lower():
#                 return role
        
#         return domain_text.title()
