-- Safe, additive and idempotent. No rows are deleted or rewritten.
ALTER TABLE public.cp_payment_proofs
ADD COLUMN IF NOT EXISTS file_fingerprint VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_cp_payment_proofs_file_fingerprint
ON public.cp_payment_proofs (file_fingerprint);
