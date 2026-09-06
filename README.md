# Trace 🪵

**Trace** is an AI-native multimedia engine and logbook platform designed to automate the extraction, normalization, and indexing of multi-modal data streams (video, audio, text, and spatial telemetry) while maintaining zero-retention private cloud storage.

> **Repository Scope & Architecture Note**  
> This public repository contains the source code for the **TRACE Core Engine (Community Tier)**, providing client data bridging (Google Drive & YouTube Data APIs), basic Gemini-powered metadata generation, and local logbook record management.  
> 
> The **Advanced Enterprise Engine**—comprising the multi-agent orchestration framework (MAO), vector RAG pipeline, audio signal processing, computer vision pose analytics, and trace-based evaluation tooling—runs on a dedicated, asynchronous backend. The full system architecture and technical specifications are documented below.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Client ["Client Layer"]
        A[Mobile / Web Client] -->|Upload Media / Logs| B[Flask API Gateway]
    end

    subgraph Core ["TRACE Core Engine (Public Repo)"]
        B -->|OAuth 2.0 Auth| C[Google Storage Bridge]
        C -->|Private Video| D[YouTube Data API v3]
        C -->|Files / Photos| E[Google Drive API v3]
        B -->|CRUD Log Entries| F[(PostgreSQL Logbook DB)]
        B -->|Basic Summary| G[Google GenAI SDK - Gemini]
    end

    subgraph Advanced ["Advanced Enterprise Engine (Proprietary)"]
        B -.->|Async Queue / Event Webhook| H[FastAPI Async Worker]
        
        subgraph Pipeline ["Inference & Signal Pipelines"]
            H --> I[Audio Signal Processing & Transcription]
            H --> J[CV Upper-Torso Pose & Motion Tracking]
            H --> K[Multi-Agent Router - MAO]
        end

        subgraph RAG ["Vector & Memory Architecture"]
            K --> L[Document Chunking Engine]
            L --> M[Embedding Model]
            M --> N[(PostgreSQL / pgvector Storage)]
        end

        subgraph Eval ["Observability & Tracing"]
            K --> O[Trace-Based Reasoning Monitor]
            O --> P[Stochastic Output Validation & Eval]
        end
    end
```
## 🚀 Key Features & Engine Tiers

### 1. Core Engine (Included in this Repository)
- **Zero-Retention Cloud Bridge:** Directly routes large media files to user-owned Google Drive folders and private YouTube channels without caching raw media on application servers.
- **Multi-Format Ingestion:** Standardized ingest handlers for MP4 videos, raw photos, PDF documents, and voice/text notes.
- **Basic AI Shield Analysis:** Integrated via `google-genai` to automatically extract structural metadata, key tags, and brief summaries for incoming log entries.
- **Trace-Vault Security:** OAuth 2.0 token management using Base64 environment secret injections for stateless deployment environments (Render, Azure Container Apps).

### 2. Advanced Enterprise Engine (Architectural Specification)
- **Multi-Agent Orchestration (MAO):** Dynamic agent routing engine built in Python using state-managed context windows, persistent long-term memory, and tool-use skills for unstructured data synthesis.
- **Advanced RAG & Vector Pipeline:** Dynamic document/transcript chunking strategies paired with dense vector embedding generation and thread-safe PostgreSQL `pgvector` indexing for semantic search over historical logs.
- **Audio Processing & Speech-to-Text:** Automated audio stream extraction, high-pass/low-pass noise filtering via SciPy, and automated transcription pipeline into structured markdown.
- **Computer Vision & Posture Tracking:** Frame-by-frame spatial marker tracking (upper-torso, joint angles, postural deviation metrics) for biomechanical and movement analysis.
- **AI Observability & Trace-Based Evaluation:** Real-time execution tracing, prompt-behavior evaluation, and stochastic output validation to ensure agent stability under high-throughput conditions.

---

## 👥 Use Cases

- **Physiotherapists & Sports Scientists:** Securely log patient movement videos, run posture-tracking telemetry, and track recovery trajectories.
- **Coaches & Personal Trainers:** Maintain a searchable, AI-indexed history of client execution technique, workout logs, and verbal notes.
- **Researchers & Field Engineers:** Capture multi-modal observational data (photos, voice notes, PDFs) routed straight to structured database layers.

---

## 🛠️ Tech Stack

- **Backend Frameworks:** Flask (Core Gateway), FastAPI (Async Worker Engine)
- **Database & Spatial Storage:** PostgreSQL (with `PostGIS` & `pgvector`), SQLite (Local Dev)
- **AI & ML Integration:** Google Gemini API (`google-genai`), PyTorch, OpenCV / MediaPipe
- **Data Engineering:** Python 3.11+, Pandas, NumPy, SciPy, Async Worker Queues (Celery/Redis)
- **Cloud & Storage APIs:** Google Drive API v3, YouTube Data API v3, OAuth 2.0

---

## ⚙️ Environment Variables

| Variable | Description |
| :--- | :--- |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql://user:pass@host:5432/dbname`) |
| `GOOGLE_API_KEY` | Gemini API key for structured metadata extraction |
| `FLASK_SECRET_KEY` | Key for session encryption and CSRF security |
| `GOOGLE_CLIENT_SECRET_BASE64` | Base64-encoded client secrets for OAuth 2.0 flow |
| `GOOGLE_TOKEN_BASE64` | Base64-encoded persistent storage token |

---

## 🛡️ Privacy & Zero-Retention Principle

- **User Ownership:** Media is never retained on central servers. Video assets route to private YouTube channels (unlisted/private), and files route to specific user Drive directories.
- **Stateless Operations:** Session tokens and secrets are handled via memory or secure environment variables.
- **Role-Based Access:** Admin authentication layer prevents unauthorized access to execution bridges.

---

## 📄 License & Copyright

Copyright (c) 2026 Gio-Reg. All rights reserved.

No unauthorized use, distribution, or modification of this software is permitted. This repository is made public for portfolio, architecture demonstration, and code review purposes only. For licensing or enterprise inquiries, please contact the repository owner.


