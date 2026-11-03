# Chapter 11 — Sales orders

**Audience:** sales desk and administrators. **Permissions:** `sales:read` to view and preview tax, `sales:write` to create, submit, cancel or change a promise, `dispatch:write` to dispatch, approval decisions by an Administrator (see chapter 12). **UI route:** `#/sales`. **Evidence:** `app/api/sales_orders.py`; `app/api/approvals.py`; `tests/test_approvals.py`; `tests/test_catalog_orders.py`; migration `0024_catalog_order_dates`.

A sales order moves through **draft → pending approval or approved → dispatched**, or ends as **cancelled** or **rejected**. Stock and credit are checked at submit and again at dispatch; the order does not reserve stock.

## 1. Creating a draft

Choose the distributor and add product lines. For each line choose a product, a whole-number quantity above zero, and optionally a unit price.

- Leave the price blank to sell at MRP. A price above MRP is refused.
- A discount beyond the configured threshold raises an approval request instead of being saved silently.
- A product may appear only once per order.
- **Expected delivery date (optional)** records the date promised to the buyer. It cannot be in the past. Leave it blank when no promise was made; nothing is inferred from payment terms.
- The order is saved as a **draft**. Saving does not check stock or credit — submitting does.

## 2. The order detail

The drawer shows the lines with quantity, unit price, the discount below MRP and the line total, plus the status and, when held, the approval reasons. The **Promised delivery date** section shows the date and, once dispatched, a chip:

| Chip | Meaning |
|---|---|
| `N days late` | Dispatched after the promised date |
| `On the promised day` | Dispatched on the date |
| `N days early` | Dispatched before the date |
| **Not recorded** | No promise was captured; no lateness is claimed |

`sales:write` can set or **Clear promise** while the order is draft, pending approval or approved. The server refuses an unchanged date (422), a past date (422) and any change after dispatch, cancellation or rejection (409). Every change is audited as `so.delivery_date` with the old and new date.

## 3. Submitting

**Submit** checks stock availability and credit exposure.

- **Insufficient stock** — the submit is refused and names the SKU, the quantity needed and the quantity available.
- **Credit limit exceeded** or **discount over the threshold** — the order becomes **pending approval** and the approval queue receives a request with its reasons. The order cannot be dispatched until an Administrator decides it.
- **Within limits** — the order becomes **approved** immediately, and the approval timestamp is stored at that moment.

Approval time is stored separately from dispatch time. That is what lets the Overview report the approval wait and the after-approval wait separately instead of calling the whole interval "dispatch time".

## 4. Dispatching

**Dispatch** asks for a warehouse, then:

1. re-checks that the order is still approved and the distributor is active;
2. re-checks credit unless the credit-limit approval waived it;
3. allocates stock first-expiry-first-out from the chosen warehouse;
4. issues the tax invoice at the same time;
5. posts one outbound movement per batch with its issue cost.

If stock is short or the invoice cannot be issued, nothing moves and the order stays approved. A dispatched order cannot be dispatched again.

## 5. Cancelling

**Cancel** requires a reason and is allowed only before dispatch. The reason is stored on the order and audited. A rejected approval leaves the order **rejected**; it is not silently returned to draft.

## 6. Credit and debit notes on the Billing screen

A note corrects a dispatched order's invoice. The **Billing** screen lists invoices and, below them, every credit and debit note together; each row offers **Open** and, to a role with `print:document`, **Print**.

- **Open** slides in the note's detail: its number, the invoice it corrects, the buyer, the date and reason, the taxable value, each tax head, the note total and one line per product. A credit note also says whether the goods went back to stock. The drawer notes that an issued note cannot be edited or deleted; it is corrected by issuing another note against the same invoice.
- **Print** produces the secure PDF through the same printing path as an invoice, choosing **CREDIT NOTE** or **DEBIT NOTE** and carrying the note number, the invoice number and the print verification code. The Print button is hidden and refused without `print:document`; the server enforces it, not the screen.
- **Open** needs only the read access that draws the Billing list. Nothing about a note changes through this screen; it is a read and a print, not an edit.

**VERIFIED:** `tests/test_file_audit.py::test_a_credit_and_a_debit_note_can_be_opened_and_printed` creates a credit and a debit note against one invoice, checks that each list row carries its line detail and invoice number, and reads both PDFs for the document title and note number. The Open drawer and both Print buttons were also walked in a browser on the disposable test database on 3 November 2026. Evidence: [`../VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md) §25.6.

## 7. What the Overview reports

For dispatched orders, the Pipeline card shows:

- **raised → dispatch** — order to dispatch, including the approval wait;
- **approval** — order to approval, measured only for orders with a stored approval stamp;
- **after approval** — approval to dispatch;
- **delivery** — on time, late and average days late, measured only for orders with a promise;
- **overdue open** — approved or pending-approval orders whose promise date has passed.

Orders approved before migration `0024` have no approval stamp and orders without a promise have no date. Those orders are **excluded** from the relevant average rather than counted as zero, so the card never implies a fast approval or an on-time delivery that was never measured.

## 8. Known limitations

| Limitation | Effect |
|---|---|
| No stock reservation | Two orders can be approved against the same stock; the second dispatch is refused if the stock has gone |
| No partial dispatch | The whole order ships at once |
| No order-level expected date before `0024` | Historical orders show no promise and are excluded from lateness |
| No pipeline view inside the order screen | Use the Overview's Pipeline card |
| Purchase orders have no expected date | Supplier lateness is still not reported |

## 9. Verification

- Credit-limit approval, self-approval refusal and decision rights: `tests/test_approvals.py`.
- Dispatch, FEFO and warehouse choice: `tests/test_capacity.py`, `tests/test_costing.py`.
- Promise create/edit/clear/past-date/after-dispatch rules, approval stamp and pipeline lateness reconciled with the database: `tests/test_catalog_orders.py`.
- The form, detail drawer and promise editor were read in `static/js/app.js` (`soForm`, `saveSO`, `soDetail`, `promiseCell`, `promiseEditor`, `saveSoPromise`) and syntax-checked; they were not re-exercised in a browser after migration `0024`.
