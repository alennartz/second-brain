# Flutter mobile client

## The idea

Build an ultra-minimal Android-first Flutter client for the brain server. It gives the user two fast actions: stage a thought for the knowledge system and ask one question over stored memory.

## Key decisions

- **Use Flutter, Android first.** Flutter keeps the client portable for iOS without making the first milestone carry two native implementations.
- **Use two tabs: Capture and Ask.** Separate screens make the two server operations distinct. A mode switch or capture inbox would add ambiguity or local state without helping the core workflow.
- **Open on Capture.** Thoughts are time-sensitive, so the app prioritizes intake staging at launch.
- **Capture submits text to `POST /ingest`.** The server remains the source of truth for intake staging and returns the stored chunk count.
- **Support voice through system dictation.** The server accepts text only. Using the phone keyboard's speech-to-text gives voice input without recording audio, storing audio, or adding a transcription service.
- **Retain failed captures as drafts.** A failed request must not lose a thought. The app will offer explicit retry rather than introduce an offline queue in the first release. Retries need a stable idempotency key to avoid duplicate staging after timeouts.
- **Ask uses one-shot `POST /recall`.** A single question and answer preserve the minimal mental model. Conversation history, streamed chat, and graph navigation are out of scope.
- **Show the answer first with expandable Evidence.** Limited Markdown improves answer readability. Returned graph records and unprocessed evidence remain available on demand without turning the client into a graph browser.
- **Configure the server on first launch.** Store the base URL locally and expose it through a small settings action. Tunneling, authentication, and loopback deployment remain outside this change.

## Direction

The client is a two-action utility, not a mobile copy of the terminal UI:

- A Capture tab contains one multiline field and one submit action. Success shows `chunks_stored`; failure preserves the draft and offers Retry.
- An Ask tab contains one question field and one submit action. The result page renders the recall answer, then a collapsed Evidence section.
- The app has no local capture history, offline queue, graph tab, conversation transcript, or dedicated microphone recorder.

## Open questions

### Sharp questions

- Where should the Flutter package live in the repository, and how will Android builds and tests integrate with existing checks?
- Which Flutter packages and evidence mapping will provide limited Markdown, local URL storage, stable idempotency keys, and HTTP error handling?
- What exact Android device and emulator smoke journey will validate capture, retry, recall, and evidence expansion?

### Fog

- The visual identity and exact spacing, typography, and error copy are not yet defined.
- iOS packaging, signing, and release work remain future scope.
