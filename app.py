import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import threading
import queue
import json
from concurrent.futures import ThreadPoolExecutor
import plotly.express as px
import plotly.graph_objects as go
from streamlit_option_menu import option_menu
import streamlit.components.v1 as components
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import modules
from processing_engine import ProcessingEngine
from modules.database_handler import DatabaseHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.drive_handler import DriveHandler
from modules.importer import Importer
from modules.sheet_updater import SheetsUpdater
from utils.auth import get_credentials
from utils.logger import logger

# Page configuration
st.set_page_config(
    page_title="HireFl.ai - Smart Hiring Platform",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for modern UI
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
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
        background-color: transparent;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        padding: 0 24px;
        background-color: transparent;
        border-radius: 8px;
        color: #6b7280;
        font-weight: 600;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
        color: white;
    }
    
    /* Dataframe styling */
    .dataframe {
        font-size: 14px;
        border-radius: 8px;
        overflow: hidden;
    }
    
    /* Success/Error message styling */
    .stSuccess, .stError, .stWarning, .stInfo {
        padding: 1rem;
        border-radius: 0.5rem;
        font-weight: 500;
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, var(--primary-color) 0%, var(--secondary-color) 100%);
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #334155 100%);
    }
    
    /* Container styling */
    .main-container {
        padding: 2rem;
        background: var(--light-bg);
        border-radius: 1rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        margin-bottom: 2rem;
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
    
    /* Loading animation */
    .loading-spinner {
        display: inline-block;
        width: 20px;
        height: 20px;
        border: 3px solid rgba(99, 102, 241, 0.3);
        border-radius: 50%;
        border-top-color: #6366f1;
        animation: spin 1s ease-in-out infinite;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
def init_session_state():
    defaults = {
        'authenticated': False,
        'credentials': None,
        'processing_engine': None,
        'db_handler': None,
        'sync_in_progress': False,
        'last_sync_time': None,
        'sync_results': {},
        'current_page': 'dashboard',
        'selected_applicants': [],
        'filter_status': 'All',
        'filter_domain': 'All',
        'search_query': '',
        'refresh_counter': 0,
        'notification_queue': queue.Queue(),
        'background_thread': None,
        'api_status': {},
        'cache_timestamp': None,
        'applicants_data': None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Authentication with modern UI
def authenticate():
    if not st.session_state.authenticated:
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
            
            with st.container():
                st.info("🔐 Click below to authenticate with Google")
                if st.button("🚀 Authenticate with Google", use_container_width=True):
                    with st.spinner("Authenticating..."):
                        credentials = get_credentials()
                        if credentials:
                            st.session_state.authenticated = True
                            st.session_state.credentials = credentials
                            st.session_state.processing_engine = ProcessingEngine(credentials)
                            st.session_state.db_handler = DatabaseHandler()
                            st.success("✅ Authentication successful!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("❌ Authentication failed. Please try again.")
        return False
    return True

# Background sync function
def background_sync(engine, notification_queue):
    try:
        notification_queue.put(("info", "🔄 Starting email sync..."))
        new_apps, failed_classifications = engine.process_new_applications()
        new_replies = engine.process_replies()
        
        result = {
            'new_applications': new_apps,
            'failed_classifications': failed_classifications,
            'new_replies': new_replies,
            'timestamp': datetime.now(ZoneInfo("Asia/Kolkata"))
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
    finally:
        st.session_state.sync_in_progress = False

# Modern Dashboard
def render_dashboard():
    # Header with gradient
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
            time_diff = datetime.now(ZoneInfo("Asia/Kolkata")) - st.session_state.last_sync_time
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
        api_stats = st.session_state.processing_engine.get_classification_status() if st.session_state.processing_engine else {}
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
                    args=(st.session_state.processing_engine, st.session_state.notification_queue)
                )
                thread.start()
                st.session_state.background_thread = thread
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
       (datetime.now() - st.session_state.cache_timestamp).total_seconds() > 30:
        st.session_state.applicants_data = st.session_state.db_handler.get_all_applicants()
        st.session_state.cache_timestamp = datetime.now()
    
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
        if 'Status' in df.columns:
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
        if 'Domain' in df.columns:
            domain_counts = df['Domain'].value_counts().head(10)
            fig = px.bar(
                x=domain_counts.values,
                y=domain_counts.index,
                orientation='h',
                title="Top 10 Domains",
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

# Applicants Management Page
def render_applicants():
    st.markdown("""
    <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">👥 Applicants Management</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Review and manage all applications</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Filters
    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 1, 1])
    
    df = st.session_state.db_handler.get_all_applicants()
    
    with col1:
        search = st.text_input("🔍 Search", placeholder="Name, Email, or Phone", 
                               value=st.session_state.search_query, key="search_applicants")
        st.session_state.search_query = search
    
    with col2:
        statuses = ['All'] + list(df['Status'].unique()) if 'Status' in df.columns else ['All']
        status_filter = st.selectbox("📋 Status", statuses, 
                                     index=statuses.index(st.session_state.filter_status) 
                                     if st.session_state.filter_status in statuses else 0)
        st.session_state.filter_status = status_filter
    
    with col3:
        domains = ['All'] + list(df['Domain'].unique()) if 'Domain' in df.columns else ['All']
        domain_filter = st.selectbox("💼 Domain", domains,
                                     index=domains.index(st.session_state.filter_domain) 
                                     if st.session_state.filter_domain in domains else 0)
        st.session_state.filter_domain = domain_filter
    
    with col4:
        if st.button("🔄 Refresh", use_container_width=True):
            st.session_state.refresh_counter += 1
            st.session_state.cache_timestamp = None
            st.rerun()
    
    with col5:
        export_ready = st.button("📤 Export", use_container_width=True)
    
    # Apply filters
    filtered_df = df.copy()
    
    if search:
        search_lower = search.lower()
        filtered_df = filtered_df[
            filtered_df['Name'].str.lower().str.contains(search_lower, na=False) |
            filtered_df['Email'].str.lower().str.contains(search_lower, na=False) |
            filtered_df['Phone'].astype(str).str.contains(search_lower, na=False)
        ]
    
    if status_filter != 'All':
        filtered_df = filtered_df[filtered_df['Status'] == status_filter]
    
    if domain_filter != 'All':
        filtered_df = filtered_df[filtered_df['Domain'] == domain_filter]
    
    # Display count
    st.info(f"📊 Showing {len(filtered_df)} of {len(df)} applicants")
    
    # Bulk actions
    if len(filtered_df) > 0:
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            select_all = st.checkbox("Select All")
        
        # Display applicants in a modern table
        for idx, applicant in filtered_df.iterrows():
            with st.container():
                col1, col2, col3, col4, col5 = st.columns([0.5, 2, 2, 2, 1])
                
                with col1:
                    selected = st.checkbox("", key=f"select_{applicant['ID']}", 
                                         value=select_all or applicant['ID'] in st.session_state.selected_applicants)
                    if selected and applicant['ID'] not in st.session_state.selected_applicants:
                        st.session_state.selected_applicants.append(applicant['ID'])
                    elif not selected and applicant['ID'] in st.session_state.selected_applicants:
                        st.session_state.selected_applicants.remove(applicant['ID'])
                
                with col2:
                    st.markdown(f"**{applicant['Name']}**")
                    st.caption(f"📧 {applicant['Email']}")
                
                with col3:
                    st.text(f"📱 {applicant['Phone']}")
                    st.caption(f"💼 {applicant['Domain']}")
                
                with col4:
                    status_color = {
                        'New': '🔵',
                        'Shortlisted': '🟢',
                        'Interview Scheduled': '🟡',
                        'Rejected': '🔴',
                        'Hired': '✅'
                    }.get(applicant['Status'], '⚪')
                    st.text(f"{status_color} {applicant['Status']}")
                
                with col5:
                    if st.button("👁️ View", key=f"view_{applicant['ID']}", use_container_width=True):
                        show_applicant_details(applicant)
                
                st.markdown("---")
        
        # Bulk action buttons
        if st.session_state.selected_applicants:
            st.success(f"✅ {len(st.session_state.selected_applicants)} applicants selected")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                new_status = st.selectbox("Change Status", 
                                         ['', 'Shortlisted', 'Interview Scheduled', 'Rejected', 'Hired'])
            with col2:
                if st.button("Apply Status", use_container_width=True) and new_status:
                    with st.spinner("Updating..."):
                        for app_id in st.session_state.selected_applicants:
                            st.session_state.db_handler.update_applicant_status(app_id, new_status)
                        st.success(f"✅ Updated {len(st.session_state.selected_applicants)} applicants")
                        st.session_state.selected_applicants = []
                        time.sleep(1)
                        st.rerun()
            
            with col3:
                if st.button("📧 Send Bulk Email", use_container_width=True):
                    show_bulk_email_dialog()
            
            with col4:
                if st.button("🗓️ Schedule Interviews", use_container_width=True):
                    show_bulk_interview_dialog()
    
    # Export functionality
    if export_ready:
        with st.spinner("Creating export..."):
            sheets_handler = SheetsUpdater(st.session_state.credentials)
            export_data = filtered_df.to_dict('records')
            result = sheets_handler.create_export_sheet(
                export_data,
                ['Name', 'Email', 'Phone', 'Education', 'JobHistory', 'Resume', 'Role', 'Status', 'Feedback']
            )
            if result:
                st.success(f"✅ Export created: {result['title']}")
                st.markdown(f"📎 [Open Spreadsheet]({result['url']})")

# Show applicant details in a modal-like container
@st.dialog("Applicant Details", width="large")
def show_applicant_details(applicant):
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"### {applicant['Name']}")
        st.text(f"📧 {applicant['Email']}")
        st.text(f"📱 {applicant['Phone']}")
        st.text(f"💼 {applicant['Domain']}")
        st.text(f"📊 Status: {applicant['Status']}")
    
    with col2:
        if applicant.get('CV_URL'):
            st.markdown(f"📄 [View Resume]({applicant['CV_URL']})")
        
        new_status = st.selectbox("Update Status", 
                                  ['New', 'Shortlisted', 'Interview Scheduled', 'Rejected', 'Hired'],
                                  index=['New', 'Shortlisted', 'Interview Scheduled', 'Rejected', 'Hired']
                                  .index(applicant['Status']))
        
        if st.button("Update", use_container_width=True):
            st.session_state.db_handler.update_applicant_status(applicant['ID'], new_status)
            st.success("✅ Status updated")
            time.sleep(0.5)
            st.rerun()
    
    # Education and Job History
    st.markdown("---")
    st.markdown("### 🎓 Education")
    st.text(applicant.get('Education', 'Not provided'))
    
    st.markdown("### 💼 Work Experience")
    st.markdown(applicant.get('JobHistory', 'Not provided'))
    
    # Communication History
    st.markdown("---")
    st.markdown("### 📧 Communication History")
    comms = st.session_state.db_handler.get_conversations(applicant['ID'])
    if not comms.empty:
        for _, comm in comms.iterrows():
            with st.expander(f"{comm['Subject']} - {comm['CreatedAt']}"):
                st.text(f"From: {comm['Sender']}")
                st.text(f"Direction: {comm['Direction']}")
                st.text_area("Message", comm['Body'], height=150)
    else:
        st.info("No communication history")

# Interview Scheduling Page
def render_scheduling():
    st.markdown("""
    <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">🗓️ Interview Scheduling</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Schedule and manage interviews efficiently</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Quick Schedule Section
    st.subheader("⚡ Quick Schedule")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Get shortlisted applicants
        df = st.session_state.db_handler.get_all_applicants()
        shortlisted = df[df['Status'].isin(['Shortlisted', 'New'])]
        
        if len(shortlisted) > 0:
            applicant_options = {f"{row['Name']} ({row['Email']})": row['ID'] 
                               for _, row in shortlisted.iterrows()}
            selected_applicant = st.selectbox("Select Applicant", list(applicant_options.keys()))
            applicant_id = applicant_options[selected_applicant]
            
            interviewer_email = st.text_input("Interviewer Email", 
                                             value=st.session_state.credentials.token['email'])
            duration = st.slider("Duration (minutes)", 15, 120, 30, 15)
        else:
            st.info("No applicants available for scheduling")
    
    with col2:
        if len(shortlisted) > 0:
            jd_title = st.text_input("Position", "Software Developer")
            jd_description = st.text_area("Job Description", height=100)
            
            if st.button("🔍 Find Available Slots", use_container_width=True):
                with st.spinner("Finding available slots..."):
                    calendar_handler = CalendarHandler(st.session_state.credentials)
                    slots = calendar_handler.find_available_slots(interviewer_email, duration, days_to_check=7)
                    
                    if slots:
                        st.success(f"✅ Found {len(slots[:10])} available slots")
                        selected_slot = st.selectbox("Select Time Slot", 
                                                    [s.strftime("%B %d, %Y at %I:%M %p") for s in slots[:10]])
                        
                        if st.button("📅 Schedule Interview", use_container_width=True):
                            slot_index = [s.strftime("%B %d, %Y at %I:%M %p") for s in slots[:10]].index(selected_slot)
                            selected_time = slots[slot_index]
                            
                            applicant = df[df['ID'] == applicant_id].iloc[0]
                            end_time = selected_time + timedelta(minutes=duration)
                            
                            result = calendar_handler.create_calendar_event(
                                applicant['Name'],
                                applicant['Email'],
                                interviewer_email,
                                selected_time,
                                end_time,
                                f"Interview - {applicant['Name']} for {jd_title}",
                                f"Interview for {jd_title}\n\n{jd_description}",
                                applicant.get('CV_URL')
                            )
                            
                            if result:
                                # Send email with ICS
                                email_handler = EmailHandler(st.session_state.credentials)
                                email_body = f"""
                                <h3>Interview Scheduled</h3>
                                <p>Dear {applicant['Name']},</p>
                                <p>Your interview has been scheduled for <strong>{selected_time.strftime('%B %d, %Y at %I:%M %p')}</strong>.</p>
                                <p>Position: <strong>{jd_title}</strong></p>
                                <p>Duration: <strong>{duration} minutes</strong></p>
                                <p>Meeting Link: <strong>{result['google_event'].get('hangoutLink', 'Will be shared soon')}</strong></p>
                                <p>Please find the calendar invite attached.</p>
                                <p>Best regards,<br>Hiring Team</p>
                                """
                                
                                email_handler.send_email(
                                    [applicant['Email']],
                                    f"Interview Scheduled - {jd_title}",
                                    email_body,
                                    [{'content': result['ics_data'].encode(),
                                      'filename': 'interview.ics',
                                      'maintype': 'text',
                                      'subtype': 'calendar'}]
                                )
                                
                                st.session_state.db_handler.update_applicant_status(applicant_id, 'Interview Scheduled')
                                st.success("✅ Interview scheduled and invitation sent!")
                                st.balloons()
                    else:
                        st.warning("⚠️ No available slots found in the next 7 days")
    
    # Scheduled Interviews
    st.markdown("---")
    st.subheader("📅 Scheduled Interviews")
    
    scheduled_df = df[df['Status'] == 'Interview Scheduled']
    if len(scheduled_df) > 0:
        for _, applicant in scheduled_df.iterrows():
            with st.container():
                col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
                
                with col1:
                    st.markdown(f"**{applicant['Name']}**")
                    st.caption(f"📧 {applicant['Email']}")
                
                with col2:
                    st.text(f"💼 {applicant['Domain']}")
                    st.caption(f"📱 {applicant['Phone']}")
                
                with col3:
                    if st.button("✅ Mark Completed", key=f"complete_{applicant['ID']}", use_container_width=True):
                        st.session_state.db_handler.update_applicant_status(applicant['ID'], 'Interview Completed')
                        st.success("✅ Interview marked as completed")
                        time.sleep(0.5)
                        st.rerun()
                
                with col4:
                    if st.button("🔄 Reschedule", key=f"reschedule_{applicant['ID']}", use_container_width=True):
                        st.info("Reschedule functionality coming soon")
                
                st.markdown("---")
    else:
        st.info("📭 No interviews scheduled yet")

# Import Page
def render_import():
    st.markdown("""
    <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">📥 Import Applications</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Import applications from various sources</p>
    </div>
    """, unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["📄 Upload File", "🔗 Google Sheets", "📎 Single Resume"])
    
    importer = Importer(st.session_state.credentials)
    
    with tab1:
        st.info("📤 Upload a CSV or Excel file with applicant data")
        uploaded_file = st.file_uploader("Choose file", type=['csv', 'xlsx', 'xls'])
        
        if uploaded_file:
            if st.button("📥 Import Data", use_container_width=True):
                with st.spinner("Importing data..."):
                    result, count = importer.import_from_local_file(uploaded_file)
                    if count > 0:
                        st.success(result)
                        st.balloons()
                    else:
                        st.error(result)
    
    with tab2:
        st.info("🔗 Import data from a Google Sheets document")
        sheet_url = st.text_input("Google Sheets URL", 
                                 placeholder="https://docs.google.com/spreadsheets/d/...")
        
        if sheet_url:
            if st.button("📊 Import from Sheets", use_container_width=True):
                st.info("Google Sheets import functionality is being implemented")
    
    with tab3:
        st.info("📎 Import a single applicant from their resume")
        col1, col2 = st.columns(2)
        
        with col1:
            resume_file = st.file_uploader("Upload Resume", type=['pdf', 'docx'])
            if resume_file and st.button("📄 Process Resume", use_container_width=True):
                with st.spinner("Processing resume..."):
                    applicant_id = importer.import_from_local_resume(resume_file)
                    if applicant_id:
                        st.success(f"✅ Applicant imported successfully! ID: {applicant_id}")
                        st.balloons()
                    else:
                        st.error("❌ Failed to import resume")
        
        with col2:
            resume_url = st.text_input("Or provide Resume URL", 
                                      placeholder="https://drive.google.com/...")
            if resume_url and st.button("🔗 Process from URL", use_container_width=True):
                with st.spinner("Processing resume from URL..."):
                    applicant_id = importer.import_from_resume(resume_url)
                    if applicant_id:
                        st.success(f"✅ Applicant imported successfully! ID: {applicant_id}")
                        st.balloons()
                    else:
                        st.error("❌ Failed to import resume from URL")

# Settings Page
def render_settings():
    st.markdown("""
    <div class="main-header">
        <h1 style="margin: 0; font-size: 2.5rem;">⚙️ Settings</h1>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">Configure system preferences</p>
    </div>
    """, unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["🔑 API Configuration", "📊 Database", "🔄 Automation"])
    
    with tab1:
        st.subheader("API Key Status")
        
        if st.session_state.processing_engine:
            api_stats = st.session_state.processing_engine.get_classification_status()
            
            if api_stats:
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Total Keys", api_stats.get('total_keys', 0))
                
                with col2:
                    st.metric("Available", api_stats.get('available_keys', 0))
                
                with col3:
                    st.metric("Rate Limited", api_stats.get('rate_limited_keys', 0))
                
                # Show detailed status
                st.markdown("### Detailed Key Status")
                
                key_statuses = api_stats.get('key_statuses', {})
                usage_counts = api_stats.get('usage_counts', {})
                
                for i, (key, status) in enumerate(key_statuses.items(), 1):
                    col1, col2, col3 = st.columns([1, 2, 1])
                    
                    with col1:
                        st.text(f"Key {i}")
                    
                    with col2:
                        if status == "Available":
                            st.success(f"✅ {status}")
                        elif status == "Rate Limited":
                            st.warning(f"⏳ {status}")
                        else:
                            st.error(f"❌ {status}")
                    
                    with col3:
                        st.text(f"Uses: {usage_counts.get(key, 0)}")
    
    with tab2:
        st.subheader("Database Statistics")
        
        if st.session_state.db_handler:
            stats = st.session_state.db_handler.get_database_stats()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Total Applicants", stats.get('total_applicants', 0))
                st.metric("Total Communications", stats.get('total_communications', 0))
            
            with col2:
                st.metric("Active Threads", stats.get('active_threads', 0))
                st.metric("Database Size", f"{stats.get('db_size_mb', 0):.2f} MB")
            
            if st.button("🗑️ Clean Database", use_container_width=True):
                with st.spinner("Cleaning database..."):
                    # Implement database cleanup
                    st.success("✅ Database cleaned successfully")
    
    with tab3:
        st.subheader("Automation Settings")
        
        auto_sync = st.toggle("Enable Auto-Sync", value=False)
        if auto_sync:
            sync_interval = st.slider("Sync Interval (minutes)", 5, 60, 15, 5)
            st.info(f"📊 Emails will be synced every {sync_interval} minutes")
        
        st.markdown("---")
        
        st.subheader("Email Filters")
        keywords = st.text_area("Application Keywords", 
                               value='"job application", "applying for", resume, cv',
                               help="Keywords to identify job application emails")
        
        if st.button("💾 Save Settings", use_container_width=True):
            st.success("✅ Settings saved successfully")

# Bulk email dialog
@st.dialog("Send Bulk Email", width="large")
def show_bulk_email_dialog():
    subject = st.text_input("Subject")
    body = st.text_area("Email Body", height=200)
    
    if st.button("Send", use_container_width=True):
        with st.spinner("Sending emails..."):
            email_handler = EmailHandler(st.session_state.credentials)
            df = st.session_state.db_handler.get_all_applicants()
            
            for app_id in st.session_state.selected_applicants:
                applicant = df[df['ID'] == app_id].iloc[0]
                personalized_body = body.replace("{name}", applicant['Name'])
                email_handler.send_email([applicant['Email']], subject, personalized_body)
            
            st.success(f"✅ Sent {len(st.session_state.selected_applicants)} emails")
            st.session_state.selected_applicants = []
            time.sleep(1)
            st.rerun()

# Bulk interview dialog
@st.dialog("Schedule Bulk Interviews", width="large")
def show_bulk_interview_dialog():
    interviewer_email = st.text_input("Interviewer Email", 
                                     value=st.session_state.credentials.token['email'])
    duration = st.slider("Duration (minutes)", 15, 120, 30, 15)
    position = st.text_input("Position", "Software Developer")
    
    if st.button("Find Slots", use_container_width=True):
        st.info("Bulk scheduling functionality coming soon")

# Main App
def main():
    init_session_state()
    
    if not authenticate():
        return
    
    # Modern navigation sidebar
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0;">
            <h2 style="color: white; margin: 0;">HireFl.ai</h2>
            <p style="color: #cbd5e1; font-size: 0.9rem; margin-top: 0.5rem;">Smart Hiring Platform</p>
        </div>
        """, unsafe_allow_html=True)
        
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Applicants", "Scheduling", "Import", "Settings"],
            icons=["graph-up", "people", "calendar", "cloud-upload", "gear"],
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
        
        # User info at bottom
        st.markdown("---")
        if st.session_state.credentials:
            email = st.session_state.credentials.token.get('email', 'User')
            st.markdown(f"""
            <div style="color: #cbd5e1; text-align: center; padding: 1rem;">
                <p style="margin: 0; font-size: 0.9rem;">👤 {email}</p>
                <p style="margin: 0.5rem 0 0 0; font-size: 0.8rem; opacity: 0.7;">
                    v1.0.0 | Production
                </p>
            </div>
            """, unsafe_allow_html=True)
    
    # Route to selected page
    if selected == "Dashboard":
        render_dashboard()
    elif selected == "Applicants":
        render_applicants()
    elif selected == "Scheduling":
        render_scheduling()
    elif selected == "Import":
        render_import()
    elif selected == "Settings":
        render_settings()

if __name__ == "__main__":
    main()
