import streamlit as st
import requests
import re
import json
import time
from utils.logger import logger

class AIClassifier:
    def __init__(self):
        # Using Hugging Face's free API with a powerful model
        self.api_key = st.secrets.get("HUGGINGFACE_API_KEY", "")
        
        # Using Mistral-7B-Instruct - excellent for structured extraction tasks
        # Alternative models you can try:
        # - "microsoft/DialoGPT-large" 
        # - "HuggingFaceH4/zephyr-7b-beta"
        # - "mistralai/Mixtral-8x7B-Instruct-v0.1" (if you need more power)
        # self.model = "mistralai/Mistral-7B-Instruct-v0.1"
        self.model = "HuggingFaceH4/zephyr-7b-beta"
        
        # Fallback to local/offline model if HF API fails
        self.use_local_fallback = st.secrets.get("USE_LOCAL_FALLBACK", False)
        
        self.api_url = f"https://api-inference.huggingface.co/models/{self.model}"
        self.headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def extract_info(self, email_subject, email_body, resume_text):
        """Extract structured data using Hugging Face's free API or local model."""
        try:
            combined_text = (
                f"EMAIL SUBJECT: {email_subject}\n\n"
                f"EMAIL BODY: {email_body}\n\n"
                f"RESUME CONTENT: {resume_text}"
            )

            company_roles = [
                "LLM engineer", "AI/ML engineer", "SEO", "Full Stack Developer",
                "Project manager", "Content", "digital marketing", "QA engineer",
                "software developer", "UI/UX", "App developer", "graphic designer",
                "videographer", "BDE", "HR", "PPC"
            ]

            # Try Hugging Face API first
            if self.api_key:
                result = self._extract_with_huggingface(combined_text, company_roles)
                if result:
                    return result
                logger.warning("Hugging Face API failed, trying local fallback...")
            
            # Fallback to rule-based extraction if API fails
            return self._extract_with_rules(email_subject, email_body, resume_text, company_roles)
            
        except Exception as e:
            logger.error(f"AI processing failed: {str(e)}", exc_info=True)
            # Always fallback to rule-based extraction
            return self._extract_with_rules(email_subject, email_body, resume_text, company_roles)

    def _extract_with_huggingface(self, combined_text, company_roles):
        """Extract using Hugging Face's free inference API."""
        try:
            
            # Crafted prompt for better JSON extraction
            # New prompt optimized for Zephyr-style models
            prompt = f"""<|system|>
            You are an expert HR data extraction system. Your task is to extract information from the provided text and return ONLY a single, valid JSON object with the specified keys. Do not include any other text, explanations, or conversational markers. The keys are: "Name", "Email", "Phone", "Education", "JobHistory", "Domain".</s>
            <|user|>
            Please analyze the following text and provide the JSON object.

            **Text to analyze:**
            {combined_text[:2000]}</s>
            <|assistant|>
            """  

Return only the JSON object, no other text: [/INST]"""

            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": 1000,
                    "temperature": 0.1,
                    "do_sample": True,
                    "return_full_text": False
                }
            }

            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=30)
            
            if response.status_code == 503:
                # Model is loading, wait and retry
                logger.info("Model loading, waiting 20 seconds...")
                time.sleep(20)
                response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    generated_text = result[0].get('generated_text', '')
                    return self._parse_and_clean_response(generated_text)
                else:
                    logger.warning(f"Unexpected HF API response format: {result}")
            else:
                logger.warning(f"HF API error {response.status_code}: {response.text}")
                
        except requests.exceptions.Timeout:
            logger.warning("Hugging Face API request timed out")
        except Exception as e:
            logger.warning(f"Hugging Face API error: {str(e)}")
        
        return None

    def _extract_with_rules(self, email_subject, email_body, resume_text, company_roles):
        """Advanced rule-based extraction as fallback - surprisingly effective!"""
        logger.info("Using rule-based extraction fallback")
        
        full_text = f"{email_subject} {email_body} {resume_text}".lower()
        
        # Extract name (multiple strategies)
        name = self._extract_name(email_body, resume_text)
        
        # Extract email
        email = self._extract_email(email_body, resume_text)
        
        # Extract phone
        phone = self._extract_phone(email_body, resume_text)
        
        # Extract education
        education = self._extract_education(resume_text)
        
        # Extract job history
        job_history = self._extract_job_history(resume_text)
        
        # Extract domain
        domain = self._extract_domain(full_text, company_roles)
        
        return {
            "Name": name,
            "Email": email,
            "Phone": phone,
            "Education": education,
            "JobHistory": job_history,
            "Domain": domain
        }

    def _extract_name(self, email_body, resume_text):
        """Extract name using multiple strategies."""
        # Strategy 1: Look for "My name is", "I am", etc.
        patterns = [
            r"my name is ([A-Za-z\s]+)",
            r"i am ([A-Za-z\s]+)",
            r"this is ([A-Za-z\s]+)",
            r"dear sir/madam,?\s*([A-Za-z\s]+)",
            r"^([A-Z][a-z]+ [A-Z][a-z]+)",  # First line capitalized name
        ]
        
        text = f"{email_body} {resume_text}"
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Validate it's a proper name (2-4 words, each capitalized)
                words = name.split()
                if 2 <= len(words) <= 4 and all(w.replace("'", "").isalpha() for w in words):
                    return ' '.join(word.capitalize() for word in words)
        
        # Strategy 2: Extract from resume header (first few lines)
        lines = resume_text.split('\n')[:5]
        for line in lines:
            line = line.strip()
            # Look for lines that look like names
            if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+', line) and len(line.split()) <= 4:
                return line
        
        return "Unknown Applicant"

    def _extract_email(self, email_body, resume_text):
        """Extract email address."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        text = f"{email_body} {resume_text}"
        
        matches = re.findall(email_pattern, text)
        if matches:
            # Return the first valid email that's not a generic one
            for email in matches:
                if not any(generic in email.lower() for generic in ['noreply', 'admin', 'support']):
                    return email
        return ""

    def _extract_phone(self, email_body, resume_text):
        """Extract and clean phone number."""
        text = f"{email_body} {resume_text}"
        
        # Multiple phone patterns
        patterns = [
            r'\+?91[-\s]?[6-9]\d{9}',  # Indian format
            r'\b[6-9]\d{9}\b',         # 10 digit starting with 6-9
            r'\+?91\s?[6-9]\d{4}\s?\d{5}',  # Spaced format
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # Clean the phone number
                phone_digits = re.sub(r'\D', '', match)
                if phone_digits.startswith('91') and len(phone_digits) == 12:
                    phone_digits = phone_digits[2:]
                if len(phone_digits) == 10 and phone_digits[0] in '6789':
                    return phone_digits
        
        return ""

    def _extract_education(self, resume_text):
        """Extract education information."""
        education_keywords = [
            'education', 'qualification', 'academic', 'degree', 'university', 
            'college', 'school', 'b.tech', 'btech', 'm.tech', 'mtech', 'mba', 
            'bca', 'mca', 'b.sc', 'bsc', 'm.sc', 'msc', 'bachelor', 'master'
        ]
        
        lines = resume_text.split('\n')
        education_lines = []
        in_education_section = False
        
        for line in lines:
            line_lower = line.lower().strip()
            
            # Start of education section
            if any(keyword in line_lower for keyword in education_keywords[:6]) and len(line.strip()) < 50:
                in_education_section = True
                continue
            
            # End of education section (new section starts)
            if in_education_section and any(end_word in line_lower for end_word in ['experience', 'work', 'skills', 'projects']):
                break
            
            # Collect education lines
            if in_education_section and line.strip():
                education_lines.append(line.strip())
            
            # Also catch degree mentions anywhere
            if any(degree in line_lower for degree in education_keywords[6:]):
                education_lines.append(line.strip())
        
        # Clean and format
        education_text = '. '.join(education_lines[:5])  # Limit to first 5 relevant lines
        return education_text if education_text else "Not specified"

    def _extract_job_history(self, resume_text):
        """Extract job history in markdown format."""
        lines = resume_text.split('\n')
        work_lines = []
        in_work_section = False
        
        for line in lines:
            line_lower = line.lower().strip()
            
            # Start of work section
            if any(keyword in line_lower for keyword in ['experience', 'work', 'employment', 'career']):
                in_work_section = True
                continue
            
            # End of work section
            if in_work_section and any(end_word in line_lower for end_word in ['education', 'skills', 'projects', 'achievements']):
                break
            
            # Collect work lines
            if in_work_section and line.strip():
                work_lines.append(line.strip())
        
        # Process into markdown bullets
        if not work_lines:
            return "No work experience specified"
        
        # Simple formatting - take first few meaningful lines
        formatted_jobs = []
        for line in work_lines[:10]:  # Limit lines
            if len(line) > 20:  # Meaningful content
                formatted_jobs.append(f"- {line}")
        
        return '\n'.join(formatted_jobs) if formatted_jobs else "No work experience specified"

    def _extract_domain(self, full_text, company_roles):
        """Extract domain/role based on keyword matching."""
        # Create scoring system
        role_scores = {role: 0 for role in company_roles}
        
        # Define keywords for each role
        role_keywords = {
            "LLM engineer": ["llm", "large language model", "gpt", "bert", "transformer", "nlp", "language model"],
            "AI/ML engineer": ["machine learning", "artificial intelligence", "deep learning", "neural network", "tensorflow", "pytorch", "data science"],
            "SEO": ["seo", "search engine optimization", "google analytics", "keyword research", "organic traffic"],
            "Full Stack Developer": ["full stack", "frontend", "backend", "react", "node", "javascript", "python", "java"],
            "Project manager": ["project manager", "scrum", "agile", "pmp", "project management", "coordination"],
            "Content": ["content writing", "content creation", "copywriting", "blog", "content marketing"],
            "digital marketing": ["digital marketing", "social media", "facebook ads", "google ads", "marketing"],
            "QA engineer": ["qa", "quality assurance", "testing", "automation testing", "selenium", "manual testing"],
            "software developer": ["software developer", "programming", "coding", "development", "software engineer"],
            "UI/UX": ["ui", "ux", "user interface", "user experience", "figma", "design", "wireframe"],
            "App developer": ["mobile app", "android", "ios", "flutter", "react native", "app development"],
            "graphic designer": ["graphic design", "photoshop", "illustrator", "logo design", "visual design"],
            "videographer": ["video editing", "videography", "after effects", "premiere pro", "video production"],
            "BDE": ["business development", "sales", "lead generation", "client acquisition", "bde"],
            "HR": ["human resources", "recruitment", "hiring", "hr", "talent acquisition"],
            "PPC": ["ppc", "pay per click", "google ads", "facebook ads", "advertising"]
        }
        
        # Score each role
        for role, keywords in role_keywords.items():
            for keyword in keywords:
                if keyword in full_text:
                    role_scores[role] += 1
        
        # Return the highest scoring role
        if any(score > 0 for score in role_scores.values()):
            return max(role_scores, key=role_scores.get)
        else:
            return "Other"

    def _parse_and_clean_response(self, text):
        
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
                # Post-processing for phone number
                if 'Phone' in data and data['Phone']:
                    phone_digits = re.sub(r'\D', '', str(data['Phone']))
                    if len(phone_digits) == 12 and phone_digits.startswith('91'):
                        phone_digits = phone_digits[2:]
                    data['Phone'] = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
                
                return data
            else:
                logger.warning("No JSON found in LLM response, falling back to rule-based extraction")
                return None
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from LLM: {str(e)}")
            return None
