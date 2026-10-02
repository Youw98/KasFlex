# Security policy

KasFlex is a research tool that runs on your own computer. It plans greenhouse
energy use and never switches equipment itself: every plan needs a person's
approval, and a safety checker reviews it first.

## Supported versions

Only the latest release gets security fixes. Update before reporting.

## Reporting a problem

Please report a vulnerability privately, not in a public issue:

- open a [private security advisory](https://github.com/Youw98/KasFlex/security/advisories/new), or
- contact the maintainers listed in `CITATION.cff`.

Say what you found, how to reproduce it, and what someone could do with it. You
will get a reply within 5 working days. Fixes for confirmed problems aim to ship
within 30 days, sooner for anything that exposes participant data. We will credit
you in the release notes unless you would rather not be named.

## What is in scope

- The local web app (`kasflex ui`): access to participant or research data,
  getting past the settings password, consent or withdrawal, or reaching the app
  from another website or computer.
- Handling of API keys in `.env` and the settings files.
- The release workflow and published builds.

## What is out of scope

- Running KasFlex with `--allow-network`: that deliberately lets other computers
  on your network in. Use it only on a network you trust, with your own password.
- The default settings password `admin99`, which is documented. Set
  `KASFLEX_ADMIN_PASSWORD` for any real study.
- Answers from a language model that are wrong. They are labelled as AI answers
  and the safety checker, not the model, decides what is allowed.

## How KasFlex protects itself

- It only accepts connections from this computer unless started with
  `--allow-network` and a non-default password.
- It refuses requests from other websites (Host, Origin and Fetch-Metadata checks)
  and sends a strict Content-Security-Policy.
- Settings, research data and exports need the settings password. Repeated wrong
  passwords pause logins from that browser tab for five minutes, with a shared cap
  for all tabs together.
- With participant codes required, the server refuses any participant id the
  researcher did not hand out.
- A participant's consent can only be withdrawn with their own withdrawal key or
  the settings password, and withdrawal erases their research data.
