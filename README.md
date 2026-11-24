# TexTech

TexTech is a React frontend with a FastAPI and MongoDB backend.

## Run locally

1. Install Python 3.10+ and Node.js.
2. Copy `backend/.env.example` to `backend/.env` and set your MongoDB URI and a private admin username/password. Configure SMTP values to enable email verification and password-reset emails. Never commit `backend/.env`.
3. In a terminal:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python -m uvicorn main:app --reload
   ```

4. In a second terminal:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

5. Open `http://localhost:5173/admin` and sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
   The registration form remains at `http://localhost:5173/`.

The admin directory starts empty. Add actual buying houses, factories, and foreign buyers from the dashboard. Their portfolios are stored in MongoDB; no demo records are generated.

## Collaborate with Git

Commit and push source files, `backend/requirements.txt`, `frontend/package-lock.json`, and `backend/.env.example`. Do not push `.env` files, virtual environments, `node_modules`, or credentials. Each teammate should create their own `backend/.env` from the example and use the shared team MongoDB only if authorized.

Use a feature branch for work:

```powershell
git pull
git switch -c feature/your-change
git add .
git commit -m "Describe your change"
git push -u origin feature/your-change
```

Open a pull request so teammates can review changes before merging.
