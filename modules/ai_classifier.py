import streamlit as st
import google.generativeai as genai
import re
import json
from utils.logger import logger

class AIClassifier:
    def __init__(self):
        """Initializes the classifier with the Google Gemini model."""
        # Fetch the API key from secrets and configure the Gemini client
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        self.model = genai.GenerativeModel('gemini-1.5-pro-latest')

    def extract_info(self, email_subject, email_body, resume_text):
        """Extracts structured data using Google's Gemini model with JSON mode."""
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
            
            # Your detailed prompt remains the same as it's very effective.
            prompt = (
                "You are a hyper-precise HR data extraction engine. From the provided text, extract a valid JSON object with the exact following keys:\n"
                "- 'Name': Full name of the applicant.\n"
                "- 'Email': The email address of the applicant.\n"
                "- 'Phone': The 10-digit mobile number, extracted as a plain string of digits. If a country code (like +91 or 91) is present, it must be removed. The final output for this key must be exactly 10 digits.\n"
                "- 'Education': A single-string summary of their education background.\n"
                "- 'JobHistory': Create a markdown-formatted bulleted list. Each bullet point, starting with a hyphen (-), should represent a single job, including the Job Title, Company, and duration. Follow this with a very concise 1-2 line summary of their key responsibilities and achievements for that role. Do not copy long paragraphs.\n"
                f"- 'Domain': Analyze the entire text and classify the candidate's primary role into ONE of the following: {', '.join(company_roles)}. Base your decision on their most recent and significant experience. If no role is a clear match, use 'Other'."
            )
            
            # This is the new API call for Google Gemini
            response = self.model.generate_content(
                [prompt, combined_text],
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json"
                )
            )

            return self._parse_and_clean_response(response.text)
        except Exception as e:
            logger.error(f"Gemini AI processing failed: {str(e)}", exc_info=True)
            return {}

    def _parse_and_clean_response(self, json_str):
        """Parse AI response into a dictionary and clean the phone number."""
        try:
            data = json.loads(json_str)
            
            # Post-processing for the phone number to ensure it's 10 digits
            if 'Phone' in data and data['Phone']:
                phone_digits = re.sub(r'\D', '', str(data['Phone']))
                if len(phone_digits) == 12 and phone_digits.startswith('91'):
                    phone_digits = phone_digits[2:]
                data['Phone'] = phone_digits[-10:]

            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from AI: {str(e)}")
            return {}
