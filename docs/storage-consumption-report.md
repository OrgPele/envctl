# Storage Consumption Report

Generated on: 2026-03-21
Machine scope: targeted scan across `~/`, `/Applications`, `/Library`, `/private/var`, and common developer storage locations

This document captures what is most likely consuming disk space on the machine. It is meant to explain where the space is going, not to recommend deletions directly.

## Filesystem Summary

Writable data volume state at scan time:

| Mount | Size | Used | Free |
| --- | --- | --- | --- |
| `/System/Volumes/Data` | 460G | 380G | 21G |

Notes:

- The machine is constrained by free space on the writable data volume.
- APFS local snapshots were checked and none were present on the Data volume.

## Main Storage Buckets

These are the biggest attributed buckets found during the scan.

| Size | Path |
| --- | --- |
| 96G | `/Users/kfiramar/Library` |
| about 56.5G | `/Users/kfiramar/projects` |
| 38G | `/Users/kfiramar/Downloads` |
| 27G | `/Users/kfiramar/fix_oneplus` |
| 20G | `/Applications` |
| 7.8G | `/Users/kfiramar/.bun` |
| 5.8G | `/Users/kfiramar/.npm` |
| 5.5G | `/Library` |
| 5.1G | `/opt/homebrew` |
| 3.7G | `/Users/kfiramar/.cache` |
| 3.5G | `/Users/kfiramar/.rustup` |
| 2.4G | `/Users/kfiramar/go` |

## `~/Library`

`~/Library` is the single largest named bucket at `96G`.

Largest identified areas inside it:

| Size | Path | Notes |
| --- | --- | --- |
| 56G | `/Users/kfiramar/Library/Containers/com.docker.docker` | Docker Desktop VM and data |
| 16G | `/Users/kfiramar/Library/Application Support/kiro-cli` | Checkout/object cache |
| 2.3G | `/Users/kfiramar/Library/Application Support/Google` | Chrome profile data and Google updater |
| 2.1G | `/Users/kfiramar/Library/Caches/Google` | Chrome cache |
| 1.4G | `/Users/kfiramar/Library/Application Support/stremio-server` | Mostly cache |
| 1.4G | `/Users/kfiramar/Library/Caches/Comet` | Browser cache |
| 1.1G | `/Users/kfiramar/Library/Caches/ms-playwright` | Downloaded browser binaries |
| 1.0G | `/Users/kfiramar/Library/Application Support/Code` | VS Code app data |
| 688M | `/Users/kfiramar/Library/Application Support/Notion` | App data |
| 660M | `/Users/kfiramar/Library/Caches/pip` | pip cache |

## Docker

Docker is the single biggest active storage area.

| Size | Path |
| --- | --- |
| 56G | `/Users/kfiramar/Library/Containers/com.docker.docker` |

Docker CLI summary:

| Category | Total | Reclaimable |
| --- | --- | --- |
| Images | 40.94G | 15.11G |
| Containers | 342.1M | 110.5M |
| Local volumes | 16.14G | 15.48G |
| Build cache | 8.145G | 2.466G |

Additional facts:

- Docker volume count: `6,144`
- Docker Desktop sparse disk image:
  `/Users/kfiramar/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`
- Reported file size of `Docker.raw`: `460G`
- Actual on-disk Docker usage observed through directory sizing: about `56G`

Interpretation:

- The sparse disk image has grown very large in logical size.
- The live on-disk Docker footprint is still about `56G`.
- The unusually high number of volumes suggests long-term accumulation of state.

## Kiro CLI

This was one of the least expected large consumers.

| Size | Path |
| --- | --- |
| 16G | `/Users/kfiramar/Library/Application Support/kiro-cli` |
| 16G | `/Users/kfiramar/Library/Application Support/kiro-cli/cli-checkouts/0e3ef79d-fe71-4aff-af97-e61e489bd817` |
| 9.6G | `/Users/kfiramar/Library/Application Support/kiro-cli/cli-checkouts/0e3ef79d-fe71-4aff-af97-e61e489bd817/objects/pack/tmp_pack_VM2lro` |

Interpretation:

- Most of the footprint is concentrated in one checkout object store.
- The `tmp_pack_*` filename looks like interrupted or temporary git-pack state.

## Downloads And Flashing Assets

`Downloads` and `fix_oneplus` together hold a large amount of firmware and flashing material.

### `Downloads`

| Size | Path |
| --- | --- |
| 38G | `/Users/kfiramar/Downloads` |
| 9.2G | `/Users/kfiramar/Downloads/flasher` |
| 8.9G | `/Users/kfiramar/Downloads/Super Flasher Global 703` |
| 8.9G | `/Users/kfiramar/Downloads/Super Flasher Global 602` |
| 7.1G | `/Users/kfiramar/Downloads/SuperHybrid_DerpFest-v16` |

Largest files:

| Size | Path |
| --- | --- |
| 8.5G | `/Users/kfiramar/Downloads/flasher/super.img` |
| 8.2G | `/Users/kfiramar/Downloads/Super Flasher Global 602/super.img` |
| 8.1G | `/Users/kfiramar/Downloads/Super Flasher Global 703/super.img` |
| 6.5G | `/Users/kfiramar/Downloads/SuperHybrid_DerpFest-v16/FASTBOOT_FILES_HERE/super.img` |

### `fix_oneplus`

| Size | Path |
| --- | --- |
| 27G | `/Users/kfiramar/fix_oneplus` |
| 9.2G | `/Users/kfiramar/fix_oneplus/flasher` |
| 8.9G | `/Users/kfiramar/fix_oneplus/Super-Flasher-Global-703` |
| 8.5G | `/Users/kfiramar/fix_oneplus/flasher/super.img` |
| 8.1G | `/Users/kfiramar/fix_oneplus/super.img` |
| 8.1G | `/Users/kfiramar/fix_oneplus/Super-Flasher-Global-703/super.img` |

Interpretation:

- These directories contain some of the largest individual user files on the machine.
- There is clear duplication across `Downloads` and `fix_oneplus`.

## Projects

Project storage is concentrated in a handful of repos.

| Size | Path |
| --- | --- |
| 29G | `/Users/kfiramar/projects/claudia` |
| 5.9G | `/Users/kfiramar/projects/supportopia` |
| 4.7G | `/Users/kfiramar/projects/opencode` |
| 3.4G | `/Users/kfiramar/projects/old` |
| 3.3G | `/Users/kfiramar/projects/current` |
| 1.9G | `/Users/kfiramar/projects/vibeproxy-old` |
| 1.7G | `/Users/kfiramar/projects/OmniRoute` |
| 1.4G | `/Users/kfiramar/projects/remotion-videos` |
| 1.2G | `/Users/kfiramar/projects/vibeproxy` |
| 1.1G | `/Users/kfiramar/projects/t3code-official` |
| 1.1G | `/Users/kfiramar/projects/t3code` |

### `projects/claudia`

| Size | Path |
| --- | --- |
| 29G | `/Users/kfiramar/projects/claudia` |
| 21G | `/Users/kfiramar/projects/claudia/src-tauri/target` |
| 6.8G | `/Users/kfiramar/projects/claudia/trees-commands` |
| 306M | `/Users/kfiramar/projects/claudia/node_modules` |

Inside `target`:

| Size | Path |
| --- | --- |
| 19G | `/Users/kfiramar/projects/claudia/src-tauri/target/debug` |
| 15G | `/Users/kfiramar/projects/claudia/src-tauri/target/debug/deps` |
| 2.8G | `/Users/kfiramar/projects/claudia/src-tauri/target/debug/incremental` |
| 1.5G | `/Users/kfiramar/projects/claudia/src-tauri/target/release` |

### `projects/supportopia`

| Size | Path |
| --- | --- |
| 5.9G | `/Users/kfiramar/projects/supportopia` |
| 3.0G | `/Users/kfiramar/projects/supportopia/trees` |
| 1.1G | `/Users/kfiramar/projects/supportopia/logs` |
| 568M | `/Users/kfiramar/projects/supportopia/venv` |
| 461M | `/Users/kfiramar/projects/supportopia/frontend/node_modules` |
| 338M | `/Users/kfiramar/projects/supportopia/backend` |
| 267M | `/Users/kfiramar/projects/supportopia/backend/venv` |
| 257M | `/Users/kfiramar/projects/supportopia/.venv-312` |

### `projects/opencode`

| Size | Path |
| --- | --- |
| 4.7G | `/Users/kfiramar/projects/opencode` |
| 4.3G | `/Users/kfiramar/projects/opencode/node_modules` |
| 250M | `/Users/kfiramar/projects/opencode/.git` |

### `projects/current/envctl`

| Size | Path |
| --- | --- |
| 2.2G | `/Users/kfiramar/projects/current/envctl` |
| 1.8G | `/Users/kfiramar/projects/current/envctl/trees` |
| 329M | `/Users/kfiramar/projects/current/envctl/.venv` |

### `projects/OmniRoute`

| Size | Path |
| --- | --- |
| 1.7G | `/Users/kfiramar/projects/OmniRoute` |
| 921M | `/Users/kfiramar/projects/OmniRoute/.next` |
| 712M | `/Users/kfiramar/projects/OmniRoute/node_modules` |

### `projects/vibeproxy-old`

| Size | Path |
| --- | --- |
| 1.9G | `/Users/kfiramar/projects/vibeproxy-old` |
| 1.0G | `/Users/kfiramar/projects/vibeproxy-old/src/.build` |
| 739M | `/Users/kfiramar/projects/vibeproxy-old/.git` |

## Developer Tooling Caches

These are not project source. They are package, runtime, or browser caches.

| Size | Path |
| --- | --- |
| 7.8G | `/Users/kfiramar/.bun/install/cache` |
| 5.0G | `/Users/kfiramar/.npm/_cacache` |
| 821M | `/Users/kfiramar/.npm/_npx` |
| 3.4G | `/Users/kfiramar/.cache/puppeteer` |
| 2.1G | `/Users/kfiramar/Library/Caches/Google` |
| 1.1G | `/Users/kfiramar/Library/Caches/ms-playwright` |
| 660M | `/Users/kfiramar/Library/Caches/pip` |
| 179M | `/Users/kfiramar/Library/Caches/node-gyp` |
| 3.5G | `/Users/kfiramar/.rustup` |
| 2.4G | `/Users/kfiramar/go` |

## Browser And App Data

Chrome and Chromium-family apps account for a few more gigabytes of state.

| Size | Path |
| --- | --- |
| 2.3G | `/Users/kfiramar/Library/Application Support/Google` |
| 1.6G | `/Users/kfiramar/Library/Application Support/Google/Chrome` |
| 1.4G | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2` |
| 720M | `/Users/kfiramar/Library/Application Support/Google/GoogleUpdater` |
| 1.0G | `/Users/kfiramar/Library/Application Support/Code` |
| 688M | `/Users/kfiramar/Library/Application Support/Notion` |
| 573M | `/Users/kfiramar/Library/Application Support/Comet` |
| 522M | `/Users/kfiramar/Library/Application Support/Antigravity` |
| 346M | `/Users/kfiramar/Library/Application Support/Cursor` |

Notable Chrome Profile 2 data:

| Size | Path |
| --- | --- |
| 790M | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2/Service Worker` |
| 745M | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2/Service Worker/CacheStorage` |
| 425M | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2/IndexedDB` |
| 279M | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2/IndexedDB/https_web.whatsapp.com_0.indexeddb.leveldb` |
| 104M | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2/IndexedDB/https_photos.google.com_0.indexeddb.leveldb` |

## Installed Applications

Installed app bundles are not the main issue, but they are still a visible chunk.

Largest items in `/Applications`:

| Size | Path |
| --- | --- |
| 3.7G | `/Applications/iMovie.app` |
| 2.4G | `/Applications/Docker.app` |
| 1.7G | `/Applications/Comet.app` |
| 1.3G | `/Applications/Google Chrome.app` |
| 1.0G | `/Applications/calibre.app` |
| 1.0G | `/Applications/GarageBand.app` |

User Applications:

| Size | Path |
| --- | --- |
| 1.1G | `/Users/kfiramar/Applications/OmniRoute 2.3.13.backup.app` |
| 385M | `/Users/kfiramar/Applications/OmniRoute.app` |
| 362M | `/Users/kfiramar/Applications/T3 Code (Alpha).app` |

## System-Level Non-Home Usage

These areas do consume space, but they are not driving the storage problem.

| Size | Path | Notes |
| --- | --- | --- |
| 8.0G | `/private/var/vm` | Entirely `sleepimage` at scan time |
| 3.4G | `/private/var/db` | Mostly diagnostics and uuid text |
| 2.8G | `/private/var/folders` | Normal temporary and cache state |
| 5.5G | `/Library` | App support, audio assets, CLI tools |
| 5.1G | `/opt/homebrew` | Homebrew installation |

Inside `/private/var/db`:

| Size | Path |
| --- | --- |
| 2.5G | `/private/var/db/diagnostics` |
| 706M | `/private/var/db/diagnostics/Signpost` |
| 519M | `/private/var/db/uuidtext` |

Inside `/Library`:

| Size | Path |
| --- | --- |
| 2.7G | `/Library/Application Support` |
| 1.8G | `/Library/Developer/CommandLineTools` |
| 908M | `/Library/Application Support/GarageBand` |
| 895M | `/Library/Application Support/Logic` |
| 560M | `/Library/Application Support/Logi` |

## Main Conclusions

The storage pressure is primarily explained by:

1. Docker state and Docker Desktop data in `~/Library/Containers/com.docker.docker`
2. Large flashing images and duplicate firmware bundles in `Downloads` and `fix_oneplus`
3. Large generated build artifacts and historical tree/worktree directories in `~/projects`
4. Package manager and browser caches
5. A large and suspicious Kiro CLI checkout cache

This machine does not look like it is losing space mostly to hidden macOS system storage. The dominant consumers are user-space developer and downloaded assets.

## Large Consumers Not Included In The Cleanup Script

The cleanup script was intentionally conservative. These large consumers are shown there as "protected" because they are either active data, source repositories, application state, or system-managed files.

| Size | Path | Reason excluded from cleanup script |
| --- | --- | --- |
| 56G | `/Users/kfiramar/Library/Containers/com.docker.docker` | Docker data needs a dedicated cleanup decision |
| 29G | `/Users/kfiramar/projects/claudia` | Active repo root; only generated outputs are safe defaults |
| 5.9G | `/Users/kfiramar/projects/supportopia` | Active repo root; only logs and envs are safe defaults |
| 4.7G | `/Users/kfiramar/projects/opencode` | Active repo root |
| 2.2G | `/Users/kfiramar/projects/current/envctl` | Current working repository |
| 2.3G | `/Users/kfiramar/Library/Application Support/Google` | Active browser and updater state |
| 1.4G | `/Users/kfiramar/Library/Application Support/Google/Chrome/Profile 2` | Active browser profile data |
| 1.4G | `/Users/kfiramar/Library/Application Support/stremio-server` | App state mixed with cache |
| 1.0G | `/Users/kfiramar/Library/Application Support/Code` | Editor state and extensions |
| 3.5G | `/Users/kfiramar/.rustup` | Installed Rust toolchains |
| 2.4G | `/Users/kfiramar/go` | Go workspace and modules |
| 8.0G | `/private/var/vm/sleepimage` | System-managed VM sleep image |
| 20G | `/Applications` | Installed applications |
