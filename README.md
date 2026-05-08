# Trace 🪵

**Trace** is a private documentation bridge designed for professionals who need a secure, organized way to track progress using their own personal cloud storage. 

Whether you are a **Physiotherapist** tracking a patient's recovery, a **Teacher** documenting student milestones, a **Personal Trainer** logging client form, or a **Researcher** capturing field data, Trace bridges the gap between your mobile device and your private Google ecosystem.

## 🚀 Key Features

- **Multi-Format Uploads:** Seamlessly handle **Videos, Photos, Documents, and Voice/Text Notes**.
- **AI Shield Analysis (Gemini):** Automatically generates summaries and insights for every entry, making your logbook searchable and professional.
- **Private YouTube & Drive Bridge:** Automatically routes video to your private YouTube channel and documents/photos to specific Google Drive folders.
- **Progress Tracking:** Maintains a chronological "Logbook" view for easy review of past sessions or entries.
- **Trace-Vault Security:** Enterprise-grade logic that keeps your Google credentials in a secure environment variable or secret file—never hardcoded.

## 👥 Who is Trace For?

- **Physiotherapists & Doctors:** Securely log patient movement videos and recovery notes.
- **Teachers & Educators:** Document student progress and classroom activities privately.
- **Personal Trainers:** Keep a video history of client technique and workout logs.
- **Researchers & Students:** Capture field notes, photos, and voice memos directly to a managed cloud drive.

## 🛠️ Tech Stack

- **Backend:** Flask (Python)
- **Database:** PostgreSQL (Cloud/Render) or SQLite (Local)
- **AI:** Google Gemini API (`google-genai`)
- **Storage Bridge:** Google Drive API v3 & YouTube Data API v3
- **Authentication:** OAuth 2.0 & Flask-Login

## 📦 Prerequisites

To deploy Trace, you provide the storage; we provide the bridge:
1. A **Google Cloud Project** with Drive and YouTube APIs enabled.
2. Your own **OAuth 2.0 Credentials** (client_secrets.json).
3. A **`token_base64.txt`** generated from your unique Google login flow.
4. A **Gemini API Key** from Google AI Studio.

## ⚙️ Environment Variables

| Variable | Description |
| :--- | :--- |
| `DATABASE_URL` | Connection string for your logbook database. |
| `GOOGLE_API_KEY` | Your Gemini AI key for automatic file analysis. |
| `FLASK_SECRET_KEY` | Secures your login sessions. |

## 🛡️ Privacy First

Trace is built on the **"Zero-Retention"** principle:
- **Your Storage:** Files go directly to *your* Drive and *your* YouTube channel.
- **No Data Mining:** We don't see, sell, or store your media on our servers.
- **Secure Sessions:** Professional admin approval logic ensures only you (and your authorized team) can access the bridge.

---
*Developed for the Trace Studio Ecosystem.*

## 📄 License & Copyright

Copyright (c) 2026 Gio-Reg. All rights reserved. 

No unauthorized use, distribution, or modification of this software is permitted. This repository is made public for portfolio and review purposes only. For licensing inquiries, please contact the author.
