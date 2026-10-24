import X402Conformance
open X402Conformance
#print axioms credit_sound
#print axioms step_idem
#print axioms step_nodup
#print axioms run_nodup
#print axioms consume_once
#print axioms only_open_consumes
open X402Conformance.Pending
#print axioms pending_never_credits
#print axioms timeout_never_credits
#print axioms failure_never_credits
#print axioms concurrent_nodup
#print axioms resolved_final
#print axioms failed_never_pending
#print axioms failed_never_credits
#print axioms reconcile_credits_once
#print axioms racy_not_nodup
open X402Conformance.Replicas
#print axioms shared_cas_at_most_one_grant
#print axioms partitioned_caches_admit_double_grant
#print axioms partitioned_grants_not_nodup
