# Waitress Cash Control

Odoo 17 module enforcing manager-only order cancellation/deletion for a
restaurant POS with per-waitress cash drawers, with a permanent audit
trail, an extended Daily Sales report, and an 80mm thermal
end-of-session report.

## What this module verified against your actual install

Several rounds of this build were corrected against files pulled
directly from this Odoo 17.0 installation rather than assumed from
memory or web search, specifically:
- `addons/point_of_sale/models/pos_session.py` — confirmed
  `action_pos_session_closing_control` / `action_pos_session_close` /
  `close_session_from_ui` call chain and exact return contracts.
- `addons/point_of_sale/models/report_sale_details.py` — confirmed the
  real model name `report.point_of_sale.report_saledetails`,
  `get_sale_details()`'s exact signature and returned dict shape, and
  `_get_report_values()`'s `session_ids` resolution.
- `addons/point_of_sale/views/report_saledetails.xml` — confirmed the
  real template structure, in particular that `<div class="page">`
  closes BEFORE the Invoices/Session Control sections, and that
  `<t id="closing_session">` is a unique, reliable anchor for "the end
  of the report."
- `addons/point_of_sale/models/pos_order.py` — confirmed, line by line:
  - `_order_fields()` (used for every ordinary order-building/payment
    sync write) never includes a `state` key at all, so the write()
    guard below cannot interfere with normal POS sync, payment
    processing, or order building — verified, not assumed.
  - `remove_from_ui()` is the ONE real mechanism a waitress uses to
    discard her own draft order: it does a non-sudo
    `orders.write({'state': 'cancel'})` followed by a sudo'd unlink.
    The write() guard below correctly intercepts the first (non-sudo)
    step and blocks it with the required message before the sudo'd
    unlink ever runs — this is exactly the intended behavior per the
    spec, not an accidental side effect.
  - `action_pos_order_cancel()` is explicitly commented "unused" by
    Odoo's own developers — safe to leave blocked for non-managers.
  - A core `@api.ondelete` hook, `_unlink_except_draft_or_cancel`,
    unconditionally rejects `unlink()` on any order not already in
    `draft`/`cancel` state — and `@api.ondelete` hooks are NOT bypassed
    by `.sudo()`. This was a real bug: the wizard's "delete" action
    originally called `order.sudo().unlink()` directly, which would
    have failed on every paid order. Fixed to cancel first, then
    unlink, mirroring core's own `remove_from_ui()` pattern exactly.
  - `account_move` (Many2one, no `ondelete=` override → defaults to
    "set null") and `picking_ids` (One2many) are NOT cascade-linked to
    unlink — deleting a pos.order does NOT delete or corrupt its
    already-posted journal entry or stock pickings, they simply become
    orphaned from their source order (traceability loss, not data
    corruption). The wizard now warns the manager about this
    specifically before they confirm a "Delete" on such an order (see
    "A note on deleting paid orders" below).

## What was NOT verified, and needs your attention

This module's author (an AI assistant) did not have access to:
- No print dialog is automatically triggered inside the POS till
  screen after closing. Instead, the thermal PDF is generated and
  stored as an `ir.attachment` on the session automatically after a
  verified-successful close, and is also available via the "Print
  Thermal Report" button on the session form (backend), which is
  disabled until the session is actually `closed`.
- Whichever core method (not visible in `pos_order.py`) manages
  `stock.picking.pos_order_id`'s own `ondelete` behavior — a low-risk
  gap (stock pickings orphaning is far less severe than the accounting
  risk already ruled out above), but not literally confirmed.

## A note on deleting paid orders

Core Odoo deliberately makes it hard to delete any order that isn't
`draft`/`cancel` — that `@api.ondelete` hook exists specifically to
discourage removing orders with real accounting/stock history. This
module's wizard lets a manager override that, per the spec's explicit
requirement, but doing so is a genuine trade-off: the posted journal
entry and any stock pickings survive intact (verified above), but they
lose their link back to the order that generated them, and any
`refunded_order_ids`/`refunded_orderline_id` relationships pointing at
the deleted order will break. The wizard shows a warning banner when
the target order has an invoice or picking attached and "Delete" is
selected. Recommend treating "Cancel" as the default and reserving
"Delete" for orders with no real downstream accounting/stock impact —
this is a business-process recommendation, not something the code
enforces, since the spec asks for both options to genuinely exist.

## Frontend on-till session receipt (new)

Separate from the backend PDF thermal report, there is now a quick
on-till printout that fires automatically right after a verified
successful close, using the SAME mechanism Odoo's own sale receipt
uses (`this.printer.print()` on an OWL component with its own
client-side template) — a server-rendered PDF cannot be handed to that
API, which is why this is a second, distinct artifact rather than a
reuse of the backend report.

- `models/pos_session.py`: `get_thermal_receipt_data()` — RPC-callable,
  returns a flattened, JSON-safe dict sourced from the exact same
  `report.point_of_sale.report_saledetails._get_report_values()` used
  everywhere else in this module. No independent calculation.
- `static/src/app/session_receipt/`: `SessionReceipt` OWL component +
  template, modeled directly on core's own `OrderReceipt`/
  `order_receipt.xml`.
- `static/src/app/navbar/closing_popup/closing_popup_patch.js`: patches
  `ClosePosPopup.prototype.closeSession()`. This required a FULL method
  override rather than a smaller hook, because in the verified source
  `redirectToBackend()` is called from two places — once on genuine
  success, once on a generic failure path — so there is no narrower
  seam that only fires on success. The override was diffed
  programmatically against the actual uploaded `closing_popup.js`; the
  only difference is one clearly marked block (search for
  `waitress_cash_control` in that file) plus the trailing `}` → `},`
  required by `patch()`'s object-literal syntax. If you upgrade Odoo,
  re-diff this file against the new core version the same way.
- The print is wrapped in try/catch and can never block the redirect —
  a printer problem after a successful close is not a reason to trap
  the cashier in the till screen. The comprehensive backend PDF (with
  every one of the 16 requested sections, vs. this shorter till
  version) remains available regardless.

**UNVERIFIED:** the `'point_of_sale._assets_pos'` bundle key in
`__manifest__.py` is the well-known 17.0 convention but was not
confirmed against this install's actual
`addons/point_of_sale/__manifest__.py`. Wrong key → the component
simply doesn't load (safe, obvious failure, nothing else affected) —
please confirm/correct via:
```powershell
Select-String -Path .\addons\point_of_sale\__manifest__.py -Pattern "assets"
```

## Per-user "Disable Order Deletion" (replaces the group-based till check)

The till's trash-icon visibility was originally gated on POS-manager
group membership via a new RPC method. That was wrong for two
independent reasons, both worth recording:

1. **Root cause of "still showing for all users"**: the RPC method
   checked the GLOBAL `point_of_sale.group_pos_manager`. Core Odoo
   itself (verified in `pos_session.py`'s `_get_pos_ui_res_users`)
   computes `pos.user.role` from `self.config_id.group_pos_manager_id`
   — a group Odoo auto-creates **per POS config**, not the global one.
   Checking the wrong group meant the till-visibility check and core's
   own manager/cashier concept could disagree.
2. **Deployment reality**: multiple physical stations/waitresses may
   share one generic Odoo login, at which point ANY group-membership
   check (global or per-config) is the same answer for everyone by
   construction, regardless of which physical till is in use.

The fix replaces group-checking entirely with an explicit, per-user
boolean:

- `models/res_users.py`: `res.users.pos_disable_order_deletion`
  (default off).
- `models/pos_session.py`: `_loader_params_res_users()` is extended to
  include this field, piggybacked onto core's own verified
  `_loader_params_res_users`/`_get_pos_ui_res_users` mechanism — the
  exact same pattern core uses to compute `pos.user.role`. This means
  the frontend gets the flag **synchronously**, at session boot, with
  zero extra RPC calls and zero timing/race risk (a real weakness of
  the previous onWillStart-RPC approach, independent of the wrong-group
  bug above).
- `models/pos_order.py`: `write()` now blocks moving an order to
  `'cancel'` only when `self.env.user.pos_disable_order_deletion` is
  True (and the call isn't sudo'd). **Unchecked is the default and
  means fully normal, unrestricted Odoo behavior** for that specific
  write — per your spec: "☐ Disable Order Deletion → normal POS
  behavior remains unchanged." `unlink()` is UNCHANGED — deleting an
  already-PAID order still always requires the manager wizard,
  regardless of this flag, since nothing in the request asked to loosen
  that heavier protection.
- `static/src/app/screens/ticket_screen/ticket_screen_patch.js`: now
  reads `this.pos.user.pos_disable_order_deletion` directly — no RPC,
  no group check of any kind.

**View placement (needs your confirmation):**
`views/res_users_views.xml` currently adds the checkbox to the
Preferences tab (`//page[@name='preferences']`) as a working default —
NOT verified against your actual `res_users_views.xml`, and NOT
positioned next to "Bypass HTML Field Sanitize" as specifically
requested (that field lives in a technical/debug-only section whose
exact name needs confirming first). Send:
```powershell
Get-ChildItem -Path .\addons\base -Recurse -Include *.xml | Select-String -Pattern "Bypass HTML"
```
and this becomes a one-line xpath change to the exact spot requested.

**Still open: the "Clear" button beside the numeric keypad.** I don't
yet have the file that defines it — the numpad shown in your
screenshots is used by multiple screens (ProductScreen, TicketScreen's
refund numpad), and I don't want to guess which one or what it
actually does (clear the current numeric entry vs. clear the whole
order) without seeing it, given how the till-visibility bug above
played out from an unverified assumption. Please locate and upload it,
e.g.:
```powershell
Get-ChildItem -Path .\addons\point_of_sale -Recurse -Include *.js,*.xml | Select-String -Pattern "Clear" -List
```
Once I see what it actually calls, I'll gate it the same way (checking
`pos_disable_order_deletion` client-side, and server-side if it turns
out to trigger a write/unlink path not already covered above).

## "Waitress" display convention

Per your clarification: each waitress operates her own dedicated POS
config/cash drawer, and staff may share a generic Odoo login, so the
POS **config name** — not `session.user_id`/`order.user_id` — is what
actually identifies "the waitress" for reporting purposes. All three
report surfaces (Daily Sales appended section, backend Thermal PDF,
on-till receipt) now use `config_id.name` as the "Waitress" display
value, computed once in `models/report_sale_details.py` and reused
everywhere via `pos_sessions_summary`/`deleted_orders_summary`.

This is a **display-only** change. The underlying
`pos.order.deletion.audit.waitress_id` field (shown in the backend
Order Deletion Audit log under its own "Waitress / POS User" label)
still records the real logged-in `res.users` at the time of deletion —
that's a genuine accountability record and is intentionally left
alone, separate from the "what do we call this on a printed report"
question.

## Tips

`total_tips` is now computed once per session (in
`report_sale_details.py`, from `pos.order.tip_amount` over the same
"closed orders" set core itself uses) and appears as its own line on
all three surfaces: the on-till receipt, the backend Thermal PDF, and
a new column in the Daily Sales appended Session Cash Control table.

## Numpad "Backspace" emptying the whole order

`static/src/app/screens/product_screen/product_screen_patch.js` — the
last remaining gap in "the trash icon isn't the only way to discard an
order." Verified against your actual `product_screen.js`: backspacing
a selected line down to empty calls `_setValue("remove")` →
`this.currentOrder.removeOrderline(selectedLine)`, purely client-side.

Removing a line while others remain is left completely alone — that's
normal, necessary order editing (fixing a misclick), not something
this module should ever restrict. The patch only intercepts the
specific case where the line being removed is the **last** one, i.e.
where the result would be an empty order — functionally equivalent to
discarding the whole ticket, and a way to bypass
`pos_disable_order_deletion` entirely via the numpad instead of the
trash icon.

**Stated plainly, not glossed over**: this one action has no separate
server RPC to backstop it the way `remove_from_ui` does — it's just
reconciled silently on the next routine order sync (the same
`pos_order.lines.unlink()`/rebuild visible in your earlier server log).
This patch is a client-side-only mitigation for the visible UI path an
ordinary restricted user would take. It does not and cannot defend
against someone bypassing the frontend entirely (e.g. editing JS in
the browser console) — no client-side check ever can; that's exactly
why every OTHER restriction in this module is enforced server-side.

## Report totals: Total Sales and Total Voids

Added to all three report surfaces (till receipt, backend Thermal PDF,
Daily Sales appended section), computed once in
`report_sale_details.py` and read everywhere else — never recalculated
per surface:
- **Total Sales** = the literal sum of every payment method's total
  (not a separate calculation against order lines/taxes), printed
  directly under the Payments breakdown so it can never visually
  disagree with the numbers above it.
- **Total Voids** = the sum of all deleted/cancelled order amounts for
  the session (from the audit trail), shown as a summary line above
  the itemized list, alongside a count.

## Security design

- **Deleting a PAID order** (`pos.order.unlink()`) is blocked in Python
  for anyone whose call isn't running as superuser (`self.env.su`),
  with the exact required message. A global `ir.rule`
  (`security/security.xml`) backstops this at the ORM layer
  independently of the Python code. Unaffected by
  `pos_disable_order_deletion` — always wizard-only.
- **Cancelling/clearing a draft order** (`write({'state': 'cancel'})`)
  is blocked only for a user whose `pos_disable_order_deletion` is
  checked (see the dedicated section above for why this replaced the
  original blanket sudo-only design).
- The only way to reach the superuser path for an actual deletion is
  `pos.order.deletion.wizard.action_confirm()`, which:
  1. Checks `point_of_sale.group_pos_manager` membership against the
     real acting user (`self.env.user`), before any `.sudo()` is used.
  2. Requires a non-empty reason.
  3. Creates the permanent audit record (`pos.order.deletion.audit`,
     write/unlink always raise — even for admins) in the same
     transaction as the cancel/delete, with no manual commit anywhere,
     so both succeed or both roll back together.
  4. Only then calls `order.sudo().unlink()` or
     `order.sudo().write({'state': 'cancel'})`.
- No boolean context flag is used anywhere as a security gate — the
  per-user setting is a real, persisted `res.users` field, checked
  server-side on every write, not a client-suppliable value.

## Reports

- **Daily Sales** (`point_of_sale.report_saledetails`, unchanged
  button/workflow) gets two appended sections: session cash control
  (opening/closing/expected/difference) and deleted/cancelled orders.
  Deleted orders are sourced from the audit table and are never merged
  into the sales totals above them — core's own order search already
  excludes them naturally, since a deleted order no longer exists to be
  found.
- **Thermal Session Report** (new, 80mm, dynamic/continuous height via
  `page_height = 0`) renders the exact same underlying data — no
  separate sales calculation exists anywhere in this module.

## Operational note: resolving a stray draft order before closing

For a user with `pos_disable_order_deletion` CHECKED,
`remove_from_ui()` (the standard frontend "discard order" call) is
blocked, and a manager must use the "Cancel / Delete Order..." wizard
instead to resolve a leftover draft order before
`action_pos_session_closing_control` will allow the session to close
(core still raises "You cannot close the POS when orders are still in
draft" regardless of this module). For a user with the box UNCHECKED
(the default — e.g. an actual manager's own login), the standard
discard button works exactly as core Odoo intends, and no wizard step
is required to clear a stray draft before closing.

## Testing checklist (per the original spec)

Waitress: cannot cancel/clear/remove/delete a draft order; cannot
delete a paid order; cannot bypass any of this via direct RPC calls to
`unlink()`/`write()`.

Manager: can cancel or delete via the wizard; reason is mandatory;
audit record is created; deleted order disappears from sales totals but
appears in the audit/report; two different waitresses' sessions never
show each other's data (enforced by the existing `session_id`
relations already present in the data model — this module always
filters by resolved `session_ids`, never assumes a shared POS config
means shared data).

Closing: session closes normally through the existing
`action_pos_session_closing_control` / `close_session_from_ui` flow,
completely unmodified in its return contract; thermal report is only
ever generated after a verified successful close.
