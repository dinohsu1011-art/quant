# Annual EPS input for Theme Returns P/E bands

`annual_eps.json` is the normalized application payload derived from
`grid_mve3se5l.xlsx` on 2026-07-28.

Each row is:

```text
[fiscal_year, annual_report_date, consensus_eps, record_type]
```

Record types are `h` (historical report), `e` (historical estimate only), and
`f` (current forecast).

## Annual-vintage convention

The consensus column is the historical annual consensus vintage. A value
labelled FY N is treated as the estimate observed after the FY N-1 annual
report:

- FY+1 after the FY N report uses the source estimate for FY N+1.
- FY+2 after the FY N report uses the source estimate for FY N+2.
- The estimate is held constant until the next annual report rollover.

This is an annual step series rather than a daily analyst-revision history.

## Source-quality exceptions

- The duplicate `HOOD` block was suppressed.
- The unlabeled semiconductor block was inferred as `AMAT`.
- `SNDK` is excluded because its entire source block duplicates `MU`.
- `ASML`, `TSM`, and `NOK` are excluded until their EPS is converted into the
  same currency and ADR/share basis as the stored US price series.
- `GOOG` historical rows contain estimates only, not reported/comparable EPS.
- `GOOGL` uses the same consolidated per-share EPS series as `GOOG`.
