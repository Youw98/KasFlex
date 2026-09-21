# WUR / GreenLight licence check

This checklist is not legal advice. It makes the open question concrete before a
public or commercial KasFlex release.

## Current technical facts

- KasFlex core is Apache-2.0.
- `gl-gym==0.3.2` / GreenLight-Gym2 is AGPL-3.0-or-later.
- KasFlex does not import `gl_gym` in its core process. It sends one JSON request
  to `workers/greenlight/worker.py` and reads one JSON response.
- The GreenLight worker lives in a separate Python environment because its NumPy
  requirement conflicts with the grid-model environment.
- Current packaged KasFlex binaries do not bundle `gl-gym`; users install the
  worker dependencies separately.
- The AGC2 archive is CC0-1.0 and is not redistributed in the repository.
- Process separation is an engineering boundary, not proof that the combined
  distribution is outside AGPL obligations.

## Questions requiring a written answer

1. May an Apache-2.0 KasFlex release invoke an independently installed
   AGPL-3.0-or-later GreenLight-Gym2 worker through this documented JSON protocol?
2. If both components are offered from one installer or download page, must the
   complete corresponding source of KasFlex be offered under AGPL terms?
3. Does hosting the worker behind a service trigger AGPL network-source duties for
   KasFlex core, the worker modifications, or both?
4. Is written permission or a dual licence available for demonstrations with
   growers, consortium partners, and potential commercial users?
5. Which copyright notices, citations and source links must appear in the UI,
   binaries and release notes?
6. Is use of the names GreenLight, GreenLight-Gym2, WUR or Wageningen allowed in
   public project descriptions, and under what wording?

## Email draft

Subject: Licence clarification for GreenLight-Gym2 use in the KasFlex research prototype

> Dear GreenLight-Gym2 maintainers / WUR legal contact,
>
> We are preparing a public research release of KasFlex, an Apache-2.0 greenhouse
> energy-planning prototype. KasFlex can optionally invoke `gl-gym==0.3.2`
> (GreenLight-Gym2, AGPL-3.0-or-later) in a separate Python process. The two
> processes exchange a single documented JSON request/response. KasFlex core does
> not import or vendor GreenLight-Gym2, and the current binary does not bundle it.
> We have modified only our worker wrapper; any changes to AGPL-covered code would
> be published with source.
>
> Could you confirm the licence obligations for (a) separate user installation,
> (b) a combined installer or release page, and (c) a hosted demonstration? We
> would also like to know whether a dual licence or written permission is needed
> for grower demonstrations and possible later commercial collaboration, and what
> attribution/name-use wording you require.
>
> Relevant repository: https://github.com/Youw98/KasFlex
> Worker boundary: `workers/greenlight/worker.py`
> Architecture/licence decision: `docs/DECISIONS.md`, ADR-0001 and ADR-0002
>
> Kind regards,
> [name, organisation, contact details]

## Release gate

Save the written response with the project records and summarize it in
`docs/DECISIONS.md`. Do not describe process isolation as licence clearance. Do
not ship a combined GreenLight worker until the answer has been reviewed by the
release owner or counsel.
