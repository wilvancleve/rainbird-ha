# Reverse-engineering tools

Capture the Rain Bird 2.0 app and extract the OAuth `client_id`/`client_secret`
the integration needs. **This project doesn't ship Rain Bird's app credentials**,
so you capture your own here (a one-time, couple-minute step) and paste them into
the integration's setup fields. Re-run this any time they change.

> Static extraction from the app package does **not** recover the credentials —
> the app supplies them to its OAuth library from a non-literal source, so they
> aren't grep-able even after decompiling. Capturing the live token request is
> the reliable method. (Endpoints, however, *are* plaintext in the app.)

## Requirements

- [mitmproxy](https://mitmproxy.org/): `pipx install mitmproxy` (or `brew install mitmproxy`).
- The phone running the Rain Bird 2.0 app, on the same network as this machine.

## Capture

1. Start the proxy:
   ```bash
   ./tools/run_proxy.sh
   ```
   It prints this machine's LAN IP and listens on port 8080.
2. On the phone: **Wi-Fi → (your network) → Configure Proxy → Manual**, Server =
   that LAN IP, Port = **8080**.
3. First time only, to intercept HTTPS: open **http://mitm.it** on the phone,
   install the mitmproxy CA profile, and trust it
   (iOS: Settings → General → About → Certificate Trust Settings).
4. Open the Rain Bird 2.0 app and **sign in** (log out first if already signed
   in, so it hits the token endpoint).
5. Watch the terminal — on the token request it prints:
   ```
   ★ EXTRACTED OAuth client — client_id=… client_secret=…
   ```
   and writes `captures/rainbird-keys-<stamp>.json`.
6. **Ctrl-C**, and turn the phone's Wi-Fi proxy back **off**.

## Analyze a saved capture

```bash
python tools/analyze_capture.py captures/rainbird-iq4-<stamp>.jsonl
```

Prints the `client_id`/`client_secret` (flagging whether they **changed** from
what the integration ships), whether a `refresh_token` was captured, and every
endpoint the app used.

## Use the values

In Home Assistant, add the **Rain Bird (self-hosted IQ4)** integration and paste
the captured `client_id`/`client_secret` (along with your email + password) into
the setup form. Re-run this capture and reconfigure if they ever change.

> Captures contain tokens and credentials — the `captures/` folder is gitignored;
> never share those files.
