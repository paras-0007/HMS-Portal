import streamlit as st
import pandas as pd
import datetime
import json
import uuid
import re
import requests
import time
import threading
import queue
from datetime import timedelta
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import plotly.express as px
import plotly.graph_objects as go
from streamlit_option_menu import option_menu

# Application Modules
from modules.database_handler import DatabaseHandler
from modules.drive_handler import DriveHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from processing_engine import ProcessingEngine
from modules.importer import Importer
from streamlit_quill import st_quill
from utils.logger import logger

# Page Configuration
st.set_page_config(
    page_title="HireFl.ai - Smart Hiring Platform",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Modern CSS styling
st.markdown("""
<style>
    /* Modern color scheme */
    :root {
        --primary-color: #6366f1;
        --secondary-color: #8b5cf6;
        --success-color: #10b981;
        --warning-color: #f59e0b;
        --danger-color: #ef4444;
        --dark-bg: #1f2937;
        --light-bg: #f9fafb;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Modern card styling */
    div[data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 600;
        color: var(--primary-color);
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 0.5rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, var(--primary-color) 0%, var(--secondary-color) 100%);
    }
    
    /* Metric card styling */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 0.75rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        border-left: 4px solid var(--primary-color);
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    
    /* Header gradient */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 1rem;
        color: white;
        margin-bottom: 2rem;
    }
    
    /* Table hover effect */
    tr:hover {
        background-color: #f3f4f6 !important;
        transition: background-color 0.2s;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
def init_session_state():
    defaults = {
        'view_mode': 'grid',
        'selected_applicant_id': None,
        'active_detail_tab': 'Profile',
        'confirm_delete': False,
        'schedule_view_active': False,
        'uploader_key': 0,
        'resume_uploader_key': 0,
        'show_sync_dialog': False,
        'sync_in_progress': False,
        'last_sync_time': None,
        'sync_results': {},
        'notification_queue': queue.Queue(),
        'selected_applicants': [],
        'filter_status': 'All',
        'filter_domain': 'All',
        'search_query': '',
        'cache_timestamp': None,
        'applicants_data': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Authentication Setup
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

# Utility Functions
def get_status_color(status):
    status = status.lower()
    if 'rejected' in status:
        return '#FF4B4B'
    elif 'hired' in status:
        return '#28a745'
    elif 'new' in status:
        return '#007bff'
    elif 'interview' in status:
        return '#ffc107'
    elif 'offer' in status:
        return '#17a2b8'
    else:
        return '#FFFFFF'

def download_file_from_url(url):
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if match:
        file_id = match.group(1)
        download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
        response = requests.get(download_url)
        if response.status_code == 200:
            return response.content
    return None

# Background sync function
def background_sync(engine, notification_queue):
    try:
        notification_queue.put(("info", "🔄 Starting email sync..."))
        new_apps = 0
        failed_classifications = 0
        
        messages = engine.email_handler.fetch_unread_emails()
        if messages:
            for msg in messages:
                success = engine.process_single_email(msg['id'])
                if success:
                    new_apps += 1
                else:
                    failed_classifications += 1
        
        new_replies = engine.process_replies()
        
        result = {
            'new_applications': new_apps,
            'failed_classifications': failed_classifications,
            'new_replies': new_replies,
            'timestamp': datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
        }
        
        st.session_state.sync_results = result
        st.session_state.last_sync_time = result['timestamp']
        
        if new_apps > 0:
            notification_queue.put(("success", f"✅ Processed {new_apps} new applications"))
        if failed_classifications > 0:
            notification_queue.put(("warning", f"⚠️ {failed_classifications} classifications failed"))
        if new_replies > 0:
            notification_queue.put(("info", f"📧 {new_replies} new replies received"))
        
        notification_queue.put(("success", "✅ Sync completed successfully"))
    except Exception as e:
        notification_queue.put(("error", f"❌ Sync failed: {str(e)}"))
        logger.error(f"Sync error: {e}", exc_info=True)
    finally:
        st.session_state.sync_in_progress = False

# Data Loading Functions
@st.cache_data(ttl=300)
def load_all_applicants(db_handler):
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
def load_statuses(db_handler):
    return db_handler.get_statuses()

@st.cache_data(ttl=3600)
def load_interviewers(db_handler):
    return db_handler.get_interviewers()

def set_detail_view(applicant_id):
    st.session_state.view_mode = 'detail'
    st.session_state.selected_applicant_id = applicant_id

def set_grid_view():
    st.session_state.view_mode = 'grid'
    st.session_state.selected_applicant_id = None
    st.session_state.schedule_view_active = False

# Modern Dashboard
def render_dashboard(db_handler, processing_engine):
    st.markdown("""
    <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">📊 Dashboard</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Real-time hiring analytics and insights</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sync status bar
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        if st.session_state.last_sync_time:
            time_diff = datetime.datetime.now(ZoneInfo("Asia/Kolkata")) - st.session_state.last_sync_time
            if time_diff < timedelta(minutes=1):
                sync_text = "Just now"
            elif time_diff < timedelta(hours=1):
                sync_text = f"{int(time_diff.total_seconds() / 60)} minutes ago"
            else:
                sync_text = st.session_state.last_sync_time.strftime("%I:%M %p")
            st.info(f"🕐 Last sync: {sync_text}")
        else:
            st.info("🕐 Not synced yet")
    
    with col2:
        if processing_engine:
            api_stats = processing_engine.get_classification_status()
            if api_stats:
                available = api_stats.get('available_keys', 0)
                total = api_stats.get('total_keys', 0)
                if available > 0:
                    st.success(f"✅ API Keys: {available}/{total} available")
                else:
                    st.error(f"❌ API Keys: All exhausted")
    
    with col3:
        if not st.session_state.sync_in_progress:
            if st.button("🔄 Sync Emails", use_container_width=True, key="sync_main"):
                st.session_state.sync_in_progress = True
                thread = threading.Thread(
                    target=background_sync,
                    args=(processing_engine, st.session_state.notification_queue)
                )
                thread.start()
                st.rerun()
        else:
            st.button("⏳ Syncing...", disabled=True, use_container_width=True)
    
    # Show notifications
    while not st.session_state.notification_queue.empty():
        msg_type, msg = st.session_state.notification_queue.get()
        if msg_type == "success":
            st.success(msg)
        elif msg_type == "error":
            st.error(msg)
        elif msg_type == "warning":
            st.warning(msg)
        else:
            st.info(msg)
    
    # Fetch data with caching
    if st.session_state.cache_timestamp is None or \
       (datetime.datetime.now() - st.session_state.cache_timestamp).total_seconds() > 30:
        st.session_state.applicants_data = load_all_applicants(db_handler)
        st.session_state.cache_timestamp = datetime.datetime.now()
    
    df = st.session_state.applicants_data
    
    # Metrics Row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("Total Applications", len(df), 
                  delta=f"+{st.session_state.sync_results.get('new_applications', 0)} new" 
                  if st.session_state.sync_results else None)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        new_count = len(df[df['Status'] == 'New']) if 'Status' in df.columns else 0
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("Unreviewed", new_count)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col3:
        shortlisted = len(df[df['Status'] == 'Shortlisted']) if 'Status' in df.columns else 0
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("Shortlisted", shortlisted)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col4:
        scheduled = len(df[df['Status'] == 'Interview Scheduled']) if 'Status' in df.columns else 0
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("Interviews", scheduled)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col5:
        hired = len(df[df['Status'] == 'Hired']) if 'Status' in df.columns else 0
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("Hired", hired)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Charts Row
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if 'Status' in df.columns and len(df) > 0:
            status_counts = df['Status'].value_counts()
            fig = px.pie(
                values=status_counts.values,
                names=status_counts.index,
                title="Application Status Distribution",
                color_discrete_sequence=px.colors.sequential.Purples_r
            )
            fig.update_traces(hovertemplate='<b>%{label}</b><br>Count: %{value}<br>%{percent}')
            fig.update_layout(height=350, font=dict(size=14))
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        if 'Role' in df.columns and len(df) > 0:
            domain_counts = df['Role'].value_counts().head(10)
            fig = px.bar(
                x=domain_counts.values,
                y=domain_counts.index,
                orientation='h',
                title="Top 10 Roles",
                color=domain_counts.values,
                color_continuous_scale="Viridis"
            )
            fig.update_layout(
                height=350,
                showlegend=False,
                font=dict(size=14),
                yaxis=dict(categoryorder='total ascending')
            )
            fig.update_traces(hovertemplate='<b>%{y}</b><br>Count: %{x}')
            st.plotly_chart(fig, use_container_width=True)
    
    # Timeline chart
    if 'CreatedAt' in df.columns and len(df) > 0:
        df['Date'] = pd.to_datetime(df['CreatedAt']).dt.date
        daily_counts = df.groupby('Date').size().reset_index(name='Applications')
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=daily_counts['Date'],
            y=daily_counts['Applications'],
            mode='lines+markers',
            line=dict(color='#6366f1', width=3),
            marker=dict(size=8, color='#8b5cf6'),
            fill='tozeroy',
            fillcolor='rgba(99, 102, 241, 0.1)'
        ))
        fig.update_layout(
            title="Application Trend",
            height=300,
            showlegend=False,
            font=dict(size=14),
            hovermode='x unified'
        )
        st.plotly_chart(fig, use_container_width=True)

# Main Application
def run_app():
    credentials = st.session_state.credentials
    
    # Initialize handlers
    db_handler = DatabaseHandler()
    email_handler = EmailHandler(credentials)
    sheets_updater = SheetsUpdater(credentials)
    calendar_handler = CalendarHandler(credentials)
    importer = Importer(credentials)
    drive_handler = DriveHandler(credentials)
    processing_engine = ProcessingEngine(credentials)
    
    # Sidebar
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0;">
            <h2 style="color: white; margin: 0;">HireFl.ai</h2>
            <p style="color: #cbd5e1; font-size: 0.9rem; margin-top: 0.5rem;">Smart Hiring Platform</p>
        </div>
        """, unsafe_allow_html=True)
        
        # User info
        if st.session_state.user_info:
            st.image(st.session_state.user_info['picture'], width=80)
            st.markdown(f"**{st.session_state.user_info['given_name']}**")
        
        st.divider()
        
        if st.button("🚪 Logout", use_container_width=True):
            logout()
        
        st.divider()
        
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Applicants", "Settings"],
            icons=["graph-up", "people", "gear"],
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#cbd5e1", "font-size": "18px"},
                "nav-link": {
                    "font-size": "16px",
                    "text-align": "left",
                    "margin": "0.5rem 0",
                    "padding": "0.75rem 1rem",
                    "color": "#cbd5e1",
                    "border-radius": "0.5rem",
                    "transition": "all 0.3s"
                },
                "nav-link-selected": {
                    "background-color": "#6366f1",
                    "color": "white",
                    "font-weight": "600"
                },
            }
        )
    
    # Main content routing
    if selected == "Dashboard":
        render_dashboard(db_handler, processing_engine)
    elif selected == "Applicants":
        st.info("Applicants view - Use your existing applicant management code here")
    elif selected == "Settings":
        st.info("Settings view - Use your existing settings code here")

# Authentication Flow
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
        # Modern login page
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
            <div style="text-align: center; padding: 3rem 0;">
                <h1 style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                           font-size: 3rem; font-weight: 800; margin-bottom: 1rem;">
                    HireFl.ai
                </h1>
                <p style="color: #6b7280; font-size: 1.2rem; margin-bottom: 2rem;">
                    Smart Hiring Platform with AI-Powered Automation
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            flow = create_flow()
            authorization_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
            st.link_button("🚀 Login with Google", authorization_url, use_container_width=True)
else:
    run_app()
