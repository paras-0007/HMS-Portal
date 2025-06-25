import psycopg2
import pandas as pd
from utils.logger import logger
import streamlit as st

class DatabaseHandler:
    def __init__(self):
        """
        Initializes the database connection parameters by fetching them
        from Streamlit's secrets manager.
        """
        self.conn_params = {
            "dbname": st.secrets["DB_NAME"],
            "user": st.secrets["DB_USER"],
            "password": st.secrets["DB_PASSWORD"],
            "host": st.secrets["DB_HOST"],
            "port": st.secrets["DB_PORT"]
        }
        self.conn = None

    def _connect(self):
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg2.connect(**self.conn_params)
        except psycopg2.OperationalError as e:
            logger.error(f"Could not connect to the database: {e}")
            self.conn = None

    def create_tables(self):
        self._connect()
        if not self.conn: return
        queries = [
            """CREATE TABLE IF NOT EXISTS applicants (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255) UNIQUE,
                phone VARCHAR(20),
                domain VARCHAR(255),
                education TEXT,
                job_history TEXT,
                cv_url TEXT,
                status VARCHAR(255) DEFAULT 'New',
                feedback TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                gmail_thread_id VARCHAR(255)
            );""",
            """CREATE TABLE IF NOT EXISTS communications (
                id SERIAL PRIMARY KEY,
                applicant_id INTEGER REFERENCES applicants(id) ON DELETE CASCADE,
                gmail_message_id VARCHAR(255) UNIQUE,
                sender TEXT,
                subject TEXT,
                body TEXT,
                direction VARCHAR(50),
                sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS export_logs (
                id SERIAL PRIMARY KEY,
                file_name VARCHAR(255),
                sheet_url TEXT,
                created_by VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS applicant_statuses (
                id SERIAL PRIMARY KEY,
                status_name VARCHAR(255) UNIQUE NOT NULL
            );""",
            """CREATE TABLE IF NOT EXISTS interviewers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL
            );""",
            """CREATE TABLE IF NOT EXISTS interviews (
                id SERIAL PRIMARY KEY,
                applicant_id INTEGER REFERENCES applicants(id) ON DELETE CASCADE,
                interviewer_id INTEGER REFERENCES interviewers(id) ON DELETE SET NULL,
                event_title VARCHAR(255),
                start_time TIMESTAMP WITH TIME ZONE,
                end_time TIMESTAMP WITH TIME ZONE,
                google_calendar_event_id VARCHAR(255),
                status VARCHAR(50) DEFAULT 'Pending'
            );""",
            """CREATE TABLE IF NOT EXISTS applicant_status_history (
                id SERIAL PRIMARY KEY,
                applicant_id INTEGER REFERENCES applicants(id) ON DELETE CASCADE,
                status_name VARCHAR(255) NOT NULL,
                changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );"""
        ]
        try:
            with self.conn.cursor() as cur:
                for query in queries:
                    cur.execute(query)
                self.conn.commit()
                logger.info("All tables are ready.")
        except Exception as e:
            logger.error(f"Error during initial table creation: {e}")
            self.conn.rollback()
            return
        self._populate_initial_statuses()

    def insert_applicant_and_communication(self, applicant_data, email_data):
        self._connect()
        if not self.conn: return None
        check_sql = "SELECT id FROM applicants WHERE email = %s;"
        insert_applicant_sql = "INSERT INTO applicants (name, email, phone, domain, education, job_history, cv_url, gmail_thread_id, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'New') RETURNING id;"
        insert_comm_sql = "INSERT INTO communications (applicant_id, gmail_message_id, sender, subject, body, direction) VALUES (%s, %s, %s, %s, %s, 'Incoming');"
        log_status_sql = "INSERT INTO applicant_status_history (applicant_id, status_name) VALUES (%s, %s);"
        
        try:
            with self.conn.cursor() as cur:
                cur.execute(check_sql, (applicant_data.get("Email"),))
                if cur.fetchone():
                    logger.info(f"Skipping duplicate applicant: {applicant_data.get('Email')}")
                    return None
                
                cur.execute(insert_applicant_sql, (
                    applicant_data.get("Name"), applicant_data.get("Email"), applicant_data.get("Phone"),
                    applicant_data.get("Domain", "Other"), applicant_data.get("Education"),
                    applicant_data.get("JobHistory"), applicant_data.get("CV_URL"),
                    email_data.get("thread_id")
                ))
                applicant_id = cur.fetchone()[0]

                # Log the initial 'New' status
                cur.execute(log_status_sql, (applicant_id, 'New'))

                cur.execute(insert_comm_sql, (
                    applicant_id, email_data.get("id"), email_data.get("sender"),
                    email_data.get("subject"), email_data.get("body")
                ))
                self.conn.commit()
                logger.info(f"New applicant '{applicant_data.get('Name')}' and initial email inserted. Initial status logged.")
                return applicant_id
        except Exception as e:
            logger.error(f"Error in combined insert: {e}", exc_info=True)
            self.conn.rollback()
            return None

    def update_applicant_status(self, applicant_id, new_status):
        self._connect()
        if not self.conn: return False
        update_sql = "UPDATE applicants SET status = %s WHERE id = %s;"
        log_sql = "INSERT INTO applicant_status_history (applicant_id, status_name) VALUES (%s, %s);"
        try:
            with self.conn.cursor() as cur:
                cur.execute(update_sql, (new_status, applicant_id))
                cur.execute(log_sql, (applicant_id, new_status))
                self.conn.commit()
                logger.info(f"Updated status for applicant {applicant_id} to '{new_status}' and logged history.")
                return True
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            self.conn.rollback()
            return False

    def get_status_history(self, applicant_id):
        self._connect()
        if not self.conn: return pd.DataFrame()
        query = """
        SELECT status_name, changed_at
        FROM applicant_status_history
        WHERE applicant_id = %s
        ORDER BY changed_at ASC;
        """
        try:
            df = pd.read_sql_query(query, self.conn, params=(applicant_id,))
            return df
        except Exception as e:
            logger.error(f"Error fetching status history for applicant {applicant_id}: {e}")
            return pd.DataFrame()

    def update_applicant_feedback(self, applicant_id, feedback):
        self._connect()
        if not self.conn: return False
        sql = "UPDATE applicants SET feedback = %s WHERE id = %s;"
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, (feedback, applicant_id))
                self.conn.commit()
                logger.info(f"Updated feedback for applicant {applicant_id}.")
                return True
        except Exception as e:
            logger.error(f"Error updating feedback: {e}")
            self.conn.rollback()
            return False

    def fetch_applicants_as_df(self):
        self._connect()
        if not self.conn: return pd.DataFrame()
        
        # This query uses COALESCE to show the creation date if no other action exists
        query = """
        SELECT 
            a.id, a.name, a.email, a.phone, a.domain, a.job_history, 
            a.education, a.cv_url, a.status, a.feedback, a.created_at, 
            a.gmail_thread_id, 
            COALESCE(h.last_action_date, a.created_at) as last_action_date
        FROM 
            applicants a
        LEFT JOIN (
            SELECT 
                applicant_id, 
                MAX(changed_at) as last_action_date
            FROM 
                applicant_status_history
            GROUP BY 
                applicant_id
        ) h ON a.id = h.applicant_id
        ORDER BY 
            last_action_date DESC, a.created_at DESC;
        """
        try:
            df = pd.read_sql_query(query, self.conn)
            df['job_history'] = df['job_history'].fillna('')
            df['feedback'] = df['feedback'].fillna('')
            return df
        except Exception as e:
            logger.error(f"Error fetching applicants with last action date: {e}")
            # Fallback to a simpler query if the advanced one fails
            try:
                simple_query = "SELECT *, created_at as last_action_date FROM applicants ORDER BY created_at DESC;"
                df = pd.read_sql_query(simple_query, self.conn)
                df['job_history'] = df['job_history'].fillna('')
                df['feedback'] = df['feedback'].fillna('')
                return df
            except Exception as fallback_e:
                logger.error(f"Fallback query also failed: {fallback_e}")
                return pd.DataFrame()

    def insert_bulk_applicants(self, applicants_df):
        self._connect()
        if not self.conn: return 0, 0
        inserted_count, skipped_count = 0, 0
        applicants_df.columns = [col.replace('_', ' ').title().replace(' ', '') for col in applicants_df.columns]
        required_cols = ['Name', 'Email']
        if not all(col in applicants_df.columns for col in required_cols):
            logger.error(f"Import failed: DataFrame is missing required columns 'Name' or 'Email'. Found: {list(applicants_df.columns)}")
            return "Import failed: The sheet must contain 'Name' and 'Email' columns.", 0
        
        check_sql = "SELECT id FROM applicants WHERE email = %s;"
        insert_sql = "INSERT INTO applicants (name, email, phone, domain, education, job_history, cv_url, status, feedback) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;"
        log_status_sql = "INSERT INTO applicant_status_history (applicant_id, status_name) VALUES (%s, %s);"

        try:
            with self.conn.cursor() as cur:
                for _, row in applicants_df.iterrows():
                    email = row.get('Email')
                    if not email:
                        skipped_count += 1
                        continue
                    cur.execute(check_sql, (email,))
                    if cur.fetchone():
                        skipped_count += 1
                        continue
                    
                    status = row.get('Status', 'New')
                    cur.execute(insert_sql, (
                        row.get('Name'), email, row.get('Phone'), row.get('Domain', 'Other'),
                        row.get('Education'), row.get('JobHistory'), row.get('CvUrl'),
                        status, row.get('Feedback')
                    ))
                    applicant_id = cur.fetchone()[0]
                    cur.execute(log_status_sql, (applicant_id, status))
                    inserted_count += 1
                self.conn.commit()
                logger.info(f"Bulk insert complete. Inserted: {inserted_count}, Skipped: {skipped_count}")
        except Exception as e:
            logger.error(f"Error during bulk insert: {e}", exc_info=True)
            self.conn.rollback()
            return str(e), 0
        return inserted_count, skipped_count
    
    def log_interview(self, applicant_id, interviewer_id, title, start_time, end_time, event_id):
        self._connect();
        if not self.conn: return False
        sql = """INSERT INTO interviews (applicant_id, interviewer_id, event_title, start_time, end_time, google_calendar_event_id, status) VALUES (%s, %s, %s, %s, %s, %s, 'Scheduled');""";
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (applicant_id, interviewer_id, title, start_time, end_time, event_id)); self.conn.commit(); logger.info(f"Successfully logged interview for applicant {applicant_id}"); return True
        except Exception as e: logger.error(f"Failed to log interview: {e}", exc_info=True); self.conn.rollback(); return False
    def get_interviews_for_applicant(self, applicant_id):
        self._connect();
        if not self.conn: return pd.DataFrame()
        query = """SELECT i.event_title, i.start_time, i.status, iv.name as interviewer_name FROM interviews i LEFT JOIN interviewers iv ON i.interviewer_id = iv.id WHERE i.applicant_id = %s ORDER BY i.start_time DESC;""";
        try: return pd.read_sql_query(query, self.conn, params=(applicant_id,));
        except Exception as e: logger.error(f"Error fetching interviews for applicant {applicant_id}: {e}"); return pd.DataFrame()
    def get_interviewers(self):
        self._connect();
        if not self.conn: return pd.DataFrame()
        query = "SELECT id, name, email FROM interviewers ORDER BY name;";
        try: return pd.read_sql_query(query, self.conn)
        except Exception as e: logger.error(f"Error fetching interviewers: {e}"); return pd.DataFrame()
    def add_interviewer(self, name, email):
        self._connect();
        if not self.conn: return False
        sql = "INSERT INTO interviewers (name, email) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (name, email)); self.conn.commit(); return cur.rowcount > 0
        except Exception as e: logger.error(f"Error adding interviewer '{name}': {e}"); self.conn.rollback(); return False
    def delete_interviewer(self, interviewer_id):
        self._connect();
        if not self.conn: return False
        sql = "DELETE FROM interviewers WHERE id = %s;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (interviewer_id,)); self.conn.commit(); return True
        except Exception as e: logger.error(f"Error deleting interviewer {interviewer_id}: {e}"); self.conn.rollback(); return False
    def _populate_initial_statuses(self):
        self._connect();
        if not self.conn: return
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM applicant_statuses;")
                if cur.fetchone()[0] == 0:
                    default_statuses = ["New",  "Interview Round 1", "Interview Round 2", "Offer", "Rejected", "Hired"]
                    insert_query = "INSERT INTO applicant_statuses (status_name) VALUES (%s);"
                    for status in default_statuses: cur.execute(insert_query, (status,))
                    self.conn.commit(); logger.info("Populated applicant_statuses with default values.")
        except Exception as e: logger.error(f"Error populating default statuses: {e}"); self.conn.rollback()
    def get_statuses(self):
        self._connect();
        if not self.conn: return []
        try:
            with self.conn.cursor() as cur: cur.execute("SELECT status_name FROM applicant_statuses ORDER BY id;"); return [row[0] for row in cur.fetchall()]
        except Exception as e: logger.error(f"Error fetching statuses: {e}"); return []
    def add_status(self, status_name):
        self._connect();
        if not self.conn: return False
        sql = "INSERT INTO applicant_statuses (status_name) VALUES (%s) ON CONFLICT (status_name) DO NOTHING;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (status_name,)); self.conn.commit(); return cur.rowcount > 0
        except Exception as e: logger.error(f"Error adding status '{status_name}': {e}"); self.conn.rollback(); return False
    def delete_status(self, status_name):
        self._connect();
        if not self.conn: return "Database connection failed."
        check_sql = "SELECT 1 FROM applicants WHERE status = %s LIMIT 1;"; delete_sql = "DELETE FROM applicant_statuses WHERE status_name = %s;"
        try:
            with self.conn.cursor() as cur:
                cur.execute(check_sql, (status_name,))
                if cur.fetchone(): return f"Cannot delete '{status_name}' as it is currently assigned to one or more applicants."
                cur.execute(delete_sql, (status_name,)); self.conn.commit()
                if cur.rowcount > 0: return None
                else: return f"Status '{status_name}' not found."
        except Exception as e: logger.error(f"Error deleting status '{status_name}': {e}"); self.conn.rollback(); return f"An unexpected error occurred: {e}"
    def delete_applicants(self, applicant_ids):
        if not applicant_ids: return False
        self._connect();
        if not self.conn: return False
        ids_tuple = tuple(applicant_ids) if isinstance(applicant_ids, list) else applicant_ids; sql = "DELETE FROM applicants WHERE id IN %s;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (ids_tuple,)); self.conn.commit(); logger.info(f"Successfully deleted {cur.rowcount} applicants."); return True
        except Exception as e: logger.error(f"Error deleting applicants: {e}"); self.conn.rollback(); return False
    def clear_all_tables(self):
        self._connect();
        if not self.conn: return False
        drop_command = "DROP TABLE IF EXISTS applicants, communications, applicant_statuses, export_logs, interviewers, interviews, applicant_status_history CASCADE;"
        try:
            with self.conn.cursor() as cur: cur.execute(drop_command); self.conn.commit(); logger.info("Successfully dropped all application tables."); return True
        except Exception as e: logger.error(f"Error dropping tables: {e}"); self.conn.rollback(); return False
    def insert_communication(self, comm_data):
        self._connect();
        if not self.conn: return False
        sql = "INSERT INTO communications (applicant_id, gmail_message_id, sender, subject, body, direction) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (gmail_message_id) DO NOTHING;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (comm_data.get("applicant_id"), comm_data.get("gmail_message_id"), comm_data.get("sender"), comm_data.get("subject"), comm_data.get("body"), comm_data.get("direction"))); self.conn.commit(); return True
        except Exception as e: logger.error(f"Error inserting communication: {e}"); self.conn.rollback(); return False
    def get_conversations(self, applicant_id):
        self._connect();
        if not self.conn: return pd.DataFrame()
        query = "SELECT gmail_message_id, sender, subject, body, direction, sent_at FROM communications WHERE applicant_id = %s ORDER BY sent_at ASC;"
        try: return pd.read_sql_query(query, self.conn, params=(applicant_id,))
        except Exception as e: logger.error(f"Error fetching conversations: {e}"); return pd.DataFrame()
    def get_active_threads(self):
        self._connect();
        if not self.conn: return []
        query = "SELECT id, gmail_thread_id FROM applicants WHERE status NOT IN ('Rejected', 'Hired');"
        try:
            with self.conn.cursor() as cur: cur.execute(query); return cur.fetchall() 
        except Exception as e: logger.error(f"Error fetching active threads: {e}"); return []
    def insert_export_log(self, file_name, sheet_url, user="HR"):
        self._connect();
        if not self.conn: return False
        sql = "INSERT INTO export_logs (file_name, sheet_url, created_by) VALUES (%s, %s, %s);"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (file_name, sheet_url, user)); self.conn.commit(); logger.info(f"New export log created for: {file_name}"); return True
        except Exception as e: logger.error(f"Error inserting export log: {e}"); self.conn.rollback(); return False
    def delete_export_log(self, log_id):
        self._connect();
        if not self.conn: return False
        sql = "DELETE FROM export_logs WHERE id = %s;"
        try:
            with self.conn.cursor() as cur: cur.execute(sql, (log_id,)); self.conn.commit(); logger.info(f"Deleted export log with ID: {log_id}"); return True
        except Exception as e: logger.error(f"Error deleting export log {log_id}: {e}"); self.conn.rollback(); return False
    def fetch_export_logs(self):
        self._connect();
        if not self.conn: return pd.DataFrame()
        query = "SELECT id, file_name, sheet_url, created_at FROM export_logs ORDER BY created_at DESC LIMIT 5;"
        try: return pd.read_sql_query(query, self.conn)
        except Exception as e: logger.error(f"Error fetching export logs: {e}"); return pd.DataFrame()
    
    
    def update_applicant_status(self, applicant_id, new_status):
        """
        Updates an applicant's status only if the new status is different from the current one.
        Logs the change in the status history table.
        """
        self._connect()
        if not self.conn: return False

        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT status FROM applicants WHERE id = %s;", (applicant_id,))
                result = cur.fetchone()
                if not result:
                    logger.warning(f"Attempted to update status for non-existent applicant ID: {applicant_id}")
                    return False
                
                current_status = result[0]

                # Only proceed if the status has actually changed
                if current_status == new_status:
                    logger.info(f"Status for applicant {applicant_id} is already '{new_status}'. No update performed.")
                    return True  

                # If status is different, perform the update and log it
                update_sql = "UPDATE applicants SET status = %s WHERE id = %s;"
                log_sql = "INSERT INTO applicant_status_history (applicant_id, status_name) VALUES (%s, %s);"
                
                cur.execute(update_sql, (new_status, applicant_id))
                cur.execute(log_sql, (applicant_id, new_status))
                
                self.conn.commit()
                logger.info(f"Updated status for applicant {applicant_id} from '{current_status}' to '{new_status}' and logged history.")
                return True

        except Exception as e:
            logger.error(f"Error updating status for applicant {applicant_id}: {e}", exc_info=True)
            self.conn.rollback()
            return False
