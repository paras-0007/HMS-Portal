import streamlit as st
import pandas as pd
import datetime
import json
import uuid
import re
import html
import requests
import plotly.express as px
import plotly.graph_objects as go
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Dict, Any

from modules.database_handler import DatabaseHandler
from modules.drive_handler import DriveHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from processing_engine import ProcessingEngine
from modules.importer import Importer
from streamlit_quill import st_quill

st.set_page_config(page_title="HireFl.ai - HMS", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    .main {
        padding: 0rem 1rem;
    }
    
    .stButton>button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    .metric-card-success {
        background: linear-gradient(135deg, #56ab2f 0%, #a8e063 100%);
    }
    
    .metric-card-warning {
        background: linear-gradient(135deg, #f2994a 0%, #f2c94c 100%);
    }
    
    .metric-card-info {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    }
    
    .applicant-card {
        background: rgba(255, 255, 255, 0.05);
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        transition: all 0.3s ease;
        cursor: pointer;
        margin-bottom: 1rem;
    }
    
    .applicant-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 16px rgba(0,0,0,0.15);
        border-color: #667eea;
        background: rgba(102, 126, 234, 0.1);
    }
    
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
    
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
    }
    
    [data-testid="stSidebar"] .stButton button {
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        background: rgba(255, 255, 255, 0.1) !important;
    }
    
    [data-testid="stSidebar"] .stButton button:hover {
        background: rgba(255, 255, 255, 0.2) !important;
        border-color: white !important;
    }
    
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] div {
        color: white !important;
    }
    
    .timeline-item {
        padding: 1rem;
        border-left: 3px solid #667eea;
        margin-left: 1rem;
        margin-bottom: 1rem;
        background: rgba(102, 126, 234, 0.05);
        border-radius: 0 8px 8px 0;
    }
    
    .chat-bubble {
        padding: 1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        max-width: 80%;
    }
    
    .chat-incoming {
        background: rgba(102, 126, 234, 0.1);
        margin-right: auto;
        border: 1px solid rgba(102, 126, 234, 0.2);
    }
    
    .chat-outgoing {
        background: rgba(86, 171, 47, 0.1);
        margin-left: auto;
        border: 1px solid rgba(86, 171, 47, 0.2);
    }
    
    .card-text {
        color: inherit;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def init_session_state():
    defaults = {
        'page': 'Dashboard',
        'selected_applicant_id': None,
        'confirm_delete': False,
        'show_sync_dialog': False,
        'sync_in_progress': False,
        'data_loaded': False,
        'applicants_data': None,
        'statuses_list': None,
        'interviewers_list': None,
        'jd_list': None,
        'last_refresh': None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

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
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/calendar'
    ]
    
    return Flow.from_client_config(
        client_config=client_config,
        scopes=scopes,
        redirect_uri=redirect_uri
    )

@st.cache_resource
def get_db_handler():
    return DatabaseHandler()

def load_all_data():
    """Load all data once into session state"""
    if not st.session_state.data_loaded:
        with st.spinner("Loading data..."):
            db = get_db_handler()
            st.session_state.applicants_data = db.fetch_applicants_as_df()
            st.session_state.statuses_list = db.get_statuses()
            st.session_state.interviewers_list = db.get_interviewers()
            st.session_state.jd_list = db.get_job_descriptions()
            st.session_state.data_loaded = True
            st.session_state.last_refresh = datetime.datetime.now()

def refresh_data():
    """Refresh all data from database"""
    db = get_db_handler()
    st.session_state.applicants_data = db.fetch_applicants_as_df()
    st.session_state.statuses_list = db.get_statuses()
    st.session_state.interviewers_list = db.get_interviewers()
    st.session_state.jd_list = db.get_job_descriptions()
    st.session_state.last_refresh = datetime.datetime.now()

def get_handlers(creds):
    if 'handlers' not in st.session_state:
        st.session_state.handlers = {
            'email': EmailHandler(creds),
            'sheets': SheetsUpdater(creds),
            'calendar': CalendarHandler(creds),
            'importer': Importer(creds),
            'drive': DriveHandler(creds),
            'processing': ProcessingEngine(creds)
        }
    return st.session_state.handlers

def get_status_color(status):
    status = status.lower()
    if 'rejected' in status: return '#eb3349'
    elif 'hired' in status: return '#56ab2f'
    elif 'new' in status: return '#4facfe'
    elif 'interview' in status: return '#f2994a'
    elif 'offer' in status: return '#667eea'
    else: return '#888888'

def create_metric_card(title, value, icon, gradient_class=""):
    return f"""
    <div class="metric-card {gradient_class}">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 0.9rem; opacity: 0.9; margin-bottom: 0.5rem;">{title}</div>
                <div style="font-size: 2.5rem; font-weight: 700;">{value}</div>
            </div>
            <div style="font-size: 3rem; opacity: 0.3;">{icon}</div>
        </div>
    </div>
    """

def render_sidebar(user_info):
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align: center; padding: 1rem 0 2rem 0;">
            <h1 style="font-size: 2rem; margin: 0; color: white !important;">🎯 HireFl.ai</h1>
            <p style="opacity: 0.9; font-size: 0.9rem; margin-top: 0.5rem; color: white !important;">Hiring Management System</p>
        </div>
        """, unsafe_allow_html=True)
        
        pages = {
            '📊 Dashboard': 'Dashboard',
            '👥 Applicants': 'Applicants',
            '💬 Communications': 'Communications',
            '📅 Interviews': 'Interviews',
            '📥 Import': 'Import',
            '📤 Export': 'Export',
            '⚙️ Settings': 'Settings'
        }
        
        for icon_label, page_name in pages.items():
            if st.button(icon_label, key=f"nav_{page_name}", use_container_width=True, 
                        type="primary" if st.session_state.page == page_name else "secondary"):
                st.session_state.page = page_name
                st.rerun()
        
        st.markdown("---")
        
        if st.button("🔄 Sync Emails & Replies", use_container_width=True, type="secondary"):
            st.session_state.show_sync_dialog = True
            st.rerun()
        
        st.markdown("---")
        st.markdown(f"""
        <div style="text-align: center; padding: 1rem;">
            <div style="opacity: 0.9; font-size: 0.85rem; color: white !important;">Logged in as</div>
            <div style="font-weight: 600; margin-top: 0.25rem; color: white !important;">{html.escape(user_info.get('name', 'User'))}</div>
            <div style="opacity: 0.8; font-size: 0.8rem; color: white !important;">{html.escape(user_info.get('email', ''))}</div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            logout()

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

@st.dialog("🔄 Sync Emails & Replies", width="large")
def show_sync_dialog(processing_engine):
    if not st.session_state.sync_in_progress:
        st.info("🔍 Ready to check for new applications and replies")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Start Sync", use_container_width=True, type="primary", key="start_sync_btn"):
                st.session_state.sync_in_progress = True
                st.rerun()
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key="cancel_sync_btn"):
                st.session_state.show_sync_dialog = False
                st.rerun()
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.write("🔍 Checking for new applications...")
        progress_bar.progress(25)
        new_apps, failed = processing_engine.process_new_applications()
        
        status_text.write("💬 Checking for replies...")
        progress_bar.progress(50)
        new_replies = processing_engine.process_replies()
        
        progress_bar.progress(100)
        status_text.write("✅ Sync completed!")
        
        st.success(f"**Results:** {new_apps} new application(s), {new_replies} new reply(ies)")
        if failed > 0:
            st.warning(f"⚠️ {failed} application(s) failed to process")
        
        refresh_data()
        
        if st.button("✔️ Done", use_container_width=True, type="primary", key="done_sync_btn"):
            st.session_state.show_sync_dialog = False
            st.session_state.sync_in_progress = False
            st.rerun()

def render_dashboard():
    st.markdown('<h1 style="margin-bottom: 2rem;">📊 Dashboard</h1>', unsafe_allow_html=True)
    
    applicants = st.session_state.applicants_data
    
    if applicants is None or applicants.empty:
        st.info("No applicants data available yet.")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(create_metric_card("Total Applicants", len(applicants), "👥", "metric-card-info"), unsafe_allow_html=True)
    
    with col2:
        new_count = len(applicants[applicants['status'] == 'New'])
        st.markdown(create_metric_card("New Applications", new_count, "🆕", ""), unsafe_allow_html=True)
    
    with col3:
        interview_count = len(applicants[applicants['status'].str.contains('Interview', case=False, na=False)])
        st.markdown(create_metric_card("In Interview", interview_count, "📋", "metric-card-warning"), unsafe_allow_html=True)
    
    with col4:
        hired_count = len(applicants[applicants['status'] == 'Hired'])
        st.markdown(create_metric_card("Hired", hired_count, "✅", "metric-card-success"), unsafe_allow_html=True)
    
    st.markdown("<div style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📈 Applications by Status")
        status_counts = applicants['status'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        
        fig = px.pie(status_counts, values='Count', names='Status', 
                    color_discrete_sequence=px.colors.qualitative.Set3,
                    hole=0.4)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(height=350, margin=dict(t=0, b=0, l=0, r=0), showlegend=True, 
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True, key="status_pie")
    
    with col2:
        st.markdown("### 🎯 Applications by Domain")
        domain_counts = applicants['domain'].value_counts().head(8).reset_index()
        domain_counts.columns = ['Domain', 'Count']
        
        fig = px.bar(domain_counts, x='Count', y='Domain', orientation='h',
                    color='Count', color_continuous_scale='Viridis')
        fig.update_layout(height=350, margin=dict(t=0, b=0, l=20, r=0), showlegend=False,
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True, key="domain_bar")
    
    st.markdown("<div style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    st.markdown("### 📅 Recent Activity Timeline")
    recent = applicants.sort_values('created_at', ascending=False).head(10)
    for idx, app in recent.iterrows():
        created_date = pd.to_datetime(app['created_at']).strftime('%b %d, %Y %I:%M %p')
        st.markdown(f"""
        <div class="timeline-item">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div class="card-text">
                    <strong>{html.escape(str(app['name']))}</strong> applied for <em>{html.escape(str(app['domain']))}</em>
                </div>
                <div style="opacity: 0.7; font-size: 0.85rem;" class="card-text">{created_date}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_applicants():
    st.markdown('<h1 style="margin-bottom: 1rem;">👥 Applicants</h1>', unsafe_allow_html=True)
    
    applicants = st.session_state.applicants_data
    status_list = st.session_state.statuses_list
    
    if applicants is None or applicants.empty:
        st.info("No applicants found. Import applicants or sync emails to get started.")
        return
    
    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 1, 1])
    
    with col1:
        search = st.text_input("🔍 Search", placeholder="Name, email, or domain...", label_visibility="collapsed", key="search_applicants")
    
    with col2:
        status_filter = st.multiselect("Filter by Status", options=status_list, default=[], placeholder="All Statuses", key="filter_status")
    
    with col3:
        domains = applicants['domain'].unique().tolist()
        domain_filter = st.multiselect("Filter by Domain", options=domains, default=[], placeholder="All Domains", key="filter_domain")
    
    with col4:
        view_mode = st.selectbox("View", ["Grid", "List"], label_visibility="collapsed", key="view_mode_select")
    
    with col5:
        sort_by = st.selectbox("Sort", ["Recent", "Name", "Status"], label_visibility="collapsed", key="sort_by_select")
    
    filtered = applicants.copy()
    
    if search:
        filtered = filtered[
            filtered['name'].str.contains(search, case=False, na=False) |
            filtered['email'].str.contains(search, case=False, na=False) |
            filtered['domain'].str.contains(search, case=False, na=False)
        ]
    
    if status_filter:
        filtered = filtered[filtered['status'].isin(status_filter)]
    
    if domain_filter:
        filtered = filtered[filtered['domain'].isin(domain_filter)]
    
    if sort_by == "Recent":
        filtered = filtered.sort_values('created_at', ascending=False)
    elif sort_by == "Name":
        filtered = filtered.sort_values('name')
    elif sort_by == "Status":
        filtered = filtered.sort_values('status')
    
    st.markdown(f"<p style='opacity: 0.7;'>Showing {len(filtered)} of {len(applicants)} applicants</p>", unsafe_allow_html=True)
    
    if view_mode == "Grid":
        cols = st.columns(3)
        for idx, (_, app) in enumerate(filtered.iterrows()):
            with cols[idx % 3]:
                status_color = get_status_color(app['status'])
                
                card_html = f"""
                <div class="applicant-card" style="min-height: 200px;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                        <h3 style="margin: 0;" class="card-text">{html.escape(str(app['name']))}</h3>
                        <span class="status-badge" style="background: {status_color}; color: white;">
                            {html.escape(str(app['status']))}
                        </span>
                    </div>
                    <div style="font-size: 0.9rem; margin-bottom: 0.5rem;" class="card-text">
                        <strong>📧</strong> {html.escape(str(app['email']))}<br>
                        <strong>📱</strong> {html.escape(str(app['phone']))}<br>
                        <strong>💼</strong> {html.escape(str(app['domain']))}
                    </div>
                    <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.85rem; opacity: 0.7;" class="card-text">
                        Applied: {pd.to_datetime(app['created_at']).strftime('%b %d, %Y')}
                    </div>
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)
                
                if st.button("View Details", key=f"view_{app['id']}", use_container_width=True):
                    st.session_state.selected_applicant_id = app['id']
                    st.session_state.page = 'Applicant Detail'
                    st.rerun()
    else:
        for _, app in filtered.iterrows():
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 1])
            
            with col1:
                st.write(f"**{app['name']}**")
                st.caption(app['email'])
            
            with col2:
                st.write(app['domain'])
            
            with col3:
                status_color = get_status_color(app['status'])
                st.markdown(f'<span class="status-badge" style="background: {status_color}; color: white;">{html.escape(str(app["status"]))}</span>', unsafe_allow_html=True)
            
            with col4:
                st.caption(pd.to_datetime(app['created_at']).strftime('%b %d, %Y'))
            
            with col5:
                if st.button("👁️", key=f"view_list_{app['id']}"):
                    st.session_state.selected_applicant_id = app['id']
                    st.session_state.page = 'Applicant Detail'
                    st.rerun()
            
            st.divider()

def render_applicant_detail(db_handler, handlers):
    applicant_id = st.session_state.selected_applicant_id
    applicants = st.session_state.applicants_data
    
    if applicants is None or applicants.empty:
        st.session_state.page = 'Applicants'
        st.rerun()
        return
    
    applicant_df = applicants[applicants['id'] == applicant_id]
    if applicant_df.empty:
        st.error("Applicant not found")
        st.session_state.page = 'Applicants'
        return
    
    applicant = applicant_df.iloc[0]
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f'<h1 style="margin-bottom: 0;">👤 {html.escape(str(applicant["name"]))}</h1>', unsafe_allow_html=True)
        st.caption(f"{applicant['domain']} • Applied on {pd.to_datetime(applicant['created_at']).strftime('%b %d, %Y')}")
    
    with col2:
        if st.button("← Back to Applicants", type="secondary", key="back_to_applicants"):
            st.session_state.page = 'Applicants'
            st.rerun()
    
    st.markdown("---")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Profile", "💬 Communications", "📅 Schedule Interview", "📝 Update Status", "🗑️ Actions"])
    
    with tab1:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Contact Information")
            st.write(f"**Email:** {applicant['email']}")
            st.write(f"**Phone:** {applicant['phone']}")
            st.write(f"**Domain:** {applicant['domain']}")
            
            st.subheader("Education")
            st.write(applicant.get('education', 'N/A'))
            
            st.subheader("Job History")
            if pd.notna(applicant.get('job_history')):
                st.markdown(applicant['job_history'])
            else:
                st.info("No job history available")
        
        with col2:
            status_color = get_status_color(applicant['status'])
            st.markdown(f"""
            <div style="background: {status_color}; color: white; padding: 1.5rem; border-radius: 12px; text-align: center; margin-bottom: 1rem;">
                <div style="font-size: 0.9rem; opacity: 0.9;">Current Status</div>
                <div style="font-size: 1.5rem; font-weight: 700; margin-top: 0.5rem;">{html.escape(str(applicant['status']))}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if pd.notna(applicant.get('cv_url')):
                st.link_button("📄 View Resume", applicant['cv_url'], use_container_width=True)
            
            if pd.notna(applicant.get('feedback')):
                st.subheader("Feedback")
                st.info(applicant['feedback'])
    
    with tab2:
        render_communications_tab(db_handler, handlers['email'], applicant_id, applicant)
    
    with tab3:
        render_schedule_tab(db_handler, handlers['calendar'], applicant_id, applicant)
    
    with tab4:
        render_update_status_tab(db_handler, applicant_id, applicant)
    
    with tab5:
        st.warning("⚠️ Danger Zone")
        if st.button("🗑️ Delete Applicant", type="secondary", key="delete_applicant_btn"):
            st.session_state.confirm_delete = True
        
        if st.session_state.confirm_delete:
            st.error("Are you sure? This action cannot be undone.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Yes, Delete", type="primary", key="confirm_delete_btn"):
                    if db_handler.delete_applicants([applicant_id]):
                        st.success("Applicant deleted successfully")
                        st.session_state.confirm_delete = False
                        st.session_state.page = 'Applicants'
                        refresh_data()
                        st.rerun()
            with col2:
                if st.button("❌ Cancel", key="cancel_delete_btn"):
                    st.session_state.confirm_delete = False
                    st.rerun()

def render_communications_tab(db_handler, email_handler, applicant_id, applicant):
    conversations = db_handler.get_conversations(applicant_id)
    
    if not conversations.empty:
        st.markdown(f"**{len(conversations)} Message(s) in Thread**")
        
        for idx, conv in conversations.iterrows():
            is_outgoing = conv['direction'] == 'Outgoing'
            bubble_class = 'chat-outgoing' if is_outgoing else 'chat-incoming'
            
            sender_text = html.escape(str(conv['sender']))
            subject_text = html.escape(str(conv['subject']))
            body_preview = html.escape(str(conv['body'])[:500])
            if len(str(conv['body'])) > 500:
                body_preview += '...'
            
            st.markdown(f"""
            <div class="chat-bubble {bubble_class}">
                <div style="font-weight: 600; margin-bottom: 0.5rem;">
                    {sender_text} <span style="opacity: 0.7; font-weight: 400; font-size: 0.85rem;">
                    • {pd.to_datetime(conv['sent_at']).strftime('%b %d, %Y %I:%M %p')}</span>
                </div>
                <div style="font-weight: 600; margin-bottom: 0.25rem;">{subject_text}</div>
                <div>{body_preview}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No communications yet")
    
    st.markdown("---")
    st.subheader("📧 Send Email")
    
    with st.form(key=f"email_form_{applicant_id}", clear_on_submit=True):
        subject = st.text_input("Subject", value=f"Re: Application for {applicant['domain']}")
        email_body = st.text_area("Message", height=200, placeholder="Type your message here...")
        uploaded_file = st.file_uploader("Attach File (optional)", type=['pdf', 'docx', 'jpg', 'png'])
        
        if st.form_submit_button("📤 Send Email", type="primary"):
            if email_body and len(email_body.strip()) > 10:
                with st.spinner("Sending..."):
                    thread_id = applicant['gmail_thread_id'] if pd.notna(applicant['gmail_thread_id']) else None
                    
                    attachments = None
                    if uploaded_file:
                        attachments = [{
                            'content': uploaded_file.getvalue(),
                            'filename': uploaded_file.name,
                            'maintype': 'application',
                            'subtype': 'octet-stream'
                        }]
                    
                    msg = email_handler.send_email([applicant['email']], subject, email_body, attachments)
                    
                    if msg:
                        st.success("Email sent successfully!")
                        db_handler.insert_communication({
                            "applicant_id": applicant_id,
                            "gmail_message_id": msg['id'],
                            "sender": "HR (Sent from App)",
                            "subject": subject,
                            "body": email_body,
                            "direction": "Outgoing"
                        })
                        
                        if not thread_id and msg.get('threadId'):
                            db_handler.update_applicant_thread_id(applicant_id, msg['threadId'])
                        
                        st.rerun()
                    else:
                        st.error("Failed to send email.")
            else:
                st.warning("Email body is too short.")

def render_schedule_tab(db_handler, calendar_handler, applicant_id, applicant):
    st.subheader("📅 Schedule Interview")
    
    interviewers = st.session_state.interviewers_list
    jd_list = st.session_state.jd_list
    
    if interviewers is None or interviewers.empty:
        st.warning("No interviewers configured. Add interviewers in Settings.")
        return
    
    interviewer_options = {f"{row['name']} ({row['email']})": row for _, row in interviewers.iterrows()}
    selected_interviewer_key = st.selectbox("Select Interviewer", options=list(interviewer_options.keys()), key=f"select_interviewer_{applicant_id}")
    selected_interviewer = interviewer_options[selected_interviewer_key]
    
    duration = st.slider("Interview Duration (minutes)", 30, 120, 60, 15, key=f"duration_{applicant_id}")
    
    event_title = st.text_input("Event Title", value=f"Interview with {applicant['name']}", key=f"event_title_{applicant_id}")
    
    jd_options = ["None"] + ([f"{row['name']}" for _, row in jd_list.iterrows()] if jd_list is not None and not jd_list.empty else [])
    selected_jd_name = st.selectbox("Attach Job Description (Optional)", options=jd_options, key=f"select_jd_{applicant_id}")
    
    if st.button("🔍 Find Available Slots", type="primary", key=f"find_slots_{applicant_id}"):
        with st.spinner("Searching for available slots..."):
            slots = calendar_handler.find_available_slots(selected_interviewer['email'], duration)
            
            if slots:
                st.success(f"Found {len(slots)} available slot(s)")
                st.session_state[f'available_slots_{applicant_id}'] = slots
            else:
                st.error("No available slots found in the next 7 days")
    
    if f'available_slots_{applicant_id}' in st.session_state:
        slots = st.session_state[f'available_slots_{applicant_id}']
        
        slot_options = {slot.strftime('%A, %B %d, %Y at %I:%M %p'): slot for slot in slots[:20]}
        selected_slot_str = st.selectbox("Select Time Slot", options=list(slot_options.keys()), key=f"select_slot_{applicant_id}")
        selected_slot = slot_options[selected_slot_str]
        
        if st.button("✅ Confirm & Schedule", type="primary", key=f"confirm_schedule_{applicant_id}"):
            with st.spinner("Creating calendar event..."):
                end_time = selected_slot + datetime.timedelta(minutes=duration)
                
                jd_info = None
                if selected_jd_name != "None" and jd_list is not None and not jd_list.empty:
                    jd_row = jd_list[jd_list['name'] == selected_jd_name].iloc[0]
                    jd_info = {"name": jd_row['name'], "url": jd_row['drive_url']}
                
                description = f"Interview with {applicant['name']} for {applicant['domain']} position.\n\n"
                description += f"Applicant Email: {applicant['email']}\n"
                description += f"Applicant Phone: {applicant['phone']}\n"
                if jd_info:
                    description += f"\nJob Description: {jd_info['url']}\n"
                if pd.notna(applicant.get('cv_url')):
                    description += f"Resume: {applicant['cv_url']}\n"
                
                result = calendar_handler.create_calendar_event(
                    applicant['name'],
                    applicant['email'],
                    selected_interviewer['email'],
                    selected_slot,
                    end_time,
                    event_title,
                    description,
                    applicant.get('cv_url'),
                    jd_info
                )
                
                if result:
                    google_event = result['google_event']
                    ics_data = result['ics_data']
                    
                    db_handler.log_interview(
                        applicant_id,
                        selected_interviewer['id'],
                        event_title,
                        selected_slot,
                        end_time,
                        google_event['id']
                    )
                    
                    attachments = [{
                        'content': ics_data.encode('utf-8'),
                        'filename': 'interview_invite.ics',
                        'maintype': 'text',
                        'subtype': 'calendar'
                    }]
                    
                    meet_link = google_event.get('hangoutLink', 'N/A')
                    email_body = f"""
                    <html>
                    <body>
                    <p>Dear {html.escape(applicant['name'])},</p>
                    <p>Your interview has been scheduled with {html.escape(selected_interviewer['name'])}.</p>
                    <p><strong>Date & Time:</strong> {selected_slot.strftime('%A, %B %d, %Y at %I:%M %p')} IST</p>
                    <p><strong>Duration:</strong> {duration} minutes</p>
                    <p><strong>Google Meet Link:</strong> <a href="{meet_link}">{meet_link}</a></p>
                    <p>Please find the calendar invite attached.</p>
                    <p>Best regards,<br>HR Team</p>
                    </body>
                    </html>
                    """
                    
                    email_handler.send_email(
                        [applicant['email']],
                        f"Interview Scheduled - {event_title}",
                        email_body,
                        attachments
                    )
                    
                    st.success("✅ Interview scheduled and invitation sent!")
                    del st.session_state[f'available_slots_{applicant_id}']
                    st.rerun()
                else:
                    st.error("Failed to create calendar event")

def render_update_status_tab(db_handler, applicant_id, applicant):
    st.subheader("📝 Update Status")
    
    status_list = st.session_state.statuses_list
    current_status = applicant['status']
    
    with st.form(key=f"status_form_{applicant_id}", clear_on_submit=False):
        new_status = st.selectbox("Select New Status", options=status_list, 
                                  index=status_list.index(current_status) if current_status in status_list else 0)
        
        if st.form_submit_button("💾 Update Status", type="primary"):
            if db_handler.update_applicant_status(applicant_id, new_status):
                st.success(f"Status updated to: {new_status}")
                refresh_data()
                st.rerun()
            else:
                st.error("Failed to update status")
    
    st.markdown("---")
    st.subheader("📋 Feedback")
    
    with st.form(key=f"feedback_form_{applicant_id}", clear_on_submit=False):
        feedback = st.text_area("Add Feedback or Notes", value=applicant.get('feedback', ''), height=150)
        
        if st.form_submit_button("💾 Save Feedback", type="primary"):
            if db_handler.update_applicant_feedback(applicant_id, feedback):
                st.success("Feedback saved successfully")
                refresh_data()
                st.rerun()
            else:
                st.error("Failed to save feedback")

def render_communications_page(db_handler):
    st.markdown('<h1 style="margin-bottom: 1rem;">💬 Communications</h1>', unsafe_allow_html=True)
    
    applicants = st.session_state.applicants_data
    
    if applicants is None or applicants.empty:
        st.info("No applicants with communications yet.")
        return
    
    search = st.text_input("🔍 Search applicant", placeholder="Name or email...", key="search_communications")
    
    filtered = applicants
    if search:
        filtered = applicants[
            applicants['name'].str.contains(search, case=False, na=False) |
            applicants['email'].str.contains(search, case=False, na=False)
        ]
    
    for idx, app in filtered.iterrows():
        conversations = db_handler.get_conversations(app['id'])
        
        with st.expander(f"💬 {app['name']} ({app['email']}) - {len(conversations)} message(s)"):
            if not conversations.empty:
                for _, conv in conversations.iterrows():
                    is_outgoing = conv['direction'] == 'Outgoing'
                    bubble_class = 'chat-outgoing' if is_outgoing else 'chat-incoming'
                    
                    sender_text = html.escape(str(conv['sender']))
                    subject_text = html.escape(str(conv['subject']))
                    body_preview = html.escape(str(conv['body'])[:300])
                    if len(str(conv['body'])) > 300:
                        body_preview += '...'
                    
                    st.markdown(f"""
                    <div class="chat-bubble {bubble_class}">
                        <div style="font-weight: 600; margin-bottom: 0.5rem;">
                            {sender_text} <span style="opacity: 0.7; font-weight: 400; font-size: 0.85rem;">
                            • {pd.to_datetime(conv['sent_at']).strftime('%b %d, %Y %I:%M %p')}</span>
                        </div>
                        <div style="font-weight: 600; margin-bottom: 0.25rem;">{subject_text}</div>
                        <div>{body_preview}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No communications for this applicant")
            
            if st.button(f"View Full Profile", key=f"view_profile_{app['id']}"):
                st.session_state.selected_applicant_id = app['id']
                st.session_state.page = 'Applicant Detail'
                st.rerun()

def render_interviews_page(db_handler):
    st.markdown('<h1 style="margin-bottom: 1rem;">📅 Interviews</h1>', unsafe_allow_html=True)
    
    db_handler._connect()
    if db_handler.conn:
        query = """
        SELECT 
            i.id as interview_id,
            i.applicant_id,
            a.name as applicant_name,
            i.interviewer_id,
            iv.name as interviewer_name,
            i.event_title,
            i.start_time,
            i.end_time,
            i.status
        FROM interviews i
        LEFT JOIN applicants a ON i.applicant_id = a.id
        LEFT JOIN interviewers iv ON i.interviewer_id = iv.id
        ORDER BY i.start_time DESC;
        """
        try:
            interviews = pd.read_sql_query(query, db_handler.conn)
        except Exception:
            interviews = pd.DataFrame()
    else:
        interviews = pd.DataFrame()
    
    if interviews.empty:
        st.info("No interviews scheduled yet.")
        return
    
    upcoming = interviews[interviews['start_time'] > datetime.datetime.now(ZoneInfo("Asia/Kolkata"))]
    past = interviews[interviews['start_time'] <= datetime.datetime.now(ZoneInfo("Asia/Kolkata"))]
    
    tab1, tab2 = st.tabs([f"📅 Upcoming ({len(upcoming)})", f"📋 Past ({len(past)})"])
    
    with tab1:
        if not upcoming.empty:
            for _, interview in upcoming.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                
                with col1:
                    st.write(f"**{interview['event_title']}**")
                    st.caption(interview['applicant_name'])
                
                with col2:
                    st.write(interview['interviewer_name'])
                
                with col3:
                    start_time = pd.to_datetime(interview['start_time'])
                    st.write(start_time.strftime('%b %d, %Y'))
                    st.caption(start_time.strftime('%I:%M %p'))
                
                with col4:
                    if st.button("👁️", key=f"view_interview_{interview['interview_id']}"):
                        st.session_state.selected_applicant_id = interview['applicant_id']
                        st.session_state.page = 'Applicant Detail'
                        st.rerun()
                
                st.divider()
        else:
            st.info("No upcoming interviews")
    
    with tab2:
        if not past.empty:
            for _, interview in past.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                
                with col1:
                    st.write(f"**{interview['event_title']}**")
                    st.caption(interview['applicant_name'])
                
                with col2:
                    st.write(interview['interviewer_name'])
                
                with col3:
                    start_time = pd.to_datetime(interview['start_time'])
                    st.write(start_time.strftime('%b %d, %Y'))
                    st.caption(start_time.strftime('%I:%M %p'))
                
                with col4:
                    if st.button("👁️", key=f"view_past_interview_{interview['interview_id']}"):
                        st.session_state.selected_applicant_id = interview['applicant_id']
                        st.session_state.page = 'Applicant Detail'
                        st.rerun()
                
                st.divider()
        else:
            st.info("No past interviews")

def render_import_page(db_handler, handlers):
    st.markdown('<h1 style="margin-bottom: 1rem;">📥 Import Applicants</h1>', unsafe_allow_html=True)
    
    tab1, tab2, tab3, tab4 = st.tabs(["📄 Upload File", "📊 Google Sheet", "🔗 Resume URL", "📎 Resume File"])
    
    with tab1:
        st.markdown("### Upload CSV or Excel File")
        uploaded_file = st.file_uploader("Choose file", type=['csv', 'xlsx', 'xls'], key="file_upload_import")
        
        if uploaded_file and st.button("📥 Import from File", type="primary", key="import_file_btn"):
            with st.spinner("Importing..."):
                message, count = handlers['importer'].import_from_local_file(uploaded_file)
                if count > 0:
                    st.success(message)
                    refresh_data()
                    st.rerun()
                else:
                    st.error(message)
    
    with tab2:
        st.markdown("### Import from Google Sheet")
        sheet_url = st.text_input("Google Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/...", key="g_sheet_url_import")
        
        if sheet_url and st.button("📥 Import from Sheet", type="primary", key="import_sheet_btn"):
            if sid := re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url):
                with st.spinner("Reading & Importing..."):
                    data = handlers['sheets'].read_sheet_data(sid.group(1))
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        inserted, skipped = handlers['importer']._process_dataframe(data)
                        st.success(f"Import complete! Added: {inserted}, Skipped: {skipped}")
                        refresh_data()
                        st.rerun()
                    else:
                        st.error("Could not read sheet data")
            else:
                st.warning("Please provide a valid Google Sheet URL")
    
    with tab3:
        st.markdown("### Import Single Resume from URL")
        resume_url = st.text_input("Resume URL (Google Drive)", placeholder="https://drive.google.com/file/d/...", key="resume_url_import")
        
        if resume_url and st.button("📥 Import Resume", type="primary", key="import_resume_url_btn"):
            with st.spinner("Downloading and processing..."):
                result = handlers['importer'].import_from_resume(resume_url)
                if result:
                    st.success("Resume imported successfully!")
                    refresh_data()
                    st.rerun()
                else:
                    st.error("Failed to import resume")
    
    with tab4:
        st.markdown("### Upload Resume File")
        resume_file = st.file_uploader("Choose resume", type=['pdf', 'docx'], key="resume_file_import")
        
        if resume_file and st.button("📥 Import Resume File", type="primary", key="import_resume_file_btn"):
            with st.spinner("Processing..."):
                result = handlers['importer'].import_from_local_resume(resume_file)
                if result:
                    st.success("Resume imported successfully!")
                    refresh_data()
                    st.rerun()
                else:
                    st.error("Failed to import resume")

def render_export_page(db_handler, handlers):
    st.markdown('<h1 style="margin-bottom: 1rem;">📤 Export Applicants</h1>', unsafe_allow_html=True)
    
    applicants = st.session_state.applicants_data
    status_list = st.session_state.statuses_list
    
    if applicants is None or applicants.empty:
        st.info("No applicants to export.")
        return
    
    st.markdown("### Filter & Export")
    
    col1, col2 = st.columns(2)
    
    with col1:
        status_filter = st.multiselect("Filter by Status", options=status_list, default=[], key="export_status_filter")
    
    with col2:
        domains = applicants['domain'].unique().tolist()
        domain_filter = st.multiselect("Filter by Domain", options=domains, default=[], key="export_domain_filter")
    
    filtered = applicants.copy()
    
    if status_filter:
        filtered = filtered[filtered['status'].isin(status_filter)]
    
    if domain_filter:
        filtered = filtered[filtered['domain'].isin(domain_filter)]
    
    st.markdown(f"**{len(filtered)} applicant(s) will be exported**")
    
    if st.button("📤 Export to Google Sheet", type="primary", disabled=filtered.empty, key="export_sheet_btn"):
        with st.spinner("Creating and populating Google Sheet..."):
            columns = ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Resume', 'Role', 'Status', 'Feedback']
            
            data_to_export = []
            for _, app in filtered.iterrows():
                data_to_export.append({
                    'Name': app['name'],
                    'Email': app['email'],
                    'Phone': app['phone'],
                    'Education': app.get('education', ''),
                    'JobHistory': app.get('job_history', ''),
                    'Resume': app.get('cv_url', ''),
                    'Role': app['domain'],
                    'Status': app['status'],
                    'Feedback': app.get('feedback', '')
                })
            
            result = handlers['sheets'].create_export_sheet(data_to_export, columns)
            
            if result:
                db_handler.insert_export_log(result['title'], result['url'])
                st.success("✅ Export successful!")
                st.markdown(f"[📊 Open Google Sheet]({result['url']})")
            else:
                st.error("Export failed")
    
    st.markdown("---")
    st.markdown("### 📋 Recent Exports")
    
    export_logs = db_handler.fetch_export_logs()
    
    if not export_logs.empty:
        for _, log in export_logs.iterrows():
            col1, col2, col3 = st.columns([3, 2, 1])
            
            with col1:
                st.markdown(f"[📊 {log['file_name']}]({log['sheet_url']})")
            
            with col2:
                created_date = pd.to_datetime(log['created_at']).strftime('%b %d, %Y %I:%M %p')
                st.caption(created_date)
            
            with col3:
                if st.button("🗑️", key=f"del_export_{log['id']}"):
                    if db_handler.delete_export_log(log['id']):
                        st.success("Deleted")
                        st.rerun()
    else:
        st.info("No recent exports")

def render_settings_page(db_handler, handlers):
    st.markdown('<h1 style="margin-bottom: 1rem;">⚙️ Settings</h1>', unsafe_allow_html=True)
    
    status_list = st.session_state.statuses_list
    interviewer_list = st.session_state.interviewers_list
    jd_list = st.session_state.jd_list
    
    tab1, tab2, tab3 = st.tabs(["📊 Statuses", "👥 Interviewers", "📄 Job Descriptions"])
    
    with tab1:
        st.markdown("### Manage Application Statuses")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if status_list:
                for status in status_list:
                    cols = st.columns([4, 1])
                    cols[0].write(status)
                    if status not in ["New", "Hired", "Rejected"]:
                        if cols[1].button("🗑️", key=f"del_status_{status}"):
                            err = db_handler.delete_status(status)
                            if err:
                                st.error(err)
                            else:
                                st.success(f"Deleted '{status}'")
                                refresh_data()
                                st.rerun()
        
        with col2:
            st.markdown("### Add Status")
            with st.form("new_status_form", clear_on_submit=True):
                new_status = st.text_input("Status Name")
                if st.form_submit_button("➕ Add", use_container_width=True):
                    if new_status and db_handler.add_status(new_status):
                        st.success(f"Added '{new_status}'")
                        refresh_data()
                        st.rerun()
                    else:
                        st.warning("Invalid or duplicate status")
    
    with tab2:
        st.markdown("### Manage Interviewers")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if interviewer_list is not None and not interviewer_list.empty:
                for _, interviewer in interviewer_list.iterrows():
                    cols = st.columns([4, 1])
                    cols[0].write(f"{interviewer['name']} ({interviewer['email']})")
                    if cols[1].button("🗑️", key=f"del_interviewer_{interviewer['id']}"):
                        if db_handler.delete_interviewer(interviewer['id']):
                            st.success("Deleted")
                            refresh_data()
                            st.rerun()
            else:
                st.info("No interviewers configured")
        
        with col2:
            st.markdown("### Add Interviewer")
            with st.form("new_interviewer_form", clear_on_submit=True):
                name = st.text_input("Name")
                email = st.text_input("Email")
                if st.form_submit_button("➕ Add", use_container_width=True):
                    if name and email and db_handler.add_interviewer(name, email):
                        st.success("Added interviewer")
                        refresh_data()
                        st.rerun()
                    else:
                        st.warning("Invalid or duplicate email")
    
    with tab3:
        st.markdown("### Manage Job Descriptions")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if jd_list is not None and not jd_list.empty:
                for _, jd in jd_list.iterrows():
                    cols = st.columns([4, 1])
                    cols[0].markdown(f"[{jd['name']}]({jd['drive_url']})")
                    if cols[1].button("🗑️", key=f"del_jd_{jd['id']}"):
                        if db_handler.delete_job_description(jd['id']):
                            st.success("Deleted")
                            refresh_data()
                            st.rerun()
            else:
                st.info("No job descriptions uploaded")
        
        with col2:
            st.markdown("### Add JD")
            with st.form("new_jd_form", clear_on_submit=True):
                jd_name = st.text_input("JD Name")
                jd_file = st.file_uploader("Upload JD", type=['pdf', 'docx'], label_visibility="collapsed")
                if st.form_submit_button("➕ Add", use_container_width=True):
                    if jd_name and jd_file:
                        with st.spinner("Uploading..."):
                            import os
                            temp_path = f"/tmp/{uuid.uuid4()}_{jd_file.name}"
                            with open(temp_path, "wb") as f:
                                f.write(jd_file.getbuffer())
                            
                            drive_url = handlers['drive'].upload_to_drive(temp_path, new_file_name=jd_file.name)
                            os.remove(temp_path)
                            
                            if drive_url and db_handler.add_job_description(jd_name, drive_url, jd_file.name):
                                st.success("Added JD")
                                refresh_data()
                                st.rerun()
                            else:
                                st.error("Failed to add JD")
                    else:
                        st.warning("Provide name and file")

def run_app():
    credentials = st.session_state.credentials
    user_info = st.session_state.user_info
    
    db_handler = get_db_handler()
    db_handler.create_tables()
    
    load_all_data()
    
    handlers = get_handlers(credentials)
    
    render_sidebar(user_info)
    
    if st.session_state.show_sync_dialog:
        show_sync_dialog(handlers['processing'])
    
    page = st.session_state.page
    
    if page == 'Dashboard':
        render_dashboard()
    elif page == 'Applicants':
        render_applicants()
    elif page == 'Applicant Detail':
        if st.session_state.selected_applicant_id:
            render_applicant_detail(db_handler, handlers)
        else:
            st.session_state.page = 'Applicants'
            st.rerun()
    elif page == 'Communications':
        render_communications_page(db_handler)
    elif page == 'Interviews':
        render_interviews_page(db_handler)
    elif page == 'Import':
        render_import_page(db_handler, handlers)
    elif page == 'Export':
        render_export_page(db_handler, handlers)
    elif page == 'Settings':
        render_settings_page(db_handler, handlers)

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
        flow = create_flow()
        authorization_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
        
        st.markdown("""
        <div style="text-align: center; padding: 4rem 2rem;">
            <h1 style="font-size: 3rem; margin-bottom: 1rem;">🎯 HireFl.ai</h1>
            <p style="font-size: 1.2rem; margin-bottom: 3rem;">AI-Powered Hiring Management System</p>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.link_button("🔐 Login with Google", authorization_url, use_container_width=True, type="primary")
else:
    run_app()
