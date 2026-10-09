# Security

Chrome's debugging endpoint grants substantial control over a browser. Use a
dedicated test profile, keep the endpoint on a trusted interface and never expose
it to the public internet. Do not put credentials in the endpoint URL.

To bind Chrome's endpoint to loopback only, start it with
`--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1` and a
non-default `--user-data-dir` (Chrome 136 and later ignore these flags on the
default profile directory).

Run without `--close` first. An unchanged page may still be in use; exempt pages
you need with `--keep` and review the candidates before enabling closing.

Report sensitive issues through private security reporting on the repository
hosting platform when available. Otherwise request a private contact channel
without posting credentials, browser addresses, page titles or URLs.
This pre-release project offers no supported-version or response-time promise.
