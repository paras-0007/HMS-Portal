import streamlit as st
import pandas as pd
import datetime
import json
import uuid
import re
import asyncio
from zoneinfo import ZoneInfo
from streamlit_google_oauth import StGoogleOauth
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

# ---  Application Modules ---
from modules.database_handler import DatabaseHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from processing_engine import ProcessingEngine # The new processing logic
from streamlit_quill import st_quill

# --- Page Configuration ---
st.set_page_config(page_title="HR Applicant Dashboard", page_icon="📑", layout="wide")

# --- Authentication Setup ---
try:
    # This block is for local development
    with open('credentials.json') as f:
        creds_json = json.load(f)
    CLIENT_ID = creds_json['web']['client_id']
    CLIENT_SECRET = creds_json['web']['client_secret']
    # For local testing, your OAuth Redirect URI in Google Cloud must be http://localhost:8501
    REDIRECT_URI = "http://localhost:8501" 
except FileNotFoundError:
    # This block is for Streamlit Cloud deployment
    CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
    REDIRECT_URI = st.secrets["REDIRECT_URI"]

# Define the scopes your app needs.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar',
    'openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'
]

# Create the authenticator object
authenticator = StGoogleOauth(CLIENT_ID, CLIENT_SECRET, scopes=SCOPES, redirect_uri=REDIRECT_URI)

# --- State Management Initialization ---
if 'view_mode' not in st.session_state: st.session_state.view_mode = 'grid'
if 'selected_applicant_id' not in st.session_state: st.session_state.selected_applicant_id = None
if 'confirm_delete' not in st.session_state: st.session_state.confirm_delete = False
if 'schedule_view_active' not in st.session_state: st.session_state.schedule_view_active = False

# --- Authentication Flow Function ---
async def login():
    """Handles the Google OAuth login flow."""
    token = await authenticator.get_authorization_code()
    if token:
        user_info = await authenticator.get_user_info(token['access_token'])
        creds = Credentials(
            token=token['access_token'], refresh_token=token.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=CLIENT_ID, client_secret=CLIENT_SECRET, scopes=token['scope'].split()
        )
        st.session_state.token = token
        st.session_state.user_info = user_info
        st.session_state.credentials = creds
        st.rerun()

# --- Main Application Logic: Check for Login Status ---
if 'token' not in st.session_state:
    st.title("Welcome to the HMS Automation System")
    st.write("Please log in with your Google Account to begin.")
    asyncio.run(login())
    st.stop()

# --- Post-Login Application ---
credentials = st.session_state.credentials

# --- Resource Initialization ---
@st.cache_resource
def get_db_handler(): return DatabaseHandler()

def get_email_handler(creds): return EmailHandler(creds)
def get_sheets_updater(creds): return SheetsUpdater(creds)
def get_calendar_handler(creds): return CalendarHandler(creds)

db_handler = get_db_handler()
email_handler = get_email_handler(credentials)
sheets_updater = get_sheets_updater(credentials)
calendar_handler = get_calendar_handler(credentials)

# --- Data Loading & Caching Functions ---
@st.cache_data(ttl=300)
def load_all_applicants():
    df = db_handler.fetch_applicants_as_df()
    rename_map = {
        'id': 'Id', 'name': 'Name', 'email': 'Email', 'phone': 'Phone', 'domain': 'Domain',
        'education': 'Education', 'job_history': 'JobHistory', 'cv_url': 'CvUrl', 'status': 'Status',
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
        pipeline_stages = {row['status_name']: row['changed_at'] for _, row in status_history_df.iterrows()}
    if current_status not in pipeline_stages: pipeline_stages[current_status] = datetime.datetime.now(datetime.timezone.utc)
    if "Rejected" in pipeline_stages and current_status != "Rejected": del pipeline_stages["Rejected"]
    if current_status == "Rejected": st.error("**Process Ended: Applicant Rejected**", icon="✖️"); return

    stage_names = list(pipeline_stages.keys())
    current_stage_index = stage_names.index(current_status) if current_status in stage_names else -1
    num_stages = len(stage_names)
    column_widths = [3 if i % 2 == 0 else 0.5 for i in range(2 * num_stages - 1)]
    cols = st.columns(column_widths)
    for i, stage_name in enumerate(stage_names):
        with cols[i*2]:
            icon, color, weight = ("⏳", "lightgrey", "normal")
            if i < current_stage_index: icon, color, weight = "✅", "green", "normal"
            elif i == current_stage_index: icon, color, weight = "➡️", "#007bff", "bold"
            if stage_name == "Hired": icon, color, weight = "🎉", "green", "bold"
            timestamp = pipeline_stages.get(stage_name)
            time_str = f"<p style='font-size: 11px; color: grey; margin: 0; white-space: nowrap;'>{timestamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d-%b %I:%M %p')}</p>"
            st.markdown(f"""<div style='text-align: center; padding: 5px; border-radius: 10px; background-color: #2E2E2E; margin: 2px;'>
                <p style='font-size: 24px; color: {color}; margin-bottom: -5px;'>{icon}</p>
                <p style='font-weight: {weight}; color: {color}; white-space: nowrap;'>{stage_name}</p>{time_str}</div>""", unsafe_allow_html=True)
        if i < num_stages - 1:
            with cols[i*2 + 1]: st.markdown("<p style='text-align: center; font-size: 24px; color: grey; margin-top: 35px;'>→</p>", unsafe_allow_html=True)

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

# --- Sidebar UI ---
with st.sidebar:
    st.header(f"Welcome, {st.session_state.user_info['given_name']}!")
    st.image(st.session_state.user_info['picture'], width=80)
    
    if st.button("📧 Sync New Emails & Replies", use_container_width=True, type="primary"):
        try:
            with st.spinner("Processing your inbox..."):
                engine = ProcessingEngine(credentials)
                summary = engine.run_once()
                st.success(summary)
                st.cache_data.clear()
                st.rerun()
        except HttpError as e:
            if e.resp.status == 401: st.error("Authentication error. Please log out and log back in.", icon="🚨")
            else: st.error(f"An error occurred: {e}", icon="🚨")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}", icon="🚨")
            
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.divider()

    st.header("📋 Controls & Filters")
    df_all = load_all_applicants()
    df_filtered = df_all.copy()
    
    search_query = st.text_input("Search by Name or Email")
    if search_query:
        df_filtered = df_filtered[df_filtered['Name'].str.contains(search_query, case=False, na=False) | df_filtered['Email'].str.contains(search_query, case=False, na=False)]
    
    status_list = ['All'] + load_statuses()
    status_filter = st.selectbox("Filter by Status:", options=status_list)
    if status_filter != 'All': df_filtered = df_filtered[df_filtered['Status'] == status_filter]
    
    domain_options = ['All']
    if not df_all.empty and 'Domain' in df_all.columns:
        domain_options.extend(sorted(df_all['Domain'].dropna().unique().tolist()))
    domain_filter = st.selectbox("Filter by Domain:", options=domain_options)
    if domain_filter != 'All' and 'Domain' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['Domain'] == domain_filter]
    
    st.divider()
    if st.button("🔄 Refresh All Data", use_container_width=True): st.cache_data.clear(); st.rerun()

    with st.expander("📂 History & Imports"):
        st.subheader("Recent Exports")
        for _, log in db_handler.fetch_export_logs().iterrows(): 
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"• [{log['file_name']}]({log['sheet_url']})", unsafe_allow_html=True)
            if col2.button("🗑️", key=f"delete_log_{log['id']}", help="Delete this export log"):
                db_handler.delete_export_log(log['id'])
                st.success(f"Deleted log: {log['file_name']}")
                st.rerun()
        st.subheader("Import from Sheet")
        sheet_url = st.text_input("Paste Google Sheet URL")
        if st.button("Import Applicants"):
            if sheet_url and (sid := re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)):
                with st.spinner("Reading & Importing..."):
                    data = sheets_updater.read_sheet_data(sid.group(1))
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        inserted, skipped = db_handler.insert_bulk_applicants(data)
                        st.success(f"Import complete! Added: {inserted}, Skipped: {skipped}."); st.cache_data.clear(); st.rerun()
                    else: st.error("Could not read data from sheet.")
            else: st.warning("Please provide a valid Google Sheet URL.")

# --- Main Page UI ---
st.title("HR Applicant Dashboard")
df_all = load_all_applicants()
st.markdown(f"### Displaying Applicants: {len(df_all)}")
status_list = load_statuses()
interviewer_list = load_interviewers()

main_tab1, main_tab2 = st.tabs(["Applicant Dashboard", "⚙️ System Settings"])

with main_tab1:
    if st.session_state.view_mode == 'grid':
        def toggle_all(df):
            select_all_value = st.session_state.get('select_all_checkbox', False)
            for _, row in df.iterrows(): st.session_state[f"select_{row['Id']}"] = select_all_value
        st.checkbox("Select/Deselect All Visible", key="select_all_checkbox", on_change=toggle_all, args=(df_filtered,))
        header_cols = st.columns([0.5, 3, 2, 1.5, 2, 1.5, 2]); header_cols[0].markdown(""); header_cols[1].markdown("**Name**"); header_cols[2].markdown("**Domain**"); header_cols[3].markdown("**Status**"); header_cols[4].markdown("**Applied On**"); header_cols[5].markdown("**Last Action**"); st.divider()
        selected_ids = []
        df_display = df_filtered.sort_values(by="LastActionDate", ascending=False, na_position='last') if "LastActionDate" in df_filtered.columns else df_filtered
        for _, row in df_display.iterrows():
            row_cols = st.columns([0.5, 3, 2, 1.5, 2, 1.5, 2])
            is_selected = row_cols[0].checkbox("", key=f"select_{row['Id']}", value=st.session_state.get(f"select_{row['Id']}", False))
            if is_selected: selected_ids.append(int(row['Id']))
            row_cols[1].markdown(f"**{row['Name']}**", unsafe_allow_html=True)
            row_cols[2].text(row['Domain']); row_cols[3].text(row['Status']); row_cols[4].text(row['CreatedAt'].strftime('%d-%b-%Y'))
            last_action_str = pd.to_datetime(row.get('LastActionDate')).strftime('%d-%b-%Y') if pd.notna(row.get('LastActionDate')) else "N/A"
            row_cols[5].text(last_action_str)
            row_cols[6].button("View Profile ➜", key=f"view_{row['Id']}", on_click=set_detail_view, args=(row['Id'],))
        with st.sidebar:
            st.divider(); st.header("🔥 Actions on Selected")
            if not selected_ids: st.info("Select applicants from the grid.")
            else:
                st.success(f"**{len(selected_ids)} applicant(s) selected.**")
                if st.button(f"Export {len(selected_ids)} to Sheet", use_container_width=True):
                    with st.spinner("Generating Google Sheet..."):
                        export_df = df_all[df_all['Id'].isin(selected_ids)].copy()
                        export_df['Feedback'] = export_df['Feedback'].apply(format_feedback_for_export)
                        cols = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'CvUrl', 'Domain', 'Status', 'Feedback']
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
        applicant = df_all[df_all['Id'] == st.session_state.selected_applicant_id].iloc[0]
        applicant_id = int(applicant['Id'])

        st.button("⬅️ Back to Dashboard", on_click=set_grid_view)
        if 'booking_success_message' in st.session_state:
            st.success(st.session_state.booking_success_message)
            del st.session_state.booking_success_message
        
        st.header(f"Profile: {applicant['Name']}")
        st.markdown(f"**Applying for:** `{applicant['Domain']}` | **Current Status:** `{applicant['Status']}`")
        st.divider(); render_dynamic_journey_tracker(load_status_history(applicant_id), applicant['Status']); st.divider()

        tab_profile, tab_timeline, tab_comms = st.tabs(["**👤 Profile & Actions**", "**📈 Feedback & Notes**", "**💬 Email Hub**"])
        with tab_profile:
            col1, col2 = st.columns([2, 1], gap="large")
            with col1:
                st.subheader("Applicant Details"); st.markdown(f"**Email:** `{applicant['Email']}`\n\n**Phone:** `{applicant['Phone'] or 'N/A'}`")
                st.link_button("📄 View Resume on Drive", url=applicant['CvUrl'] or "#", use_container_width=True, disabled=not applicant['CvUrl'])
                st.markdown("**Education**"); st.write(applicant['Education'] or "No details.")
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
                    for _, interview in interviews.iterrows(): st.info(f"**Scheduled:** {interview['event_title']} on {interview['start_time'].strftime('%b %d, %Y')}")
                if not st.session_state.get(f'schedule_view_active_{applicant_id}', False):
                    if st.button("🗓️ Schedule New Interview", use_container_width=True, type="secondary"): st.session_state[f'schedule_view_active_{applicant_id}'] = True; st.rerun()
                if st.session_state.get(f'schedule_view_active_{applicant_id}', False):
                    with st.container(border=True):
                        st.write("**New Interview**"); 
                        with st.form(f"schedule_form_{applicant_id}"):
                            opts = {f"{name} ({email})": email for name, email in zip(interviewer_list['name'], interviewer_list['email'])}
                            interviewer_display = st.selectbox("Interviewer", options=list(opts.keys()))
                            duration = st.selectbox("Duration (mins)", options=[30, 45, 60])
                            if st.form_submit_button("Find Times", use_container_width=True):
                                st.session_state[f'schedule_interviewer_{applicant_id}'] = opts[interviewer_display]
                                st.session_state[f'schedule_duration_{applicant_id}'] = duration
                                with st.spinner("Finding open slots..."): st.session_state[f'available_slots_{applicant_id}'] = calendar_handler.find_available_slots(opts[interviewer_display], duration)
                                if not st.session_state.get(f'available_slots_{applicant_id}'): st.warning("No available slots found.")
                        if st.session_state.get(f'available_slots_{applicant_id}'):
                            slots = st.session_state[f'available_slots_{applicant_id}']; slot_options = {s.strftime('%A, %b %d at %I:%M %p'): s for s in slots}
                            with st.form(f"booking_form_{applicant_id}"):
                                final_slot_str = st.selectbox("Confirmed Time:", options=list(slot_options.keys()))
                                desc = st.text_area("Description:", placeholder="First round technical interview for the Full Stack Developer role.")
                                if st.form_submit_button("✅ Confirm & Book", use_container_width=True):
                                    start_time = slot_options[final_slot_str]; end_time = start_time + datetime.timedelta(minutes=st.session_state[f'schedule_duration_{applicant_id}'])
                                    interviewer_email = st.session_state[f'schedule_interviewer_{applicant_id}']
                                    event = calendar_handler.create_calendar_event(applicant['Name'], applicant['Email'], interviewer_email, start_time, end_time, desc)
                                    if event:
                                        i_id = interviewer_list[interviewer_list['email'] == interviewer_email].iloc[0]['id']
                                        db_handler.log_interview(applicant_id, i_id, event['summary'], start_time, end_time, event['id'])
                                        
                                        st.session_state.booking_success_message = f"✅ Interview confirmed with {applicant['Name']} for {final_slot_str}."
                                        for key in list(st.session_state.keys()):
                                            if key.startswith(f'schedule_') or key.startswith('available_slots_'): del st.session_state[key]
                                        st.cache_data.clear(); st.rerun()
                                    else: st.error("Failed to create calendar event.")
                        if st.button("✖️ Cancel", use_container_width=True, key="cancel_schedule"): st.session_state.schedule_view_active = False; st.rerun()
        with tab_timeline:
            st.subheader("Log a New Note")
            with st.form("note_form_tab"):
                history_df = load_status_history(applicant_id); note_stages = ["General Note"] + [s for s in history_df['status_name'].unique() if s]
                note_type = st.selectbox("Note for Stage", options=note_stages)
                note_content = st.text_area("Note / Feedback Content", height=100, placeholder="e.g., Candidate showed strong problem-solving skills...")
                if st.form_submit_button("Save Note", use_container_width=True):
                    if note_content:
                        notes = get_feedback_notes(applicant['Feedback'])
                        new_note = {"id": str(uuid.uuid4()), "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stage": note_type, "author": "HR", "note": note_content}
                        notes.append(new_note)
                        for note in notes:
                            if isinstance(note['timestamp'], datetime.datetime): note['timestamp'] = note['timestamp'].isoformat()
                        if db_handler.update_applicant_feedback(applicant_id, json.dumps(notes)): st.success("Note saved!"); st.cache_data.clear(); st.rerun()
                        else: st.error("Failed to save note.")
                    else: st.warning("Note cannot be empty.")
            st.divider()
            render_feedback_dossier(applicant_id, applicant['Feedback'])
        with tab_comms:
            st.subheader("Communication Hub")
            with st.container(height=300):
                conversations = db_handler.get_conversations(applicant_id)
                if conversations.empty: st.info("No communication history found.")
                else:
                    for _, comm in conversations.iterrows():
                        with st.chat_message("user" if comm['direction'] == 'Incoming' else "assistant"):
                            st.markdown(f"**From:** {comm['sender']}<br>**Subject:** {comm.get('subject', 'N/A')}<hr>{comm['body']}", unsafe_allow_html=True)
            with st.form(f"email_form_{applicant_id}"):
                content = st_quill(value=f"Dear {applicant['Name']},\n\n", html=True)
                uploaded_file = st.file_uploader("Attach a file (PDF, DOCX, Image)", type=['pdf', 'docx', 'jpg', 'jpeg', 'png'])
                
                if st.form_submit_button("Send Email", use_container_width=True):
                    if content and len(content) > 15:
                        subject = f"Re: Your application for {applicant['Domain']}"
                        with st.spinner("Sending..."):
                            msg = email_handler.send_email(applicant['Email'], subject, content, applicant['GmailThreadId'], attachment=uploaded_file)
                            if msg:
                                db_handler.insert_communication({"applicant_id": applicant_id, "gmail_message_id": msg['id'], "sender": "HR", "subject": subject, "body": content, "direction": "Outgoing"})
                                st.success("Email sent!"); st.rerun()
                            else: st.error("Failed to send email.")
                    else: st.warning("Email body is too short.")
with main_tab2:
    st.header("Manage System Settings")
    st.markdown("Add or remove statuses and interviewers available across the application.")
    st.divider()
    col_status, col_interviewer = st.columns(2, gap="large")
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
            new_status = st.text_input("Add New Status", label_visibility="collapsed")
            if st.form_submit_button("Add Status", use_container_width=True):
                if new_status and db_handler.add_status(new_status): st.success(f"Status '{new_status}' added."); st.cache_data.clear(); st.rerun()
                else: st.warning(f"Status '{new_status}' may already exist.")
    with col_interviewer:
        st.subheader("Interviewers")
        for _, interviewer in interviewer_list.iterrows():
            c1, c2 = st.columns([4, 1]); c1.text(f"{interviewer['name']} ({interviewer['email']})")
            if c2.button("🗑️", key=f"del_interviewer_{interviewer['id']}"):
                if db_handler.delete_interviewer(interviewer['id']): st.success("Interviewer deleted."); st.cache_data.clear(); st.rerun()
                else: st.error("Could not delete interviewer.")
        with st.form("new_interviewer_form", clear_on_submit=True):
            st.write("Add New Interviewer"); name = st.text_input("Name"); email = st.text_input("Google Account Email")
            if st.form_submit_button("Add Interviewer", use_container_width=True):
                if name and email and db_handler.add_interviewer(name, email): st.success("Interviewer added."); st.cache_data.clear(); st.rerun()
                else: st.warning("Please provide name and a unique email.")