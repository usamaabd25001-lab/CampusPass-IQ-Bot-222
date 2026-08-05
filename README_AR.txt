CampusPass IQ V11.7.2B — Database Schema Repair

1) فك الضغط.
2) انسخ مجلد app إلى جذر مستودع GitHub ووافق على استبدال app/db/migrations.py.
3) Commit ثم Push.
4) أصلح REDIS_URL ليشير إلى Render Key Value في نفس Region للخدمتين.
5) نفّذ Clear build cache & deploy.

حل فوري اختياري قبل النشر:
افتح Supabase SQL Editor وشغّل الملف:
docs/releases/v11_7_2/SUPABASE_IMMEDIATE_FIX.sql

الإصلاح إضافي فقط، ولا يحذف بيانات أو مزايا.
