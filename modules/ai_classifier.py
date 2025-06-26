import streamlit as st
import openai
import re
import json
from utils.logger import logger

class AIClassifier:
    def __init__(self):
        # Fetch the API key from secrets
        openai.api_key = st.secrets["OPENAI_API_KEY"]
        self.model = st.secrets.get("OPENAI_MODEL", "gpt-3.5-turbo-1106")

    def extract_info(self, email_subject, email_body, resume_text):
        """Extract structured data using an AI model with specific domain classification."""
        try:
            combined_text = (
                f"EMAIL SUBJECT: {email_subject}\n\n"
                f"EMAIL BODY: {email_body}\n\n"
                f"RESUME CONTENT: {resume_text}"
            )

            company_roles = [
                "LLM engineer", "AI/ML engineer", "SEO", "Full Stack Developer",
                "Project manager", "content writer", "digital marketing", "QA engineer",
                "software developer", "UI/UX", "App developer", "graphic designer",
                "videographer", "BDE(business developer executive)", "HR", "PPC"
            ]

            response = openai.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a hyper-precise HR data extraction engine. From the provided text, extract a valid JSON object with the exact following keys:\n"
                            "- 'Name': Full name of the applicant.\n"
                            "- 'Email': The email address of the applicant.\n"
                            "- 'Phone': The 10-digit mobile number, extracted as a plain string of digits. If a country code (like +91 or 91) is present, it must be removed. The final output for this key must be exactly 10 digits.\n"
                            "- 'Education': A single-string summary of their education background.\n"
                            "- 'JobHistory': Create a markdown-formatted bulleted list. Each bullet point, starting with a hyphen (-), should represent a single job, including the Job Title, Company, duration, and a 1-sentence summary of responsibilities.\n"
                            f"- 'Domain': Analyze the entire text and classify the candidate's primary role into ONE of the following: {', '.join(company_roles)}. Base your decision on their most recent and significant experience. If no role is a clear match, use 'Other'."
                        )
                    },
                    {
                        "role": "user",
                        "content": combined_text
                    }
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"}
            )

            return self._parse_and_clean_response(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"AI processing failed: {str(e)}", exc_info=True)
            return {}

    def _parse_and_clean_response(self, json_str):
        """Parse AI response into a dictionary and clean the phone number."""
        try:
            data = json.loads(json_str)
            
            # Post-processing for the phone number to ensure it's 10 digits
            if 'Phone' in data and data['Phone']:
                # Remove all non-digit characters
                phone_digits = re.sub(r'\D', '', str(data['Phone']))
                # If the number starts with a country code like 91 and is 12 digits, strip it
                if len(phone_digits) == 12 and phone_digits.startswith('91'):
                    phone_digits = phone_digits[2:]
                # Take the last 10 digits
                data['Phone'] = phone_digits[-10:]

            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from AI: {str(e)}")
            return {}
