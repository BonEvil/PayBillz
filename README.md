# PayBillz

An MIT-licensed, single-user recurring bill planner that runs on your own computer. Python/Django, SQLite, responsive templates, and a small amount of JavaScript. No accounts, bank connections, payment processing, analytics, or cloud service are required. Recording a payment records your manual action; it does not transfer money.

## Install and run

Requires Python 3.12+ with venv/pip, Git, a POSIX shell and ps. Linux and macOS use the same installer; Windows runs it inside WSL. See [operations](ops-delivery/OPERATIONS.md) for prerequisites, platform evidence, recovery, and custom paths.

Install directly from the public repository:

```sh
curl -fsSL https://raw.githubusercontent.com/BonEvil/PayBillz/main/install.sh | sh
```

Or run the installer from a checkout:

```sh
git clone https://github.com/BonEvil/PayBillz.git
cd PayBillz
./install.sh
```

The installer creates `~/.local/bin/paybillz` and adds its directory to bash, zsh, or POSIX-shell startup configuration without replacing existing settings. Open a new terminal afterward, or run the `export PATH=...` command printed by the installer, then:

```sh
paybillz start
paybillz status
paybillz restart
paybillz stop
paybillz update
```

Open http://127.0.0.1:8765/. The server binds only to IPv4 loopback. Application files live in `~/.local/share/paybillz/app`; SQLite and configuration live separately in `~/.local/share/paybillz/data`. `paybillz update` downloads the latest `main` from BonEvil/PayBillz, backs up your data, installs dependencies and migrations, and restarts the app if it was running. No retained source checkout is needed. Download failures leave the running app untouched; migration failures restore the prior app and data.

Use `sh install.sh --no-path` to leave shell startup files untouched. Other shells receive instructions to add the command directory to PATH. The application works offline after installation; downloading and updating require access to GitHub and pinned Python packages.

On first installation, `data/config.json` contains a generated secret and timezone `UTC`. Set `timezone` to your IANA local timezone (for example `America/New_York`) and restart before entering bills. All due dates and payment dates are calendar dates; today is evaluated in that configured timezone. Amounts use exact decimals, with two fractional digits; the MVP displays dollar amounts and has no currency conversion.

## Install as a PWA or Omarchy web app

After installing PayBillz locally, add it to Omarchy's application launcher:

```sh
paybillz install-webapp
```

This uses Omarchy's installed web-app helper and the bundled PayBillz icon. The launcher calls `paybillz open`, which starts the local server if needed and opens a frameless Omarchy browser window. It does not depend on a terminal remaining open or require a system-wide service. `paybillz open` also works directly; on other desktops it opens your default browser. A custom PAYBILLZ_HOME/BIN_DIR and the chosen port are retained in the generated launcher. Reinstall the launcher after changing the port.

Alternatively, run `paybillz start`, visit `http://127.0.0.1:8765/` in Chromium, and use **Install app** when offered or the browser's install action. The manifest provides standalone display, app icons, and shortcuts for adding bills and viewing history. Loopback HTTP is supported for PWA installation; no certificate or network exposure is needed. Always use the same hostname and port for the installed app.

Omarchy's **Install → Web App** menu can also use the name **PayBillz**, URL `http://127.0.0.1:8765/`, and icon URL `http://127.0.0.1:8765/pwa/icon-512.png`. Manual menu/browser installations require the server to be started separately; the `paybillz install-webapp` launcher starts it automatically. Remove its launcher with Omarchy's **Remove → Web App** menu. Removing the launcher does not delete your bills; uninstalling the backend does not automatically remove browser or Omarchy launchers.

The app works without internet while the local server is running. If the server is unavailable after the first visit, a service worker shows a recovery page. Only the public offline page and icons are cached: bill data, forms, and payment actions are never cached or queued by the service worker. Offline edits and payments are not supported.

References: [Omarchy web apps](https://github.com/omacom/omarchy/blob/quattro/manual/25-web-apps.md), [PWA installability](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).

## Use

1. Set a known payday and its recurrence under Pay schedule.
2. Add bills with a name, expected amount, first due date, recurrence, optional payment link and notes.
3. Review the current and next three paycheck buckets. Each includes payday through the day before the next payday. Earlier unpaid bills remain visible separately; overdue bills in the current bucket are marked there without being counted twice.
4. Choose Pay to record the actual amount and date. Correct changes an existing record; Undo makes that occurrence unpaid again. Repeated or stale payment submissions are rejected with an instruction to reload.
5. Adjust changes one occurrence's due date or expected amount. History searches bill names and filters payment status and due dates. Archive stops future scheduling while retaining missed and paid records.

The paid total sums actual payments associated with a bucket's due dates; outstanding sums expected amounts of unpaid occurrences. Paying a different amount settles that occurrence, so expected need not equal paid plus outstanding.

## Recurrence rules

Presets include weekly, fortnightly, monthly, quarterly, annually, twice monthly, and last chosen weekday. Custom rules support one time; every N days/weeks/months/years; selected weekdays; multiple monthly dates; selected months; and first through fifth or last chosen weekday of a month.

Month-end dates clamp without losing their anchor: January 31 → February 28 → March 31. Annual February 29 bills use February 28 in non-leap years. Multiple monthly dates that clamp to the same date produce one occurrence. A fifth weekday absent from a month is skipped. Weekends and holidays are never shifted automatically.

Early, late, and missed payments do not move recurrence anchors. Bill edits preserve today's and earlier records and paid history, and apply future changes to unpaid occurrences. Explicit occurrence overrides remain records. Archival preserves today's and earlier unpaid occurrences and paid records while removing future unpaid projections.

## Maintain

```sh
paybillz backup
paybillz restore /absolute/path/to/backup
paybillz update
# Developers may explicitly install a local source snapshot:
paybillz update --source /absolute/path/to/checkout
paybillz uninstall
```

Updates back up before migrations and roll back failed migrations. Uninstall preserves data and backups. Do not run lifecycle commands concurrently. See [operations](ops-delivery/OPERATIONS.md) and [contributing](CONTRIBUTING.md). Do not include personal data, SQLite files, or configuration secrets in issues or contributions.

## Multiple income sources and categories

Use **Pay schedules → Add pay schedule** for each income source. Give each a name, expected amount per payday, first included payday, and recurrence. The 15th/last-day preset handles February and shorter months automatically; custom monthly dates accept values such as `5, 20, last`. Interval, weekday, and ordinal weekday rules remain available.

All schedules form one combined timeline: a bucket starts on a payday and ends the day before the next payday from any schedule. Income arriving on the same day is added together. Each bill appears in only one bucket. Expected income is a projection, not a bank balance. Editing or removing schedules recalculates buckets without deleting bills or payment history. Existing schedules migrate with the name “Pay schedule” and an expected amount of $0; edit these values after updating.

Use **Categories** to create reusable category/subcategory pairs such as Utility → Electric or Credit card → Visa, then select one on any bill. You can also check **Add a new category** directly on the bill form, enter a category and optional subcategory, and save both together. Matching existing categories are reused; invalid bill submissions preserve your input without creating categories. The subcategory is optional. Editing a category updates its label across bills, dashboard, and history without changing recorded payment amounts or dates.
