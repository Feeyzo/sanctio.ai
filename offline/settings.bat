@echo off
rem Settings shared by Sanctio and SwiftShip when they run on this laptop.
rem These are local demo values only. Never use them on a real server.

set DEMO_API_KEY=sk_live_offline_demo_key_0001
set DEMO_WEBHOOK_SECRET=whsec_offline_demo_secret_0001
set DEMO_RESET_TOKEN=offline-reset-token
set DEMO_ADMIN_EMAIL=demo@swiftship.test
set DEMO_ADMIN_PASSWORD=Passw0rd!23
set DEMO_BUSINESS_URL=http://localhost:8100
set SANCTIO_URL=http://localhost:8000
set ALLOW_PRIVATE_WEBHOOK_URLS=1

rem AI models: put GROQ_API_KEY and/or GEMINI_API_KEY in backend\.env (copy backend\.env.example).
rem With a key and internet, the AI answers; with no key, or no internet, the built-in rule-based engine answers.
rem To force the rule-based engine even when keys are set, remove "rem" from the next line.
rem set LLM_PROVIDER=mock
