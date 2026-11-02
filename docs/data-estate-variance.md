# G-35 / G2 public data estate

**Policy (spec).** The five named public sources are actual Kaggle/OpenML datasets
(`FR-DATA-01`). The only offline synthetic path is seed/sample (`FR-DATA-12`,
`scripts/load-data.sh --sample`). The generated layer (`FR-DATA-02/03`) is
separately tagged `synthetic=true` and must never be reported as the public
estate. Authored or invented row counts are forbidden.

| Source id | Bundled in git? | Actual inventory? | Licence | Closure |
|---|---|---|---|---|
| appointments | No (`data/raw/` gitignored) | **Yes** — 110,527 rows | CC BY-NC-SA 4.0 | Inventory JSON |
| notes | No | **Yes** — 4,999 rows | check_and_record | Human licence review residual |
| symptoms | No | **Yes** — 4,920 rows | check_and_record | Human licence review residual |
| medicines | No | **Yes** — 253,973 rows | check_and_record | Human licence review residual |
| patients | No | **Yes** — 55,500 rows | check_and_record | Human licence review residual |
| seed_sample | Via `--sample` | Seed only | n/a | Keep labelled seed — not G2 public estate |

Evidence: [evidence/public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json).  
Contracts: [data-contracts/](./data-contracts/). Sizing: [d5-sizing.md](./d5-sizing.md).

**Status.** **Closed** for inventory (row_count + sha256). Residual: human licence confirmation for four `check_and_record` sources before redistribute.
