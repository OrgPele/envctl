# Likely Unused Storage Candidates

Generated on: 2026-03-21
Machine scope: targeted scan across `~/`, `/Applications`, `/Library`, and `/private/var`

This document lists files and directories that are likely safe to review for deletion because they match one or more strong signals:

- Duplicate copies
- Old installers or extracted installer folders
- Backup-named app bundles
- Generated build output
- Old worktree or tree archives
- Large dated logs
- Cache directories that are designed to be regenerated
- Suspicious temporary artifacts

This is not an automatic delete list. It is a review list ordered by confidence and likely reclaimed space.

## Highest Confidence Candidates

These are the strongest "probably unused" findings from the scan.

| Size | Path | Why flagged |
| --- | --- | --- |
| 8.5G | `/Users/kfiramar/Downloads/flasher/super.img` | Large flash image with another byte-identical copy in `fix_oneplus` |
| 8.5G | `/Users/kfiramar/fix_oneplus/flasher/super.img` | Duplicate of the `Downloads/flasher` image |
| 8.1G | `/Users/kfiramar/Downloads/Super Flasher Global 703/super.img` | Large flash image with matching copies under `fix_oneplus` |
| 8.1G | `/Users/kfiramar/fix_oneplus/Super-Flasher-Global-703/super.img` | Duplicate of the `Downloads` image |
| 8.1G | `/Users/kfiramar/fix_oneplus/super.img` | Another matching large flash image |
| 1.1G | `/Users/kfiramar/Applications/OmniRoute 2.3.13.backup.app` | Backup-named app bundle |
| 9.6G | `/Users/kfiramar/Library/Application Support/kiro-cli/cli-checkouts/0e3ef79d-fe71-4aff-af97-e61e489bd817/objects/pack/tmp_pack_VM2lro` | Suspicious temporary git pack file |

## Large Duplicate Flashing Bundles

These directories look related and contain overlapping firmware and platform-tools content.

| Size | Path | Notes |
| --- | --- | --- |
| 9.2G | `/Users/kfiramar/Downloads/flasher` | Old flashing bundle, contains `super.img` |
| 8.9G | `/Users/kfiramar/Downloads/Super Flasher Global 703` | Similar structure to other flashing bundles |
| 8.9G | `/Users/kfiramar/Downloads/Super Flasher Global 602` | Similar structure to other flashing bundles |
| 7.1G | `/Users/kfiramar/Downloads/SuperHybrid_DerpFest-v16` | Another large flashing bundle |
| 27G | `/Users/kfiramar/fix_oneplus` | Separate tree with overlapping flashing assets |

Confirmed duplicate large files:

| Size | Duplicate file set |
| --- | --- |
| 8.5G | `/Users/kfiramar/Downloads/flasher/super.img` and `/Users/kfiramar/fix_oneplus/flasher/super.img` |
| 8.1G | `/Users/kfiramar/Downloads/Super Flasher Global 703/super.img`, `/Users/kfiramar/fix_oneplus/Super-Flasher-Global-703/super.img`, `/Users/kfiramar/fix_oneplus/super.img` |
| 205M to 215M | Multiple `modem.img` copies across `Downloads` and `fix_oneplus` |

If you only keep one canonical flashing workspace, this area alone could free tens of gigabytes.

## Old Installers and Archives In Downloads

These are likely safe if the app is already installed or the archive has already been extracted.

| Size | Path | Why flagged |
| --- | --- | --- |
| 508M | `/Users/kfiramar/Downloads/Docker.dmg` | Old installer image |
| 277M | `/Users/kfiramar/Downloads/kiro-ide-0.10.32-stable-darwin-arm64.dmg` | Old installer image |
| 218M | `/Users/kfiramar/Downloads/comet_latest.dmg` | Old installer image |
| 198M | `/Users/kfiramar/Downloads/Claude.dmg` | Old installer image |
| 184M | `/Users/kfiramar/Downloads/Antigravity.dmg` | Duplicate installer |
| 184M | `/Users/kfiramar/Downloads/Antigravity (1).dmg` | Duplicate installer |
| 142M | `/Users/kfiramar/Downloads/Codex (2).dmg` | Duplicate family of installer downloads |
| 140M | `/Users/kfiramar/Downloads/Codex.dmg` | Duplicate family of installer downloads |
| 140M | `/Users/kfiramar/Downloads/Codex (1).dmg` | Duplicate family of installer downloads |
| 139M | `/Users/kfiramar/Downloads/OmniRoute-2.6.10-arm64.dmg` | Old installer image |
| 139M | `/Users/kfiramar/Downloads/OmniRoute-2.5.9-arm64.dmg` | Older installer image |
| 132M | `/Users/kfiramar/Downloads/OmniRoute-2.5.4-arm64.dmg` | Older installer image |
| 125M | `/Users/kfiramar/Downloads/T3-Code-0.0.11-arm64.zip` | Archive appears extracted already |
| 121M | `/Users/kfiramar/Downloads/ProtonVPN_mac_v6.4.0.dmg` | Old installer image |
| 119M | `/Users/kfiramar/Downloads/Kap-3.6.0-arm64.dmg` | Old installer image |
| 115M | `/Users/kfiramar/Downloads/Stremio_arm64.dmg` | Old installer image |
| 113M | `/Users/kfiramar/Downloads/Notion-7.8.0-arm64.dmg` | Duplicate installer family |
| 108M | `/Users/kfiramar/Downloads/Notion-7.8.0-arm64 (1).dmg` | Duplicate installer family |
| 75M | `/Users/kfiramar/Downloads/OpenCode Desktop.dmg` | Old installer image |
| 73M | `/Users/kfiramar/Downloads/Windscribe_2.16.14_universal.dmg` | Old installer image |
| 49M | `/Users/kfiramar/Downloads/Zoom.pkg` | Old installer package |

## Extracted Installer Folders

These are usually redundant once the corresponding app is installed.

| Size | Path | Why flagged |
| --- | --- | --- |
| 362M | `/Users/kfiramar/Downloads/T3-Code-0.0.11-arm64` | Extracted app bundle exists alongside the zip |
| 42M | `/Users/kfiramar/Downloads/logioptionsplus_installer.app` | Installer app left in `Downloads` |
| 32M | `/Users/kfiramar/Downloads/platform-tools` | Extracted tools folder, zip also present |
| 14M | `/Users/kfiramar/Downloads/platform-tools-mac.zip` | Archive duplicate of extracted tools |
| 101M | `/Users/kfiramar/Downloads/OrangeFox-R11` | Extracted recovery bundle, also mirrored under `fix_oneplus` |

## Old Generated Build Output

These paths are large generated artifacts, not source. They were also old enough to appear in the stale generated-data scan.

| Size | Path | Why flagged |
| --- | --- | --- |
| 21G | `/Users/kfiramar/projects/claudia/src-tauri/target` | Rust/Tauri build output |
| 5.8G | `/Users/kfiramar/projects/claudia/trees-commands/3` | Extra tree with large generated `src-tauri` artifacts |
| 1.0G | `/Users/kfiramar/projects/claudia/trees-commands/2` | Extra tree with generated artifacts |
| 4.3G | `/Users/kfiramar/projects/opencode/node_modules` | Dependency install tree |
| 1.3G | `/Users/kfiramar/projects/remotion-videos/example/node_modules` | Dependency install tree |
| 568M | `/Users/kfiramar/projects/supportopia/venv` | Virtual environment |
| 461M | `/Users/kfiramar/projects/supportopia/frontend/node_modules` | Dependency install tree |
| 267M | `/Users/kfiramar/projects/supportopia/backend/venv` | Virtual environment |
| 91M | `/Users/kfiramar/projects/opencode/packages/opencode/dist` | Generated distribution output |
| 61M | `/Users/kfiramar/projects/supportopia/.mypy_cache` | Type-check cache |
| 61M | `/Users/kfiramar/projects/supportopia/backend/.mypy_cache` | Type-check cache |

## Old Tree And Worktree Archives

These look like historical worktree snapshots rather than active projects.

| Size | Path | Why flagged |
| --- | --- | --- |
| 6.8G | `/Users/kfiramar/projects/claudia/trees-commands` | Historical tree workspace collection |
| 3.4G | `/Users/kfiramar/projects/old/supportopia/trees` | Old archived tree set |
| 2.0G | `/Users/kfiramar/projects/old/supportopia/trees/trees-postgres-to-supabase-migration-20250706-022036` | Dated historical tree set |
| 686M | `/Users/kfiramar/projects/old/supportopia/trees/trees-remove-all-mocks-20250705-201530` | Dated historical tree set |
| 686M | `/Users/kfiramar/projects/old/supportopia/trees/trees-postgres-to-supabase-migration-20250105-201620` | Dated historical tree set |
| 248K | `/Users/kfiramar/projects/old/supportopia/worktrees/trees-remove-all-mocks` | Old worktree bookkeeping |

## Large Dated Logs

These look like retained historical run logs rather than current operational state.

| Size | Path |
| --- | --- |
| 310M | `/Users/kfiramar/projects/supportopia/logs/run_20260125_094949` |
| 245M | `/Users/kfiramar/projects/supportopia/logs/run_20260126_103941` |
| 138M | `/Users/kfiramar/projects/supportopia/logs/run_20260215_113918` |
| 94M | `/Users/kfiramar/projects/supportopia/logs/run_20260122_155152` |
| 70M | `/Users/kfiramar/projects/supportopia/logs/run_20260122_202704` |
| 55M | `/Users/kfiramar/projects/supportopia/logs/run_20260119_191136` |

Large individual log files:

| Size | Path |
| --- | --- |
| 134M | `/Users/kfiramar/projects/supportopia/logs/run_20260125_094949/new_ui_ux_code_optimization_plan_1_b8003_f9004_backend_p8003/backend.log` |
| 134M | `/Users/kfiramar/projects/supportopia/logs/run_20260125_094949/new_ui_ux_code_optimization_plan_2_b8022_f9022_backend_p8022/backend.log` |
| 118M | `/Users/kfiramar/projects/supportopia/logs/run_20260126_103941/new_ui_ux_code_optimization_plan_1_b8007_f9008_backend_p8007/backend.log` |
| 118M | `/Users/kfiramar/projects/supportopia/logs/run_20260126_103941/new_ui_ux_code_optimization_plan_2_b8024_f9024_backend_p8024/backend.log` |

## Large Cache Directories

These are designed to be recreated and are strong candidates if you want space back without touching source data.

| Size | Path | Notes |
| --- | --- | --- |
| 16G | `/Users/kfiramar/Library/Application Support/kiro-cli/cli-checkouts/0e3ef79d-fe71-4aff-af97-e61e489bd817` | Suspiciously large cache/checkout |
| 7.8G | `/Users/kfiramar/.bun/install` | Bun package cache |
| 5.0G | `/Users/kfiramar/.npm/_cacache` | npm cache |
| 4.1G | `/Users/kfiramar/Library/Caches/net.whatsapp.WhatsApp/org.sparkle-project.Sparkle` | WhatsApp updater cache |
| 3.4G | `/Users/kfiramar/.cache/puppeteer` | Downloaded browser cache |
| 2.1G | `/Users/kfiramar/Library/Caches/Google/Chrome` | Browser cache |
| 1.9G | `/Users/kfiramar/Library/Caches/Google/Chrome/Profile 2` | Browser cache |
| 1.4G | `/Users/kfiramar/Library/Caches/Comet` | Browser cache |
| 1.4G | `/Users/kfiramar/Library/Application Support/stremio-server` | Mostly cache |
| 768M | `/Users/kfiramar/Library/Caches/com.todesktop.230313mzl4w4u92.ShipIt/update.smtxLpE/Cursor.app` | Leftover app updater payload |
| 768M | `/Users/kfiramar/Library/Caches/com.todesktop.230313mzl4w4u92.ShipIt/update.TTajZXa/Cursor.app` | Leftover app updater payload |
| 660M | `/Users/kfiramar/Library/Caches/pip` | pip cache |
| 536M | `/Users/kfiramar/Library/Caches/go-build` | Go build cache |
| 330M | `/Users/kfiramar/Library/Caches/ms-playwright/chromium-1208` | Downloaded Playwright browser |
| 324M | `/Users/kfiramar/Library/Caches/ms-playwright/chromium-1200` | Downloaded Playwright browser |
| 275M | `/Users/kfiramar/.npm/_npx/47ababa9653307a4` | Temporary npx package tree |

## Smaller Likely Duplicates In Downloads

These are not large compared with the firmware bundles, but they are still likely redundant.

| Path A | Path B |
| --- | --- |
| `/Users/kfiramar/Downloads/2025-05-15T20_41_11.250375.png` | `/Users/kfiramar/Downloads/Peru/2025-05-15T20_41_11.250375.png` |
| `/Users/kfiramar/Downloads/IMG_4854.JPG` | `/Users/kfiramar/Downloads/Peru/IMG_4854.JPG` |
| `/Users/kfiramar/Downloads/IMG_4978.heic` | `/Users/kfiramar/Downloads/Peru/IMG_4978.heic` |
| `/Users/kfiramar/Downloads/IMG_4978.heic` | `/Users/kfiramar/Downloads/Photos/IMG_4978.heic` |
| `/Users/kfiramar/Downloads/IMG_4981.heic` | `/Users/kfiramar/Downloads/Peru/IMG_4981.heic` |
| `/Users/kfiramar/Downloads/IMG_4981.heic` | `/Users/kfiramar/Downloads/Photos-2/IMG_4981.heic` |
| `/Users/kfiramar/Downloads/Gemini_Generated_Image_mc6vexmc6vexmc6v.png` | `/Users/kfiramar/Downloads/Gemini_Generated_Image_mc6vexmc6vexmc6v (1).png` |

## Review Order

If you want the safest review order later, start here:

1. Duplicate DMGs, backup app bundles, extracted installer leftovers
2. Duplicate flash images and old flashing folders
3. Old logs
4. Cache directories
5. Generated build output and dependency trees
6. Historical tree and worktree archives
7. Suspicious Kiro CLI temporary pack file

## Big Consumers Intentionally Not Included In Automatic Cleanup

These items are important to keep visible because they consume a lot of space, but they were intentionally left out of the automatic cleanup lists. The reason is that they look like active application state, source repos, browser profile data, or system files rather than disposable leftovers.

| Size | Path | Why not included in automatic cleanup |
| --- | --- | --- |
| 56G | `/Users/kfiramar/Library/Containers/com.docker.docker` | Active Docker state, volumes, images, and VM data |
| 2.3G | `/Users/kfiramar/Library/Application Support/Google` | Browser profile and updater data |
| 1.4G | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2` | Active browser profile data including IndexedDB and Service Worker cache |
| 1.0G | `/Users/kfiramar/Library/Application Support/Code` | Editor state, extensions, cache, and local settings |
| 1.4G | `/Users/kfiramar/Library/Application Support/stremio-server` | App state and cache, but not reviewed aggressively for automatic deletion |
| 29G | `/Users/kfiramar/projects/claudia` | Active repo root; only generated subtrees were listed for cleanup |
| 5.9G | `/Users/kfiramar/projects/supportopia` | Active repo root; only logs, envs, and caches were listed |
| 4.7G | `/Users/kfiramar/projects/opencode` | Active repo root; only `node_modules` was listed |
| 2.2G | `/Users/kfiramar/projects/current/envctl` | Current working repo |
| 1.7G | `/Users/kfiramar/projects/OmniRoute` | Active repo root |
| 3.5G | `/Users/kfiramar/.rustup` | Installed Rust toolchains rather than pure cache |
| 2.4G | `/Users/kfiramar/go` | Go workspace and modules rather than pure cache |
| 8.0G | `/private/var/vm/sleepimage` | System-managed macOS VM sleep image |
| 20G | `/Applications` | Installed applications, not cleanup candidates by default |

The practical distinction is:

- This document flags things that are plausibly unnecessary or regenerable.
- The items above are big, but they need a separate, more intentional decision process.
