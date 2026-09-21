# API connections

Open **Configuration → APIs**. Each provider shows its purpose, real endpoint, and key requirement.

- **ENTSO-E:** paste your personal token, then choose **Save key**. It becomes available immediately for Data sources → Download for this day. Saving is not a connection test: published data must exist for the date you choose. Use Replace key or Remove key to manage the connection.
- **Open-Meteo Forecast:** the current public connector needs no key.
- **Open-Meteo Historical Weather:** the current public reanalysis connector needs no key. Reanalysis is not an archived forecast or measured site data.

The application cannot issue account credentials. Obtain your ENTSO-E token from your own Transparency Platform account.

## Local environment file

The app creates `.env` in its data directory (the project working directory for this source checkout). For the packaged app, the normal KasFlex data directory is used. You can also copy `.env.example` to `.env` and fill in:

```dotenv
ENTSOE_API_KEY=your_personal_token
```

Restart after editing the file manually. Saving through the interface updates the running process immediately. An inherited environment value takes precedence on startup; remove a system-level token separately if you want it to stay disconnected after restarting.

Keys are stored as text in `.env`. The file is Git-ignored and excluded from the provided project archive. The browser receives configured/not-configured status only; it does not receive saved key values. Keys are excluded from browser preferences, exported plans, and audit payloads. Key input is cleared after saving and when closing Configuration.

API key save/remove buttons act immediately, independently of the main Save configuration button. The endpoints are fixed to the implemented providers. OpenAI and live gas-market connectors are not implemented, so this list does not collect unused keys for them.
