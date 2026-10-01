# Largest catalog document the validator accepts, however it arrives: fetched
# from a URL or pasted as `json_text`.
MAX_UPLOAD_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Largest request body (MAX_CONTENT_LENGTH). Pasted catalogs arrive as a JSON
# string, and encoding one escapes every quote, backslash and control character,
# so a document at the limit makes a body well over it. The document itself is
# still held to MAX_UPLOAD_BYTES; this only keeps that check reachable.
MAX_REQUEST_BYTES = 2 * MAX_UPLOAD_BYTES
