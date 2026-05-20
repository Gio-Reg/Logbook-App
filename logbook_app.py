import os, io, uuid, threading, subprocess, json, pickle, base64, re, time
from datetime import datetime, timedelta, timezone, date as dt_date

# Flask & Security
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort, session, flash, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth

# Google Services
from google import genai
from google.genai import types
from google.api_core import exceptions
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Database & External APIs
from sqlalchemy import MetaData
import cloudinary, cloudinary.uploader
from dotenv import load_dotenv

# Local Service
from utils.youtube_service import YouTubeVaultService

os.makedirs('temp', exist_ok=True)

processing_lock = threading.Lock()

# 1. Initialize the TRACE SaaS App
load_dotenv()
app = Flask(__name__)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Stay logged in for a year
app.config['SESSION_PERMANENT'] = True
app.secret_key = os.getenv("FLASK_SECRET_KEY", "trace-vault-secret-2026") 
CORS(app, resources={r"/*": {"origins": "*"}})

# Logic to handle Render's PostgreSQL and local SQLite
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)



convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///standalone_logbook.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
metadata = MetaData(naming_convention=convention)
db = SQLAlchemy(app, metadata=metadata)
migrate = Migrate(app, db, render_as_batch=True)

# --- NEW AUTHENTICATION SETUP ---
login_manager = LoginManager(app)
login_manager.session_protection = "strong"
login_manager.login_message_category = "info"
login_manager.login_view = "login"

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("YT_CLIENT_ID"), # Reusing your existing Google Credentials
    client_secret=os.getenv("YT_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- CONFIGURATION for GDRIvE UPLOADS---
ENABLE_AI_SHIELD = True 
WAIT_FOR_DRIVE_READY = False  # Set to True to re-enable the wait in the future
API_KEY = os.environ.get("GOOGLE_API_KEY")
TARGET_FOLDER_ID = "1ddoYbGLbI7YxKW48gv7OMyVUviF99cJi"
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SIZE_THRESHOLD_MB = 70  # Threshold for high-quality vs compression logic

# --- CLIENT SETUP ---
client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=5,
            initial_delay=2.0,
            max_delay=60.0
        )
    )
)

cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_NAME"), 
  api_key = os.getenv("CLOUDINARY_API_KEY"), 
  api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

# 2. The Portable Database/Relations Schema
class Author(db.Model, UserMixin):
    __tablename__ = 'authors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    secret_token = db.Column(db.String(100), unique=True, default=lambda: str(uuid.uuid4())[:12])
    tier = db.Column(db.String(20), default="LIFE_LONGER")
    
    # LOGIN FIELDS
    email = db.Column(db.String(120), unique=True, nullable=True)
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    password_hash = db.Column(db.String(200))
    
    logs = db.relationship('LogEntry', backref='author_ref', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return Author.query.get(int(user_id))

class LogEntry(db.Model):
    __tablename__ = 'log_entries'
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('authors.id'), nullable=False) # Linked to Author
    user_id = db.Column(db.Integer, index=True) 
    context_id = db.Column(db.String(50))      
    tier_type = db.Column(db.String(20))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    
    video_url = db.Column(db.Text, default="")
    video_url_homework = db.Column(db.Text, default="")
    photo_url = db.Column(db.Text, default="")
    notes_coach_after = db.Column(db.Text, default="")

    def __init__(self, author_id, context_id=None, user_id=None, tier_type=None):
        self.author_id = author_id
        self.context_id = context_id
        self.user_id = user_id
        self.tier_type = tier_type

class SharedAccess(db.Model):
    __tablename__ = 'shared_access'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('authors.id'), nullable=False)
    guest_token = db.Column(db.String(20), unique=True, default=lambda: str(uuid.uuid4())[:12])
    guest_email = db.Column(db.String(120), nullable=True) # <--- ADD THIS LINE
    role = db.Column(db.String(20)) 
    access_type = db.Column(db.String(20)) 
    target_id = db.Column(db.Integer, nullable=True) 
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Good for tracking    

with app.app_context():
    db.create_all()

# 3. The "Switchboard" Logic
def get_authorized_logs(current_user):
    """Filters logs based on the user's tier."""
    if current_user['tier'] == 'TEACHER':
        return LogEntry.query.filter_by(context_id=current_user['active_context']).order_by(LogEntry.date.desc()).all()
        
    elif current_user['tier'] == 'LIFE_LONGER':
        return LogEntry.query.filter_by(user_id=current_user['id']).order_by(LogEntry.date.desc()).all()
        
    elif current_user['tier'] == 'RESIDENT':
        return LogEntry.query.filter_by(
            user_id=current_user['id'], 
            context_id=current_user['active_context']
        ).order_by(LogEntry.date.desc()).all()
        
    return []

def get_gdrive_service():
    creds = None
    # Changed: Check for token_base64.txt and decode it
    if os.path.exists('token_base64.txt'):
        with open('token_base64.txt', 'r') as f:
            base64_data = f.read()
            creds = pickle.loads(base64.b64decode(base64_data))
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secrets.json', ['https://www.googleapis.com/auth/drive'])
            creds = flow.run_local_server(port=0)
            #creds = flow.run_local_server(port=5001, prompt='consent')
        
        # Changed: Save back as Base64 text
        with open('token_base64.txt', 'w') as f:
            f.write(base64.b64encode(pickle.dumps(creds)).decode('utf-8'))

    return build('drive', 'v3', credentials=creds)  
        
def upload_to_drive(file_path, folder_id):
    service = get_gdrive_service()
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    
    file = service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id, webViewLink',
        supportsAllDrives=True
    ).execute()
    
    file_id = file.get('id')
    
    # Set permissions so anyone can view
    permission = {'type': 'anyone', 'role': 'reader'}
    try:
        service.permissions().create(
            fileId=file_id, 
            body=permission,
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print(f"Permission failed: {e}")
    
    # -------------------------
    if WAIT_FOR_DRIVE_READY:
        print(f"⏳ Waiting for Drive to process {file_id}...")
        wait_for_drive_processing(service, file_id)
    else:
        print(f"⏩ Bypassing Drive processing wait for {file_id}.")
    # -------------------------
    
    # We return the direct embeddable link format
    embed_link = f"https://drive.google.com/file/d/{file_id}/preview"
    return file_id, embed_link

def wait_for_drive_processing(service, file_id, timeout=300):
    """Polls Google Drive until the video metadata is populated (transcoded)."""
    start_time = time.time()
    attempts = 0
    
    while time.time() - start_time < timeout:
        attempts += 1
        try:
            # Request specific video metadata fields
            file = service.files().get(
                fileId=file_id, 
                fields='videoMediaMetadata',
                supportsAllDrives=True
            ).execute()

            # If duration exists, Google has finished basic processing
            if 'videoMediaMetadata' in file and 'durationMillis' in file['videoMediaMetadata']:
                print(f"✅ Drive processing complete for {file_id} after {attempts} attempts.")
                return True
                
        except Exception as e:
            print(f"⚠️ Drive API polling error: {e}")

        # Sleep interval: 13 mins for Uptime Robot, but 10s for video readiness is safe
        time.sleep(10)
        
    print(f"❌ Timeout waiting for Drive processing for {file_id}")
    return False
    
def run_ai_shield_with_fallback(file_path):
    print("🛡️ AI Shield is scanning the video...", flush=True)
    
    time.sleep(5)
    
    try:
        with open(file_path, 'rb') as f:
            video_file = client.files.upload(file=f, config={'mime_type': 'video/mp4'})
    except Exception as e:
        print(f"❌ Failed to upload video to Files API: {e}", flush=True)
        return "BUSY"

    poll_start = time.time()
    while video_file.state.name == "PROCESSING":
        if time.time() - poll_start > 60:
            print("⚠️ Video processing timed out in Files API.", flush=True)
            client.files.delete(name=video_file.name)
            return "BUSY"
        time.sleep(2)
        try:
            video_file = client.files.get(name=video_file.name)
        except Exception as e:
            print(f"⚠️ Error polling file status: {e}", flush=True)
            client.files.delete(name=video_file.name)
            return "BUSY"

    prompt = """
    Analyze the visual content of this video. 
    Check for: 1. Sexually explicit content. 2. Terrorism/Extremism. 3. Graphic violence.
    Respond ONLY with 'SAFE', 'APPROVED', or 'REJECTED: [Reason]'.
    """

    safety_settings = [
        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_LOW_AND_ABOVE'),
        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_LOW_AND_ABOVE')
    ]

    models_to_try = [
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash"
    ]

    ai_success = False
    decision = "BUSY"

    for model_name in models_to_try:
        try:
            print(f">>> SHIELD: Trying {model_name}...", flush=True)
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt, video_file],
                config=types.GenerateContentConfig(
                    safety_settings=safety_settings,
                    http_options={'timeout': 15000} 
                )
            )
            
            if response.text:
                result_upper = response.text.strip().upper()
                print(f"AI response: {result_upper}", flush=True)

                if "SAFE" in result_upper or "APPROVED" in result_upper:
                    decision = "APPROVED"
                elif "REJECTED" in result_upper:
                    decision = "REJECTED"
                
                ai_success = True
                break

        except (exceptions.ServiceUnavailable, exceptions.ResourceExhausted) as e:
            print(f"⚠️ {model_name} busy or rate limited. Cooling down 10s before fallback...", flush=True)
            time.sleep(10)
            continue
        except Exception as e:
            print(f"⚠️ Error with {model_name}: {str(e)[:50]}. Moving to next backup...", flush=True)
            continue

    try:
        print("🧹 Deleting temporary video from Gemini Files API...", flush=True)
        client.files.delete(name=video_file.name)
    except Exception as e:
        print(f"⚠️ Failed to delete Gemini file: {e}", flush=True)

    return decision
     
def process_video_size(file_path):
    import subprocess
    # Check the actual file size
    file_size = os.path.getsize(file_path)
    MAX_SIZE_BYTES = 70 * 1024 * 1024  # 70MB
    
    output_path = file_path.replace(".mp4", "_processed.mp4")
    
    if file_size <= MAX_SIZE_BYTES:
        # RULES PRESERVED: File is under 70MB. We do NOT re-encode or compress it.
        # This instantly re-wraps the container properties in less than 0.5 seconds.
        print(f"✅ Under 70MB ({file_size / 1024 / 1024:.2f}MB). Instant copy & faststart optimize.", flush=True)
        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-c:v', 'copy',                    # Copy video track instantly without encoding
            '-c:a', 'copy',                    # Copy audio track instantly without encoding
            '-movflags', '+faststart',         # Instantly shifts maps to the front for streaming
            output_path
        ]
    else:
        # File is over 70MB. Shrink and compress it down.
        print(f"⚡ Over 70MB ({file_size / 1024 / 1024:.2f}MB). Compressing asset down...")
        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-vf', 'scale=-2:720',
            '-c:v', 'libx264', '-crf', '25',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-movflags', '+faststart',
            '-threads', '0',
            '-c:a', 'aac', '-b:a', '128k',
            output_path
        ]
        
    subprocess.run(cmd, check=True)
    return output_path
    
# --- Flask routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    next_page = request.args.get('next')
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = Author.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            if not user.is_approved:
                return redirect(url_for('pending', next=next_page))
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash("Invalid email or password.")
            
    return render_template('login.html', next=next_page)
    
@app.route('/pending')
@login_required
def pending():
    next_url = request.args.get('next') or url_for('index')
    if current_user.is_approved:
        return redirect(next_url)
        
    return render_template('pending.html', next_url=next_url)
    
@app.route('/login/google')
def google_login():
    # Capture original shared link from "next" and store it in session
    next_page = request.args.get('next')
    if next_page:
        session['next_url'] = next_page
    return google.authorize_redirect(url_for('google_callback', _external=True))

@app.route('/auth/callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    
    author = Author.query.filter_by(email=user_info['email']).first()
    
    if not author:
        author = Author.query.filter_by(name=user_info['name']).first()
        if author:
            author.email = user_info['email']
            author.google_id = user_info['sub']
            db.session.commit()

    if not author:
        author = Author(
            name=user_info['name'],
            email=user_info['email'], 
            google_id=user_info['sub']
        )
        db.session.add(author)
        db.session.commit()
    
    login_user(author)
    
    # BLOCK ACCESS HERE: Check if the user is approved before redirecting to the book
    if not author.is_approved:
        flash("Your account is pending admin approval.")
        return redirect(url_for('pending'))

    # If there was a redirect link before signing into Google, use it!
    next_url = session.pop('next_url', None)
    if next_url:
        return redirect(next_url)
        
    return redirect(url_for('index'))
    
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# 4. Routing
@app.route('/')
def index():
    next_page = request.args.get('next')
    if next_page:
        return redirect(next_page)
        
    if current_user.is_authenticated:
        user_has_logs = LogEntry.query.filter_by(author_id=current_user.id).first()
        
        if not current_user.is_admin and not user_has_logs:
            authorized_links = SharedAccess.query.filter_by(guest_email=current_user.email.lower()).all()
            
            return render_template('guest_welcome.html', links=authorized_links) 
        
        return redirect(url_for('view_mybook', token=current_user.secret_token))
    
    return redirect(url_for('login'))

@app.route('/generate_share_link', methods=['POST'])
@login_required
def generate_share_link():
    data = request.json
    role = data.get('role', 'viewer')
    access_type = data.get('access_type', 'full_book')
    target_id = data.get('log_id') # Present if sharing a single log

    # Create a unique 12-character token for this guest
    new_token = str(uuid.uuid4())[:12]
    
    new_access = SharedAccess(
        owner_id=current_user.id,
        guest_token=new_token,
        role=role,
        access_type=access_type,
        target_id=target_id
    )
    
    db.session.add(new_access)
    db.session.commit()
    
    # Generate the full link for the guest
    share_url = url_for('view_mybook', token=new_token, _external=True)
    
    return jsonify({"success": True, "share_url": share_url})

@app.route('/stream-drive/<file_id>')
def stream_drive_file(file_id):
    import requests
    try:
        service = get_gdrive_service()
        creds = service._http.credentials
        
        if not creds.valid:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            
        headers = {'Authorization': f'Bearer {creds.token}'}
        if 'Range' in request.headers:
            headers['Range'] = request.headers['Range']
            
        url = f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true'
        google_response = requests.get(url, headers=headers, stream=True)
        
        response_headers = []
        for key, val in google_response.headers.items():
            if key.lower() in ['content-range', 'accept-ranges', 'content-length']:
                response_headers.append((key, val))
                
        return Response(
            google_response.iter_content(chunk_size=128 * 1024),
            status=google_response.status_code,
            mimetype='video/mp4',
            headers=response_headers
        )
    except Exception as e:
        print(f"❌ Pass-through Streaming Error: {e}", flush=True)
        return "Streaming pipeline failure", 500
                    
@app.route('/mybook/<token>')
def view_mybook(token):
    # --- SCENARIO A: The Master Token (Owner or Master Link Visitor) ---
    book_owner = Author.query.filter_by(secret_token=token).first()
    
    if book_owner:
        if not book_owner.is_approved:
            flash("This account is currently inactive.")
            return redirect(url_for('login'))
        
        if current_user.is_authenticated and current_user.id == book_owner.id:
            # Case A1: Authorized Owner is viewing their own book
            access_level = 'owner'
            all_logs = LogEntry.query.filter_by(author_id=book_owner.id).order_by(LogEntry.date.desc()).all()
        else:
            # Case A2: Master Link "Trap" (Someone using the master link who isn't the owner)
            if not current_user.is_authenticated:
                return redirect(url_for('login', next=request.url))
            if not current_user.is_approved:
                flash("Your account is pending approval.")
                return redirect(url_for('pending', next=request.url))
            
            authorized_links = SharedAccess.query.filter_by(guest_email=current_user.email.lower()).all()
            # Redirect to the welcome "trap" page
            return render_template('guest_welcome.html', 
                                 author=book_owner, 
                                 links=authorized_links)
            
        view_token = token

    # --- SCENARIO B: The Guest Token (Granular Permissions) ---
    else:
        access = SharedAccess.query.filter_by(guest_token=token).first_or_404()
        book_owner = Author.query.get(access.owner_id)
        
        # 🛡️ SECURITY GATE 1: Check if the Owner is still approved
        if not book_owner.is_approved:
            abort(403) # Forbidden: Owner account revoked

        # 🛡️ SECURITY GATE 2: (Optional) Require Guest to be logged in
        # If you want guests to have their own accounts to see the link:
        if not current_user.is_authenticated:
             return redirect(url_for('login', next=request.url))
        
        # --- NEW: SELF-CLAIMING LOGIC ---
        if access.guest_email is None:
            access.guest_email = current_user.email.lower()
            db.session.commit()
            
        # SECURITY CHECK: If someone else tries to use this claimed link
        elif access.guest_email.lower() != current_user.email.lower():
            flash("This specific link belongs to another user.")
            return redirect(url_for('view_mybook', token=book_owner.secret_token))
        # -------------------------------
             
        access_level = access.role  # 'viewer' or 'editor'
        view_token = access.guest_token
        
        # Scope the query based on the Guest Access settings
        if access.access_type == 'single_log':
            # Only show the specific log targeted by this link
            all_logs = LogEntry.query.filter_by(author_id=book_owner.id, id=access.target_id).all()
        else:
            # Full Book access (default for viewer/editor)
            all_logs = LogEntry.query.filter_by(author_id=book_owner.id).order_by(LogEntry.date.desc()).all()

    # --- RENDER ---
    return render_template(
        'client_logbook.html', 
        logs=all_logs, 
        author=book_owner, 
        access_level=access_level,
        view_token=view_token
    )
                 
@app.route('/create_log_json', methods=['POST'])
@login_required 
def create_log_json():
    data = request.json
    token = data.get('token')
    author = Author.query.filter_by(secret_token=token).first_or_404()
    
    if author.id != current_user.id:
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    date_str = data.get('date')
    new_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
    
    new_log = LogEntry(author_id=author.id)
    new_log.date = new_date
    new_log.context_id = data.get('lesson_title', 'New Session')
    
    db.session.add(new_log)
    db.session.commit()
    
    return jsonify({
        "success": True, 
        "log_id": new_log.id, 
        "date": new_log.date.strftime('%d %b %Y')
    })

@app.route('/create-author/<name>')
def create_author(name):
    provided_key = request.args.get('key')
    required_key = os.getenv("ADMIN_CREATE_KEY")
    
    if not required_key or provided_key != required_key:
        return "Unauthorized", 403

    existing = Author.query.filter_by(name=name).first()
    if existing:
        return f"Author {name} already exists: {request.host_url}mybook/{existing.secret_token}"

    new_author = Author(name=name)
    db.session.add(new_author)
    db.session.flush()

    first_log = LogEntry(
        author_id=new_author.id, 
        context_id="Welcome to your Logbook"
    )
    
    db.session.add(first_log)
    db.session.commit()

    magic_link = f"{request.host_url}mybook/{new_author.secret_token}"
    return f"Link created for {name}: {magic_link}"


@app.route('/share-receiver', methods=['GET', 'POST'])
def share_receiver():
    token = request.args.get('token')
    user = Author.query.filter_by(secret_token=token).first() if token else None
    if not user and not current_user.is_authenticated:
        return redirect(url_for('login'))
    active_user = user if user else current_user

    now = datetime.now(timezone.utc)
    log_entry = LogEntry.query.filter(
        LogEntry.author_id == active_user.id,
        db.func.date(LogEntry.date) == now.date()
    ).first()
    
    if not log_entry:
        log_entry = LogEntry(author_id=active_user.id, date=now, context_id="Mobile Share")
        db.session.add(log_entry)
        db.session.commit()

    if 'media' in request.files:
        files = request.files.getlist('media')
        for file in files:
            if file.filename:
                # 1. Improved detection logic
                mimetype = file.content_type or ""
                is_photo = mimetype.startswith('image/') or file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                
                print(f"DEBUG: Processing file {file.filename} (Mime: {mimetype}) - Is Photo: {is_photo}")

                file_uuid = str(uuid.uuid4())[:8]
                filename = secure_filename(f"share_{file_uuid}_{file.filename}")
                save_path = os.path.join('temp', filename)
                file.save(save_path)
                
                if is_photo:
                    try:
                        # Upload directly so it's ready when we redirect
                        upload_result = cloudinary.uploader.upload(save_path)
                        img_url = upload_result.get('secure_url')
                        
                        existing = log_entry.photo_url or ""
                        log_entry.photo_url = f"{existing},{img_url}" if existing else img_url
                        db.session.commit()
                        print(f"DEBUG: Photo successfully saved to DB: {img_url}")
                        os.remove(save_path)
                    except Exception as e:
                        print(f"ERROR: Cloudinary upload failed: {e}")
                else:
                    # Video path stays in background thread (since they are heavy)
                    placeholder = "PROCESSING_MOBILE_FILE"
                    existing = log_entry.video_url or ""
                    log_entry.video_url = f"{existing},{placeholder}" if existing else placeholder
                    db.session.commit()

                    thread = threading.Thread(
                        target=background_upload_task, 
                        args=(app, save_path, log_entry.id, False, placeholder)
                    )
                    thread.start()

    # Handle Links
    shared_text = request.values.get('text') or ""
    shared_url = request.values.get('url') or ""
    combined = f"{shared_text} {shared_url}"
    match = re.search(r'https?://\S+', combined)
    if match:
        final_link = match.group(0)
        existing_vids = log_entry.video_url or ""
        if final_link not in existing_vids:
            log_entry.video_url = f"{existing_vids},{final_link}" if existing_vids else final_link
            db.session.commit()

    return redirect(url_for('view_mybook', token=active_user.secret_token, log_id=log_entry.id))
        
@app.route('/manifest.json')
def serve_manifest():
    response = send_from_directory(os.path.join(app.root_path, 'static'), 'manifest.json')
    # This bypasses the ngrok warning page for background requests
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response
    
# 5. The Data API (Bridging the Frontend JS)
@app.route('/save_logbook/<int:log_id>', methods=['POST'])
def save_logbook(log_id):
    data = request.json
    token = data.get('token')
    log_entry = LogEntry.query.get_or_404(log_id)
    
    # 1. Authorize Request (Owner OR Guest Editor)
    is_auth = False
    if current_user.is_authenticated and log_entry.author_id == current_user.id and token == current_user.secret_token:
        is_auth = True
    else:
        # Verify Editor token scope
        access = SharedAccess.query.filter_by(guest_token=token, role='editor', owner_id=log_entry.author_id).first()
        if access:
            log_date = log_entry.date.date() if log_entry.date else None
            if access.access_type == 'full_book': is_auth = True
            elif access.access_type == 'single_log' and access.target_id == log_id: is_auth = True
            elif access.access_type == 'single_day' and log_date == access.start_date: is_auth = True
            elif access.access_type == 'date_range' and log_date >= access.start_date and log_date <= access.end_date: is_auth = True

    # If they are neither the Owner nor a valid Guest Editor, boot them out.
    if not is_auth:
        return jsonify({"success": False, "message": "Unauthorized scope"}), 403
    
    # --- FROM HERE ON, WE TRUST THE USER HAS PERMISSION TO EDIT ---

    if 'lesson_title' in data:
        log_entry.context_id = data['lesson_title']
        db.session.commit()
        if len(data) == 1 or (len(data) == 2 and 'token' in data):
            return jsonify({"success": True})
    
    new_video = data.get('video_url')
    if new_video and 'delete_url' not in data and 'update_note_for_url' not in data and 'append' not in data:
        current = log_entry.video_url or ""
        if new_video not in current:
            log_entry.video_url = f"{current},{new_video}".strip(',')
            db.session.commit()
            return jsonify({"success": True})
    
    if 'update_note_for_url' in data:
        target_url = data['update_note_for_url']
        new_note = data.get('new_note', '')
        
        for field in ['video_url', 'video_url_homework']:
            current_val = getattr(log_entry, field) or ""
            urls = current_val.split(',')
            new_urls = []
            for u in urls:
                if u.split('|')[0].strip() == target_url.strip():
                    new_urls.append(f"{target_url}|{new_note}")
                else:
                    new_urls.append(u)
            setattr(log_entry, field, ",".join(filter(None, new_urls)))

    if 'delete_url' in data:
        url_to_remove = data['delete_url'].strip()
        for field in ['video_url', 'video_url_homework', 'photo_url']:
            val = getattr(log_entry, field) or ""
            updated = [
                u.strip() for u in val.split(',') 
                if u.strip() and u.split('|')[0].strip() != url_to_remove and ("http" in u or "PROCESSING" in u)
            ]
            setattr(log_entry, field, ",".join(updated))

    if 'append' in data:
        field = 'photo_url' if 'photo_url' in data else ('video_url_homework' if data.get('is_homework') else 'video_url')
        new_url = data.get(field)
        
        existing = getattr(log_entry, field) or ""
        updated_val = f"{existing},{new_url}" if existing else new_url
        setattr(log_entry, field, updated_val)
    
    if 'notes_coach_after' in data:
        log_entry.notes_coach_after = data['notes_coach_after']

    db.session.commit()
    date_str = log_entry.date.strftime('%d %b %Y') if log_entry.date else ""
    return jsonify({"success": True, "date": date_str})
    
@app.route('/upload-media/<int:log_id>', methods=['POST'])
@login_required 
def handle_media_upload(log_id):
    log_entry = LogEntry.query.get_or_404(log_id)
    if log_entry.author_id != current_user.id:
        return jsonify({"success": False, "message": "Unauthorized Session"}), 403

    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file found"}), 400
        
    file = request.files['file']
    if file.filename == '' or file.filename is None:
        return jsonify({"success": False, "message": "No selected file"}), 400

    is_homework = request.form.get('is_homework') == 'true'
    
    if not os.path.exists('./temp'):
        os.makedirs('./temp')
            
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    save_path = os.path.join('./temp', unique_filename)
    file.save(save_path)
    
    duration, is_vertical = get_video_metadata(save_path)
    
    if is_vertical and duration < 180:
        if processing_lock.locked():
            os.remove(save_path)
            return jsonify({
                "success": False, 
                "message": "⚠️ The AI Shield is currently busy with another video. Please wait 2 minutes."
            }), 503
    
    placeholder = "PROCESSING_YOUTUBE"
    field = 'video_url_homework' if is_homework else 'video_url'
    
    existing = getattr(log_entry, field) or ""
    updated_placeholder_val = f"{existing},{placeholder}" if existing else placeholder
    setattr(log_entry, field, updated_placeholder_val)
    db.session.commit()

    app_instance = app
    thread = threading.Thread(
        target=background_upload_task, 
        args=(app, save_path, log_id, is_homework, placeholder)
    )
    thread.start()

    return jsonify({
        "success": True, 
        "message": "Upload started", 
        "date": log_entry.date.strftime('%d %b %Y')
    })

def get_video_metadata(file_path):
    print(f"\n[DEBUG] Analyzing: {os.path.basename(file_path)}", flush=True)
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json', 
        '-show_format', '-show_streams', file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    
    duration = float(data.get('format', {}).get('duration', 0))
    video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    
    if not video_stream:
        print("[DEBUG] Error: No video stream found.", flush=True)
        return duration, False

    width = int(video_stream.get('width', 0))
    height = int(video_stream.get('height', 0))
    
    rotation = 0
    side_data = video_stream.get('side_data_list', [])
    for entry in side_data:
        if 'rotation' in entry:
            rotation = abs(int(entry['rotation']))
    
    if rotation == 90 or rotation == 270:
        is_vertical = True
    else:
        is_vertical = height > width
        
    print(f"[DEBUG] Width: {width}, Height: {height}, Rotation: {rotation}", flush=True)
    print(f"[DEBUG] IS_VERTICAL RESULT: {is_vertical}", flush=True)
    return duration, is_vertical
    
def background_upload_task(app, file_path, log_id, is_homework, placeholder):
    with app.app_context():
        final_url = None
        try:
            duration, is_vertical = get_video_metadata(file_path)
            
            if is_vertical and duration < 180:
                if processing_lock.locked():
                    final_url = "BUSY_ERROR: Server is currently Shielding another video. Please try again in 2 minutes."
                else:
                    with processing_lock: 
                        shield_result = run_ai_shield_with_fallback(file_path)
                
                        if shield_result == "APPROVED":
                            final_upload_file = process_video_size(file_path)
                            _, final_url = upload_to_drive(final_upload_file, TARGET_FOLDER_ID)
                            
                            if final_upload_file != file_path and os.path.exists(final_upload_file):
                                os.remove(final_upload_file)
                        
                        elif shield_result == "BUSY":
                            final_url = "BUSY_ERROR: All safety models are busy. Please try again soon."
                        
                        else:
                            final_url = "REJECTED: Video does not meet TRACE safety standards."

            if final_url is None:
                yt = YouTubeVaultService()
                yt_id = yt.upload_video(file_path, f"TRACE Session {log_id}")
                final_url = f"https://youtu.be/{yt_id}"

            log_entry = db.session.get(LogEntry, log_id)
            if log_entry and final_url:
                field = 'video_url_homework' if is_homework else 'video_url'
                current_val = getattr(log_entry, field) or ""
                setattr(log_entry, field, current_val.replace(placeholder, final_url))
                db.session.commit()
            
        except Exception as e:
            print(f"TRACE Upload Error: {e}")
        finally:
            if os.path.exists(file_path): 
                os.remove(file_path)
                                                         
@app.route('/check-status/<int:log_id>')
def check_status(log_id):
    log_entry = LogEntry.query.get_or_404(log_id)
    is_processing = "PROCESSING_YOUTUBE" in (log_entry.video_url or "") or \
                    "PROCESSING_YOUTUBE" in (log_entry.video_url_homework or "")
    
    return jsonify({
        "status": "processing" if is_processing else "ready",
        "video_url": log_entry.video_url
    })

@app.route('/delete_log/<int:log_id>', methods=['POST'])
@login_required 
def delete_log(log_id):
    log_entry = LogEntry.query.get_or_404(log_id)
    
    if log_entry.author_id != current_user.id:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    db.session.delete(log_entry)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/unstick-upload')
@login_required 
def unstick_upload():
    try:
        # Fetch all logs for the current user to scan their text fields
        logs = LogEntry.query.filter_by(author_id=current_user.id).all()
        count = 0
        
        for entry in logs:
            updated = False
            
            # Clean main video slots
            if entry.video_url:
                # Split strings by comma to inspect individual placeholders
                items = [i.strip() for i in entry.video_url.split(',') if i.strip()]
                
                # Identify items that are stuck processing strings
                stuck_items = [i for i in items if ("processing" in i.lower() or "vault" in i.lower() or i.upper() == "LOADING")]
                
                # Keep items ONLY if they are real links or don't match stuck words
                cleaned = [i for i in items if i not in stuck_items]
                
                if len(items) != len(cleaned):
                    entry.video_url = ",".join(cleaned)
                    updated = True
                    count += 1
                    
            # Clean homework video slots
            if entry.video_url_homework:
                items = [i.strip() for i in entry.video_url_homework.split(',') if i.strip()]
                stuck_items = [i for i in items if ("processing" in i.lower() or "vault" in i.lower() or i.upper() == "LOADING")]
                cleaned = [i for i in items if i not in stuck_items]
                
                if len(items) != len(cleaned):
                    entry.video_url_homework = ",".join(cleaned)
                    updated = True
                    count += 1
            
            if updated:
                db.session.add(entry)
                
        # --- NEW: SYSTEM CACHE & TEMP DISK PURGE SEQUENCE ---
        temp_dir = 'temp'
        if os.path.exists(temp_dir):
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                try:
                    # Safely remove files without breaking directory architecture
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                except Exception as file_err:
                    print(f"Skipped removing file {file_path}: {file_err}")
        # ----------------------------------------------------

        if count > 0:
            db.session.commit()
            return jsonify({"success": True, "cleared_count": count})
            
        return jsonify({"success": True, "cleared_count": 0})
    except Exception as e:
        db.session.rollback()
        print("Error clearing stuck uploads:", e)
        return jsonify({"success": False, "error": str(e)}), 500
        
@app.route('/get_upload_token')
@login_required
def get_upload_token():
    try:
        yt_service = YouTubeVaultService()
        yt_service.creds.refresh(Request())
        return jsonify({"access_token": yt_service.creds.token})
    except Exception as e:
        print(f"❌ YouTube Token refresh failed: {e}")
        return jsonify({"error": "Failed to refresh access token", "details": str(e)}), 500
        
@app.route('/admin/approve')
@login_required
def admin_list_pending():
    if not current_user.is_admin:
        abort(403)
    
    pending_users = Author.query.filter_by(is_approved=False).all()
    
    html = "<h1>Pending Approvals</h1><ul>"
    for user in pending_users:
        html += f"<li>{user.email} - <a href='/admin/approve/{user.id}'>APPROVE</a></li>"
    html += "</ul>"
    return html

@app.route('/admin/manage')
@login_required
def admin_approve(): 
    if not current_user.is_admin:
        abort(403)
    users = Author.query.all()
    return render_template('admin_list.html', users=users)
    
@app.route('/admin/approve/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_admin: abort(403)
    user = Author.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f"Approved {user.email}")
    return redirect(url_for('admin_approve'))

@app.route('/admin/revoke/<int:user_id>')
@login_required
def revoke_user(user_id):
    if not current_user.is_admin: abort(403)
    user = Author.query.get_or_404(user_id)
    user.is_approved = False
    db.session.commit()
    flash(f"Access revoked for {user.email}")
    return redirect(url_for('admin_approve'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)

    user_to_delete = Author.query.get_or_404(user_id)
    
    if user_to_delete.id == current_user.id:
        flash("Action denied: You cannot delete your own admin account.")
        return redirect(url_for('admin_dashboard'))

    try:
        LogEntry.query.filter_by(author_id=user_id).delete()
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"User {user_to_delete.email} and all their logs have been permanently wiped.")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred during deletion: {str(e)}")

    return redirect(url_for('admin_approve'))
    
@app.route('/setup_admin')
def setup_admin():
    key = request.args.get('key')
    if key != os.getenv("ADMIN_CREATE_KEY"):
        return "Invalid key", 403
    
    admin_email = os.getenv("ADMIN_EMAIL")
    user = Author.query.filter_by(email=admin_email).first()
    
    if user:
        user.is_admin = True
        user.is_approved = True
        db.session.commit()
        return f"Admin privileges granted to {admin_email}. You can now access /admin/manage"
    
    return "Admin user not found in database. Did you register with the correct email yet?", 404
    

@app.route('/register', methods=['GET', 'POST'])
def register():
    next_page = request.args.get('next')

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        name = request.form.get('name', 'New Collaborator')
        
        # NEW CHECK: Ensure passwords match
        if password != confirm_password:
            flash("Passwords do not match. Please try again.")
            return render_template('register.html', next=next_page)
            
        user = Author.query.filter_by(email=email).first()

        if user:
            # Check if this user signed up via Google and has no password yet
            if not user.password_hash:
                user.set_password(password)
                user.name = name  # Update to their preferred registration name
                db.session.commit()
                flash("Account updated with password! You can now use either login method.")
                return redirect(url_for('login', next=next_page))
            else:
                flash("This email is already registered. Please log in.")
                return redirect(url_for('login', next=next_page))

        # Normal registration for a brand new email
        new_user = Author(
            email=email,
            name=name,
            secret_token=str(uuid.uuid4())[:8],
            is_approved=False,
            is_admin=False
        )
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        
        flash("Registration successful! Your account is awaiting admin approval.")
        return redirect(url_for('pending', next=next_page))
        
    return render_template('register.html', next=next_page)
    
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        
    is_production = os.environ.get('RENDER') or os.environ.get('PORT')
    
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port, debug=not is_production, threaded=True)
