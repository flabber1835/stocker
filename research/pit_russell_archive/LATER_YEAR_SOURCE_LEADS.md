# Later-year Russell 3000 source leads

Research only. Discovery/corroboration leads are not certification authority by themselves.

## Preserved public collection

Repository: `kact998/Russell3000Components`

The collection contains extracted CSVs for the following annual dates:

- 2014-06-27
- 2015-06-26
- 2016-06-27
- 2017-06-26
- 2018-06-25
- 2019-07-01
- 2020-06-29
- 2021-06-28
- 2022-06-24
- 2023-06-23

It also preserves original-looking PDF filenames including:

- `ru3000_membershiplist_20140627.pdf`
- `ru3000_membershiplist_20150626.pdf`
- `ru3000_membershiplist_20160627.pdf`
- `ru3000_membershiplist_20170626.pdf`
- `ru3000_membershiplist_20180625_0.pdf`
- `RU3000_MembershipList_20190701.pdf`
- `ru3000_membershiplist_20200629.pdf`

The repository additionally contains 2023 final additions/deletions filenames such as `ru3000-additions-final-20230623.pdf` and `ru3000-deletions-final-20230623.pdf`.

## Interpretation

These files are valuable for:

1. deriving exact date-stamped filenames to probe against Russell/FTSE Russell/LSEG and Wayback;
2. parser holdouts and row-count cross-checks;
3. detecting whether an official capture recovered from Wayback matches a preserved copy by content hash or normalized constituent set.

They are **not** automatically Grade-A PIT authority because the GitHub repository is a third-party preservation source. Certification should prefer an original Russell/FTSE Russell/LSEG endpoint or a Wayback capture of that original publisher endpoint. A preserved copy may qualify as corroborating evidence only after provenance and date are established.

## Later naming evidence

Publicly indexed material confirms that by 2020–2021 the annual documents were titled with date-stamped names matching the `ru3000-membershiplist-YYYYMMDD` / `ru3000_membershiplist_YYYYMMDD` convention. Current LSEG-hosted Russell 3000 documents use `www.lseg.com/content/dam/ftse-russell/...` paths, while older FTSE Russell documents used `content.ftserussell.com/sites/default/files/...`.

The archive discovery probe has therefore been expanded to query:

- underscore and hyphen date-stamped `ru3000` membership filenames;
- `content.ftserussell.com/sites/default/files/`;
- LSEG `content/dam/ftse-russell/` paths;
- legacy Russell stable and wildcard membership URLs.

## Next validation

For every 2014–2026 year:

1. query the exact date-stamped filename families on original publisher hosts through Wayback;
2. retain archive timestamp, original URL, digest, byte length, and SHA-256;
3. compare recovered official content against preserved third-party constituent sets where available;
4. grade the year only after publication/effective-date causality is established;
5. keep unresolved years explicit—never silently substitute a later/current list.
