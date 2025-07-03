import streamlit as st
import requests
import re
import json
import time
from utils.logger import logger

class AIClassifier:
    def __init__(self):
        """Initializes the classifier with Hugging Face configuration."""
        self.hf_api_url = "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-7B-Instruct"
        self.max_retries = 3
        self.retry_delay = 2  # seconds

    def _extract_with_huggingface_multiple_models(self, combined_text, company_roles):
        """Extract using multiple Hugging Face models with fallback."""
        logger.info("Attempting extraction with Hugging Face models...")
        
        # List of models to try in order of preference
        models_to_try = [
            {
                "name": "microsoft/DialoGPT-medium",
                "url": "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium",
                "fast": True
            },
            {
                "name": "google/flan-t5-base", 
                "url": "https://api-inference.huggingface.co/models/google/flan-t5-base",
                "fast": True
            },
            {
                "name": "meta-llama/Llama-2-7b-chat-hf",
                "url": "https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b-chat-hf",
                "fast": False
            }
        ]
        
        try:
            hf_token = st.secrets.get("HUGGINGFACE_API_TOKEN")
            if not hf_token:
                logger.error("Hugging Face API token not found in secrets.")
                return None

            headers = {
                "Authorization": f"Bearer {hf_token}",
                "Content-Type": "application/json"
            }

            # Try each model
            for model_info in models_to_try:
                logger.info(f"Trying model: {model_info['name']}")
                
                # Simple extraction prompt that works with most models
                prompt = f"""Extract information from this job application and return only JSON:

{{"Name": "full name", "Email": "email", "Phone": "phone", "Education": "education", "JobHistory": "job history", "Domain": "role"}}

Text: {combined_text[:2000]}

JSON:"""

                payload = {
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": 400,
                        "temperature": 0.1,
                        "do_sample": False,
                        "return_full_text": False
                    }
                }

                try:
                    timeout = 15 if model_info["fast"] else 25
                    response = requests.post(
                        model_info["url"],
                        headers=headers,
                        json=payload,
                        timeout=timeout
                    )
                    
                    if response.status_code == 503:
                        logger.info(f"Model {model_info['name']} is loading, trying next model...")
                        continue
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        if isinstance(result, list) and len(result) > 0:
                            generated_text = result[0].get('generated_text', '')
                        else:
                            generated_text = result.get('generated_text', '')
                        
                        if generated_text:
                            parsed_result = self._parse_and_clean_response(generated_text)
                            if parsed_result and parsed_result.get('Name'):
                                logger.info(f"Success with model: {model_info['name']}")
                                return parsed_result
                    
                    logger.warning(f"Model {model_info['name']} failed with status: {response.status_code}")
                    
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Model {model_info['name']} failed: {str(e)}")
                    continue

            return None

        except Exception as e:
            logger.error(f"All Hugging Face models failed: {str(e)}", exc_info=True)
            return None

    def _extract_with_groq_api(self, combined_text, company_roles):
        """Extract using Groq API as a fast alternative."""
        logger.info("Attempting extraction with Groq API...")
        
        try:
            groq_token = st.secrets.get("GROQ_API_KEY")
            if not groq_token:
                logger.info("Groq API key not found, skipping...")
                return None

            headers = {
                "Authorization": f"Bearer {groq_token}",
                "Content-Type": "application/json"
            }

            prompt = f"""Extract information from this job application and return ONLY a valid JSON object:

{{"Name": "full name", "Email": "email", "Phone": "10-digit phone", "Education": "education", "JobHistory": "job history", "Domain": "role from: {', '.join(company_roles)}"}}

Application: {combined_text[:3000]}

JSON:"""

            payload = {
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "model": "llama3-8b-8192",
                "temperature": 0.1,
                "max_tokens": 500
            }

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                return self._parse_and_clean_response(content)
            else:
                logger.warning(f"Groq API failed with status: {response.status_code}")
                return None

        except Exception as e:
            logger.info(f"Groq API not available: {str(e)}")
            return None

    def _extract_with_ollama_fallback(self, combined_text, company_roles):
        """Fallback extraction using Ollama API (if available)."""
        logger.info("Attempting extraction with Ollama fallback...")
        
        try:
            # Check if Ollama is available (for local development)
            ollama_url = "http://localhost:11434/api/generate"
            
            prompt = f"""Extract information from this job application and return ONLY a valid JSON object:

{{
    "Name": "Full name",
    "Email": "Email address",
    "Phone": "10-digit phone number",
    "Education": "Educational background",
    "JobHistory": "Job history in markdown format",
    "Domain": "Role from: {', '.join(company_roles)}"
}}

Application text:
{combined_text[:3000]}

JSON:"""

            payload = {
                "model": "qwen2.5:7b-instruct",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 512
                }
            }

            response = requests.post(ollama_url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                generated_text = result.get('response', '')
                if generated_text:
                    return self._parse_and_clean_response(generated_text)
            
            return None

        except Exception as e:
            logger.info(f"Ollama fallback not available: {str(e)}")
            return None

    def _normalize_domain(self, domain_text):
        """Normalizes different variations of a role into a standard name."""
        if not domain_text:
            return "Other"

        domain_lower = domain_text.lower()

        # Enhanced role mapping
        role_map = {
            "DevOps Engineer": ['devops', 'aws cloud engineer', 'cloud engineer', 'infrastructure'],
            "Full Stack Developer": ['full stack', 'fullstack', 'full-stack'],
            "AI/ML Engineer": ['ai/ml', 'machine learning', 'ml engineer', 'data scientist', 'ai engineer'],
            "QA Engineer": ['qa', 'quality assurance', 'testing', 'test engineer', 'sdet'],
            "Software Developer": ['software developer', 'software engineer', 'backend developer', 'frontend developer'],
            "Digital Marketing": ['digital marketing', 'ppc', 'social media marketing', 'marketing specialist'],
            "Content": ["content writing", "content creation", "copywriting", "content marketing"],
            "UI/UX": ["ui/ux", "ui", "ux", "designer", "user experience", "user interface"],
            "App developer": ["mobile developer", "android developer", "ios developer", "flutter developer"],
            "Project manager": ["project manager", "program manager", "scrum master", "product manager"],
            "SEO": ["seo", "search engine optimization", "seo specialist"],
            "HR": ["human resources", "hr", "talent acquisition", "recruiter"],
            "BDE": ["business development", "sales", "bde", "business analyst"]
        }

        for standard_role, keywords in role_map.items():
            for keyword in keywords:
                if keyword in domain_lower:
                    return standard_role
        
        return domain_text.title() if domain_text else "Other"

    def extract_info(self, email_subject, email_body, resume_text):
        """Extract and normalize structured data using Hugging Face API."""
        try:
            combined_text = (
                f"EMAIL SUBJECT: {email_subject}\n\n"
                f"EMAIL BODY: {email_body}\n\n"
                f"RESUME CONTENT: {resume_text}"
            )

            # Updated company roles list
            company_roles = [
                "LLM engineer", "AI/ML Engineer", "SEO", "Full Stack Developer",
                "Project manager", "Content", "Digital Marketing", "QA Engineer",
                "Software Developer", "UI/UX", "App developer", "Graphic designer",
                "Videographer", "BDE", "HR", "DevOps Engineer", "Data Scientist"
            ]

            # Try Groq API first (fastest)
            result = self._extract_with_groq_api(combined_text, company_roles)
            if result:
                if 'Domain' in result:
                    result['Domain'] = self._normalize_domain(result['Domain'])
                return result
            
            # Try Hugging Face models
            logger.warning("Groq API failed, trying Hugging Face models...")
            result = self._extract_with_huggingface_multiple_models(combined_text, company_roles)
            if result:
                if 'Domain' in result:
                    result['Domain'] = self._normalize_domain(result['Domain'])
                return result
            
            # Try Ollama fallback (for local development)
            logger.warning("Hugging Face API failed, trying Ollama fallback...")
            result = self._extract_with_ollama_fallback(combined_text, company_roles)
            if result:
                if 'Domain' in result:
                    result['Domain'] = self._normalize_domain(result['Domain'])
                return result
            
            # If all AI methods fail, return minimal structured data
            logger.error("All AI extraction methods failed")
            return {
                "Name": "Unknown Applicant",
                "Email": "",
                "Phone": "",
                "Education": "Not specified",
                "JobHistory": "Not specified",
                "Domain": "Other"
            }
            
        except Exception as e:
            logger.error(f"AI processing failed: {str(e)}", exc_info=True)
            return {
                "Name": "Unknown Applicant",
                "Email": "",
                "Phone": "",
                "Education": "Not specified", 
                "JobHistory": "Not specified",
                "Domain": "Other"
            }

    def _parse_and_clean_response(self, text):
        """Parse and clean the response from LLM."""
        try:
            # Remove any markdown formatting
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            
            # Find JSON object in the response
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
                # Clean and validate phone number
                if 'Phone' in data and data['Phone']:
                    phone_digits = re.sub(r'\D', '', str(data['Phone']))
                    if len(phone_digits) == 12 and phone_digits.startswith('91'):
                        phone_digits = phone_digits[2:]
                    data['Phone'] = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
                
                # Ensure all required fields exist
                required_fields = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Domain']
                for field in required_fields:
                    if field not in data:
                        data[field] = ""
                
                return data
            else:
                logger.warning("No valid JSON found in LLM response")
                return None
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from LLM: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error parsing LLM response: {str(e)}")
            return None
# import streamlit as st
# import requests
# import re
# import json
# import time
# from typing import Dict, Optional, List, Any
# from utils.logger import logger

# class AIClassifier:
#     def __init__(self):
#         """Initialize the classifier with Groq LLM backend support."""
#         self.company_roles = [
#             "LLM Engineer", "AI/ML Engineer", "SEO", "Full Stack Developer",
#             "Project Manager", "Content", "Digital Marketing", "QA Engineer",
#             "Software Developer", "UI/UX", "App Developer", "Graphic Designer",
#             "Videographer", "BDE", "HR", "DevOps Engineer"
#         ]
        
#         # Configuration for the Groq LLM backend
#         self.llm_config = self._load_llm_config()
        
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
#         """Extract structured data using the Groq LLM."""
#         try:
#             # Check if Groq API key is configured
#             if not self.llm_config['groq'].get('api_key') or self.llm_config['groq']['api_key'] == "your_api_key_here":
#                 logger.error("Groq API key is not configured in Streamlit secrets.")
#                 return None

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
#             return None


#     def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
#         """Safely parse JSON from an LLM response text."""
#         try:
#             # Clean up potential markdown formatting
#             text = re.sub(r'```json\s*', '', text)
#             text = re.sub(r'```\s*', '', text)
            
#             # Find the JSON object within the text
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
            
#         # Check for the presence of all required fields
#         required_fields = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Domain']
#         for field in required_fields:
#             if field not in data:
#                 logger.warning(f"Missing required field: {field}")
#                 return False
                
#         # Validate that the Name field is not empty
#         if not data.get('Name') or not data['Name'].strip():
#             logger.warning("Name field is empty")
#             return False
            
#         return True

#     def _post_process_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
#         """Post-process and normalize the extracted data."""
#         # Clean and format the phone number
#         if data.get('Phone'):
#             phone_digits = re.sub(r'\D', '', str(data['Phone']))
#             if len(phone_digits) == 12 and phone_digits.startswith('91'):
#                 phone_digits = phone_digits[2:]
#             data['Phone'] = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
        
#         # Normalize the extracted domain
#         if data.get('Domain'):
#             data['Domain'] = self._normalize_domain(data['Domain'])
        
#         # Ensure all fields have default values if they are empty
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

#         # Define mappings from keywords to standard role names
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
        
#         # Fallback to check if the text is close to any company roles
#         for role in self.company_roles:
#             if role.lower() in domain_lower or domain_lower in role.lower():
#                 return role
        
#         return domain_text.title()
