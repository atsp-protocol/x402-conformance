/-
  n replicas of an x402 resource server: the rule the suite tests in R12 and R13.
  A request names the replica that handles it and the payment it carries. With one shared atomic check-and-set, a
  payment is granted at most once however the requests interleave across the replicas. With a cache per replica,
  two replicas can each grant the same payment. Models the rule, not anyone's code. Core Lean 4 only, no axioms added.
-/
namespace X402Conformance.Replicas

abbrev Payment := String

/-- One request: the replica that handles it and the payment (its idempotency key) it carries. -/
structure Req where
  replica : Nat
  payment : Payment

/-- One shared store for every replica. A grant is one atomic check-and-insert keyed by the payment: the check and
    the record are one step, so no request on any replica can read the store between them. `g` records the grants. -/
def sharedRun (s g : List Payment) : List Req → List Payment × List Payment
  | []      => (s, g)
  | r :: rs =>
    if s.contains r.payment then sharedRun s g rs
    else sharedRun (r.payment :: s) (r.payment :: g) rs

/-- Every grant so far is in the store, and the grants have no duplicate: both survive any run. -/
theorem sharedRun_nodup (s g : List Payment) (rs : List Req) (hg : g.Nodup) (hgs : ∀ x, x ∈ g → x ∈ s) :
    (sharedRun s g rs).2.Nodup := by
  induction rs generalizing s g with
  | nil => simpa [sharedRun]
  | cons r rs ih =>
    simp only [sharedRun]
    split
    · exact ih s g hg hgs
    · next hc =>
      have hns : r.payment ∉ s := by simpa using hc
      have hng : r.payment ∉ g := fun h => hns (hgs _ h)
      refine ih (r.payment :: s) (r.payment :: g) (List.nodup_cons.mpr ⟨hng, hg⟩) ?_
      intro x hx
      rcases List.mem_cons.mp hx with h | h
      · subst h; exact List.mem_cons_self
      · exact List.mem_cons_of_mem _ (hgs x h)

/-- With one shared atomic check-and-set, any interleaving of requests across any number of replicas grants each
    payment at most once: the list of grants holds no payment twice. -/
theorem shared_cas_at_most_one_grant (rs : List Req) : (sharedRun [] [] rs).2.Nodup :=
  sharedRun_nodup [] [] rs List.nodup_nil (fun _ h => by simp at h)

/-- The same payment sent to two replicas through the shared store is granted once. -/
theorem shared_two_replicas_one_grant : (sharedRun [] [] [⟨0, "p"⟩, ⟨1, "p"⟩]).2 = ["p"] := by
  simp [sharedRun]

/-- Two replicas with a cache each: replica 0 checks and records in `a`, every other replica in `b`. Each replica
    sees only its own cache, which is what a per-process in-memory record is. -/
def partRun (a b g : List Payment) : List Req → List Payment × List Payment × List Payment
  | []      => (a, b, g)
  | r :: rs =>
    if r.replica = 0 then
      if a.contains r.payment then partRun a b g rs else partRun (r.payment :: a) b (r.payment :: g) rs
    else
      if b.contains r.payment then partRun a b g rs else partRun a (r.payment :: b) (r.payment :: g) rs

/-- The same payment sent to two replicas that each check only their own cache is granted by both: a double grant. -/
theorem partitioned_caches_admit_double_grant :
    (partRun [] [] [] [⟨0, "p"⟩, ⟨1, "p"⟩]).2.2 = ["p", "p"] := by
  simp [partRun]

/-- So the grants of partitioned caches are not duplicate-free, which no run of the shared store can produce. -/
theorem partitioned_grants_not_nodup : ¬ ((partRun [] [] [] [⟨0, "p"⟩, ⟨1, "p"⟩]).2.2).Nodup := by
  rw [partitioned_caches_admit_double_grant]
  simp

end X402Conformance.Replicas
