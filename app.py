import streamlit as st
import pandas as pd
import datetime
import json
import uuid
import re
import asyncio
import requests
import os
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Dict, Any
import time

# --- Application Modules ---
from modules.database_handler import DatabaseHandler
from modules.drive_handler import DriveHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from processing_engine import ProcessingEngine
from modules.importer import Importer
from streamlit_quill import st_quill

# --- Page Configuration ---
st.set_page_config(
    page_title="HireFL.ai - HR Applicant Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for production-ready styling
st.markdown("""
    <style>
    .main-header { font-size: 3rem; font-weight: bold; color: #1f77b4; text-align: center; margin-bottom: 2rem; }
    .sub-header { font-size: 1.5rem; color: #333; margin-top: 2rem; }
    .metric-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; text-align: center; }
    .status-badge { padding: 0.25rem 0.5rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre; }
    .stPlotlyChart { border-radius: 10px; overflow: hidden; }
    .sidebar .sidebar-content { padding: 1rem; }
    </style>
""", unsafe_allow_html=True)

# --- State Management Initialization ---
if 'active_detail_tab' not in st.session_state: st.session_state.active_detail_tab = "Profile"
if 'view_mode' not in st.session_state: st.session_state.view_mode = 'grid'
if 'selected_applicant_id' not in st.session_state: st.session_state.selected_applicant_id = None
if 'confirm_delete' not in st.session_state: st.session_state.confirm_delete = False
if 'schedule_view_active' not in st.session_state: st.session_state.schedule_view_active = False
if 'importer_expanded' not in st.session_state: st.session_state.importer_expanded = False
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
if 'resume_uploader_key' not in st.session_state: st.session_state.resume_uploader_key = 0
if 'show_sync_dialog' not in st.session_state: st.session_state.show_sync_dialog = False
if 'sync_in_progress' not in st.session_state: st.session_state.sync_in_progress = False
if 'sync_status' not in st.session_state: st.session_state.sync_status = ""
if 'last_sync_time' not in st.session_state: st.session_state.last_sync_time = None

# --- Authentication Setup ---
@st.cache_resource
def create_flow():
    try:
        with open('credentials.json') as f:
            client_config = json.load(f)
        redirect_uri = "http://localhost:8501"
    except FileNotFoundError:
        client_config = {
            "web": {
                "client_id": st.secrets["GOOGLE_CLIENT_ID"],
                "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": [st.secrets["REDIRECT_URI"]],
            }
        }
        redirect_uri = st.secrets["REDIRECT_URI"]

    scopes = [
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'openid',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/calendar'
    ]
    
    return Flow.from_client_config(
        client_config=client_config,
        scopes=scopes,
        redirect_uri=redirect_uri
    )

def logout():
    if 'credentials' in st.session_state:
        creds = st.session_state.credentials
        token_to_revoke = creds.refresh_token or creds.token
        if token_to_revoke:
            try:
                requests.post('https://oauth2.googleapis.com/revoke',
                    params={'token': token_to_revoke},
                    headers={'content-type': 'application/x-www-form-urlencoded'})
            except Exception:
                pass

    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    if 'code' in st.query_params:
        st.query_params.clear()
    
    st.rerun()

def run_app():
    credentials = st.session_state.credentials
    user_info = st.session_state.user_info

    # --- Resource Initialization ---
    @st.cache_resource
    def get_db_handler(): return DatabaseHandler()
    @st.cache_resource
    def get_email_handler(creds): return EmailHandler(creds)
    @st.cache_resource
    def get_sheets_updater(creds): return SheetsUpdater(creds)
    @st.cache_resource
    def get_calendar_handler(creds): return CalendarHandler(creds)
    @st.cache_resource
    def get_importer(creds): return Importer(creds)
    @st.cache_resource
    def get_drive_handler(creds): return DriveHandler(creds)
    @st.cache_resource
    def get_processing_engine(creds): return ProcessingEngine(creds)

    db_handler = get_db_handler()
    db_handler.create_tables()
    email_handler = get_email_handler(credentials)
    sheets_updater = get_sheets_updater(credentials)
    calendar_handler = get_calendar_handler(credentials)
    importer = get_importer(credentials)
    drive_handler = get_drive_handler(credentials)
    processing_engine = get_processing_engine(credentials)

    # --- Sidebar ---
    with st.sidebar:
        st.markdown(f"👋 **Welcome, {user_info.get('name', 'User')}**")
        st.divider()
        if st.button("🔄 Sync Emails & Replies", type="primary", disabled=st.session_state.sync_in_progress):
            st.session_state.sync_in_progress = True
            st.session_state.sync_status = "Starting sync..."
            st.rerun()
        
        if st.session_state.sync_in_progress:
            st.info(f"**Sync Status:** {st.session_state.sync_status}")
            if st.button("⏹️ Stop Sync"):
                st.session_state.sync_in_progress = False
                st.rerun()
        
        if st.session_state.last_sync_time:
            st.caption(f"Last sync: {st.session_state.last_sync_time}")
        
        st.divider()
        if st.button("🚪 Logout"):
            logout()
        
        st.divider()
        st.markdown("### 📊 Quick Stats")
        col1, col2 = st.columns(2)
        with col1:
            total_apps = len(db_handler.fetch_applicants_as_df())
            st.metric("Total Applicants", total_apps)
        with col2:
            active = len(db_handler.fetch_applicants_as_df().query("status not in ['Rejected', 'Hired']"))
            st.metric("Active", active)

    # --- Main Header ---
    st.markdown('<h1 class="main-header">🚀 HireFL.ai Dashboard</h1>', unsafe_allow_html=True)
    st.caption("Streamline your hiring process with AI-powered applicant management.")

    # --- Sync Logic with Progress ---
    if st.session_state.sync_in_progress:
        with st.spinner("Syncing emails and replies..."):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                # Process new applications
                status_text.text("Processing new applications...")
                new_apps, failed = processing_engine.process_new_applications()
                progress_bar.progress(0.5)
                
                # Process replies
                status_text.text("Checking for replies...")
                new_replies = processing_engine.process_replies()
                progress_bar.progress(1.0)
                
                st.session_state.sync_status = f"Completed: {new_apps} new apps, {new_replies} replies, {failed} failed."
                st.session_state.last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.success(st.session_state.sync_status)
                
            except Exception as e:
                st.error(f"Sync failed: {str(e)}")
                st.session_state.sync_status = f"Failed: {str(e)}"
            
            st.session_state.sync_in_progress = False
            st.rerun()

    # --- Main Tabs ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Applicants", "💬 Conversations", "📅 Schedule", "📊 Analytics", "⚙️ Settings"])

    with tab1:
        st.markdown('<h2 class="sub-header">Applicant Management</h2>', unsafe_allow_html=True)
        
        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            selected_status = st.selectbox("Filter by Status", db_handler.get_statuses(), key="status_filter")
        with col_f2:
            selected_role = st.selectbox("Filter by Role", ["All"] + list(db_handler.fetch_applicants_as_df()["Domain"].unique()), key="role_filter")
        with col_f3:
            search_term = st.text_input("Search", placeholder="Name, Email, Phone...")
        
        # Load filtered data
        @st.cache_data(ttl=300)
        def load_filtered_applicants(status=None, role=None, search=""):
            df = db_handler.fetch_applicants_as_df()
            if status and status != "All":
                df = df[df["Status"] == status]
            if role and role != "All":
                df = df[df["Domain"] == role]
            if search:
                df = df[df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)]
            return df.sort_values("CreatedAt", ascending=False)
        
        applicants_df = load_filtered_applicants(selected_status, selected_role, search_term)
        
        # View Mode Toggle
        col_v1, col_v2 = st.columns([3, 1])
        with col_v1:
            st.info(f"Showing {len(applicants_df)} applicants")
        with col_v2:
            if st.button("🗑️ Bulk Delete", key="bulk_delete_toggle"):
                st.session_state.confirm_delete = not st.session_state.confirm_delete
        
        if st.session_state.confirm_delete:
            st.warning("⚠️ Select applicants to delete:")
            selected_ids = st.multiselect("Applicants", applicants_df["Id"].tolist(), default=[])
            if st.button("Confirm Delete", type="primary", disabled=not selected_ids):
                if db_handler.delete_applicants(selected_ids):
                    st.success("Deleted successfully!")
                    st.cache_data.clear()
                    st.rerun()
                st.session_state.confirm_delete = False
        
        # Display Applicants
        if st.session_state.view_mode == 'grid':
            for idx, row in applicants_df.iterrows():
                with st.container():
                    col1, col2, col3 = st.columns([4, 2, 1])
                    with col1:
                        st.markdown(f"**{row['Name']}**")
                        st.caption(f"{row['Email']} | {row['Phone']}")
                        st.caption(f"Role: {row['Domain']}")
                    with col2:
                        st.markdown(f"**Status:** <span class='status-badge' style='background-color: {get_status_color(row['Status'])}; color: white;'>{row['Status']}</span>", unsafe_allow_html=True)
                        if pd.notna(row['Resume']):
                            st.caption(f"[📄 Resume]({row['Resume']})")
                    with col3:
                        if st.button("👁️ View", key=f"view_{row['Id']}"):
                            st.session_state.selected_applicant_id = row['Id']
                            st.rerun()
                    st.divider()
        else:
            st.dataframe(
                applicants_df,
                column_config={
                    "Status": st.column_config.SelectboxColumn("Status", options=db_handler.get_statuses(), required=True),
                    "Domain": st.column_config.SelectboxColumn("Role", options=["All"] + list(applicants_df["Domain"].unique())),
                    "Resume": st.column_config.LinkColumn("Resume")
                },
                use_container_width=True,
                hide_index=True,
                selection_mode="multi-row" if st.session_state.confirm_delete else None
            )
        
        # View Toggle
        if st.button("Switch to List View" if st.session_state.view_mode == 'grid' else "Switch to Grid View"):
            st.session_state.view_mode = 'list' if st.session_state.view_mode == 'grid' else 'grid'
            st.rerun()
        
        # Applicant Detail Modal
        if st.session_state.selected_applicant_id:
            applicant = applicants_df[applicants_df["Id"] == st.session_state.selected_applicant_id].iloc[0]
            with st.expander(f"👤 Details: {applicant['Name']}", expanded=True):
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.metric("Name", applicant['Name'])
                    st.metric("Email", applicant['Email'])
                    st.metric("Phone", applicant['Phone'])
                    st.metric("Role", applicant['Domain'])
                with col_d2:
                    st.metric("Status", applicant['Status'])
                    st.metric("Education", applicant['Education'][:50] + "..." if len(applicant['Education']) > 50 else applicant['Education'])
                    st.metric("Created", applicant['CreatedAt'].strftime("%Y-%m-%d"))
                
                st.subheader("📝 Job History")
                st.markdown(applicant['JobHistory'])
                
                st.subheader("📝 Feedback")
                feedback = st.text_area("Feedback", value=applicant['Feedback'] or "", key=f"feedback_{applicant['Id']}")
                if st.button("Update Feedback", key=f"update_feedback_{applicant['Id']}"):
                    # Update logic here
                    pass
                
                col_u1, col_u2, col_u3 = st.columns(3)
                with col_u1:
                    new_status = st.selectbox("Update Status", db_handler.get_statuses(), index=db_handler.get_statuses().index(applicant['Status']), key=f"status_update_{applicant['Id']}")
                    if st.button("Update Status", key=f"apply_status_{applicant['Id']}"):
                        # Update status logic
                        pass
                with col_u2:
                    new_role = st.selectbox("Update Role", ["All"] + list(applicants_df["Domain"].unique()), index=list(applicants_df["Domain"].unique()).index(applicant['Domain']) if applicant['Domain'] in applicants_df["Domain"].unique() else 0, key=f"role_update_{applicant['Id']}")
                    if st.button("Update Role", key=f"apply_role_{applicant['Id']}"):
                        db_handler.update_applicant_role(applicant['Id'], new_role)
                        st.success("Role updated!")
                        st.cache_data.clear()
                        st.rerun()
                with col_u3:
                    if st.button("✉️ Send Email", key=f"email_{applicant['Id']}"):
                        # Email logic
                        pass
                
                if st.button("❌ Close", key=f"close_detail_{applicant['Id']}"):
                    st.session_state.selected_applicant_id = None
                    st.rerun()

    with tab2:
        st.markdown('<h2 class="sub-header">Conversations</h2>', unsafe_allow_html=True)
        convos_df = db_handler.fetch_applicants_as_df()
        st.dataframe(convos_df[["Name", "Email", "Status"]], use_container_width=True)

    with tab3:
        st.markdown('<h2 class="sub-header">Schedule Interviews</h2>', unsafe_allow_html=True)
        # Schedule logic here

    with tab4:
        st.markdown('<h2 class="sub-header">Analytics</h2>', unsafe_allow_html=True)
        # Analytics logic

    with tab5:
        st.markdown('<h2 class="sub-header">System Settings</h2>', unsafe_allow_html=True)
        st.markdown("Manage statuses, interviewers, and job descriptions.")
        col_s1, col_s2, col_s3 = st.columns(3)
        
        with col_s1:
            st.subheader("Statuses")
            status_list = db_handler.get_statuses()
            for status in status_list:
                col1, col2 = st.columns([4, 1])
                col1.write(status)
                if status not in ["New", "Hired", "Rejected"]:
                    if col2.button("🗑️", key=f"del_status_{status}"):
                        if not db_handler.delete_status(status):
                            st.error("Cannot delete status in use.")
                        else:
                            st.success(f"Deleted {status}")
                            st.cache_data.clear()
                            st.rerun()
            with st.form("new_status"):
                new_status = st.text_input("New Status")
                if st.form_submit_button("Add"):
                    if db_handler.add_status(new_status):
                        st.success("Added!")
                        st.cache_data.clear()
                        st.rerun()
        
        with col_s2:
            st.subheader("Interviewers")
            interviewer_list = db_handler.get_interviewers()  # Assume method exists
            for _, intv in interviewer_list.iterrows():
                col1, col2 = st.columns([4, 1])
                col1.text(f"{intv['name']} ({intv['email']})")
                if col2.button("🗑️", key=f"del_intv_{intv['id']}"):
                    db_handler.delete_interviewer(intv['id'])
                    st.success("Deleted!")
                    st.cache_data.clear()
                    st.rerun()
            with st.form("new_intv"):
                name = st.text_input("Name")
                email = st.text_input("Email")
                if st.form_submit_button("Add"):
                    db_handler.add_interviewer(name, email)
                    st.success("Added!")
                    st.cache_data.clear()
                    st.rerun()
        
        with col_s3:
            st.subheader("Job Descriptions")
            jd_list = db_handler.get_job_descriptions()
            for _, jd in jd_list.iterrows():
                col1, col2 = st.columns([4, 1])
                col1.markdown(f"[{jd['name']}]({jd['drive_url']})")
                if col2.button("🗑️", key=f"del_jd_{jd['id']}"):
                    db_handler.delete_job_description(jd['id'])
                    st.success("Deleted!")
                    st.cache_data.clear()
                    st.rerun()
            with st.form("new_jd"):
                jd_name = st.text_input("JD Name")
                jd_file = st.file_uploader("JD File", type=['pdf', 'docx'])
                if st.form_submit_button("Add"):
                    if jd_name and jd_file:
                        temp_path = f"/tmp/{uuid.uuid4()}_{jd_file.name}"
                        with open(temp_path, "wb") as f:
                            f.write(jd_file.getbuffer())
                        drive_url = drive_handler.upload_to_drive(temp_path, jd_file.name)
                        os.remove(temp_path)
                        db_handler.add_job_description(jd_name, drive_url, jd_file.name)
                        st.success("Added!")
                        st.cache_data.clear()
                        st.rerun()

    # --- Importer Section (in sidebar or modal) ---
    with st.sidebar.expander("📥 Import Data", expanded=st.session_state.importer_expanded):
        st.subheader("Bulk Import")
        g_sheet_url = st.text_input("Google Sheet URL")
        if st.button("Import from Sheet"):
            # Logic
            pass
        
        uploaded_file = st.file_uploader("CSV/Excel File")
        if st.button("Import File"):
            # Logic
            pass
        
        st.subheader("Single Resume")
        resume_url = st.text_input("Resume URL")
        if st.button("Import from URL"):
            # Logic
            pass
        
        resume_file = st.file_uploader("Upload Resume")
        if st.button("Import Resume"):
            # Logic
            pass

def get_status_color(status):
    status_lower = status.lower()
    colors = {
        'rejected': '#FF4B4B',
        'hired': '#28a745',
        'new': '#007bff',
        'interview': '#ffc107',
        'offer': '#17a2b8'
    }
    return colors.get(next((k for k in colors if k in status_lower), ''), '#FFFFFF')

# --- Authentication Flow ---
if 'credentials' not in st.session_state:
    if 'code' in st.query_params:
        try:
            flow = create_flow()
            flow.fetch_token(code=st.query_params['code'])

            st.session_state.credentials = flow.credentials
            user_info_service = build('oauth2', 'v2', credentials=st.session_state.credentials)
            user_info = user_info_service.userinfo().get().execute()
            st.session_state.user_info = user_info

            st.query_params.clear()
            st.rerun()

        except Exception as e:
            st.error(f"Authentication error: {e}")
    else:
        st.title("🚀 Welcome to HireFL.ai")
        st.write("Log in to manage applicants efficiently.")
        flow = create_flow()
        authorization_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
        st.link_button("🔐 Login with Google", authorization_url, use_container_width=True, type="primary")
else:
    run_app()
