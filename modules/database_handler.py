import sqlite3
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
from utils.logger import logger

class DatabaseHandler:
    def __init__(self, db_path='hiring_platform.db'):
        """Initialize database connection and create tables if needed."""
        self.db_path = db_path
        self.create_tables()
        
    def get_connection(self):
        """Create and return a new database connection."""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def create_tables(self):
        """Create necessary database tables if they don't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Applicants table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS applicants (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                Name TEXT NOT NULL,
                Email TEXT UNIQUE NOT NULL,
                Phone TEXT,
                Education TEXT,
                JobHistory TEXT,
                Domain TEXT,
                CV_URL TEXT,
                Status TEXT DEFAULT 'New',
                Feedback TEXT,
                ThreadID TEXT,
                CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UpdatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Communications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS communications (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                ApplicantID INTEGER NOT NULL,
                GmailMessageID TEXT UNIQUE,
                ThreadID TEXT,
                Sender TEXT,
                Subject TEXT,
                Body TEXT,
                Direction TEXT,
                CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ApplicantID) REFERENCES applicants (ID)
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_applicant_status 
            ON applicants(Status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_applicant_email 
            ON applicants(Email)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_comm_applicant 
            ON communications(ApplicantID)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_comm_gmail_id 
            ON communications(GmailMessageID)
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database tables created/verified successfully")
    
    def insert_applicant_and_communication(self, applicant_data, email_data):
        """Insert a new applicant and their initial communication."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if applicant already exists
            cursor.execute('SELECT ID FROM applicants WHERE Email = ?', 
                          (applicant_data.get('Email'),))
            existing = cursor.fetchone()
            
            if existing:
                logger.warning(f"Applicant with email {applicant_data.get('Email')} already exists")
                return None
            
            # Insert applicant
            local_tz = ZoneInfo("Asia/Kolkata")
            current_time = datetime.now(local_tz)
            
            cursor.execute('''
                INSERT INTO applicants (Name, Email, Phone, Education, JobHistory, 
                                      Domain, CV_URL, Status, ThreadID, CreatedAt, UpdatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                applicant_data.get('Name'),
                applicant_data.get('Email'),
                applicant_data.get('Phone'),
                applicant_data.get('Education'),
                applicant_data.get('JobHistory'),
                applicant_data.get('Domain', 'Other'),
                applicant_data.get('CV_URL'),
                applicant_data.get('Status', 'New'),
                email_data.get('thread_id'),
                current_time,
                current_time
            ))
            
            applicant_id = cursor.lastrowid
            
            # Insert initial communication if email data provided
            if email_data and email_data.get('id'):
                cursor.execute('''
                    INSERT INTO communications (ApplicantID, GmailMessageID, ThreadID, 
                                              Sender, Subject, Body, Direction, CreatedAt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    applicant_id,
                    email_data.get('id'),
                    email_data.get('thread_id'),
                    email_data.get('sender'),
                    email_data.get('subject'),
                    email_data.get('body'),
                    'Incoming',
                    current_time
                ))
            
            conn.commit()
            logger.info(f"Successfully inserted applicant {applicant_id}: {applicant_data.get('Name')}")
            return applicant_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to insert applicant: {e}", exc_info=True)
            return None
        finally:
            conn.close()
    
    def get_all_applicants(self):
        """Retrieve all applicants as a pandas DataFrame."""
        conn = self.get_connection()
        query = '''
            SELECT ID, Name, Email, Phone, Education, JobHistory, Domain, 
                   CV_URL, Status, Feedback, ThreadID, CreatedAt, UpdatedAt
            FROM applicants
            ORDER BY CreatedAt DESC
        '''
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    
    def get_applicant_by_id(self, applicant_id):
        """Retrieve a specific applicant by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM applicants WHERE ID = ?
        ''', (applicant_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, result))
        return None
    
    def update_applicant_status(self, applicant_id, new_status):
        """Update the status of an applicant."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            local_tz = ZoneInfo("Asia/Kolkata")
            current_time = datetime.now(local_tz)
            
            cursor.execute('''
                UPDATE applicants 
                SET Status = ?, UpdatedAt = ?
                WHERE ID = ?
            ''', (new_status, current_time, applicant_id))
            
            conn.commit()
            logger.info(f"Updated applicant {applicant_id} status to {new_status}")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update applicant status: {e}")
            return False
        finally:
            conn.close()
    
    def update_applicant_thread_id(self, applicant_id, thread_id):
        """Update the thread ID for an applicant."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE applicants 
                SET ThreadID = ?, UpdatedAt = ?
                WHERE ID = ?
            ''', (thread_id, datetime.now(ZoneInfo("Asia/Kolkata")), applicant_id))
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update thread ID: {e}")
            return False
        finally:
            conn.close()
    
    def get_active_threads(self):
        """Get all active email threads for monitoring replies."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ID, ThreadID 
            FROM applicants 
            WHERE ThreadID IS NOT NULL 
            AND Status NOT IN ('Rejected', 'Hired')
        ''')
        
        results = cursor.fetchall()
        conn.close()
        return results
    
    def insert_communication(self, comm_data):
        """Insert a new communication record."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if communication already exists
            cursor.execute('SELECT ID FROM communications WHERE GmailMessageID = ?',
                          (comm_data.get('gmail_message_id'),))
            if cursor.fetchone():
                logger.info(f"Communication {comm_data.get('gmail_message_id')} already exists")
                return None
            
            cursor.execute('''
                INSERT INTO communications (ApplicantID, GmailMessageID, ThreadID, 
                                          Sender, Subject, Body, Direction, CreatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                comm_data.get('applicant_id'),
                comm_data.get('gmail_message_id'),
                comm_data.get('thread_id'),
                comm_data.get('sender'),
                comm_data.get('subject'),
                comm_data.get('body'),
                comm_data.get('direction', 'Incoming'),
                datetime.now(ZoneInfo("Asia/Kolkata"))
            ))
            
            comm_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Inserted communication {comm_id} for applicant {comm_data.get('applicant_id')}")
            return comm_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to insert communication: {e}")
            return None
        finally:
            conn.close()
    
    def get_conversations(self, applicant_id):
        """Get all communications for a specific applicant."""
        conn = self.get_connection()
        query = '''
            SELECT * FROM communications 
            WHERE ApplicantID = ?
            ORDER BY CreatedAt DESC
        '''
        df = pd.read_sql_query(query, conn, params=(applicant_id,))
        conn.close()
        return df
    
    def update_applicant_feedback(self, applicant_id, feedback):
        """Update feedback for an applicant."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE applicants 
                SET Feedback = ?, UpdatedAt = ?
                WHERE ID = ?
            ''', (feedback, datetime.now(ZoneInfo("Asia/Kolkata")), applicant_id))
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update feedback: {e}")
            return False
        finally:
            conn.close()
    
    def get_database_stats(self):
        """Get database statistics for monitoring."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Total applicants
        cursor.execute('SELECT COUNT(*) FROM applicants')
        stats['total_applicants'] = cursor.fetchone()[0]
        
        # Total communications
        cursor.execute('SELECT COUNT(*) FROM communications')
        stats['total_communications'] = cursor.fetchone()[0]
        
        # Active threads
        cursor.execute('''
            SELECT COUNT(*) FROM applicants 
            WHERE ThreadID IS NOT NULL 
            AND Status NOT IN ('Rejected', 'Hired')
        ''')
        stats['active_threads'] = cursor.fetchone()[0]
        
        # Status distribution
        cursor.execute('''
            SELECT Status, COUNT(*) as count 
            FROM applicants 
            GROUP BY Status
        ''')
        stats['status_distribution'] = dict(cursor.fetchall())
        
        # Database size
        if os.path.exists(self.db_path):
            stats['db_size_mb'] = os.path.getsize(self.db_path) / (1024 * 1024)
        
        conn.close()
        return stats
    
    def search_applicants(self, search_query):
        """Search applicants by name, email, or phone."""
        conn = self.get_connection()
        query = '''
            SELECT * FROM applicants 
            WHERE Name LIKE ? OR Email LIKE ? OR Phone LIKE ?
            ORDER BY CreatedAt DESC
        '''
        search_pattern = f'%{search_query}%'
        df = pd.read_sql_query(query, conn, params=(search_pattern, search_pattern, search_pattern))
        conn.close()
        return df
    
    def bulk_update_status(self, applicant_ids, new_status):
        """Update status for multiple applicants."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            placeholders = ','.join('?' * len(applicant_ids))
            cursor.execute(f'''
                UPDATE applicants 
                SET Status = ?, UpdatedAt = ?
                WHERE ID IN ({placeholders})
            ''', [new_status, datetime.now(ZoneInfo("Asia/Kolkata"))] + applicant_ids)
            
            conn.commit()
            logger.info(f"Bulk updated {len(applicant_ids)} applicants to status {new_status}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to bulk update status: {e}")
            return False
        finally:
            conn.close()
    
    def get_recent_applicants(self, days=7):
        """Get applicants from the last N days."""
        conn = self.get_connection()
        query = '''
            SELECT * FROM applicants 
            WHERE CreatedAt >= datetime('now', ? || ' days')
            ORDER BY CreatedAt DESC
        '''
        df = pd.read_sql_query(query, conn, params=(-days,))
        conn.close()
        return df
