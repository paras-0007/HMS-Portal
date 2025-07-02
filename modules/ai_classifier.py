import streamlit as st
import requests
import re
import json
import time
from utils.logger import logger
import google.generativeai as genai

class AIClassifier:
    def __init__(self):
        """Initializes the classifier. Configuration is now handled within extraction methods."""
        pass

    def _extract_with_google_gemini(self, combined_text, company_roles):
        """Extract using Google's Gemini Pro API."""
        logger.info("Attempting extraction with Google Gemini Pro...")
        try:
            # Configure the API key from Streamlit secrets
            api_key = st.secrets.get("GOOGLE_API_KEY")
            if not api_key:
                logger.error("Google API Key not found in secrets.")
                return None
            genai.configure(api_key=api_key)

            # Craft a prompt for Gemini
            prompt = f"""
            You are an expert HR data extraction system. Your task is to analyze the following text from a job application.
            Extract the information and return ONLY a single, valid JSON object with these exact keys:

            "Name": Full name of applicant
            "Email": Email address
            "Phone": 10-digit mobile number (remove country codes like +91)
            "Education": A brief summary of their educational background
            "JobHistory": A markdown bullet list of their recent jobs
            "Domain": Their primary role, chosen from these options: {', '.join(company_roles)}

            Text to analyze:
            ---
            {combined_text[:30000]}
            ---

            Return only the raw JSON object. Do not include any other text, explanations, or ```json markers.
            """

            # Set up the model and generate content
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = model.generate_content(prompt)

            # Clean and parse the response
            if response and response.text:
                return self._parse_and_clean_response(response.text)
            else:
                logger.warning("Google Gemini API returned an empty response.")
                return None

        except Exception as e:
            logger.error(f"An error occurred with the Google Gemini API: {str(e)}", exc_info=True)
            return None

    def extract_info(self, email_subject, email_body, resume_text):
        """Extract structured data using a primary AI API or rule-based fallback."""
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

            # Try Google Gemini API first
            result = self._extract_with_google_gemini(combined_text, company_roles)
            if result:
                return result
            
            logger.warning("Google Gemini API failed, trying rule-based fallback...")
            # Fallback to rule-based extraction
            return self._extract_with_rules(email_subject, email_body, resume_text, company_roles)
            
        except Exception as e:
            logger.error(f"AI processing failed: {str(e)}", exc_info=True)
            # Always fallback to rule-based extraction
            return self._extract_with_rules(email_subject, email_body, resume_text, company_roles)

    def _extract_with_rules(self, email_subject, email_body, resume_text, company_roles):
        """Advanced rule-based extraction as fallback."""
        logger.info("Using rule-based extraction fallback")
        
        full_text = f"{email_subject} {email_body} {resume_text}".lower()
        
        name = self._extract_name(email_body, resume_text)
        email = self._extract_email(email_body, resume_text)
        phone = self._extract_phone(email_body, resume_text)
        education = self._extract_education(resume_text)
        job_history = self._extract_job_history(resume_text)
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
        """Extract name using multiple, improved strategies."""
        # Strategy 1: Look for a likely name in the first few lines of the resume.
        lines = resume_text.split('\n')[:5]
        for line in lines:
            line = line.strip()
            # A name is likely 2-4 words, capitalized, and contains only letters/spaces.
            if re.fullmatch(r'([A-Z][a-z\']+ )+[A-Z][a-z\']+', line) and 2 <= len(line.split()) <= 4:
                 # Avoid common non-name phrases
                if not any(word in line.lower() for word in ['email', 'phone', 'profile', 'objective', 'summary']):
                    return line

        # Strategy 2: Look for common "My name is..." patterns in the email body.
        text_to_search = f"{email_body}\n{resume_text}"
        patterns = [
            r"my name is\s+([A-Z][a-z]+ [A-Z][a-z\']+)",
            r"i am\s+([A-Z][a-z]+ [A-Z][a-z\']+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, text_to_search, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "Unknown Applicant"

    def _extract_email(self, email_body, resume_text):
        """Extract email address."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        text = f"{email_body} {resume_text}"
        
        matches = re.findall(email_pattern, text)
        if matches:
            for email in matches:
                if not any(generic in email.lower() for generic in ['noreply', 'admin', 'support']):
                    return email
        return ""

    def _extract_phone(self, email_body, resume_text):
        """Extract and clean phone number."""
        text = f"{email_body} {resume_text}"
        
        patterns = [
            r'\+?91[-\s]?[6-9]\d{9}',
            r'\b[6-9]\d{9}\b',
            r'\+?91\s?[6-9]\d{4}\s?\d{5}',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
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
            
            if any(keyword in line_lower for keyword in education_keywords[:6]) and len(line.strip()) < 50:
                in_education_section = True
                continue
            
            if in_education_section and any(end_word in line_lower for end_word in ['experience', 'work', 'skills', 'projects']):
                break
            
            if in_education_section and line.strip():
                education_lines.append(line.strip())
            
            if any(degree in line_lower for degree in education_keywords[6:]):
                education_lines.append(line.strip())
        
        education_text = '. '.join(list(dict.fromkeys(education_lines))[:5])
        return education_text if education_text else "Not specified"

    def _extract_job_history(self, resume_text):
        """Extract job history in markdown format."""
        lines = resume_text.split('\n')
        work_lines = []
        in_work_section = False
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if any(keyword in line_lower for keyword in ['experience', 'work', 'employment', 'career']):
                in_work_section = True
                continue
            
            if in_work_section and any(end_word in line_lower for end_word in ['education', 'skills', 'projects', 'achievements']):
                break
            
            if in_work_section and line.strip():
                work_lines.append(line.strip())
        
        if not work_lines:
            return "No work experience specified"
        
        formatted_jobs = []
        for line in work_lines[:10]:
            if len(line) > 20:
                formatted_jobs.append(f"- {line}")
        
        return '\n'.join(formatted_jobs) if formatted_jobs else "No work experience specified"

    def _extract_domain(self, full_text, company_roles):
        """Extract domain/role based on keyword matching."""
        role_scores = {role: 0 for role in company_roles}
        
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
        
        for role, keywords in role_keywords.items():
            for keyword in keywords:
                if keyword in full_text:
                    role_scores[role] += 1
        
        if any(score > 0 for score in role_scores.values()):
            return max(role_scores, key=role_scores.get)
        else:
            return "Other"

    def _parse_and_clean_response(self, text):
        """Parse and clean the response from LLM."""
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
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
