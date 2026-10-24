# Brainstorm: Local Production Server

## Idea

Adopt the existing Second Brain container as a reliable production service for one
user on this machine. This is not a public deployment and does not need a public
domain, reverse proxy, or application authentication.

## Key decisions

- **Keep the current systemd user service.** The service is healthy, already starts
  the container, persists data, and uses the existing client port. Hardening this
  deployment avoids a service migration and reduces risk to the database.
- **Use loopback-only access on port 8100.** The server serves one local user, so
  binding to `127.0.0.1` removes network exposure while preserving the current
  client configuration.
- **Do not add application authentication.** Loopback access is the chosen trust
  boundary. Other local processes under the user account can still reach the API.
- **Build the image from the current checkout now.** The current service relies on
  a cached local image and its registry pull is denied. Building locally makes the
  intended source explicit before the fresh start.
- **Reset only the active database after archiving it.** Move `data/brain.db` to a
  dated backup, then initialize a fresh active database. This honors the requested
  clean start while preserving recovery. Leave experiment databases untouched.
- **Keep port 8100.** Existing clients can continue to use the server without a
  configuration change.
- **Keep local rotating backups.** Create daily backups for seven days and one
  backup before each update. The data is valuable, but external backup
  infrastructure is outside this setup.
- **Protect the application environment file.** It contains provider credentials and
  must not remain readable by unrelated local users.

## Direction

Harden the existing systemd-managed container in place. Build the current checkout,
archive the active database, start with a fresh database, bind the service to
loopback, and verify health, persistence, restart behavior, and backup creation.
Keep the current service lifecycle and journal logs. Do not modify experiment data.

## Open questions

### Sharp questions

- What safe snapshot method preserves a consistent SurrealKV backup while the
  service runs?
- How will the systemd unit use the locally built image without depending on an
  unavailable registry pull?
- Where will backup archives live, how will permissions and retention work, and
  what restore contract will the operator use?
- How will the fresh database initialization and mounted volume be verified after
  the reset?

### Fog

- The most useful restore interaction is not yet defined beyond restoring a named
  backup and restarting the service.
- Future off-machine backup needs are unknown and remain outside this setup.
