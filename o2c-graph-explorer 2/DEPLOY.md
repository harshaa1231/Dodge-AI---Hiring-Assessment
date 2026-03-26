# DEPLOYMENT GUIDE — O2C Graph Query System

## Repository Structure (what your GitHub repo should look like)

```
o2c-graph-explorer/
├── backend/
│   ├── main.py
│   ├── db.py
│   ├── graph.py
│   ├── pipeline.py
│   ├── prompts.py
│   ├── requirements.txt
│   └── start.sh
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── .env.production
├── sap-o2c-data/               ← The JSONL dataset (commit this!)
│   ├── sales_order_headers/
│   ├── outbound_delivery_headers/
│   ├── billing_document_headers/
│   └── ... (all 19 entity directories)
├── claude-code-logs/           ← Your Claude Code session transcripts
│   └── session-*.md
├── Dockerfile                  ← For Docker-based deploy (recommended)
├── render.yaml                 ← Render Blueprint (optional auto-deploy)
├── .gitignore
└── README.md
```

---

## OPTION A: Deploy with Docker on Render (RECOMMENDED — simplest)

### Step 1: Prep your repo
```bash
mkdir o2c-graph-explorer && cd o2c-graph-explorer
git init

# Copy all files into the structure above
# Make sure sap-o2c-data/ is included (it's small, ~3.8MB)

# Copy Dockerfile to root
cp deploy/Dockerfile .

# Make start.sh executable
chmod +x backend/start.sh

git add .
git commit -m "Initial commit"
```

### Step 2: Push to GitHub
```bash
# Create a PUBLIC repo on GitHub (required by submission)
gh repo create o2c-graph-explorer --public
git push -u origin main
```

### Step 3: Deploy Backend on Render
1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect your GitHub repo
4. Settings:
   - **Name**: `o2c-backend`
   - **Region**: Oregon (or closest to you)
   - **Runtime**: Docker
   - **Plan**: Free
5. Environment Variables:
   - `GOOGLE_API_KEY` = your Gemini API key (get from https://ai.google.dev)
6. Click "Deploy"
7. Wait for build (~2-3 min). Note your URL: `https://o2c-backend-XXXX.onrender.com`

### Step 4: Deploy Frontend on Render
1. Click "New +" → "Static Site"
2. Connect same GitHub repo
3. Settings:
   - **Name**: `o2c-frontend`
   - **Build Command**: `cd frontend && npm install && npm run build`
   - **Publish Directory**: `frontend/dist`
4. Environment Variables:
   - `VITE_API_URL` = `https://o2c-backend-XXXX.onrender.com` (your backend URL from step 3)
5. Click "Deploy"
6. Your frontend URL: `https://o2c-frontend-XXXX.onrender.com`

### Step 5: Update CORS (if needed)
If the frontend can't reach the backend, update `main.py` CORS origins:
```python
allow_origins=[
    "https://o2c-frontend-XXXX.onrender.com",
    "http://localhost:3000",
    "*",
]
```

### Step 6: Test
- Open your frontend URL
- The graph should load
- Try asking: "Which products have the most billing documents?"
- Try asking: "What is the capital of France?" (should be blocked)

---

## OPTION B: Deploy without Docker (Render native buildpack)

Same as above, but instead of Docker:
- **Runtime**: Python 3
- **Build Command**: `cd backend && pip install -r requirements.txt`
- **Start Command**: `cd backend && bash start.sh`

---

## IMPORTANT NOTES

### Free tier cold starts
Render's free tier spins down after 15 minutes of inactivity. First request after
idle will take ~30-60 seconds. This is fine for a demo — just wake it up before
your evaluator looks at it.

**Pro tip**: Before submission, hit your backend URL once to wake it up.
Or use a free uptime monitor (UptimeRobot) to ping it every 14 minutes.

### Gemini API Key
- Get a free key at https://ai.google.dev
- Free tier: 15 RPM, 1M tokens/day — more than enough
- NEVER commit this key to your repo

### Dataset in repo
The JSONL dataset is only ~3.8MB — commit it directly. Don't use Git LFS.
The Dockerfile builds the SQLite DB at build time, so startup is instant.

### CORS
The backend allows all origins (`*`) by default. This is fine for a demo.
Don't waste time on CORS configuration.

### Frontend API URL
The frontend reads `VITE_API_URL` at BUILD time (not runtime). So after
changing it in Render, you need to trigger a re-deploy of the frontend.

---

## LOCAL DEVELOPMENT

Terminal 1 (backend):
```bash
cd backend
pip install -r requirements.txt
export GOOGLE_API_KEY="your-key"
python main.py
# → http://localhost:8000
# → Swagger docs at http://localhost:8000/docs
```

Terminal 2 (frontend):
```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
# Vite proxy routes /api/* to localhost:8000
```
