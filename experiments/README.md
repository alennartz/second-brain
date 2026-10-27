# Historical experiment records

This directory preserves benchmark journals, reliability notes, progress reports,
and generated run artifacts from the former server stack. The executable Python
benchmark runners were removed during the Bun server migration.

These records are historical. They do not describe a supported build, deploy, or
runtime workflow. Use the Bun HTTP API and the current manual-test tools for new
measurements.

## Dream-cycle helper

`wait_dream.sh` remains a small HTTP helper for the current API:

```bash
experiments/wait_dream.sh http://localhost:8000
```

It starts a dream job with `POST /dream` and polls
`GET /dream/jobs/{job_id}` until the job reaches a terminal state.
