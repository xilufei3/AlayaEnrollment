# AlayaEnrollment Web

This directory contains the standalone Next.js frontend for AlayaEnrollment.

## Run Locally

Install dependencies:

```bash
cd D:\AlayaEnrollment\web
npm install
```

Start the dev server:

```bash
cd D:\AlayaEnrollment\web
npm run dev
```

The app is available at `http://localhost:3000`.

## Environment Variables

The frontend reads public environment variables from the repository root:

- `D:\AlayaEnrollment\.env`

Relevant variables:

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_ASSISTANT_ID`
- `NEXT_PUBLIC_LANGSMITH_API_KEY`

## Build

```bash
cd D:\AlayaEnrollment\web
npm run build
npm run start
```

## Notes

- The frontend is intentionally independent from `D:\AlayaEnrollment\apps`.
- You can remove the old `apps` directory after migration as long as the root `.env` and backend remain in place.
