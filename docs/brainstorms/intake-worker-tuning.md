# Brainstorm: Intake worker tuning

**Date:** 2026-10-15
**Status:** parked

## The idea

Tune the background intake worker after real workloads provide evidence. The current pipeline uses configurable concurrency, retry backoff, request/chunk/batch character limits, leases, and polling intervals.

## Open questions

- What worker concurrency fits provider rate limits and the embedded database?
- What processing-batch character budget gives reliable extraction without wasting context?
- What retry base and cap balance recovery speed against repeated model spend?
- What lease and shutdown grace values minimize duplicate replay without delaying deploys?

No tuning decision is made here. Measure queue age, retry rates, provider latency, and recall quality before changing defaults.
