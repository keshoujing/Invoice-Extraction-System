# secrets/

Credentials live here and must **never** be committed. Only the `.example`
template and this README are tracked; real key files are git-ignored.

## Google Cloud service account (for Vertex AI)

1. In the Google Cloud Console, create a service account with Vertex AI access and
   download its JSON key.
2. Save it in this folder as **`gemini-service-account.json`** — either paste your
   values into a copy of `gemini-service-account.json.example`, or just drop your
   downloaded key file here under that name.
3. Set `GOOGLE_APPLICATION_CREDENTIALS` in your `.env` to point at it (see
   `.env.example`). With Docker Compose this path is set for you.

The real `gemini-service-account.json` is ignored by git, so it won't be pushed.
