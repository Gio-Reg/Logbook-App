import os
import io
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

load_dotenv() # Loads your CLIENT_ID, SECRET, and REFRESH_TOKEN from .env

class YouTubeVaultService:
	def __init__(self):
		self.channel_id = os.getenv("YT_CHANNEL_ID")
		self.creds = Credentials(
			None,
			refresh_token=os.getenv("YT_REFRESH_TOKEN"),
			token_uri="https://oauth2.googleapis.com/token",
			client_id=os.getenv("YT_CLIENT_ID"),
			client_secret=os.getenv("YT_CLIENT_SECRET"),
		)
		self.youtube = self._get_authenticated_service()

	def _get_authenticated_service(self):
		if not self.creds.valid:
			self.creds.refresh(Request())
		
		service = build("youtube", "v3", credentials=self.creds)
		
		try:
			# Verify that we are actually in the "Vault"
			check = service.channels().list(mine=True, part="id").execute()
			if check.get("items"):
				print(f"✅ VERIFIED: Logged in as Channel {check['items'][0]['id']}")
			else:
				print("❌ ERROR: Still logged into the empty email profile!")
		except Exception as e:
			print(f"⚠️ Verification skipped: {e}")
			
		return service

		
	def upload_video(self, file_path, title, description="Uploaded Trace Direct Browser"):
		"""
		Standard server-side upload. 
		Note: Use get_resumable_upload_url for large files to avoid Render crashes.
		"""
		request_body = {
			'snippet': {
				'title': title,
				'description': description,
				'categoryId': '24' 
			},
			'status': {
				'privacyStatus': 'unlisted',
				'selfDeclaredMadeForKids': False
			}
		}

		media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True)
		
		request = self.youtube.videos().insert(
			part="snippet,status",
			body=request_body,
			media_body=media
		)

		response = None
		while response is None:
			status, response = request.next_chunk()
			
		return response['id']
