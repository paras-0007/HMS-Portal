import streamlit as st
import pandas as pd
import datetime
import json
import uuid
import re
import asyncio
import requests
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Dict, Any

# ---  Application Modules ---
from modules.database_handler import DatabaseHandler
from modules.drive_handler import DriveHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from processing_engine import ProcessingEngine
from modules.importer import Importer
from streamlit_quill import st_quill

# --- Page Configuration ---
st.set_page_config(page_title="HR Applicant Dashboard", page_icon="📑", layout="wide")
if 'active_detail_tab' not in st.session_state: st.session_state.active_detail_tab = "Profile"

# --- Authentication Setup ---
def create_flow():
    """
    Creates a Google OAuth Flow object. It uses secrets for deployment 
    and a local credentials.json file for development.
    """
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

# --- State Management Initialization ---
if 'view_mode' not in st.session_state: st.session_state.view_mode = 'grid'
if 'selected_applicant_id' not in st.session_state: st.session_state.selected_applicant_id = None
if 'confirm_delete' not in st.session_state: st.session_state.confirm_delete = False
if 'schedule_view_active' not in st.session_state: st.session_state.schedule_view_active = False
if 'importer_expanded' not in st.session_state: st.session_state.importer_expanded = False
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
if 'resume_uploader_key' not in st.session_state: st.session_state.resume_uploader_key = 0
if 'show_sync_dialog' not in st.session_state: st.session_state.show_sync_dialog = False


def run_app():
    def get_status_color(status):
        """Returns a hex color code for a given status."""
        status = status.lower()
        if 'rejected' in status:
            return '#FF4B4B'  # Red
        elif 'hired' in status:
            return '#28a745'  # Green
        elif 'new' in status:
            return '#007bff'  # Blue
        elif 'interview' in status:
            return '#ffc107'  # Yellow/Orange
        elif 'offer' in status:
            return '#17a2b8'  # Cyan/Teal
        else:
            return '#FFFFFF'  # Default (White)
            
    def download_file_from_url(url):
        import requests
        import re
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            file_id = match.group(1)
            download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
            response = requests.get(download_url)
            if response.status_code == 200:
                return response.content
        return None
    def logout():
        """
        Handles the logout process by revoking the Google token, clearing the session,
        and cleaning the URL to ensure a fresh login state.
        """
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
    
    credentials = st.session_state.credentials

    # --- Resource Initialization ---
    @st.cache_resource
    def get_db_handler(): return DatabaseHandler()
    def get_email_handler(creds): return EmailHandler(creds)
    def get_sheets_updater(creds): return SheetsUpdater(creds)
    def get_calendar_handler(creds): return CalendarHandler(creds)
    def get_importer(creds): return Importer(creds)
    def get_drive_handler(creds): return DriveHandler(creds)

    db_handler = get_db_handler()
    email_handler = get_email_handler(credentials)
    sheets_updater = get_sheets_updater(credentials)
    calendar_handler = get_calendar_handler(credentials)
    importer = get_importer(credentials)
    drive_handler = DriveHandler(credentials)

    # --- Callbacks for Importer ---
    def handle_google_sheet_import():
        sheet_url = st.session_state.g_sheet_url
        if sheet_url and (sid := re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)):
            with st.spinner("Reading & Importing from Google Sheet..."):
                data = sheets_updater.read_sheet_data(sid.group(1))
                if isinstance(data, pd.DataFrame) and not data.empty:
                    inserted, skipped = importer._process_dataframe(data)
                    st.success(f"Import complete! Added: {inserted}, Skipped: {skipped}.")
                    st.session_state.g_sheet_url = ""
                    st.cache_data.clear()
                else:
                    st.error(f"Could not read data from sheet. {data}")
        else:
            st.warning("Please provide a valid Google Sheet URL.")
    
    def handle_bulk_file_import():
        uploader_key = f"bulk_uploader_{st.session_state.uploader_key}"
        uploaded_file = st.session_state[uploader_key]
        if uploaded_file:
            with st.spinner("Processing file and importing..."):
                status_msg, count = importer.import_from_local_file(uploaded_file)
                st.success(status_msg)
                if count > 0:
                    st.session_state.uploader_key += 1
                    st.cache_data.clear()

    def handle_resume_url_import():
        resume_link = st.session_state.resume_url_input
        if resume_link:
            with st.spinner("Analyzing resume and creating profile..."):
                applicant_id = importer.import_from_resume(resume_link)
                if applicant_id:
                    st.success(f"Successfully imported applicant. New ID: {applicant_id}")
                    st.session_state.resume_url_input = ""
                    st.cache_data.clear()
                else:
                    st.error("Failed to import from resume link.")
        else:
            st.warning("Please provide a resume URL.")

    def handle_local_resume_import():
        uploader_key = f"resume_uploader_{st.session_state.resume_uploader_key}"
        uploaded_resume = st.session_state[uploader_key]
        if uploaded_resume:
            with st.spinner("Analyzing resume and creating profile..."):
                applicant_id = importer.import_from_local_resume(uploaded_resume)
                if applicant_id:
                    st.success(f"Successfully imported applicant. New ID: {applicant_id}")
                    st.session_state.resume_uploader_key += 1
                    st.cache_data.clear()
                else:
                    st.error("Failed to import from resume file.")


    # --- Data Loading & Caching Functions ---
    @st.cache_data(ttl=300)
    def load_all_applicants():
        df = db_handler.fetch_applicants_as_df()
        rename_map = {
            'id': 'Id', 'name': 'Name', 'email': 'Email', 'phone': 'Phone', 'domain': 'Role',
            'education': 'Education', 'job_history': 'JobHistory', 'cv_url': 'Resume', 'status': 'Status',
            'feedback': 'Feedback', 'created_at': 'CreatedAt', 'gmail_thread_id': 'GmailThreadId',
            'last_action_date': 'LastActionDate'
        }
        if not df.empty:
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df

    @st.cache_data(ttl=3600)
    def load_statuses(): return db_handler.get_statuses()
    @st.cache_data(ttl=3600)
    def load_interviewers(): return db_handler.get_interviewers()
    @st.cache_data(ttl=300)
    def load_interviews(applicant_id): return db_handler.get_interviews_for_applicant(applicant_id) 
    @st.cache_data(ttl=300)
    def load_status_history(applicant_id): return db_handler.get_status_history(applicant_id) 
    @st.cache_data(ttl=10) 
    def load_conversations(applicant_id): return db_handler.get_conversations(applicant_id) 

    # --- Callbacks and UI Functions ---
    def set_detail_view(applicant_id):
        st.session_state.view_mode = 'detail'
        st.session_state.selected_applicant_id = applicant_id

    def set_grid_view():
        st.session_state.view_mode = 'grid'
        st.session_state.selected_applicant_id = None
        st.session_state.schedule_view_active = False
        for key in list(st.session_state.keys()):
            if key.startswith(('schedule_', 'available_slots_', 'select_', 'booking_success_message')):
                del st.session_state[key]

    def get_feedback_notes(feedback_json_str):
        if not feedback_json_str or not feedback_json_str.strip(): return []
        try:
            notes = json.loads(feedback_json_str)
            for note in notes:
                if isinstance(note.get('timestamp'), str): note['timestamp'] = datetime.datetime.fromisoformat(note['timestamp'])
            return notes
        except (json.JSONDecodeError, TypeError):
            return [{"id": str(uuid.uuid4()), "timestamp": datetime.datetime.now(datetime.timezone.utc), "stage": "Legacy Note", "author": "System", "note": feedback_json_str}]

    def format_feedback_for_export(feedback_json_str):
        notes = get_feedback_notes(feedback_json_str)
        if not notes: return ""
        sorted_notes = sorted(notes, key=lambda x: x['timestamp'])
        return "\n---\n\n".join([f"Note for '{n['stage']}' ({n['timestamp'].astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b-%Y %I:%M %p')}):\n{n['note']}\n" for n in sorted_notes])

    def render_dynamic_journey_tracker(status_history_df, current_status):
        if status_history_df.empty and current_status == "New":
            pipeline_stages = {"New": datetime.datetime.now(datetime.timezone.utc)}
        else:
            pipeline_stages = {
                row["status_name"]: row["changed_at"]
                for _, row in status_history_df.iterrows()
            }
    
        if current_status not in pipeline_stages:
            pipeline_stages[current_status] = datetime.datetime.now(
                datetime.timezone.utc
            )
   
        if current_status == "Rejected":
            st.error("**Process Ended: Applicant Rejected**", icon="✖️")
    
        stage_names = list(pipeline_stages.keys())
        if "Hired" in stage_names:
            stage_names.remove("Hired")
            stage_names.append("Hired")
        if "Rejected" in stage_names:
            stage_names.remove("Rejected")
            stage_names.append("Rejected")
            
        current_stage_index = (
            stage_names.index(current_status) if current_status in stage_names else -1
        )
        num_stages = len(stage_names)
        
        column_widths = [
            3 if i % 2 == 0 else 0.5 for i in range(2 * num_stages - 1)
        ]
        
        if not column_widths: return

        cols = st.columns(column_widths)
    
        for i, stage_name in enumerate(stage_names):
            with cols[i * 2]:
                icon, color, weight = ("⏳", "lightgrey", "normal")
                if i < current_stage_index:
                    icon, color, weight = ("✅", "green", "normal")
                elif i == current_stage_index:
                    icon, color, weight = ("➡️", "#007bff", "bold")
    
                if stage_name == "Hired":
                    icon, color, weight = ("🎉", "green", "bold")
                if stage_name == "Rejected":  
                    icon, color, weight = ("✖️", "#FF4B4B", "bold")
    
                timestamp = pipeline_stages.get(stage_name)
                time_str = (
                    f"<p style='font-size: 11px; color: grey; margin: 0; "
                    f"white-space: nowrap;'>"
                    f"{timestamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b %I:%M %p')}"
                    f"</p>"
                )
             
                st.markdown(
                    f"""
                    <div style='text-align: center; padding: 5px; border-radius: 10px;
                                background-color: #2E2E2E; margin: 2px;'>
                        <p style='font-size: 24px; color: {color}; margin-bottom: -5px;'>
                            {icon}
                        </p>
                        <p style='font-weight: {weight}; color: {color}; white-space: nowrap;'>
                            {stage_name}
                        </p>
                        {time_str}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if i < num_stages - 1:
                with cols[i * 2 + 1]:
                    st.markdown(
                        "<p style='text-align: center; font-size: 24px; color: grey; "
                        "margin-top: 35px;'>→</p>",
                        unsafe_allow_html=True,
                    )

    def render_feedback_dossier(applicant_id, feedback_json_str):
        st.subheader("Feedback & Notes")
        all_notes = get_feedback_notes(feedback_json_str)
        if not all_notes: st.info("No feedback notes have been logged for this applicant yet."); return
        
        note_filter_stages = ["All Notes"] + list(pd.Series([n['stage'] for n in all_notes]).unique())
        
        if f"note_filter_{applicant_id}" not in st.session_state:
            st.session_state[f"note_filter_{applicant_id}"] = "All Notes"
            
        selected_stage = st.radio("Filter notes by stage:", options=note_filter_stages, horizontal=True, key=f"note_filter_radio_{applicant_id}")
        
        filtered_notes = all_notes if selected_stage == "All Notes" else [n for n in all_notes if n['stage'] == selected_stage]
        sorted_notes = sorted(filtered_notes, key=lambda x: x['timestamp'], reverse=True)

        if not sorted_notes: st.warning(f"No notes found for the stage: '{selected_stage}'")
        else:
            for note in sorted_notes:
                with st.container(border=True):
                    time_str = note['timestamp'].astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b-%Y, %I:%M %p')
                    st.markdown(f"**Note for: {note['stage']}** | <small>Logged on: {time_str}</small>", unsafe_allow_html=True)
                    st.markdown(note['note'])


   
    def render_api_monitoring(stats: Dict[str, Any]):
        """Render API key pool monitoring information from a stats dictionary."""
        st.subheader("🔑 API Key Pool Live Status")
        
        # Overall status
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Keys", stats.get("total_keys", 0))
        col2.metric("Available", stats.get("available_keys", 0))
        col3.metric("Rate Limited", stats.get("rate_limited_keys", 0))
        col4.metric("Failed", stats.get("failed_keys", 0))

        # Status indicator
        available = stats.get("available_keys", 0)
        total = stats.get("total_keys", 1) # Avoid division by zero
        if available == 0:
            st.error("⚠️ No API keys available! Classification will fail.")
        elif available / total < 0.3:
            st.warning(f"⚠️ Low API key availability: {available}/{total} keys available")
        else:
            st.success(f"✅ API key pool healthy: {available}/{total} keys available")
        
        # Usage statistics
        if stats.get("usage_counts"):
            st.caption("Key Usage Statistics")
            usage_data = []
            key_statuses = stats.get("key_statuses", {})
            for i, (key, count) in enumerate(stats["usage_counts"].items(), 1):
                status = key_statuses.get(key, "Unknown")
                if status == "Failed": status_str = "🔴 Failed"
                elif status == "Rate Limited": status_str = "🟡 Rate Limited"
                else: status_str = "🟢 Available"
                
                usage_data.append({
                    "Key": f"Key {i} ({key[:8]}...)",
                    "Status": status_str,
                    "Usage Count": count
                })
            
            st.dataframe(usage_data, use_container_width=True, height=150)                
    # --- Sidebar UI ---
    with st.sidebar:
        st.header(f"Welcome {st.session_state.user_info['given_name']}!")
        st.image(st.session_state.user_info['picture'], width=80)

        if st.button("📧 Sync New Emails & Replies", use_container_width=True, type="primary"):
            st.session_state.show_sync_dialog = True
            st.rerun()


        # if st.button("📧 Sync New Emails & Replies", use_container_width=True, type="primary"):
        #     try:
        #         with st.spinner("Processing your inbox..."):
        #             engine = ProcessingEngine(credentials)
        #             summary = engine.run_once()
        #             st.success(summary)
        #             st.cache_data.clear()
        #             st.rerun()
        #     except HttpError as e:
        #         if e.resp.status == 401: st.error("Authentication error. Please log out and log back in.", icon="🚨")
        #         else: st.error(f"An error occurred: {e}", icon="🚨")
        #     except Exception as e:
        #         st.error(f"An unexpected error occurred: {e}", icon="🚨")
                
        if st.button("Logout", use_container_width=True, on_click=logout):
            pass
        st.divider()

        st.header("📋 Controls & Filters")
        df_all = load_all_applicants()
        df_filtered = df_all.copy()
        
        search_query = st.text_input("Search by Name or Email" , placeholder="e.g Paras Kaushik ")
        if search_query:
            df_filtered = df_filtered[df_filtered['Name'].str.contains(search_query, case=False, na=False) | df_filtered['Email'].str.contains(search_query, case=False, na=False)]
        
        status_list = ['All'] + load_statuses()
        status_filter = st.selectbox("Filter by Status:", options=status_list)
        if status_filter != 'All': df_filtered = df_filtered[df_filtered['Status'] == status_filter]
        
        domain_options = ['All']
        if not df_all.empty and 'Role' in df_all.columns:
            domain_options.extend(sorted(df_all['Role'].dropna().unique().tolist()))
        domain_filter = st.selectbox("Filter by Role:", options=domain_options)
        if domain_filter != 'All' and 'Role' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['Role'] == domain_filter]
        
        st.divider()
        if st.button("🔄 Refresh All Data", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear() 
            st.rerun()

        with st.expander("📂 Recent Exports"):
            logs = db_handler.fetch_export_logs()
            if logs.empty:
                st.info("No exports have been made yet.")
            for _, log in logs.iterrows(): 
                col1, col2 = st.columns([4, 1])
                col1.markdown(f"• [{log['file_name']}]({log['sheet_url']})", unsafe_allow_html=True)
                if col2.button("🗑️", key=f"delete_log_{log['id']}", help="Delete this export log"):
                    db_handler.delete_export_log(log['id'])
                    st.success(f"Deleted log: {log['file_name']}")
                    st.rerun()

        importer_was_rendered = False
        with st.expander("📥 Import Applicants", expanded=st.session_state.get('importer_expanded', False)):
            importer_was_rendered = True
            
            import_option = st.selectbox("Choose import method:", ["From local file (CSV/Excel)", "From Google Sheet", "From single resume URL", "From single resume file (PDF/DOCX)"])
            
            # --- MODIFICATION START: Refactored importer with callbacks ---
            if import_option == "From Google Sheet":
                st.text_input(
                    "Paste Google Sheet URL",
                    key="g_sheet_url",
                     help="""
                    - Your Google Sheet must be public or shared.
                    - The first row must be the header.
                    - Columns order: Name,Email,Phone,Education,JobHistory,Resume,Role,Status	
                    """
                )
                st.button("Import from Sheet", on_click=handle_google_sheet_import)
            
            elif import_option == "From local file (CSV/Excel)":
                st.file_uploader(
                    "Choose a CSV or Excel file for bulk import",
                    type=["csv", "xls", "xlsx"],
                    key=f"bulk_uploader_{st.session_state.uploader_key}",
                    help="""
                    - Supported formats: CSV, XLS, XLSX.
                    - The first row must be the header.
                    - Columns order: Name,Email,Phone,Education,JobHistory,Resume,Role,Status	
                    """
                )
                if st.session_state[f"bulk_uploader_{st.session_state.uploader_key}"]:
                    st.button("Import from File", on_click=handle_bulk_file_import)

            elif import_option == "From single resume URL":
                st.text_input(
                    "Paste resume URL",
                    key="resume_url_input",
                    help="""
                    - Paste a direct download link to a resume file.
                    - For Google Drive, set sharing to "Anyone with the link".
                    """
                )
                st.button("Import from Resume URL", on_click=handle_resume_url_import)
            
            elif import_option == "From single resume file (PDF/DOCX)":
                st.file_uploader(
                    "Upload a single resume",
                    type=['pdf', 'docx'],
                    key=f"resume_uploader_{st.session_state.resume_uploader_key}",
                    help="- Upload a single resume in PDF or DOCX format."
                )
                if st.session_state[f"resume_uploader_{st.session_state.resume_uploader_key}"]:
                    st.button("Import from Resume File", on_click=handle_local_resume_import)
            # --- MODIFICATION END ---

        st.session_state.importer_expanded = importer_was_rendered
    if st.session_state.show_sync_dialog:
        @st.dialog("🚀 Real-time Sync & API Status", width="large")
        def sync_dialog():
            # --- UI Placeholders ---
            st.info("Sync process initiated. Please monitor the logs below.")
            progress_bar = st.progress(0, text="Initializing...")
            api_status_container = st.empty()
            st.markdown("---")
            st.subheader("📜 Live Log")
            log_container = st.container(height=300)
            log_messages = st.session_state.get("sync_log_messages", [])

            def log_message(msg):
                log_messages.append(f"[{datetime.datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}] {msg}")
                st.session_state.sync_log_messages = log_messages
                with log_container:
                    st.code("\n".join(log_messages[-20:]), language="log")

            def update_api_display(engine_instance):
                with api_status_container:
                    stats = engine_instance.get_classification_status()
                    render_api_monitoring(stats)
            
            # --- Processing Logic ---
            try:
                # 1. Initialization
                engine = ProcessingEngine(credentials)
                engine.db_handler.create_tables()
                if not log_messages:
                    log_message("Engine initialized. Checking for new applications...")
                update_api_display(engine)
                
                # 2. Process New Applications
                progress_bar.progress(5, text="Fetching new applications...")
                messages = engine.email_handler.fetch_unread_emails()
                
                new_app_count = 0
                failed_app_count = 0

                if not messages:
                    log_message("No new applications found.")
                else:
                    log_message(f"Found {len(messages)} new email(s) to process.")
                    total_steps = len(messages)
                    for i, msg in enumerate(messages):
                        percent_done = 5 + int(45 * (i + 1) / total_steps)
                        progress_bar.progress(percent_done, text=f"Processing application {i+1}/{len(messages)}...")
                        log_message(f"-> Processing email ID: ...{msg['id'][-12:]}")
                        
                        update_api_display(engine) 
                        success = engine.process_single_email(msg['id'])
                        
                        if success:
                            new_app_count += 1
                            log_message(f"✅ SUCCESS: Saved new applicant from email ...{msg['id'][-12:]}")
                        else:
                            failed_app_count += 1
                            log_message(f"⚠️ FAILED: Could not process email ...{msg['id'][-12:]}. Check server logs for details.")
                        
                        update_api_display(engine)
                
                # 3. Process Replies
                progress_bar.progress(50, text="Checking for replies...")
                log_message("Checking for replies in active threads...")
                reply_count = engine.process_replies()
                log_message(f"Found and saved {reply_count} new reply/replies.")

                # 4. Finalization
                progress_bar.progress(100, text="Sync complete!")
                summary = f"Sync finished! Processed {new_app_count} new applications ({failed_app_count} failures) and {reply_count} replies."
                st.success(summary)
                log_message(f"🎉 {summary}")
                
                if st.button("Close and Refresh Dashboard"):
                    st.session_state.show_sync_dialog = False
                    del st.session_state.sync_log_messages
                    st.cache_data.clear()
                    st.rerun()

            except Exception as e:
                st.error(f"A critical error occurred: {e}")
                logger.error("Critical error during sync dialog", exc_info=True)
                if st.button("Close"):
                    st.session_state.show_sync_dialog = False
                    del st.session_state.sync_log_messages
                    st.rerun()

        if "sync_instance_started" not in st.session_state:
             st.session_state.sync_instance_started = True
             st.session_state.sync_log_messages = []
        
        sync_dialog()
    else:
        # Cleanup state if dialog was closed without the button
        if "sync_instance_started" in st.session_state:
            del st.session_state.sync_instance_started
        if "sync_log_messages" in st.session_state:
            del st.session_state.sync_log_messages


    # --- Main Page UI ---
    st.title("Hiring Management System")
    df_all = load_all_applicants()
    st.markdown(f"### Displaying Applicants: {len(df_all)}")
    status_list = load_statuses()
    interviewer_list = load_interviewers()

    active_tab = st.radio(
        "Main Navigation",
        ["Applicant Dashboard", "System Settings"],
        horizontal=True,
        label_visibility="collapsed",
        key='main_tab'
    )

    if st.session_state.main_tab == "Applicant Dashboard":
        if st.session_state.view_mode == 'grid':
            
            def toggle_all(df):
                select_all_value = st.session_state.get('select_all_checkbox', False)
                for _, row in df.iterrows():
                    st.session_state[f"select_{row['Id']}"] = select_all_value
            
            st.checkbox("Select/Deselect All", key="select_all_checkbox", on_change=toggle_all, args=(df_filtered,))
            
            header_cols = st.columns([0.5, 2.5, 2, 1.5, 2, 1.5, 2])
            header_cols[0].markdown("")
            header_cols[1].markdown("**Name**")
            header_cols[2].markdown("**Role**")
            header_cols[3].markdown("**Status**")
            header_cols[4].markdown("**Applied On**")
            header_cols[5].markdown("**Last Action**")
            st.divider()
            
            selected_ids = []
            if "LastActionDate" in df_filtered.columns:
                # Create a temporary column for sorting 'Rejected' status to the bottom
                df_filtered['is_rejected'] = (df_filtered['Status'] == 'Rejected')
                # Sort by the new column first (False then True), then by date
                df_display = df_filtered.sort_values(
                    by=['is_rejected', 'LastActionDate'],
                    ascending=[True, False],
                    na_position='last'
                )
            else:
                df_display = df_filtered
            for _, row in df_display.iterrows():
                row_cols = st.columns([0.5, 2.5, 2, 1.5, 2, 1.5, 2])
                is_selected = row_cols[0].checkbox("", key=f"select_{row['Id']}", value=st.session_state.get(f"select_{row['Id']}", False))
                if is_selected: selected_ids.append(int(row['Id']))
                row_cols[1].markdown(f"<div style='padding-top: 0.6rem;'><b>{row['Name']}</b></div>", unsafe_allow_html=True)
                row_cols[2].markdown(f"<div style='padding-top: 0.6rem;'><b>{str(row['Role'])}</b></div>", unsafe_allow_html=True)
                status_color = get_status_color(row['Status'])
                row_cols[3].markdown(f"<div style='padding-top: 0.6rem; color: {status_color};'><b>{str(row['Status'])}</b></div>", unsafe_allow_html=True)
                row_cols[4].markdown(f"<div style='padding-top: 0.6rem;'><b>{row['CreatedAt'].strftime('%d-%b-%Y')}</b></div>", unsafe_allow_html=True)
                last_action_str = pd.to_datetime(row.get('LastActionDate')).strftime('%d-%b-%Y') if pd.notna(row.get('LastActionDate')) else "N/A"
                row_cols[5].markdown(f"<div style='padding-top: 0.6rem;'><b>{last_action_str}</b></div>", unsafe_allow_html=True)
                row_cols[6].button("View Profile ➜", key=f"view_{row['Id']}", on_click=set_detail_view, args=(row['Id'],))
            
            with st.sidebar:
                st.divider(); st.header("🔥 Actions on Selected")
                if not selected_ids: st.info("Select applicants from the dashboard.")
                else:
                    st.success(f"**{len(selected_ids)} applicant(s) selected.**")
                    if st.button(f"Export {len(selected_ids)} to Sheet", use_container_width=True):
                        with st.spinner("Generating Google Sheet..."):
                            export_df = df_all[df_all['Id'].isin(selected_ids)].copy()
                            export_df['Feedback'] = export_df['Feedback'].apply(format_feedback_for_export)
                            cols = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Resume', 'Role', 'Status', 'Feedback']
                            res = sheets_updater.create_export_sheet(export_df[cols].to_dict('records'), cols)
                            if res: db_handler.insert_export_log(res['title'], res['url']); st.success("Export successful!"); st.rerun()
                            else: st.error("Export failed.")
                    if st.button(f"Delete {len(selected_ids)} Applicant(s)", type="primary", use_container_width=True): st.session_state.confirm_delete = True
                    if st.session_state.confirm_delete:
                        st.warning("This is permanent. Are you sure?", icon="⚠️")
                        c1, c2 = st.columns(2);
                        if c1.button("✅ Yes, Delete", use_container_width=True, type="primary"):
                            if db_handler.delete_applicants(selected_ids): st.success("Applicants deleted."); st.session_state.confirm_delete = False; st.cache_data.clear(); st.rerun()
                            else: st.error("Deletion failed.")
                        if c2.button("❌ Cancel", use_container_width=True): st.session_state.confirm_delete = False; st.rerun()
        elif st.session_state.view_mode == 'detail':
            applicant_df = df_all[df_all['Id'] == st.session_state.selected_applicant_id]
            if applicant_df.empty:
                st.warning("Applicant not found. They may have been deleted.")
                st.button("⬅️ Back to Dashboard", on_click=set_grid_view)
            else:
                applicant = applicant_df.iloc[0]
                applicant_id = int(applicant['Id'])

                st.button("⬅️ Back to Dashboard", on_click=set_grid_view)
                if 'booking_success_message' in st.session_state:
                    st.success(st.session_state.booking_success_message)
                    del st.session_state.booking_success_message
                
                st.header(f"{applicant['Name']}")
                role_cols = st.columns([1.5, 4, 0.2, 3])
                role_cols[0].markdown("<div style='padding-top: 0.5rem;'><b>Applying for:</b></div>", unsafe_allow_html=True)
                
                # This column contains the compact form for editing
                with role_cols[1]:
                    with st.form("inline_role_form"):
                        form_cols = st.columns([4, 1])
                        new_role = form_cols[0].text_input(
                            "Role",
                            value=applicant['Role'],
                            label_visibility="collapsed"
                        )
                        
                        # The submit button is now a compact save icon
                        submitted = form_cols[1].form_submit_button("💾", help="Save Role")
                
                        if submitted:
                            if new_role and new_role.strip() != applicant['Role']:
                                if db_handler.update_applicant_role(applicant_id, new_role.strip()):
                                    st.toast("Role Updated!")
                                    st.cache_data.clear()
                                    st.cache_resource.clear()
                                    st.rerun()
                                else:
                                    st.error("Failed to update role.")
                            else:
                                st.toast("No change in role.")
                
                # This column is for the separator
                role_cols[2].markdown("<p style='text-align: center; padding-top: 0.5rem;'>|</p>", unsafe_allow_html=True)
                # This column displays the status
                role_cols[3].markdown(f"<div style='padding-top: 0.5rem;'><b>Current Status:</b> `{applicant['Status']}`</div>", unsafe_allow_html=True)
                st.divider(); render_dynamic_journey_tracker(load_status_history(applicant_id), applicant['Status']); st.divider()

                tab_options = ["**👤 Profile & Actions**", "**📈 Feedback & Notes**", "**💬 Email Hub**"]
                
                if f'detail_tab_index_{applicant_id}' not in st.session_state:
                    st.session_state[f'detail_tab_index_{applicant_id}'] = 0
                
                selected_tab_index = st.radio(
                    "Detail Navigation",
                    options=range(len(tab_options)),
                    format_func=lambda i: tab_options[i],
                    index=st.session_state[f'detail_tab_index_{applicant_id}'], 
                    horizontal=True,
                    label_visibility="collapsed",
                    key=f'detail_tab_index_{applicant_id}'
                )                
                
                if selected_tab_index == 0: 
                    col1, col2 = st.columns([2, 1], gap="large")
                    with col1:
                        st.subheader("Applicant Details"); st.markdown(f"**Email:** `{applicant['Email']}`\n\n**Phone:** `{applicant['Phone'] or 'N/A'}`")
                        st.link_button("📄 View Resume on Drive", url=applicant['Resume'] or "#", use_container_width=True, disabled=not applicant['Resume'])
                        st.markdown("**Education**"); st.write(applicant['Education'] or "No details.")
                        st.divider() 
                        st.markdown("**Job History**"); st.markdown(applicant['JobHistory'] or "No details.", unsafe_allow_html=True)
                    with col2:
                        st.subheader("Actions")
                        with st.form("status_form_tab"):
                            st.markdown("**Change Applicant Status**")
                            idx = status_list.index(applicant['Status']) if applicant['Status'] in status_list else 0
                            new_status = st.selectbox("New Status", options=status_list, index=idx, label_visibility="collapsed")
                            if st.form_submit_button("Save Status", use_container_width=True):
                                if db_handler.update_applicant_status(applicant_id, new_status): st.success("Status Updated!"); st.cache_data.clear(); st.rerun()
                                else: st.error("Update failed.")
                        st.divider()
                        st.markdown("**Interview Management**")
                        interviews = load_interviews(applicant_id)
                        if not interviews.empty:
                            for _, interview in interviews.iterrows():
                                st.info(f"**Scheduled:** {interview['event_title']} on {interview['start_time'].strftime('%b %d, %Y at %I:%M %p')}")
                        
                        # The button now just opens the dialog
                        if st.button("🗓️ Schedule New Interview", use_container_width=True, type="secondary"):
                            st.session_state.show_schedule_dialog = True
                        
                        # --- DEFINE AND CALL THE DIALOG ---
                        if st.session_state.get("show_schedule_dialog"):
                        
                            @st.dialog("Schedule Interview", width="large")
                            def schedule_dialog():
                                # All the form logic now lives inside this dialog function
                                st.subheader(f"New Interview for: {applicant['Name']}")
                        
                                jd_list = db_handler.get_job_descriptions()
                                jd_options = {jd['name']: {'drive_url': jd['drive_url'], 'name': jd['name']} for _, jd in jd_list.iterrows()}
                                jd_options["None (Don't attach)"] = None
                        
                                with st.form("dialog_schedule_form"):
                                    title = st.text_input("Email Subject / Interview Title", value=f"Interview for {applicant['Role']} role with {applicant['Name']}")
                        
                                    # Use st_quill for a rich text editor for the email body
                                    email_body_template = f"""
                                    <p>Dear {applicant['Name']} and Interviewer,</p>
                                    <p>This email confirms the interview details as follows. Please use the attached calendar file to add this event to your calendar.</p>
                                    <p><b>Role:</b> {applicant['Role']}</p>
                                    <p>Further details will be provided if necessary.</p>
                                    <p>Best regards,</p>
                                    <p>HR Team</p>
                                    """
                                    email_body = st_quill(value=email_body_template, html=True, key="quill_schedule")
                        
                                    opts = {f"{name} ({email})": email for name, email in zip(interviewer_list['name'], interviewer_list['email'])}
                                    interviewer_display = st.selectbox("Interviewer", options=list(opts.keys()))
                                    duration = st.selectbox("Duration (mins)", options=[30, 45, 60])
                                    selected_jd_name = st.selectbox("Attach Job Description", options=list(jd_options.keys()))
                        
                                    # Use columns for buttons
                                    col1, col2 = st.columns(2)
                        
                                    find_times_pressed = col1.form_submit_button("Find Available Times", use_container_width=True)
                        
                                    if find_times_pressed:
                                        interviewer_email = opts[interviewer_display]
                                        st.session_state.dialog_interviewer_email = interviewer_email
                                        st.session_state.dialog_duration = duration
                                        st.session_state.dialog_title = title
                                        st.session_state.dialog_body = email_body
                                        st.session_state.dialog_jd = jd_options[selected_jd_name]
                        
                                        with st.spinner("Finding open slots..."):
                                            st.session_state.available_slots = calendar_handler.find_available_slots(interviewer_email, duration)
                                        if not st.session_state.available_slots:
                                            st.warning("No available slots found.")
                        
                                if st.session_state.get('available_slots'):
                                    slots = st.session_state.available_slots
                                    slot_options = {s.strftime('%A, %b %d at %I:%M %p'): s for s in slots}
                        
                                    with st.form("dialog_booking_form"):
                                        final_slot_str = st.selectbox("Select Confirmed Time:", options=list(slot_options.keys()))
                        
                                        if st.form_submit_button("✅ Confirm & Send Email", use_container_width=True):
                                            with st.spinner("Creating event and sending emails..."):
                                                start_time = slot_options[final_slot_str]
                                                end_time = start_time + datetime.timedelta(minutes=st.session_state.dialog_duration)
                        
                                                # Call the modified calendar handler
                                                event_data = calendar_handler.create_calendar_event(
                                                    applicant['Name'], applicant['Email'], st.session_state.dialog_interviewer_email,
                                                    start_time, end_time, st.session_state.dialog_title, st.session_state.dialog_body
                                                )
                        
                                                if event_data:
                                                    # Prepare attachments for the email
                                                    attachments = []
                                                    # 1. ICS file
                                                    attachments.append({
                                                        "content": event_data['ics_data'].encode('utf-8'),
                                                        "filename": "invite.ics",
                                                        "maintype": "text",
                                                        "subtype": "calendar"
                                                    })
                                                    # 2. Resume
                                                    if pd.notna(applicant['Resume']):
                                                        resume_content = download_file_from_url(applicant['Resume'])
                                                        if resume_content:
                                                            attachments.append({"content": resume_content, "filename": f"Resume_{applicant['Name']}.pdf"})
                                                    # 3. Job Description
                                                    jd_info = st.session_state.dialog_jd
                                                    if jd_info:
                                                        jd_content = download_file_from_url(jd_info['drive_url'])
                                                        if jd_content:
                                                            attachments.append({"content": jd_content, "filename": jd_info['name'] + '.pdf'})
                        
                                                    # Send the custom email
                                                    sent_message = email_handler.send_email(
                                                        to=[applicant['Email'], st.session_state.dialog_interviewer_email],
                                                        subject=st.session_state.dialog_title,
                                                        body=st.session_state.dialog_body,
                                                        attachments=attachments
                                                    )
                        
                                                    if sent_message:
                                                        # Log the interview and the communication
                                                        i_id = interviewer_list[interviewer_list['email'] == st.session_state.dialog_interviewer_email].iloc[0]['id']
                                                        db_handler.log_interview(applicant_id, i_id, st.session_state.dialog_title, start_time, end_time, event_data['google_event']['id'])
                                                        db_handler.insert_communication({
                                                            "applicant_id": applicant_id, "gmail_message_id": sent_message['id'],
                                                            "sender": "HR (Sent from App)", "subject": st.session_state.dialog_title,
                                                            "body": st.session_state.dialog_body, "direction": "Outgoing"
                                                        })
                                                        st.success("Interview email sent successfully to both parties!")
                                                        # Clean up and close dialog
                                                        st.session_state.show_schedule_dialog = False
                                                        for key in list(st.session_state.keys()):
                                                            if key.startswith('dialog_') or key == 'available_slots':
                                                                del st.session_state[key]
                                                        st.rerun()
                                                    else:
                                                        st.error("Failed to send email.")
                                                else:
                                                    st.error("Failed to create calendar event.")
                        
                                if st.button("Close"):
                                    st.session_state.show_schedule_dialog = False
                                    st.rerun()
                        
                            schedule_dialog()

                elif selected_tab_index == 1: 
                    st.subheader("Log a New Note")
                    with st.form("note_form_tab", clear_on_submit=True):
                        history_df = load_status_history(applicant_id)
                        note_stages = ["General Note"] + [s for s in history_df['status_name'].unique() if s]
                        
                        note_type = st.selectbox("Note for Stage", options=note_stages)
                        note_content = st.text_area("Note / Feedback Content", height=100, placeholder="e.g., Candidate showed strong problem-solving skills...")
                        
                        submitted = st.form_submit_button("Save Note", use_container_width=True)
                        if submitted:
                            if note_content:
                                notes = get_feedback_notes(applicant['Feedback'])
                                new_note = {
                                    "id": str(uuid.uuid4()), 
                                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), 
                                    "stage": note_type, 
                                    "author": "HR", 
                                    "note": note_content
                                }
                                notes.append(new_note)
                                
                                for note in notes:
                                    if isinstance(note.get('timestamp'), datetime.datetime):
                                        note['timestamp'] = note['timestamp'].isoformat()
                                
                                if db_handler.update_applicant_feedback(applicant_id, json.dumps(notes)):
                                    st.success("Note saved!")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error("Failed to save note.")
                            else:
                                st.warning("Note cannot be empty.")
                    
                    st.divider()
                    render_feedback_dossier(applicant_id, applicant['Feedback'])

                elif selected_tab_index == 2: 
                    st.subheader("Email Hub")
                    conversations = load_conversations(applicant_id)
                    with st.container(height=300):
                        if conversations.empty: st.info("No communication history found for this applicant.")
                        else:
                            for _, comm in conversations.iterrows():
                                with st.chat_message("user" if comm['direction'] == 'Incoming' else "assistant"):
                                    st.markdown(f"**From:** {comm['sender']}<br>**Subject:** {comm.get('subject', 'N/A')}<hr>{comm['body']}", unsafe_allow_html=True)
                    
                    with st.form(f"email_form_{applicant_id}"):
                        email_body_content = st_quill(value=f"Dear {applicant['Name']},\n\n", html=True, key=f"quill_{applicant_id}")
                        uploaded_file = st.file_uploader("Attach a file", type=['pdf', 'docx', 'jpg', 'png'])
                        
                        disable_form = not applicant['Email'] or pd.isna(applicant['Email'])
                        if disable_form:
                            st.warning("Cannot send email: Applicant has no email address.")

                        if st.form_submit_button("Send Email", use_container_width=True, disabled=disable_form):
                            if email_body_content and len(email_body_content) > 15:
                                subject = f"Re: Your application for {applicant['Role']}"
                                with st.spinner("Sending..."):
                                    thread_id = applicant['GmailThreadId'] if pd.notna(applicant['GmailThreadId']) else None
                                    
                                    msg = email_handler.send_email(applicant['Email'], subject, email_body_content, thread_id, attachment=uploaded_file)
                                    
                                    if msg:
                                        st.success("Email sent successfully!")
                                        db_handler.insert_communication({
                                            "applicant_id": applicant_id, 
                                            "gmail_message_id": msg['id'], 
                                            "sender": "HR (Sent from App)", 
                                            "subject": subject, 
                                            "body": email_body_content, 
                                            "direction": "Outgoing"
                                        })

                                        if not thread_id and msg.get('threadId'):
                                            db_handler.update_applicant_thread_id(applicant_id, msg['threadId'])

                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error("Failed to send email.")
                            else:
                                st.warning("Email body is too short.")

    elif st.session_state.main_tab == "System Settings":
        st.header("Manage System Settings")
        st.markdown("Add or remove statuses and interviewers available across the application.")
        st.divider()
        col_status, col_interviewer, col_jd = st.columns(3, gap="large")
        with col_status:
            st.subheader("Applicant Statuses")
            for status in status_list:
                c1, c2 = st.columns([4, 1]); c1.write(status)
                if status not in ["New", "Hired", "Rejected"]:
                    if c2.button("🗑️", key=f"del_status_{status}"):
                        err = db_handler.delete_status(status) 
                        if err: st.error(err)
                        else: st.success(f"Status '{status}' deleted."); st.cache_data.clear(); st.rerun()
            with st.form("new_status_form", clear_on_submit=True):
                new_status = st.text_input("Add New Status", label_visibility="collapsed", key="new_status_input")
                if st.form_submit_button("Add Status", use_container_width=True):
                    if new_status and db_handler.add_status(new_status):
                        st.success(f"Status '{new_status}' added.")
                        st.cache_data.clear()
                        st.rerun()
                    else: st.warning(f"Status '{new_status}' may already exist or is empty.")
        with col_interviewer:
            st.subheader("Interviewers")
            for _, interviewer in interviewer_list.iterrows():
                c1, c2 = st.columns([4, 1]); c1.text(f"{interviewer['name']} ({interviewer['email']})")
                if c2.button("🗑️", key=f"del_interviewer_{interviewer['id']}"):
                    if db_handler.delete_interviewer(interviewer['id']): st.success("Interviewer deleted."); st.cache_data.clear(); st.rerun()
                    else: st.error("Could not delete interviewer.")
            with st.form("new_interviewer_form", clear_on_submit=True):
                st.write("Add New Interviewer")
                name = st.text_input("Name", key="new_interviewer_name")
                email = st.text_input("Google Account Email", key="new_interviewer_email")
                if st.form_submit_button("Add Interviewer", use_container_width=True):
                    if name and email and db_handler.add_interviewer(name, email):
                        st.success("Interviewer added.")
                        st.cache_data.clear()
                        st.rerun()
                    else: st.warning("Please provide name and a unique email.")
                        
        with col_jd:
            st.subheader("Job Descriptions")
            jd_list = db_handler.get_job_descriptions()
            if not jd_list.empty:
                for _, jd in jd_list.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"[{jd['name']}]({jd['drive_url']})")
                    if c2.button("🗑️", key=f"del_jd_{jd['id']}"):
                        if db_handler.delete_job_description(jd['id']):
                            st.success(f"JD '{jd['name']}' deleted.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Could not delete JD.")
        
            with st.form("new_jd_form", clear_on_submit=True):
                st.write("Add New Job Description")
                jd_name = st.text_input("JD Name (e.g., AI Engineer JD)")
                jd_file = st.file_uploader("Upload JD File (PDF/DOCX)", type=['pdf', 'docx'])
                if st.form_submit_button("Add Job Description", use_container_width=True):
                    if jd_name and jd_file:
                        with st.spinner("Uploading to Drive and saving..."):
                            # Save temp file to upload
                            import os
                            temp_file_path = f"/tmp/{uuid.uuid4()}_{jd_file.name}"
                            with open(temp_file_path, "wb") as f:
                                f.write(jd_file.getbuffer())
        
                            # Upload and get URL
                            drive_url = drive_handler.upload_to_drive(temp_file_path, new_file_name=jd_file.name)
        
                            # Clean up
                            os.remove(temp_file_path)
        
                            if drive_url and db_handler.add_job_description(jd_name, drive_url, jd_file.name):
                                st.success(f"JD '{jd_name}' added.")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Failed to add JD.")
                    else:
                        st.warning("Please provide both name and a file.")
        # st.subheader("🔴 Danger Zone")
        # with st.expander("Reset Application Data"):
        #     st.warning("**WARNING:** This action is irreversible. It will permanently delete all applicants, communications, and history from the database.")
            
        #     if 'confirm_delete_db' not in st.session_state:
        #         st.session_state.confirm_delete_db = False

        #     if st.button("Initiate Database Reset", type="primary"):
        #         st.session_state.confirm_delete_db = True
            
        #     if st.session_state.confirm_delete_db:
        #         st.write("To confirm, please type **DELETE ALL DATA** in the box below.")
        #         confirmation_text = st.text_input("Confirmation Phrase", placeholder="DELETE ALL DATA")
                
        #         if st.button("✅ Confirm and Delete All Data", disabled=(confirmation_text != "DELETE ALL DATA")):
        #             with st.spinner("Deleting all data and resetting tables..."):
        #                 if db_handler.clear_all_tables():
        #                     st.success("Database cleared successfully.")
        #                     db_handler.create_tables()
        #                     st.info("Application tables have been reset.")
        #                     st.session_state.confirm_delete_db = False
        #                     st.cache_data.clear()
        #                     st.cache_resource.clear()
        #                     st.rerun()
        #                 else:
        #                     st.error("An error occurred while clearing the database.")


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
            st.error(f"Error during authentication: {e}")
    else:
        flow = create_flow()
        authorization_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
        st.title("Welcome to HMS")
        st.write("Please log in with your Google Account to continue.")
        st.link_button("Login with Google", authorization_url, use_container_width=True)
else:
    run_app()













# import streamlit as st
# import pandas as pd
# import datetime
# import json
# import uuid
# import re
# import asyncio
# import requests
# from zoneinfo import ZoneInfo
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import Flow
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError
# from typing import Dict, Any

# # ---  Application Modules ---
# from modules.database_handler import DatabaseHandler
# from modules.drive_handler import DriveHandler
# from modules.email_handler import EmailHandler
# from modules.calendar_handler import CalendarHandler
# from modules.sheet_updater import SheetsUpdater
# from processing_engine import ProcessingEngine
# from modules.importer import Importer
# from streamlit_quill import st_quill

# # --- Page Configuration ---
# st.set_page_config(page_title="HR Applicant Dashboard", page_icon="📑", layout="wide")
# if 'active_detail_tab' not in st.session_state: st.session_state.active_detail_tab = "Profile"

# # --- Authentication Setup ---
# def create_flow():
#     """
#     Creates a Google OAuth Flow object. It uses secrets for deployment 
#     and a local credentials.json file for development.
#     """
#     try:
#         with open('credentials.json') as f:
#             client_config = json.load(f)
#         redirect_uri = "http://localhost:8501"
#     except FileNotFoundError:
#         client_config = {
#             "web": {
#                 "client_id": st.secrets["GOOGLE_CLIENT_ID"],
#                 "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
#                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#                 "token_uri": "https://oauth2.googleapis.com/token",
#                 "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
#                 "redirect_uris": [st.secrets["REDIRECT_URI"]],
#             }
#         }
#         redirect_uri = st.secrets["REDIRECT_URI"]

#     scopes = [
#         'https://www.googleapis.com/auth/userinfo.profile',
#         'https://www.googleapis.com/auth/userinfo.email',
#         'openid',
#         'https://www.googleapis.com/auth/gmail.readonly',
#         'https://www.googleapis.com/auth/gmail.modify',
#         'https://www.googleapis.com/auth/drive.file',
#         'https://www.googleapis.com/auth/spreadsheets',
#         'https://www.googleapis.com/auth/calendar'
#     ]
    
#     return Flow.from_client_config(
#         client_config=client_config,
#         scopes=scopes,
#         redirect_uri=redirect_uri
#     )

# # --- State Management Initialization ---
# if 'view_mode' not in st.session_state: st.session_state.view_mode = 'grid'
# if 'selected_applicant_id' not in st.session_state: st.session_state.selected_applicant_id = None
# if 'confirm_delete' not in st.session_state: st.session_state.confirm_delete = False
# if 'schedule_view_active' not in st.session_state: st.session_state.schedule_view_active = False
# if 'importer_expanded' not in st.session_state: st.session_state.importer_expanded = False
# if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
# if 'resume_uploader_key' not in st.session_state: st.session_state.resume_uploader_key = 0
# if 'show_sync_dialog' not in st.session_state: st.session_state.show_sync_dialog = False


# def run_app():
#     def logout():
#         """
#         Handles the logout process by revoking the Google token, clearing the session,
#         and cleaning the URL to ensure a fresh login state.
#         """
#         if 'credentials' in st.session_state:
#             creds = st.session_state.credentials
#             token_to_revoke = creds.refresh_token or creds.token
#             if token_to_revoke:
#                 try:
#                     requests.post('https://oauth2.googleapis.com/revoke',
#                         params={'token': token_to_revoke},
#                         headers={'content-type': 'application/x-www-form-urlencoded'})
#                 except Exception:
#                     pass

#         for key in list(st.session_state.keys()):
#             del st.session_state[key]
        
#         if 'code' in st.query_params:
#             st.query_params.clear()
        
#         st.rerun()
    
#     credentials = st.session_state.credentials

#     # --- Resource Initialization ---
#     @st.cache_resource
#     def get_db_handler(): return DatabaseHandler()
#     def get_email_handler(creds): return EmailHandler(creds)
#     def get_sheets_updater(creds): return SheetsUpdater(creds)
#     def get_calendar_handler(creds): return CalendarHandler(creds)
#     def get_importer(creds): return Importer(creds)
#     def get_drive_handler(creds): return DriveHandler(creds)

#     db_handler = get_db_handler()
#     email_handler = get_email_handler(credentials)
#     sheets_updater = get_sheets_updater(credentials)
#     calendar_handler = get_calendar_handler(credentials)
#     importer = get_importer(credentials)
#     drive_handler = DriveHandler(credentials)

#     # --- Callbacks for Importer ---
#     def handle_google_sheet_import():
#         sheet_url = st.session_state.g_sheet_url
#         if sheet_url and (sid := re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)):
#             with st.spinner("Reading & Importing from Google Sheet..."):
#                 data = sheets_updater.read_sheet_data(sid.group(1))
#                 if isinstance(data, pd.DataFrame) and not data.empty:
#                     inserted, skipped = importer._process_dataframe(data)
#                     st.success(f"Import complete! Added: {inserted}, Skipped: {skipped}.")
#                     st.session_state.g_sheet_url = ""
#                     st.cache_data.clear()
#                 else:
#                     st.error(f"Could not read data from sheet. {data}")
#         else:
#             st.warning("Please provide a valid Google Sheet URL.")
    
#     def handle_bulk_file_import():
#         uploader_key = f"bulk_uploader_{st.session_state.uploader_key}"
#         uploaded_file = st.session_state[uploader_key]
#         if uploaded_file:
#             with st.spinner("Processing file and importing..."):
#                 status_msg, count = importer.import_from_local_file(uploaded_file)
#                 st.success(status_msg)
#                 if count > 0:
#                     st.session_state.uploader_key += 1
#                     st.cache_data.clear()

#     def handle_resume_url_import():
#         resume_link = st.session_state.resume_url_input
#         if resume_link:
#             with st.spinner("Analyzing resume and creating profile..."):
#                 applicant_id = importer.import_from_resume(resume_link)
#                 if applicant_id:
#                     st.success(f"Successfully imported applicant. New ID: {applicant_id}")
#                     st.session_state.resume_url_input = ""
#                     st.cache_data.clear()
#                 else:
#                     st.error("Failed to import from resume link.")
#         else:
#             st.warning("Please provide a resume URL.")

#     def handle_local_resume_import():
#         uploader_key = f"resume_uploader_{st.session_state.resume_uploader_key}"
#         uploaded_resume = st.session_state[uploader_key]
#         if uploaded_resume:
#             with st.spinner("Analyzing resume and creating profile..."):
#                 applicant_id = importer.import_from_local_resume(uploaded_resume)
#                 if applicant_id:
#                     st.success(f"Successfully imported applicant. New ID: {applicant_id}")
#                     st.session_state.resume_uploader_key += 1
#                     st.cache_data.clear()
#                 else:
#                     st.error("Failed to import from resume file.")


#     # --- Data Loading & Caching Functions ---
#     @st.cache_data(ttl=300)
#     def load_all_applicants():
#         df = db_handler.fetch_applicants_as_df()
#         rename_map = {
#             'id': 'Id', 'name': 'Name', 'email': 'Email', 'phone': 'Phone', 'domain': 'Role',
#             'education': 'Education', 'job_history': 'JobHistory', 'cv_url': 'Resume', 'status': 'Status',
#             'feedback': 'Feedback', 'created_at': 'CreatedAt', 'gmail_thread_id': 'GmailThreadId',
#             'last_action_date': 'LastActionDate'
#         }
#         if not df.empty:
#             df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
#         return df

#     @st.cache_data(ttl=3600)
#     def load_statuses(): return db_handler.get_statuses()
#     @st.cache_data(ttl=3600)
#     def load_interviewers(): return db_handler.get_interviewers()
#     @st.cache_data(ttl=300)
#     def load_interviews(applicant_id): return db_handler.get_interviews_for_applicant(applicant_id) 
#     @st.cache_data(ttl=300)
#     def load_status_history(applicant_id): return db_handler.get_status_history(applicant_id) 
#     @st.cache_data(ttl=10) 
#     def load_conversations(applicant_id): return db_handler.get_conversations(applicant_id) 

#     # --- Callbacks and UI Functions ---
#     def set_detail_view(applicant_id):
#         st.session_state.view_mode = 'detail'
#         st.session_state.selected_applicant_id = applicant_id

#     def set_grid_view():
#         st.session_state.view_mode = 'grid'
#         st.session_state.selected_applicant_id = None
#         st.session_state.schedule_view_active = False
#         for key in list(st.session_state.keys()):
#             if key.startswith(('schedule_', 'available_slots_', 'select_', 'booking_success_message')):
#                 del st.session_state[key]

#     def get_feedback_notes(feedback_json_str):
#         if not feedback_json_str or not feedback_json_str.strip(): return []
#         try:
#             notes = json.loads(feedback_json_str)
#             for note in notes:
#                 if isinstance(note.get('timestamp'), str): note['timestamp'] = datetime.datetime.fromisoformat(note['timestamp'])
#             return notes
#         except (json.JSONDecodeError, TypeError):
#             return [{"id": str(uuid.uuid4()), "timestamp": datetime.datetime.now(datetime.timezone.utc), "stage": "Legacy Note", "author": "System", "note": feedback_json_str}]

#     def format_feedback_for_export(feedback_json_str):
#         notes = get_feedback_notes(feedback_json_str)
#         if not notes: return ""
#         sorted_notes = sorted(notes, key=lambda x: x['timestamp'])
#         return "\n---\n\n".join([f"Note for '{n['stage']}' ({n['timestamp'].astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b-%Y %I:%M %p')}):\n{n['note']}\n" for n in sorted_notes])

#     def render_dynamic_journey_tracker(status_history_df, current_status):
#         if status_history_df.empty and current_status == "New":
#             pipeline_stages = {"New": datetime.datetime.now(datetime.timezone.utc)}
#         else:
#             pipeline_stages = {
#                 row["status_name"]: row["changed_at"]
#                 for _, row in status_history_df.iterrows()
#             }
    
#         if current_status not in pipeline_stages:
#             pipeline_stages[current_status] = datetime.datetime.now(
#                 datetime.timezone.utc
#             )
   
#         if current_status == "Rejected":
#             st.error("**Process Ended: Applicant Rejected**", icon="✖️")
    
#         stage_names = list(pipeline_stages.keys())
#         if "Hired" in stage_names:
#             stage_names.remove("Hired")
#             stage_names.append("Hired")
#         if "Rejected" in stage_names:
#             stage_names.remove("Rejected")
#             stage_names.append("Rejected")
            
#         current_stage_index = (
#             stage_names.index(current_status) if current_status in stage_names else -1
#         )
#         num_stages = len(stage_names)
        
#         column_widths = [
#             3 if i % 2 == 0 else 0.5 for i in range(2 * num_stages - 1)
#         ]
        
#         if not column_widths: return

#         cols = st.columns(column_widths)
    
#         for i, stage_name in enumerate(stage_names):
#             with cols[i * 2]:
#                 icon, color, weight = ("⏳", "lightgrey", "normal")
#                 if i < current_stage_index:
#                     icon, color, weight = ("✅", "green", "normal")
#                 elif i == current_stage_index:
#                     icon, color, weight = ("➡️", "#007bff", "bold")
    
#                 if stage_name == "Hired":
#                     icon, color, weight = ("🎉", "green", "bold")
#                 if stage_name == "Rejected":  
#                     icon, color, weight = ("✖️", "#FF4B4B", "bold")
    
#                 timestamp = pipeline_stages.get(stage_name)
#                 time_str = (
#                     f"<p style='font-size: 11px; color: grey; margin: 0; "
#                     f"white-space: nowrap;'>"
#                     f"{timestamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b %I:%M %p')}"
#                     f"</p>"
#                 )
             
#                 st.markdown(
#                     f"""
#                     <div style='text-align: center; padding: 5px; border-radius: 10px;
#                                 background-color: #2E2E2E; margin: 2px;'>
#                         <p style='font-size: 24px; color: {color}; margin-bottom: -5px;'>
#                             {icon}
#                         </p>
#                         <p style='font-weight: {weight}; color: {color}; white-space: nowrap;'>
#                             {stage_name}
#                         </p>
#                         {time_str}
#                     </div>
#                     """,
#                     unsafe_allow_html=True,
#                 )
#             if i < num_stages - 1:
#                 with cols[i * 2 + 1]:
#                     st.markdown(
#                         "<p style='text-align: center; font-size: 24px; color: grey; "
#                         "margin-top: 35px;'>→</p>",
#                         unsafe_allow_html=True,
#                     )

#     def render_feedback_dossier(applicant_id, feedback_json_str):
#         st.subheader("Feedback & Notes")
#         all_notes = get_feedback_notes(feedback_json_str)
#         if not all_notes: st.info("No feedback notes have been logged for this applicant yet."); return
        
#         note_filter_stages = ["All Notes"] + list(pd.Series([n['stage'] for n in all_notes]).unique())
        
#         if f"note_filter_{applicant_id}" not in st.session_state:
#             st.session_state[f"note_filter_{applicant_id}"] = "All Notes"
            
#         selected_stage = st.radio("Filter notes by stage:", options=note_filter_stages, horizontal=True, key=f"note_filter_radio_{applicant_id}")
        
#         filtered_notes = all_notes if selected_stage == "All Notes" else [n for n in all_notes if n['stage'] == selected_stage]
#         sorted_notes = sorted(filtered_notes, key=lambda x: x['timestamp'], reverse=True)

#         if not sorted_notes: st.warning(f"No notes found for the stage: '{selected_stage}'")
#         else:
#             for note in sorted_notes:
#                 with st.container(border=True):
#                     time_str = note['timestamp'].astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b-%Y, %I:%M %p')
#                     st.markdown(f"**Note for: {note['stage']}** | <small>Logged on: {time_str}</small>", unsafe_allow_html=True)
#                     st.markdown(note['note'])


   
#     def render_api_monitoring(stats: Dict[str, Any]):
#         """Render API key pool monitoring information from a stats dictionary."""
#         st.subheader("🔑 API Key Pool Live Status")
        
#         # Overall status
#         col1, col2, col3, col4 = st.columns(4)
#         col1.metric("Total Keys", stats.get("total_keys", 0))
#         col2.metric("Available", stats.get("available_keys", 0))
#         col3.metric("Rate Limited", stats.get("rate_limited_keys", 0))
#         col4.metric("Failed", stats.get("failed_keys", 0))

#         # Status indicator
#         available = stats.get("available_keys", 0)
#         total = stats.get("total_keys", 1) # Avoid division by zero
#         if available == 0:
#             st.error("⚠️ No API keys available! Classification will fail.")
#         elif available / total < 0.3:
#             st.warning(f"⚠️ Low API key availability: {available}/{total} keys available")
#         else:
#             st.success(f"✅ API key pool healthy: {available}/{total} keys available")
        
#         # Usage statistics
#         if stats.get("usage_counts"):
#             st.caption("Key Usage Statistics")
#             usage_data = []
#             key_statuses = stats.get("key_statuses", {})
#             for i, (key, count) in enumerate(stats["usage_counts"].items(), 1):
#                 status = key_statuses.get(key, "Unknown")
#                 if status == "Failed": status_str = "🔴 Failed"
#                 elif status == "Rate Limited": status_str = "🟡 Rate Limited"
#                 else: status_str = "🟢 Available"
                
#                 usage_data.append({
#                     "Key": f"Key {i} ({key[:8]}...)",
#                     "Status": status_str,
#                     "Usage Count": count
#                 })
            
#             st.dataframe(usage_data, use_container_width=True, height=150)                
#     # --- Sidebar UI ---
#     with st.sidebar:
#         st.header(f"Welcome {st.session_state.user_info['given_name']}!")
#         st.image(st.session_state.user_info['picture'], width=80)

#         if st.button("📧 Sync New Emails & Replies", use_container_width=True, type="primary"):
#             st.session_state.show_sync_dialog = True
#             st.rerun()


#         # if st.button("📧 Sync New Emails & Replies", use_container_width=True, type="primary"):
#         #     try:
#         #         with st.spinner("Processing your inbox..."):
#         #             engine = ProcessingEngine(credentials)
#         #             summary = engine.run_once()
#         #             st.success(summary)
#         #             st.cache_data.clear()
#         #             st.rerun()
#         #     except HttpError as e:
#         #         if e.resp.status == 401: st.error("Authentication error. Please log out and log back in.", icon="🚨")
#         #         else: st.error(f"An error occurred: {e}", icon="🚨")
#         #     except Exception as e:
#         #         st.error(f"An unexpected error occurred: {e}", icon="🚨")
                
#         if st.button("Logout", use_container_width=True, on_click=logout):
#             pass
#         st.divider()

#         st.header("📋 Controls & Filters")
#         df_all = load_all_applicants()
#         df_filtered = df_all.copy()
        
#         search_query = st.text_input("Search by Name or Email" , placeholder="e.g Paras Kaushik ")
#         if search_query:
#             df_filtered = df_filtered[df_filtered['Name'].str.contains(search_query, case=False, na=False) | df_filtered['Email'].str.contains(search_query, case=False, na=False)]
        
#         status_list = ['All'] + load_statuses()
#         status_filter = st.selectbox("Filter by Status:", options=status_list)
#         if status_filter != 'All': df_filtered = df_filtered[df_filtered['Status'] == status_filter]
        
#         domain_options = ['All']
#         if not df_all.empty and 'Role' in df_all.columns:
#             domain_options.extend(sorted(df_all['Role'].dropna().unique().tolist()))
#         domain_filter = st.selectbox("Filter by Role:", options=domain_options)
#         if domain_filter != 'All' and 'Role' in df_filtered.columns:
#             df_filtered = df_filtered[df_filtered['Role'] == domain_filter]
        
#         st.divider()
#         if st.button("🔄 Refresh All Data", use_container_width=True): st.cache_data.clear(); st.rerun()

#         with st.expander("📂 Recent Exports"):
#             logs = db_handler.fetch_export_logs()
#             if logs.empty:
#                 st.info("No exports have been made yet.")
#             for _, log in logs.iterrows(): 
#                 col1, col2 = st.columns([4, 1])
#                 col1.markdown(f"• [{log['file_name']}]({log['sheet_url']})", unsafe_allow_html=True)
#                 if col2.button("🗑️", key=f"delete_log_{log['id']}", help="Delete this export log"):
#                     db_handler.delete_export_log(log['id'])
#                     st.success(f"Deleted log: {log['file_name']}")
#                     st.rerun()

#         importer_was_rendered = False
#         with st.expander("📥 Import Applicants", expanded=st.session_state.get('importer_expanded', False)):
#             importer_was_rendered = True
            
#             import_option = st.selectbox("Choose import method:", ["From local file (CSV/Excel)", "From Google Sheet", "From single resume URL", "From single resume file (PDF/DOCX)"])
            
#             # --- MODIFICATION START: Refactored importer with callbacks ---
#             if import_option == "From Google Sheet":
#                 st.text_input(
#                     "Paste Google Sheet URL",
#                     key="g_sheet_url",
#                      help="""
#                     - Your Google Sheet must be public or shared.
#                     - The first row must be the header.
#                     - Columns order: Name,Email,Phone,Education,JobHistory,Resume,Role,Status	
#                     """
#                 )
#                 st.button("Import from Sheet", on_click=handle_google_sheet_import)
            
#             elif import_option == "From local file (CSV/Excel)":
#                 st.file_uploader(
#                     "Choose a CSV or Excel file for bulk import",
#                     type=["csv", "xls", "xlsx"],
#                     key=f"bulk_uploader_{st.session_state.uploader_key}",
#                     help="""
#                     - Supported formats: CSV, XLS, XLSX.
#                     - The first row must be the header.
#                     - Columns order: Name,Email,Phone,Education,JobHistory,Resume,Role,Status	
#                     """
#                 )
#                 if st.session_state[f"bulk_uploader_{st.session_state.uploader_key}"]:
#                     st.button("Import from File", on_click=handle_bulk_file_import)

#             elif import_option == "From single resume URL":
#                 st.text_input(
#                     "Paste resume URL",
#                     key="resume_url_input",
#                     help="""
#                     - Paste a direct download link to a resume file.
#                     - For Google Drive, set sharing to "Anyone with the link".
#                     """
#                 )
#                 st.button("Import from Resume URL", on_click=handle_resume_url_import)
            
#             elif import_option == "From single resume file (PDF/DOCX)":
#                 st.file_uploader(
#                     "Upload a single resume",
#                     type=['pdf', 'docx'],
#                     key=f"resume_uploader_{st.session_state.resume_uploader_key}",
#                     help="- Upload a single resume in PDF or DOCX format."
#                 )
#                 if st.session_state[f"resume_uploader_{st.session_state.resume_uploader_key}"]:
#                     st.button("Import from Resume File", on_click=handle_local_resume_import)
#             # --- MODIFICATION END ---

#         st.session_state.importer_expanded = importer_was_rendered
#     if st.session_state.show_sync_dialog:
#         @st.dialog("🚀 Real-time Sync & API Status", width="large")
#         def sync_dialog():
#             # --- UI Placeholders ---
#             st.info("Sync process initiated. Please monitor the logs below.")
#             progress_bar = st.progress(0, text="Initializing...")
#             api_status_container = st.empty()
#             st.markdown("---")
#             st.subheader("📜 Live Log")
#             log_container = st.container(height=300)
#             log_messages = st.session_state.get("sync_log_messages", [])

#             def log_message(msg):
#                 log_messages.append(f"[{datetime.datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}] {msg}")
#                 st.session_state.sync_log_messages = log_messages
#                 with log_container:
#                     st.code("\n".join(log_messages[-20:]), language="log")

#             def update_api_display(engine_instance):
#                 with api_status_container:
#                     stats = engine_instance.get_classification_status()
#                     render_api_monitoring(stats)
            
#             # --- Processing Logic ---
#             try:
#                 # 1. Initialization
#                 engine = ProcessingEngine(credentials)
#                 engine.db_handler.create_tables()
#                 if not log_messages:
#                     log_message("Engine initialized. Checking for new applications...")
#                 update_api_display(engine)
                
#                 # 2. Process New Applications
#                 progress_bar.progress(5, text="Fetching new applications...")
#                 messages = engine.email_handler.fetch_unread_emails()
                
#                 new_app_count = 0
#                 failed_app_count = 0

#                 if not messages:
#                     log_message("No new applications found.")
#                 else:
#                     log_message(f"Found {len(messages)} new email(s) to process.")
#                     total_steps = len(messages)
#                     for i, msg in enumerate(messages):
#                         percent_done = 5 + int(45 * (i + 1) / total_steps)
#                         progress_bar.progress(percent_done, text=f"Processing application {i+1}/{len(messages)}...")
#                         log_message(f"-> Processing email ID: ...{msg['id'][-12:]}")
                        
#                         update_api_display(engine) 
#                         success = engine.process_single_email(msg['id'])
                        
#                         if success:
#                             new_app_count += 1
#                             log_message(f"✅ SUCCESS: Saved new applicant from email ...{msg['id'][-12:]}")
#                         else:
#                             failed_app_count += 1
#                             log_message(f"⚠️ FAILED: Could not process email ...{msg['id'][-12:]}. Check server logs for details.")
                        
#                         update_api_display(engine)
                
#                 # 3. Process Replies
#                 progress_bar.progress(50, text="Checking for replies...")
#                 log_message("Checking for replies in active threads...")
#                 reply_count = engine.process_replies()
#                 log_message(f"Found and saved {reply_count} new reply/replies.")

#                 # 4. Finalization
#                 progress_bar.progress(100, text="Sync complete!")
#                 summary = f"Sync finished! Processed {new_app_count} new applications ({failed_app_count} failures) and {reply_count} replies."
#                 st.success(summary)
#                 log_message(f"🎉 {summary}")
                
#                 if st.button("Close and Refresh Dashboard"):
#                     st.session_state.show_sync_dialog = False
#                     del st.session_state.sync_log_messages
#                     st.cache_data.clear()
#                     st.rerun()

#             except Exception as e:
#                 st.error(f"A critical error occurred: {e}")
#                 logger.error("Critical error during sync dialog", exc_info=True)
#                 if st.button("Close"):
#                     st.session_state.show_sync_dialog = False
#                     del st.session_state.sync_log_messages
#                     st.rerun()

#         if "sync_instance_started" not in st.session_state:
#              st.session_state.sync_instance_started = True
#              st.session_state.sync_log_messages = []
        
#         sync_dialog()
#     else:
#         # Cleanup state if dialog was closed without the button
#         if "sync_instance_started" in st.session_state:
#             del st.session_state.sync_instance_started
#         if "sync_log_messages" in st.session_state:
#             del st.session_state.sync_log_messages


#     # --- Main Page UI ---
#     st.title("Hiring Management System")
#     df_all = load_all_applicants()
#     st.markdown(f"### Displaying Applicants: {len(df_all)}")
#     status_list = load_statuses()
#     interviewer_list = load_interviewers()

#     active_tab = st.radio(
#         "Main Navigation",
#         ["Applicant Dashboard", "System Settings"],
#         horizontal=True,
#         label_visibility="collapsed",
#         key='main_tab'
#     )

#     if st.session_state.main_tab == "Applicant Dashboard":
#         if st.session_state.view_mode == 'grid':
            
#             def toggle_all(df):
#                 select_all_value = st.session_state.get('select_all_checkbox', False)
#                 for _, row in df.iterrows():
#                     st.session_state[f"select_{row['Id']}"] = select_all_value
            
#             st.checkbox("Select/Deselect All", key="select_all_checkbox", on_change=toggle_all, args=(df_filtered,))
            
#             header_cols = st.columns([0.5, 2.5, 2, 1.5, 2, 1.5, 2])
#             header_cols[0].markdown("")
#             header_cols[1].markdown("**Name**")
#             header_cols[2].markdown("**Role**")
#             header_cols[3].markdown("**Status**")
#             header_cols[4].markdown("**Applied On**")
#             header_cols[5].markdown("**Last Action**")
#             st.divider()
            
#             selected_ids = []
#             df_display = df_filtered.sort_values(by="LastActionDate", ascending=False, na_position='last') if "LastActionDate" in df_filtered.columns else df_filtered
#             for _, row in df_display.iterrows():
#                 row_cols = st.columns([0.5, 2.5, 2, 1.5, 2, 1.5, 2])
#                 is_selected = row_cols[0].checkbox("", key=f"select_{row['Id']}", value=st.session_state.get(f"select_{row['Id']}", False))
#                 if is_selected: selected_ids.append(int(row['Id']))
#                 row_cols[1].markdown(f"<div style='padding-top: 0.6rem;'><b>{row['Name']}</b></div>", unsafe_allow_html=True)
#                 row_cols[2].markdown(f"<div style='padding-top: 0.6rem;'><b>{str(row['Role'])}</b></div>", unsafe_allow_html=True)
#                 row_cols[3].markdown(f"<div style='padding-top: 0.6rem;'><b>{str(row['Status'])}</b></div>", unsafe_allow_html=True)
#                 row_cols[4].markdown(f"<div style='padding-top: 0.6rem;'><b>{row['CreatedAt'].strftime('%d-%b-%Y')}</b></div>", unsafe_allow_html=True)
#                 last_action_str = pd.to_datetime(row.get('LastActionDate')).strftime('%d-%b-%Y') if pd.notna(row.get('LastActionDate')) else "N/A"
#                 row_cols[5].markdown(f"<div style='padding-top: 0.6rem;'><b>{last_action_str}</b></div>", unsafe_allow_html=True)
#                 row_cols[6].button("View Profile ➜", key=f"view_{row['Id']}", on_click=set_detail_view, args=(row['Id'],))
            
#             with st.sidebar:
#                 st.divider(); st.header("🔥 Actions on Selected")
#                 if not selected_ids: st.info("Select applicants from the dashboard.")
#                 else:
#                     st.success(f"**{len(selected_ids)} applicant(s) selected.**")
#                     if st.button(f"Export {len(selected_ids)} to Sheet", use_container_width=True):
#                         with st.spinner("Generating Google Sheet..."):
#                             export_df = df_all[df_all['Id'].isin(selected_ids)].copy()
#                             export_df['Feedback'] = export_df['Feedback'].apply(format_feedback_for_export)
#                             cols = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Resume', 'Role', 'Status', 'Feedback']
#                             res = sheets_updater.create_export_sheet(export_df[cols].to_dict('records'), cols)
#                             if res: db_handler.insert_export_log(res['title'], res['url']); st.success("Export successful!"); st.rerun()
#                             else: st.error("Export failed.")
#                     if st.button(f"Delete {len(selected_ids)} Applicant(s)", type="primary", use_container_width=True): st.session_state.confirm_delete = True
#                     if st.session_state.confirm_delete:
#                         st.warning("This is permanent. Are you sure?", icon="⚠️")
#                         c1, c2 = st.columns(2);
#                         if c1.button("✅ Yes, Delete", use_container_width=True, type="primary"):
#                             if db_handler.delete_applicants(selected_ids): st.success("Applicants deleted."); st.session_state.confirm_delete = False; st.cache_data.clear(); st.rerun()
#                             else: st.error("Deletion failed.")
#                         if c2.button("❌ Cancel", use_container_width=True): st.session_state.confirm_delete = False; st.rerun()
#         elif st.session_state.view_mode == 'detail':
#             applicant_df = df_all[df_all['Id'] == st.session_state.selected_applicant_id]
#             if applicant_df.empty:
#                 st.warning("Applicant not found. They may have been deleted.")
#                 st.button("⬅️ Back to Dashboard", on_click=set_grid_view)
#             else:
#                 applicant = applicant_df.iloc[0]
#                 applicant_id = int(applicant['Id'])

#                 st.button("⬅️ Back to Dashboard", on_click=set_grid_view)
#                 if 'booking_success_message' in st.session_state:
#                     st.success(st.session_state.booking_success_message)
#                     del st.session_state.booking_success_message
                
#                 st.header(f"{applicant['Name']}")
#                 st.markdown(f"**Applying for:** `{applicant['Role']}` | **Current Status:** `{applicant['Status']}`")
#                 st.divider(); render_dynamic_journey_tracker(load_status_history(applicant_id), applicant['Status']); st.divider()

#                 tab_options = ["**👤 Profile & Actions**", "**📈 Feedback & Notes**", "**💬 Email Hub**"]
                
#                 if f'detail_tab_index_{applicant_id}' not in st.session_state:
#                     st.session_state[f'detail_tab_index_{applicant_id}'] = 0
                
#                 selected_tab_index = st.radio(
#                     "Detail Navigation",
#                     options=range(len(tab_options)),
#                     format_func=lambda i: tab_options[i],
#                     index=st.session_state[f'detail_tab_index_{applicant_id}'], 
#                     horizontal=True,
#                     label_visibility="collapsed",
#                     key=f'detail_tab_index_{applicant_id}'
#                 )                
                
#                 if selected_tab_index == 0: 
#                     col1, col2 = st.columns([2, 1], gap="large")
#                     with col1:
#                         st.subheader("Applicant Details"); st.markdown(f"**Email:** `{applicant['Email']}`\n\n**Phone:** `{applicant['Phone'] or 'N/A'}`")
#                         st.link_button("📄 View Resume on Drive", url=applicant['Resume'] or "#", use_container_width=True, disabled=not applicant['Resume'])
#                         st.markdown("**Education**"); st.write(applicant['Education'] or "No details.")
#                         st.divider() 
#                         st.markdown("**Job History**"); st.markdown(applicant['JobHistory'] or "No details.", unsafe_allow_html=True)
#                     with col2:
#                         st.subheader("Actions")
#                         with st.form("status_form_tab"):
#                             st.markdown("**Change Applicant Status**")
#                             idx = status_list.index(applicant['Status']) if applicant['Status'] in status_list else 0
#                             new_status = st.selectbox("New Status", options=status_list, index=idx, label_visibility="collapsed")
#                             if st.form_submit_button("Save Status", use_container_width=True):
#                                 if db_handler.update_applicant_status(applicant_id, new_status): st.success("Status Updated!"); st.cache_data.clear(); st.rerun()
#                                 else: st.error("Update failed.")
#                         st.divider()
#                         st.markdown("**Interview Management**")
#                         interviews = load_interviews(applicant_id)
#                         if not interviews.empty:
#                             for _, interview in interviews.iterrows(): st.info(f"**Scheduled:** {interview['event_title']} on {interview['start_time'].strftime('%b %d, %Y')}")
#                         if not st.session_state.get(f'schedule_view_active_{applicant_id}', False):
#                             if st.button("🗓️ Schedule New Interview", use_container_width=True, type="secondary"): st.session_state[f'schedule_view_active_{applicant_id}'] = True; st.rerun()
#                         if st.session_state.get(f'schedule_view_active_{applicant_id}', False):
#                             with st.container(border=True):
#                                 st.write("**New Interview**"); 
#                                 jd_list = db_handler.get_job_descriptions()
#                                 jd_options = {jd['name']: {'drive_url': jd['drive_url'], 'name': jd['name']} for _, jd in jd_list.iterrows()}
#                                 jd_options["None (Don't attach)"] = None
                        
#                                 with st.form(f"schedule_form_{applicant_id}"):
#                                     # New fields for title and description
#                                     title = st.text_input("Interview Title", value=f"Interview: {applicant['Name']} for {applicant['Role']}")
#                                     desc = st.text_area("Event Description / Notes for Attendees", placeholder="First round technical interview for the specified role.", height=150)
                                    
#                                     opts = {f"{name} ({email})": email for name, email in zip(interviewer_list['name'], interviewer_list['email'])}
#                                     interviewer_display = st.selectbox("Interviewer", options=list(opts.keys()))
#                                     duration = st.selectbox("Duration (mins)", options=[30, 45, 60])
                                    
#                                     # New dropdown for JDs
#                                     selected_jd_name = st.selectbox("Attach Job Description", options=list(jd_options.keys()))
                        
#                                     if st.form_submit_button("Find Available Times", use_container_width=True):
#                                         # Store all form data in session state to use after finding times
#                                         st.session_state[f'schedule_interviewer_{applicant_id}'] = opts[interviewer_display]
#                                         st.session_state[f'schedule_duration_{applicant_id}'] = duration
#                                         st.session_state[f'schedule_title_{applicant_id}'] = title
#                                         st.session_state[f'schedule_desc_{applicant_id}'] = desc
#                                         st.session_state[f'schedule_jd_{applicant_id}'] = jd_options[selected_jd_name]
                                        
#                                         with st.spinner("Finding open slots..."):
#                                             st.session_state[f'available_slots_{applicant_id}'] = calendar_handler.find_available_slots(opts[interviewer_display], duration)
#                                         if not st.session_state.get(f'available_slots_{applicant_id}'):
#                                             st.warning("No available slots found.")
                        
#                                 if st.session_state.get(f'available_slots_{applicant_id}'):
#                                     slots = st.session_state[f'available_slots_{applicant_id}']
#                                     slot_options = {s.strftime('%A, %b %d at %I:%M %p'): s for s in slots}
                                    
#                                     with st.form(f"booking_form_{applicant_id}"):
#                                         final_slot_str = st.selectbox("Select Confirmed Time:", options=list(slot_options.keys()))
                                        
#                                         if st.form_submit_button("✅ Confirm & Book Interview", use_container_width=True):
#                                             start_time = slot_options[final_slot_str]
#                                             end_time = start_time + datetime.timedelta(minutes=st.session_state[f'schedule_duration_{applicant_id}'])
                                            
#                                             # Retrieve all data from session state
#                                             interviewer_email = st.session_state[f'schedule_interviewer_{applicant_id}']
#                                             event_title = st.session_state[f'schedule_title_{applicant_id}']
#                                             event_desc = st.session_state[f'schedule_desc_{applicant_id}']
#                                             jd_to_attach = st.session_state[f'schedule_jd_{applicant_id}']
#                                             resume_to_attach = applicant['Resume'] if pd.notna(applicant['Resume']) else None
                        
#                                             event = calendar_handler.create_calendar_event(
#                                                 applicant['Name'], applicant['Email'], interviewer_email, 
#                                                 start_time, end_time, event_title, event_desc,
#                                                 resume_url=resume_to_attach, jd_info=jd_to_attach
#                                             )
                                            
#                                             if event:
#                                                 i_id = interviewer_list[interviewer_list['email'] == interviewer_email].iloc[0]['id']
#                                                 db_handler.log_interview(applicant_id, i_id, event['summary'], start_time, end_time, event['id'])
                                                
#                                                 st.session_state.booking_success_message = f"✅ Interview confirmed with {applicant['Name']} for {final_slot_str}."
#                                                 # Clean up all scheduling-related session state keys
#                                                 for key in list(st.session_state.keys()):
#                                                     if key.startswith(f'schedule_') or key.startswith('available_slots_'):
#                                                         del st.session_state[key]
#                                                 st.cache_data.clear()
#                                                 st.rerun()
#                                             else:
#                                                 st.error("Failed to create calendar event.")
                        
#                                 if st.button("✖️ Cancel Scheduling", use_container_width=True, key="cancel_schedule"):
#                                     # Clean up keys on cancel
#                                     for key in list(st.session_state.keys()):
#                                         if key.startswith(f'schedule_') or key.startswith(f'available_slots_'):
#                                             del st.session_state[key]
#                                     st.session_state[f'schedule_view_active_{applicant_id}'] = False
#                                     st.rerun()

#                 elif selected_tab_index == 1: 
#                     st.subheader("Log a New Note")
#                     with st.form("note_form_tab"):
#                         history_df = load_status_history(applicant_id); note_stages = ["General Note"] + [s for s in history_df['status_name'].unique() if s]
#                         note_type = st.selectbox("Note for Stage", options=note_stages)
#                         note_content = st.text_area("Note / Feedback Content", height=100, placeholder="e.g., Candidate showed strong problem-solving skills...")
#                         if st.form_submit_button("Save Note", use_container_width=True):
#                             if note_content:
#                                 notes = get_feedback_notes(applicant['Feedback'])
#                                 new_note = {"id": str(uuid.uuid4()), "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stage": note_type, "author": "HR", "note": note_content}
#                                 notes.append(new_note)
#                                 for note in notes:
#                                     if isinstance(note['timestamp'], datetime.datetime): note['timestamp'] = note['timestamp'].isoformat()
#                                 if db_handler.update_applicant_feedback(applicant_id, json.dumps(notes)): st.success("Note saved!"); st.cache_data.clear(); st.rerun()
#                                 else: st.error("Failed to save note.")
#                             else: st.warning("Note cannot be empty.")
#                     st.divider()
#                     render_feedback_dossier(applicant_id, applicant['Feedback'])

#                 elif selected_tab_index == 2: 
#                     st.subheader("Email Hub")
#                     conversations = load_conversations(applicant_id)
#                     with st.container(height=300):
#                         if conversations.empty: st.info("No communication history found for this applicant.")
#                         else:
#                             for _, comm in conversations.iterrows():
#                                 with st.chat_message("user" if comm['direction'] == 'Incoming' else "assistant"):
#                                     st.markdown(f"**From:** {comm['sender']}<br>**Subject:** {comm.get('subject', 'N/A')}<hr>{comm['body']}", unsafe_allow_html=True)
                    
#                     with st.form(f"email_form_{applicant_id}"):
#                         email_body_content = st_quill(value=f"Dear {applicant['Name']},\n\n", html=True, key=f"quill_{applicant_id}")
#                         uploaded_file = st.file_uploader("Attach a file", type=['pdf', 'docx', 'jpg', 'png'])
                        
#                         disable_form = not applicant['Email'] or pd.isna(applicant['Email'])
#                         if disable_form:
#                             st.warning("Cannot send email: Applicant has no email address.")

#                         if st.form_submit_button("Send Email", use_container_width=True, disabled=disable_form):
#                             if email_body_content and len(email_body_content) > 15:
#                                 subject = f"Re: Your application for {applicant['Role']}"
#                                 with st.spinner("Sending..."):
#                                     thread_id = applicant['GmailThreadId'] if pd.notna(applicant['GmailThreadId']) else None
                                    
#                                     msg = email_handler.send_email(applicant['Email'], subject, email_body_content, thread_id, attachment=uploaded_file)
                                    
#                                     if msg:
#                                         st.success("Email sent successfully!")
#                                         db_handler.insert_communication({
#                                             "applicant_id": applicant_id, 
#                                             "gmail_message_id": msg['id'], 
#                                             "sender": "HR (Sent from App)", 
#                                             "subject": subject, 
#                                             "body": email_body_content, 
#                                             "direction": "Outgoing"
#                                         })

#                                         if not thread_id and msg.get('threadId'):
#                                             db_handler.update_applicant_thread_id(applicant_id, msg['threadId'])

#                                         st.cache_data.clear()
#                                         st.rerun()
#                                     else:
#                                         st.error("Failed to send email.")
#                             else:
#                                 st.warning("Email body is too short.")

#     elif st.session_state.main_tab == "System Settings":
#         st.header("Manage System Settings")
#         st.markdown("Add or remove statuses and interviewers available across the application.")
#         st.divider()
#         col_status, col_interviewer, col_jd = st.columns(3, gap="large")
#         with col_status:
#             st.subheader("Applicant Statuses")
#             for status in status_list:
#                 c1, c2 = st.columns([4, 1]); c1.write(status)
#                 if status not in ["New", "Hired", "Rejected"]:
#                     if c2.button("🗑️", key=f"del_status_{status}"):
#                         err = db_handler.delete_status(status) 
#                         if err: st.error(err)
#                         else: st.success(f"Status '{status}' deleted."); st.cache_data.clear(); st.rerun()
#             with st.form("new_status_form", clear_on_submit=True):
#                 new_status = st.text_input("Add New Status", label_visibility="collapsed", key="new_status_input")
#                 if st.form_submit_button("Add Status", use_container_width=True):
#                     if new_status and db_handler.add_status(new_status):
#                         st.success(f"Status '{new_status}' added.")
#                         st.cache_data.clear()
#                         st.rerun()
#                     else: st.warning(f"Status '{new_status}' may already exist or is empty.")
#         with col_interviewer:
#             st.subheader("Interviewers")
#             for _, interviewer in interviewer_list.iterrows():
#                 c1, c2 = st.columns([4, 1]); c1.text(f"{interviewer['name']} ({interviewer['email']})")
#                 if c2.button("🗑️", key=f"del_interviewer_{interviewer['id']}"):
#                     if db_handler.delete_interviewer(interviewer['id']): st.success("Interviewer deleted."); st.cache_data.clear(); st.rerun()
#                     else: st.error("Could not delete interviewer.")
#             with st.form("new_interviewer_form", clear_on_submit=True):
#                 st.write("Add New Interviewer")
#                 name = st.text_input("Name", key="new_interviewer_name")
#                 email = st.text_input("Google Account Email", key="new_interviewer_email")
#                 if st.form_submit_button("Add Interviewer", use_container_width=True):
#                     if name and email and db_handler.add_interviewer(name, email):
#                         st.success("Interviewer added.")
#                         st.cache_data.clear()
#                         st.rerun()
#                     else: st.warning("Please provide name and a unique email.")
                        
#         with col_jd:
#             st.subheader("Job Descriptions")
#             jd_list = db_handler.get_job_descriptions()
#             if not jd_list.empty:
#                 for _, jd in jd_list.iterrows():
#                     c1, c2 = st.columns([4, 1])
#                     c1.markdown(f"[{jd['name']}]({jd['drive_url']})")
#                     if c2.button("🗑️", key=f"del_jd_{jd['id']}"):
#                         if db_handler.delete_job_description(jd['id']):
#                             st.success(f"JD '{jd['name']}' deleted.")
#                             st.cache_data.clear()
#                             st.rerun()
#                         else:
#                             st.error("Could not delete JD.")
        
#             with st.form("new_jd_form", clear_on_submit=True):
#                 st.write("Add New Job Description")
#                 jd_name = st.text_input("JD Name (e.g., AI Engineer JD)")
#                 jd_file = st.file_uploader("Upload JD File (PDF/DOCX)", type=['pdf', 'docx'])
#                 if st.form_submit_button("Add Job Description", use_container_width=True):
#                     if jd_name and jd_file:
#                         with st.spinner("Uploading to Drive and saving..."):
#                             # Save temp file to upload
#                             import os
#                             import uuid
#                             temp_file_path = f"/tmp/{uuid.uuid4()}_{jd_file.name}"
#                             with open(temp_file_path, "wb") as f:
#                                 f.write(jd_file.getbuffer())
        
#                             # Upload and get URL
#                             drive_url = drive_handler.upload_to_drive(temp_file_path, new_file_name=jd_file.name)
        
#                             # Clean up
#                             os.remove(temp_file_path)
        
#                             if drive_url and db_handler.add_job_description(jd_name, drive_url, jd_file.name):
#                                 st.success(f"JD '{jd_name}' added.")
#                                 st.cache_data.clear()
#                                 st.rerun()
#                             else:
#                                 st.error("Failed to add JD.")
#                     else:
#                         st.warning("Please provide both name and a file.")
#         # st.subheader("🔴 Danger Zone")
#         # with st.expander("Reset Application Data"):
#         #     st.warning("**WARNING:** This action is irreversible. It will permanently delete all applicants, communications, and history from the database.")
            
#         #     if 'confirm_delete_db' not in st.session_state:
#         #         st.session_state.confirm_delete_db = False

#         #     if st.button("Initiate Database Reset", type="primary"):
#         #         st.session_state.confirm_delete_db = True
            
#         #     if st.session_state.confirm_delete_db:
#         #         st.write("To confirm, please type **DELETE ALL DATA** in the box below.")
#         #         confirmation_text = st.text_input("Confirmation Phrase", placeholder="DELETE ALL DATA")
                
#         #         if st.button("✅ Confirm and Delete All Data", disabled=(confirmation_text != "DELETE ALL DATA")):
#         #             with st.spinner("Deleting all data and resetting tables..."):
#         #                 if db_handler.clear_all_tables():
#         #                     st.success("Database cleared successfully.")
#         #                     db_handler.create_tables()
#         #                     st.info("Application tables have been reset.")
#         #                     st.session_state.confirm_delete_db = False
#         #                     st.cache_data.clear()
#         #                     st.cache_resource.clear()
#         #                     st.rerun()
#         #                 else:
#         #                     st.error("An error occurred while clearing the database.")


# # --- Authentication Flow ---
# if 'credentials' not in st.session_state:
#     if 'code' in st.query_params:
#         try:
#             flow = create_flow()
#             flow.fetch_token(code=st.query_params['code'])

#             st.session_state.credentials = flow.credentials
#             user_info_service = build('oauth2', 'v2', credentials=st.session_state.credentials)
#             user_info = user_info_service.userinfo().get().execute()
#             st.session_state.user_info = user_info

#             st.query_params.clear()
            
#             st.rerun()

#         except Exception as e:
#             st.error(f"Error during authentication: {e}")
#     else:
#         flow = create_flow()
#         authorization_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
#         st.title("Welcome to HMS")
#         st.write("Please log in with your Google Account to continue.")
#         st.link_button("Login with Google", authorization_url, use_container_width=True)
# else:
#     run_app()










