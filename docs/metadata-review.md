# Reviewing sign names for the local assistant

The drawing manifest in `site/index.json` has codes and file paths, but no
verified descriptions. `data/sign-metadata.json` holds descriptions separately.

Each entry needs an existing manifest code, English and Traditional Chinese
names, a source link, and a review state. Use `source_checked` while a name has
been matched to a source but has not been checked by a human. Change it to
`verified` only after a human confirms the code, both names, and any aliases
against the cited source. Record the edition and PDF page or section where
possible. Keep informal aliases distinct from official wording in the source
notes. Do not add a name based only on an AI answer.

The current top-100 review queue is in `data/sign-review-queue.json` and five
20-entry preview batches are in `docs/sign-review-batches/`. The queue order is
frozen from the current map survey. It covers 135,660 of 157,372 surveyed
records. The project owner approved all 100 entries in the Codex chat on
2026-09-24. Each entry now has a `verified` review state and an approval record
in `data/sign-metadata.json`. These names are available to public descriptive
search and checked chat results. The other 1,227 drawings remain code-only.

For a future entry, review its preview, source, names, and aliases. Correct the
queue entry before approval. Then run one command with the exact reviewed names:

```powershell
python scripts/approve_sign.py --approve TS_115 --name-en "No entry" --name-zh-hant "不准駛入" --reviewer "Your name"
```

The command checks the exact queue names, records the reviewer and time, and
adds only that code to the public verified index. Run `python -m pytest tests/ -q`
and restart the local backend afterward. Do not run this command for a
draft you have not checked.

Current researched candidates:

| Code | English | Traditional Chinese | Current state |
|---|---|---|---|
| TS_101 | Stop | 停車 | Verified 2026-09-24 |
| TS_102 | Give Way | 讓路 | Verified 2026-09-24 |

The English references are in the [August 2026 TPDM Volume 3](https://www.td.gov.hk/filemanager/en/content_5055/V3_08_2026.pdf), PDF pages 21 and 23. The entry for each code also links its Chinese source. The TPDM's T.S. number is the drawing code; the Road Users' Code uses a different figure numbering scheme, so do not join codes by number alone.

After editing, run `python -m pytest tests/ -q`. The API refuses unknown or
duplicate metadata codes at startup. `GET /api/capabilities` reports verified,
source-checked, and code-only counts separately. A missing description means
the index is incomplete, not that the drawing does not exist.
