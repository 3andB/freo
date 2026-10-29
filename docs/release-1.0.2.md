# Freo 1.0.2

Stable release of the tested RC3 recovery-durability and microphone corrections.
The application changes from RC3 are limited to the version value; schema remains
fe28c3d4e5f6. See [RC3 acceptance](release-1.0.2-rc.3.md) for exact prior test scope
and [stable upgrade acceptance](https://github.com/3andB/freo/releases/download/v1.0.2-rc.3/STABLE-UPGRADE-ACCEPTANCE.md).

The owner confirms additional microphone and physical iPhone/Android tests passed.
This is owner-reported device acceptance; no device models, OS versions or raw
logs were supplied. Do not infer physical host-power or USB-removal certification.

Fixes include root-controlled traversable release directories, idempotent narrow
launcher relocation, root:freo 0640 canonical configuration, durable verified
restore inputs and atomic recovery publication, and quiet healthy muted live
microphone input while retaining loss/lease fallback. Original installation and
broadcast tests passed separately from the recovery defects discovered later.

Existing 1.0.1 installations require the explicit radio-maintenance upgrade path.
The ordinary administrative updater intentionally refuses this template change.
Do not reinstall over customer state or normalize failed recovery journals. Retain
failed state and matched encrypted backups; use verified corrected management
tools throughout recovery. See [installation](stable-1.0.2-installation.md).

Remaining scope limits: physical host power removal, USB microphone input/removal,
interruption of the upgrade transaction itself, other source versions/cross-schema
or suspended upgrades, and this version through Studio/World approval. Earlier
acceptance covers real unclean guest reset during recovery and successful resume.
Original v1.0.0/1.0.1/RC tags, kits and evidence remain immutable.
