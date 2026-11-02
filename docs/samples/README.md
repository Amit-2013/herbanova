# Sample scheduled-report emails

Rendered from **synthetic data only** in an isolated PostgreSQL test database
(`herbanova_bcs_test`): a sample company, three sample distributors, seven
invoices, two receipts, one supplier receipt and one supplier payment, all dated
September–October 2026. No production row, customer, address or credential was
used.

| File | Pack |
|---|---|
| `HERBANOVA_Monthly_MD_Report_2026-10.html` / `.txt` | Monthly MD Report for October 2026 |
| `HERBANOVA_Accounts_Report_2026-10.html` / `.txt` | Accounts Report for October 2026 |

Both are rendered in **test mode** with the recipient `admin@example.test`; the
banner and `[TEST]` subject are part of the sample. Figures are internally
consistent with the services that produced them, but they are illustrative, not
the company's numbers.

The HTML files inline the chart and logo PNGs as data URIs so they open directly
in a browser. The message actually sent uses CID parts, which mail clients resolve
inside the message; the content and table structure are otherwise the same. Open
the `.txt` file to see the plain-text alternative.

Regenerate after a template change with the same synthetic seed; do not point the
generator at the application database. The email layout, figure sources and
go-live checklist are documented in [docs/EMAIL_REPORTS.md](../EMAIL_REPORTS.md).
