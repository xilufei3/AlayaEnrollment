# AlayaEnrollment Web

This directory contains the standalone Next.js frontend for AlayaEnrollment.

## Run Locally

Install dependencies:

```bash
cd web
npm install
```

Start the dev server:

```bash
cd web
npm run dev
```

The app will be served at `http://localhost:3000`.

## Environment Variables

- Copy `web/.env.example` to `web/.env.local` (or configure env vars in your deployment runner).
- Only `NEXT_PUBLIC_*` values belong here. Keep private API keys in the root `.env` for the backend.
- Default `NEXT_PUBLIC_API_URL=/api` assumes you run behind a reverse proxy that forwards `/api/*` to FastAPI. When developing without Nginx, change it to `http://localhost:8008`.

## Build

```bash
cd web
npm run build
npm run start
```

## Notes

- The frontend is intentionally independent from any legacy `apps/` directory.
- After migration you can delete the old `apps` folder as long as the backend and root `.env` remain.
