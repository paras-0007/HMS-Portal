import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
import plotly.express as px
from streamlit_option_menu import option_menu
import streamlit_antd_components as sac
from streamlit_extras.metric_cards import style_metric_cards
from streamlit_extras.dataframe_explorer import dataframe_explorer
import extra_streamlit_components as stx
import json

# Import modules
from processing_engine import ProcessingEngine
from modules.database_handler import DatabaseHandler
from modules.email_handler import EmailHandler
from modules.calendar_handler import CalendarHandler
from modules.sheet_updater import SheetsUpdater
from modules.importer import Importer
from utils.logger import logger
# Add these imports if they aren't already there
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os

def create_flow():
    """
    Creates a Google OAuth Flow object. 
    Checks for local credentials.json first, then falls back to st.secrets.
    """
    # Define the scopes required for the app
    SCOPES = [
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/userinfo.email',
        'openid',
        'https://www.googleapis.com/auth/gmail.modify', # specific for app1 functionality
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/spreadsheets'
    ]

    # Check for local credentials.json (Development Mode)
    if os.path.exists('credentials.json'):
        try:
            with open('credentials.json') as f:
                client_config = json.load(f)
            redirect_uri = "http://localhost:8501" # Standard local Streamlit port
        except Exception as e:
            st.error(f"Error reading credentials.json: {e}")
            st.stop()
            
    # Fallback to st.secrets (Deployment Mode)
    else:
        try:
            client_config = {
                "web": {
                    "client_id": st.secrets["GOOGLE_CLIENT_ID"],
                    "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [st.secrets["REDIRECT_URI"]],
                }
            }
            redirect_uri = st.secrets["REDIRECT_URI"]
        except KeyError as e:
            st.error(f"Missing secrets configuration: {e}")
            st.stop()

    return Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )

# Page config
st.set_page_config(
    page_title="HireFl.ai - Smart Hiring Platform",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional styling
st.markdown("""
    <style>
    /* Main container styling */
    .main {
        padding: 0rem 1rem;
        background: linear-gradient(180deg, #f8f9fa 0%, #ffffff 100%);
    }
    
    /* Card styling */
    .dashboard-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
        border: 1px solid #e9ecef;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .dashboard-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    /* Header styling */
    .header-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 16px rgba(102, 126, 234, 0.3);
    }
    
    .header-title {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    .header-subtitle {
        font-size: 1.1rem;
        opacity: 0.95;
    }
    
    /* Metric cards */
    div[data-testid="metric-container"] {
        background: white;
        border: 1px solid #e9ecef;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        margin: 0.5rem 0;
    }
    
    div[data-testid="metric-container"] > div {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.6rem 1.5rem;
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* Success/Error messages */
    .success-message {
        background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
        color: #155724;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    .error-message {
        background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%);
        color: #721c24;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: white;
        padding: 0.5rem;
        border-radius: 12px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 0.5rem 1.5rem;
        border-radius: 8px;
        font-weight: 500;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
    }
    
    /* Dataframe styling */
    .dataframe-container {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    
    /* Progress bar */
    .stProgress > div > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9fa 0%, #ffffff 100%);
        border-right: 1px solid #e9ecef;
    }
    
    /* Loading animation */
    .loading-spinner {
        display: inline-block;
        width: 20px;
        height: 20px;
        border: 3px solid rgba(102, 126, 234, 0.2);
        border-radius: 50%;
        border-top-color: #667eea;
        animation: spin 1s ease-in-out infinite;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
    }
    
    .status-new { background: #e3f2fd; color: #1565c0; }
    .status-screening { background: #fff3e0; color: #ef6c00; }
    .status-interview { background: #f3e5f5; color: #6a1b9a; }
    .status-selected { background: #e8f5e9; color: #2e7d32; }
    .status-rejected { background: #ffebee; color: #c62828; }
    
    </style>
    """, unsafe_allow_html=True)

# Initialize session state
def init_session_state():
    defaults = {
        'authenticated': False,
        'credentials': None,
        'email': None,
        'processing_engine': None,
        'db_handler': None,
        'last_sync': None,
        'sync_in_progress': False,
        'refresh_data': True,
        'selected_applicants': [],
        'current_tab': 'Dashboard',
        'notification_queue': [],
        'api_stats': {},
        'filter_status': 'All',
        'filter_domain': 'All',
        'search_query': '',
        'page_number': 0,
        'rows_per_page': 20
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def authenticate():
    """Handle Google OAuth authentication using the flexible create_flow approach"""
    
    # 1. Handle the Callback (Code in URL)
    if 'code' in st.query_params:
        with st.spinner("Completing authentication..."):
            try:
                flow = create_flow()
                flow.fetch_token(code=st.query_params['code'])
                
                # Save credentials to session state
                creds = flow.credentials
                st.session_state['credentials'] = creds
                st.session_state['authenticated'] = True
                
                # Fetch User Info (Email & Name)
                service = build('oauth2', 'v2', credentials=creds)
                user_info = service.userinfo().get().execute()
                st.session_state['email'] = user_info.get('email')
                # Optional: You can save user_info['name'] or 'picture' here too if you want
                
                # Initialize Application Services
                st.session_state['processing_engine'] = ProcessingEngine(creds)
                st.session_state['db_handler'] = DatabaseHandler()
                
                # Clean URL and Refresh
                st.query_params.clear()
                st.success("✅ Authentication successful!")
                time.sleep(0.5)
                st.rerun()
                
            except Exception as e:
                st.error(f"Authentication failed: {str(e)}")
                # Clear params to prevent infinite error loops
                st.query_params.clear() 

    # 2. Handle Login UI (No code in URL)
    else:
        auth_container = st.container()
        with auth_container:
            # Header styling
            st.markdown("""
                <div class="header-container">
                    <h1 class="header-title">🎯 HireFl.ai</h1>
                    <p class="header-subtitle">Intelligent Hiring Management System</p>
                </div>
            """, unsafe_allow_html=True)
            
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.markdown("""
                    <div class="dashboard-card" style="text-align: center;">
                        <h2 style="color: #667eea; margin-bottom: 1rem;">Welcome Back!</h2>
                        <p style="color: #6c757d; margin-bottom: 2rem;">
                            Connect your Google Workspace to manage applications, 
                            schedule interviews, and streamline your hiring process.
                        </p>
                    </div>
                """, unsafe_allow_html=True)
                
                # Generate the Auth URL using create_flow
                flow = create_flow()
                auth_url, _ = flow.authorization_url(
                    prompt='consent', 
                    access_type='offline',
                    include_granted_scopes='true'
                )
                
                # Display the Link as a styled button
                st.markdown(f"""
                    <div style="text-align: center; margin-top: 1rem;">
                        <a href="{auth_url}" target="_self" style="
                            display: inline-block;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                            padding: 0.75rem 2rem;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: 500;
                            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
                            transition: transform 0.2s;
                        ">🔐 Sign in with Google</a>
                    </div>
                """, unsafe_allow_html=True)
# # OAuth authentication
# def authenticate():
#     """Handle Google OAuth authentication with modern UI"""
#     from google.auth.transport.requests import Request
#     from google.oauth2.credentials import Credentials
#     from google_auth_oauthlib.flow import Flow
#     import json
    
#     SCOPES = [
#         'https://www.googleapis.com/auth/gmail.modify',
#         'https://www.googleapis.com/auth/drive',
#         'https://www.googleapis.com/auth/calendar',
#         'https://www.googleapis.com/auth/spreadsheets'
#     ]
    
#     auth_container = st.container()
#     with auth_container:
#         st.markdown("""
#             <div class="header-container">
#                 <h1 class="header-title">🎯 HireFl.ai</h1>
#                 <p class="header-subtitle">Intelligent Hiring Management System</p>
#             </div>
#         """, unsafe_allow_html=True)
        
#         col1, col2, col3 = st.columns([1, 2, 1])
#         with col2:
#             st.markdown("""
#                 <div class="dashboard-card" style="text-align: center;">
#                     <h2 style="color: #667eea; margin-bottom: 1rem;">Welcome Back!</h2>
#                     <p style="color: #6c757d; margin-bottom: 2rem;">
#                         Connect your Google Workspace to manage applications, 
#                         schedule interviews, and streamline your hiring process.
#                     </p>
#                 </div>
#             """, unsafe_allow_html=True)
            
#             if st.button("🔐 Sign in with Google", use_container_width=True, key="auth_btn"):
#                 try:
#                     flow = Flow.from_client_config(
#                         {
#                             "web": {
#                                 "client_id": st.secrets["GOOGLE_CLIENT_ID"],
#                                 "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
#                                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#                                 "token_uri": "https://oauth2.googleapis.com/token",
#                                 "redirect_uris": [st.secrets["REDIRECT_URI"]]
#                             }
#                         },
#                         scopes=SCOPES
#                     )
#                     flow.redirect_uri = st.secrets["REDIRECT_URI"]
                    
#                     auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
                    
#                     st.markdown(f"""
#                         <div style="text-align: center; margin-top: 1rem;">
#                             <a href="{auth_url}" target="_self" style="
#                                 display: inline-block;
#                                 background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
#                                 color: white;
#                                 padding: 0.75rem 2rem;
#                                 border-radius: 8px;
#                                 text-decoration: none;
#                                 font-weight: 500;
#                                 box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
#                             ">Continue to Google →</a>
#                         </div>
#                     """, unsafe_allow_html=True)
                    
#                 except Exception as e:
#                     st.error(f"Authentication setup failed: {str(e)}")
    
#     # Handle OAuth callback
#     query_params = st.query_params
#     if 'code' in query_params:
#         with st.spinner("Completing authentication..."):
#             try:
#                 flow = Flow.from_client_config(
#                     {
#                         "web": {
#                             "client_id": st.secrets["GOOGLE_CLIENT_ID"],
#                             "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
#                             "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#                             "token_uri": "https://oauth2.googleapis.com/token",
#                             "redirect_uris": [st.secrets["REDIRECT_URI"]]
#                         }
#                     },
#                     scopes=SCOPES
#                 )
#                 flow.redirect_uri = st.secrets["REDIRECT_URI"]
#                 flow.fetch_token(code=query_params['code'])
                
#                 st.session_state['credentials'] = flow.credentials
#                 st.session_state['authenticated'] = True
                
#                 # Initialize services
#                 st.session_state['processing_engine'] = ProcessingEngine(flow.credentials)
#                 st.session_state['db_handler'] = DatabaseHandler()
                
#                 # Get user email
#                 from googleapiclient.discovery import build
#                 service = build('gmail', 'v1', credentials=flow.credentials)
#                 profile = service.users().getProfile(userId='me').execute()
#                 st.session_state['email'] = profile.get('emailAddress')
                
#                 st.query_params.clear()
#                 st.success("✅ Authentication successful!")
#                 time.sleep(1)
#                 st.rerun()
                
#             except Exception as e:
#                 st.error(f"Authentication failed: {str(e)}")
#                 st.query_params.clear()

# Add notification system
def show_notification(message, type="info"):
    """Show toast-like notifications"""
    if type == "success":
        st.success(message)
    elif type == "error":
        st.error(message)
    elif type == "warning":
        st.warning(message)
    else:
        st.info(message)

# Enhanced sync function with progress tracking
def sync_emails_with_progress():
    """Sync emails with real-time progress updates"""
    if st.session_state.sync_in_progress:
        st.warning("⚠️ Sync already in progress...")
        return
    
    st.session_state.sync_in_progress = True
    
    progress_container = st.container()
    with progress_container:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # Step 1: Check API status
            progress_bar.progress(10)
            status_text.text("🔍 Checking API status...")
            api_stats = st.session_state.processing_engine.get_classification_status()
            st.session_state.api_stats = api_stats
            time.sleep(0.5)
            
            # Step 2: Process new applications
            progress_bar.progress(30)
            status_text.text("📧 Processing new applications...")
            new_apps, failed_apps = st.session_state.processing_engine.process_new_applications()
            time.sleep(0.5)
            
            # Step 3: Process replies
            progress_bar.progress(70)
            status_text.text("💬 Checking for replies...")
            new_replies = st.session_state.processing_engine.process_replies()
            time.sleep(0.5)
            
            # Step 4: Complete
            progress_bar.progress(100)
            status_text.text("✅ Sync completed!")
            
            # Update last sync time
            st.session_state.last_sync = datetime.now(ZoneInfo("Asia/Kolkata"))
            st.session_state.refresh_data = True
            
            # Show results
            time.sleep(1)
            progress_bar.empty()
            status_text.empty()
            
            result_msg = f"""
            ### 📊 Sync Results
            - **New Applications:** {new_apps} processed
            - **Failed Classifications:** {failed_apps}
            - **New Replies:** {new_replies} found
            - **API Keys Available:** {api_stats.get('available_keys', 0)}/{api_stats.get('total_keys', 0)}
            """
            
            if failed_apps > 0:
                st.warning(result_msg)
            else:
                st.success(result_msg)
                
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            st.error(f"❌ Sync failed: {str(e)}")
            logger.error(f"Sync error: {str(e)}", exc_info=True)
        finally:
            st.session_state.sync_in_progress = False

# Dashboard with modern metrics
def render_dashboard():
    """Render main dashboard with analytics"""
    
    # Header with user info and sync button
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"""
            <div style="display: flex; align-items: center; gap: 1rem;">
                <h1 style="margin: 0; color: #667eea;">📊 Dashboard</h1>
                <span style="color: #6c757d;">Welcome, {st.session_state.email}</span>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        if st.session_state.last_sync:
            time_diff = datetime.now(ZoneInfo("Asia/Kolkata")) - st.session_state.last_sync
            if time_diff < timedelta(minutes=1):
                sync_text = "Just now"
            elif time_diff < timedelta(hours=1):
                sync_text = f"{int(time_diff.total_seconds() / 60)} min ago"
            else:
                sync_text = st.session_state.last_sync.strftime("%I:%M %p")
            st.markdown(f"""
                <div style="text-align: right; color: #6c757d; padding-top: 0.5rem;">
                    Last sync: {sync_text}
                </div>
            """, unsafe_allow_html=True)
    
    with col3:
        if st.button("🔄 Sync Emails", use_container_width=True, disabled=st.session_state.sync_in_progress):
            sync_emails_with_progress()
            st.rerun()
    
    # Get analytics data
    if st.session_state.refresh_data:
        with st.spinner("Loading dashboard..."):
            db = st.session_state.db_handler
            st.session_state.total_applicants = db.get_total_applicants()
            st.session_state.status_counts = db.get_status_distribution()
            st.session_state.domain_counts = db.get_domain_distribution()
            st.session_state.recent_applicants = db.get_recent_applicants(10)
            st.session_state.refresh_data = False
    
    # Metrics Row
    st.markdown("---")
    metrics_cols = st.columns(5)
    
    status_data = st.session_state.status_counts
    
    with metrics_cols[0]:
        st.metric(
            label="Total Applications",
            value=st.session_state.total_applicants,
            delta=f"+{status_data.get('New', 0)} new" if status_data.get('New', 0) > 0 else None
        )
    
    with metrics_cols[1]:
        st.metric(
            label="In Screening",
            value=status_data.get('Screening', 0),
            delta="Active" if status_data.get('Screening', 0) > 0 else None
        )
    
    with metrics_cols[2]:
        st.metric(
            label="Interview Stage",
            value=status_data.get('Interview Scheduled', 0),
            delta="Scheduled" if status_data.get('Interview Scheduled', 0) > 0 else None
        )
    
    with metrics_cols[3]:
        st.metric(
            label="Selected",
            value=status_data.get('Selected', 0),
            delta="✅" if status_data.get('Selected', 0) > 0 else None,
            delta_color="normal"
        )
    
    with metrics_cols[4]:
        conversion_rate = 0
        if st.session_state.total_applicants > 0:
            conversion_rate = (status_data.get('Selected', 0) / st.session_state.total_applicants) * 100
        st.metric(
            label="Conversion Rate",
            value=f"{conversion_rate:.1f}%",
            delta="Performance"
        )
    
    style_metric_cards()
    
    # Charts Row
    st.markdown("---")
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.markdown("### 📈 Application Pipeline")
        if status_data:
            fig_funnel = go.Figure(go.Funnel(
                y=list(status_data.keys()),
                x=list(status_data.values()),
                textposition="inside",
                textinfo="value+percent initial",
                marker=dict(
                    colorscale=[[0, '#667eea'], [1, '#764ba2']],
                    line=dict(width=2, color='white')
                ),
                connector=dict(line=dict(color="royalblue", width=2))
            ))
            fig_funnel.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_funnel, use_container_width=True)
        else:
            st.info("No data available yet")
    
    with chart_col2:
        st.markdown("### 🎯 Domain Distribution")
        domain_data = st.session_state.domain_counts
        if domain_data:
            fig_pie = px.pie(
                values=list(domain_data.values()),
                names=list(domain_data.keys()),
                color_discrete_sequence=px.colors.sequential.Plasma
            )
            fig_pie.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No data available yet")
    
    # Recent Applications
    st.markdown("---")
    st.markdown("### 🆕 Recent Applications")
    
    recent_df = st.session_state.recent_applicants
    if not recent_df.empty:
        # Format the dataframe for display
        recent_df['Applied'] = pd.to_datetime(recent_df['CreatedAt']).dt.strftime('%b %d, %I:%M %p')
        recent_df['Status_Badge'] = recent_df['Status'].apply(
            lambda x: f'<span class="status-badge status-{x.lower().replace(" ", "-")}">{x}</span>'
        )
        
        # Display with custom styling
        st.markdown(
            recent_df[['Name', 'Email', 'Domain', 'Status_Badge', 'Applied']].to_html(
                escape=False, 
                index=False,
                classes=['dataframe-container']
            ), 
            unsafe_allow_html=True
        )
    else:
        st.info("No applications received yet. Click 'Sync Emails' to check for new applications.")

# Applicants Management Tab
def render_applicants():
    """Render applicants management interface"""
    
    st.markdown("## 👥 Applicant Management")
    
    # Filters and Search Bar
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 1, 1, 1])
    
    with filter_col1:
        search_query = st.text_input("🔍 Search applicants", placeholder="Name, email, or domain...", key="search_input")
        if search_query != st.session_state.search_query:
            st.session_state.search_query = search_query
            st.session_state.page_number = 0
    
    with filter_col2:
        statuses = ['All'] + st.session_state.db_handler.get_unique_statuses()
        selected_status = st.selectbox("Status", statuses, key="status_filter")
        if selected_status != st.session_state.filter_status:
            st.session_state.filter_status = selected_status
            st.session_state.page_number = 0
    
    with filter_col3:
        domains = ['All'] + st.session_state.db_handler.get_unique_domains()
        selected_domain = st.selectbox("Domain", domains, key="domain_filter")
        if selected_domain != st.session_state.filter_domain:
            st.session_state.filter_domain = selected_domain
            st.session_state.page_number = 0
    
    with filter_col4:
        if st.button("🔄 Refresh", use_container_width=True):
            st.session_state.refresh_data = True
            st.rerun()
    
    # Get filtered applicants
    filters = {}
    if st.session_state.filter_status != 'All':
        filters['status'] = st.session_state.filter_status
    if st.session_state.filter_domain != 'All':
        filters['domain'] = st.session_state.filter_domain
    if st.session_state.search_query:
        filters['search'] = st.session_state.search_query
    
    applicants_df = st.session_state.db_handler.get_applicants_with_filters(filters)
    
    if not applicants_df.empty:
        st.markdown(f"**Found {len(applicants_df)} applicants**")
        
        # Add action buttons
        action_col1, action_col2, action_col3 = st.columns([1, 1, 5])
        
        with action_col1:
            if st.button("📧 Email Selected"):
                if st.session_state.selected_applicants:
                    st.session_state.show_email_modal = True
                else:
                    st.warning("Please select applicants first")
        
        with action_col2:
            if st.button("📅 Schedule Interview"):
                if st.session_state.selected_applicants:
                    st.session_state.show_interview_modal = True
                else:
                    st.warning("Please select applicants first")
        
        # Pagination
        total_rows = len(applicants_df)
        total_pages = (total_rows - 1) // st.session_state.rows_per_page + 1
        
        page_col1, page_col2, page_col3 = st.columns([2, 1, 2])
        with page_col2:
            page_number = st.number_input(
                f"Page (1-{total_pages})",
                min_value=1,
                max_value=total_pages,
                value=st.session_state.page_number + 1,
                step=1,
                key="page_input"
            ) - 1
            st.session_state.page_number = page_number
        
        # Display paginated data
        start_idx = page_number * st.session_state.rows_per_page
        end_idx = min(start_idx + st.session_state.rows_per_page, total_rows)
        
        display_df = applicants_df.iloc[start_idx:end_idx].copy()
        
        # Enhanced dataframe display with selection
        selected = st.data_editor(
            display_df[['Name', 'Email', 'Phone', 'Domain', 'Status', 'CreatedAt']],
            use_container_width=True,
            hide_index=True,
            disabled=['Name', 'Email', 'Phone', 'Domain', 'CreatedAt'],
            column_config={
                "Select": st.column_config.CheckboxColumn(
                    "Select",
                    help="Select applicant for bulk actions",
                    default=False,
                ),
                "CreatedAt": st.column_config.DatetimeColumn(
                    "Applied On",
                    format="DD MMM YYYY, h:mm A",
                ),
                "Status": st.column_config.SelectboxColumn(
                    "Status",
                    options=['New', 'Screening', 'Interview Scheduled', 'Selected', 'Rejected'],
                    required=True,
                ),
            },
            key=f"applicants_table_{page_number}"
        )
        
        # Update status if changed
        for idx, row in selected.iterrows():
            original_idx = display_df.index[idx - display_df.index[0]]
            if row['Status'] != applicants_df.loc[original_idx, 'Status']:
                st.session_state.db_handler.update_applicant_status(
                    applicants_df.loc[original_idx, 'ApplicantID'],
                    row['Status']
                )
                st.success(f"Updated {row['Name']}'s status to {row['Status']}")
        
        # Expandable details for each applicant
        for idx, row in display_df.iterrows():
            with st.expander(f"📋 {row['Name']} - View Details"):
                detail_col1, detail_col2 = st.columns(2)
                
                with detail_col1:
                    st.markdown("**Contact Information**")
                    st.write(f"📧 Email: {row['Email']}")
                    st.write(f"📱 Phone: {row['Phone']}")
                    st.write(f"🏢 Domain: {row['Domain']}")
                    
                    if row['CV_URL']:
                        st.markdown(f"[📄 View Resume]({row['CV_URL']})")
                
                with detail_col2:
                    st.markdown("**Application Status**")
                    st.write(f"Status: {row['Status']}")
                    st.write(f"Applied: {row['CreatedAt'].strftime('%b %d, %Y')}")
                    
                    # Quick actions
                    quick_col1, quick_col2 = st.columns(2)
                    with quick_col1:
                        if st.button(f"📧 Email", key=f"email_{row['ApplicantID']}"):
                            st.session_state.selected_applicants = [row['ApplicantID']]
                            st.session_state.show_email_modal = True
                    
                    with quick_col2:
                        if st.button(f"📅 Schedule", key=f"schedule_{row['ApplicantID']}"):
                            st.session_state.selected_applicants = [row['ApplicantID']]
                            st.session_state.show_interview_modal = True
                
                # Education and Job History
                if row['Education'] or row['JobHistory']:
                    st.markdown("---")
                    edu_col, job_col = st.columns(2)
                    
                    with edu_col:
                        if row['Education']:
                            st.markdown("**🎓 Education**")
                            st.write(row['Education'])
                    
                    with job_col:
                        if row['JobHistory']:
                            st.markdown("**💼 Job History**")
                            st.markdown(row['JobHistory'])
    else:
        st.info("No applicants found matching your criteria.")

# Settings Tab
def render_settings():
    """Render settings and configuration interface"""
    
    st.markdown("## ⚙️ Settings & Configuration")
    
    tabs = st.tabs(["📊 Import Data", "📤 Export Data", "🔑 API Status", "📧 Email Templates"])
    
    with tabs[0]:
        st.markdown("### Import Applicants")
        
        import_method = st.radio(
            "Select import method:",
            ["Upload Spreadsheet", "Upload Resume", "Google Sheets URL"]
        )
        
        if import_method == "Upload Spreadsheet":
            uploaded_file = st.file_uploader(
                "Choose a CSV or Excel file",
                type=['csv', 'xlsx', 'xls']
            )
            
            if uploaded_file:
                if st.button("🚀 Start Import"):
                    with st.spinner("Importing data..."):
                        importer = Importer(st.session_state.credentials)
                        result, count = importer.import_from_local_file(uploaded_file)
                        if count > 0:
                            st.success(result)
                            st.session_state.refresh_data = True
                        else:
                            st.error(result)
        
        elif import_method == "Upload Resume":
            uploaded_resume = st.file_uploader(
                "Choose a resume file",
                type=['pdf', 'docx']
            )
            
            if uploaded_resume:
                if st.button("🚀 Process Resume"):
                    with st.spinner("Processing resume..."):
                        importer = Importer(st.session_state.credentials)
                        applicant_id = importer.import_from_local_resume(uploaded_resume)
                        if applicant_id:
                            st.success(f"✅ Successfully imported applicant (ID: {applicant_id})")
                            st.session_state.refresh_data = True
                        else:
                            st.error("Failed to process resume")
        
        else:
            sheet_url = st.text_input("Enter Google Sheets URL")
            if sheet_url and st.button("🚀 Import from Sheets"):
                with st.spinner("Importing from Google Sheets..."):
                    st.info("Importing from Google Sheets...")
                    # Implementation here
    
    with tabs[1]:
        st.markdown("### Export Applicants")
        
        export_filters = {}
        exp_col1, exp_col2 = st.columns(2)
        
        with exp_col1:
            export_status = st.multiselect(
                "Filter by Status",
                options=['New', 'Screening', 'Interview Scheduled', 'Selected', 'Rejected'],
                default=[]
            )
            if export_status:
                export_filters['status'] = export_status
        
        with exp_col2:
            export_domain = st.multiselect(
                "Filter by Domain",
                options=st.session_state.db_handler.get_unique_domains(),
                default=[]
            )
            if export_domain:
                export_filters['domain'] = export_domain
        
        if st.button("📤 Export to Google Sheets"):
            with st.spinner("Creating export..."):
                applicants = st.session_state.db_handler.get_applicants_for_export(export_filters)
                if applicants:
                    sheets_updater = SheetsUpdater(st.session_state.credentials)
                    result = sheets_updater.create_export_sheet(
                        applicants,
                        ['Name', 'Email', 'Phone', 'Education', 'Job History', 'Resume', 'Role', 'Status', 'Feedback']
                    )
                    if result:
                        st.success(f"✅ Export created: [{result['title']}]({result['url']})")
                        st.balloons()
                else:
                    st.warning("No applicants found with selected filters")
    
    with tabs[2]:
        st.markdown("### API Key Status")
        
        if st.button("🔄 Refresh API Status"):
            api_stats = st.session_state.processing_engine.get_classification_status()
            st.session_state.api_stats = api_stats
        
        if st.session_state.api_stats:
            stats = st.session_state.api_stats
            
            # API metrics
            api_cols = st.columns(4)
            with api_cols[0]:
                st.metric("Total Keys", stats.get('total_keys', 0))
            with api_cols[1]:
                st.metric("Available", stats.get('available_keys', 0))
            with api_cols[2]:
                st.metric("Rate Limited", stats.get('rate_limited_keys', 0))
            with api_cols[3]:
                st.metric("Failed", stats.get('failed_keys', 0))
            
            # Detailed status
            st.markdown("#### Key Status Details")
            
            key_statuses = stats.get('key_statuses', {})
            if key_statuses:
                status_df = pd.DataFrame(
                    [(f"Key {i+1}", key[:8] + "...", status, stats.get('usage_counts', {}).get(key, 0)) 
                     for i, (key, status) in enumerate(key_statuses.items())],
                    columns=['Key #', 'Key ID', 'Status', 'Usage Count']
                )
                
                st.dataframe(
                    status_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Status": st.column_config.TextColumn(
                            "Status",
                            help="Current status of the API key"
                        ),
                        "Usage Count": st.column_config.ProgressColumn(
                            "Usage",
                            help="Number of times this key has been used",
                            format="%d",
                            min_value=0,
                            max_value=max(stats.get('usage_counts', {}).values()) if stats.get('usage_counts') else 100,
                        ),
                    }
                )
    
    with tabs[3]:
        st.markdown("### Email Templates")
        st.info("Configure email templates for different stages of the hiring process")
        
        template_type = st.selectbox(
            "Select Template",
            ["Interview Invitation", "Rejection", "Selection", "Follow-up"]
        )
        
        template_subject = st.text_input(
            "Subject Line",
            value=f"Regarding your application at {{company_name}}"
        )
        
        template_body = st.text_area(
            "Email Body",
            value="""Dear {{applicant_name}},

Thank you for your interest in joining our team.

{{custom_message}}

Best regards,
{{sender_name}}
{{company_name}}""",
            height=200
        )
        
        if st.button("💾 Save Template"):
            st.success("Template saved successfully!")

# Main app
def main():
    init_session_state()
    
    if not st.session_state.authenticated:
        authenticate()
        return
    
    # Sidebar with modern navigation
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding: 1rem 0;">
                <h2 style="color: #667eea; margin: 0;">🎯 HireFl.ai</h2>
                <p style="color: #6c757d; font-size: 0.9rem; margin-top: 0.5rem;">
                    Intelligent Hiring Platform
                </p>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # User info
        st.markdown(f"""
            <div style="padding: 0.5rem; background: #f8f9fa; border-radius: 8px; margin-bottom: 1rem;">
                <div style="color: #495057; font-size: 0.9rem;">
                    <strong>👤 {st.session_state.email}</strong>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        # Navigation menu
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Applicants", "Communications", "Settings"],
            icons=["speedometer2", "people", "chat-dots", "gear"],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#667eea", "font-size": "18px"},
                "nav-link": {
                    "font-size": "16px",
                    "text-align": "left",
                    "margin": "5px 0",
                    "padding": "10px 15px",
                    "border-radius": "8px",
                    "color": "#495057",
                    "--hover-color": "#f8f9fa"
                },
                "nav-link-selected": {
                    "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                    "color": "white",
                    "font-weight": "500"
                },
            }
        )
        
        st.markdown("---")
        
        # Quick stats in sidebar
        if st.session_state.authenticated:
            st.markdown("### 📊 Quick Stats")
            if hasattr(st.session_state, 'total_applicants'):
                st.metric("Total Applicants", st.session_state.total_applicants)
            if hasattr(st.session_state, 'api_stats'):
                available = st.session_state.api_stats.get('available_keys', 0)
                total = st.session_state.api_stats.get('total_keys', 0)
                st.metric("API Keys", f"{available}/{total} available")
        
        st.markdown("---")
        
        # Logout button
        if st.button("🚪 Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    # Main content area
    if selected == "Dashboard":
        render_dashboard()
    elif selected == "Applicants":
        render_applicants()
    elif selected == "Communications":
        st.markdown("## 💬 Communications")
        st.info("Communications module - Track all email threads and conversations")
        # Add communications implementation here
    elif selected == "Settings":
        render_settings()

if __name__ == "__main__":
    main()
