# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime, timedelta
import pandas as pd
import json
import cv2
from pyzbar.pyzbar import decode
import os
from functools import wraps
import numpy as np
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure secret key

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# Constants
BREAKFAST_START = 7
BREAKFAST_END = 10
LUNCH_START = 13
LUNCH_END = 16
DINNER_START = 19
DINNER_END = 22
COOLDOWN_HOURS = 2

# Database files
USERS_DB = 'users.csv'
SCANS_DB = 'scans.csv'
ADMIN_CREDENTIALS = {'dotslash': 'hsalstod'}  # Change this to secure credentials

class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

def initialize_databases():
    """Initialize CSV databases if they don't exist"""
    if not os.path.exists(USERS_DB):
        pd.DataFrame(columns=['username', 'last_scan', 'is_active']).to_csv(USERS_DB, index=False)
    
    if not os.path.exists(SCANS_DB):
        columns = ['username', 'date', 'breakfast', 'lunch', 'dinner']
        pd.DataFrame(columns=columns).to_csv(SCANS_DB, index=False)

def get_meal_counts():
    """Calculate meal counts for all users"""
    try:
        df = pd.read_csv(SCANS_DB)
        user_totals = df.groupby('username').agg({
            'breakfast': 'sum',
            'lunch': 'sum',
            'dinner': 'sum'
        }).reset_index()
        
        # Calculate total meals
        user_totals['total_meals'] = user_totals['breakfast'] + user_totals['lunch'] + user_totals['dinner']
        
        # Convert to integer and then to dictionary
        user_totals = user_totals.astype({
            'breakfast': 'int',
            'lunch': 'int',
            'dinner': 'int',
            'total_meals': 'int'
        })
        
        return user_totals.to_dict('records')
    except Exception as e:
        print(f"Error calculating meal counts: {e}")
        return []

def get_current_meal():
    """Determine current meal based on time"""
    current_hour = datetime.now().hour
    
    if BREAKFAST_START <= current_hour < BREAKFAST_END:
        return 'breakfast'
    elif LUNCH_START <= current_hour < LUNCH_END:
        return 'lunch'
    elif DINNER_START <= current_hour < DINNER_END:
        return 'dinner'
    return None

def can_scan(username):
    """Check if user can scan based on cooldown period"""
    users_df = pd.read_csv(USERS_DB)
    user = users_df[users_df['username'] == username]
    
    if user.empty or not user.iloc[0]['is_active']:
        return False
        
    last_scan = user.iloc[0]['last_scan']
    if pd.isna(last_scan):
        return True
        
    last_scan_time = datetime.strptime(last_scan, '%Y-%m-%d %H:%M:%S')
    return datetime.now() - last_scan_time > timedelta(hours=COOLDOWN_HOURS)

def update_scan_record(username, meal):
    """Update scan records in the database"""
    current_date = datetime.now().date()
    scans_df = pd.read_csv(SCANS_DB)
    
    # Create new record
    new_record = {
        'username': username,
        'date': current_date,
        'breakfast': 1 if meal == 'breakfast' else 0,
        'lunch': 1 if meal == 'lunch' else 0,
        'dinner': 1 if meal == 'dinner' else 0
    }
    scans_df = pd.concat([scans_df, pd.DataFrame([new_record])], ignore_index=True)
    scans_df.to_csv(SCANS_DB, index=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scan', methods=['POST'])
def scan():
    try:
        # Handle both image upload and camera capture
        if 'image' in request.files:
            # Handle uploaded image
            image_file = request.files['image']
            nparr = np.frombuffer(image_file.read(), np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            # Handle camera capture
            image_data = request.json['image']
            # Convert base64 to image
            # Implementation depends on how front-end sends camera data
            
        decoded_objects = decode(image)
        
        if not decoded_objects:
            return jsonify({'error': 'No QR code found'}), 400
            
        qr_data = json.loads(decoded_objects[0].data.decode('utf-8'))
        username = qr_data.get('username')
        
        if not username:
            return jsonify({'error': 'Invalid QR code format'}), 400
            
        if not can_scan(username):
            return jsonify({'error': 'Scanning not allowed. Please wait for cooldown period.'}), 400
            
        current_meal = get_current_meal()
        if not current_meal:
            return jsonify({'error': 'No meal service active at this time'}), 400
            
        # Update databases
        update_scan_record(username, current_meal)
        
        # Update last scan time
        users_df = pd.read_csv(USERS_DB)
        users_df.loc[users_df['username'] == username, 'last_scan'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        users_df.to_csv(USERS_DB, index=False)
        
        return jsonify({'success': True, 'meal': current_meal})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if ADMIN_CREDENTIALS.get(username) == password:
            user = User(username)
            login_user(user)
            return redirect(url_for('admin_dashboard'))
            
        return 'Invalid credentials', 401
        
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    users_df = pd.read_csv(USERS_DB)
    scans_df = pd.read_csv(SCANS_DB)
    meal_counts = get_meal_counts()
    return render_template('admin_dashboard.html', 
                         users=users_df.to_dict('records'), 
                         scans=scans_df.to_dict('records'),
                         meal_counts=meal_counts)

@app.route('/admin/toggle_active/<username>')
@login_required
def toggle_active(username):
    users_df = pd.read_csv(USERS_DB)
    users_df.loc[users_df['username'] == username, 'is_active'] = ~users_df.loc[users_df['username'] == username, 'is_active']
    users_df.to_csv(USERS_DB, index=False)
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    initialize_databases()
    app.run(debug=True)