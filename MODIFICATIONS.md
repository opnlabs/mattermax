# Modifications

Mattermax is a modified version of [Mattermost](https://github.com/mattermost/mattermost),
licensed under the GNU AGPL v3.0. As section 5(a) of the AGPL requires, this file
records every change made to the upstream source, with its date.

The changes come in three kinds:

- **Patches** in `patches/`, applied in the order of `patches/series`. Each one
  has an entry below.
- **Branding**, applied at build time by `branding/rebrand.py`: the product name
  "Mattermost" is replaced with "Mattermax" in user-visible text, following
  `branding/rules.json` and `branding/allowlist.json`, and logos and icons are
  replaced with the files in `branding/assets/`. Each release's
  `branding/report.md` lists every file changed.
- **Default settings** in `config/overlay.json`, merged into the packaged
  `config.json`.

## Patches

Format: `### <name>.patch`, then the date it
was added or last changed in behaviour, and what it does and why. When a patch
is removed (for example because upstream merged it), keep its entry and add the
removal date.

### release-license.patch

2026-11-03. `server/build/release.mk` packages `LICENSE.txt` (AGPL v3.0) with
the server instead of `MIT-COMPILED-LICENSE.md`. Upstream's MIT compiled
license covers only binaries produced by Mattermost, Inc.; Mattermax builds
its own, which `LICENSE.txt` places under the AGPL.

### remove-user-limits.patch

2026-11-03. Removes the 200/250 active user limit on servers without a
Mattermost license (`server/channels/app/limits.go`).


### about-dialog.patch

2026-11-04. Show the product name without "Team Edition", replace the community link
with an attribution to Mattermost, add the AGPL notice with a link to the
running version's source code (AGPL section 13), and drop the links to
Mattermost's terms of use and privacy policy, which don't cover a
self-hosted Mattermax server.

### optional-policy-links.patch

2026-11-04. Clear a blank TermsOfServiceLink instead of resetting it to Mattermost's
terms, as upstream already does for PrivacyPolicyLink. Show the sign-up
agreement checkbox only when a policy link is configured, naming only the
links that are, and don't require it otherwise.

### openid-connect.patch

2026-11-04. Sign in with any OpenID Connect provider without a license. A new
provider (`server/channels/app/oauthproviders/openid/`) finds the provider's
endpoints from `OpenIdSettings.DiscoveryEndpoint` and reads the user from the
UserInfo endpoint; it is registered in `server/cmd/mattermost/main.go`.
Discovery uses the server's outgoing HTTP client, so internal addresses must
be in `AllowedUntrustedInternalConnections`, and doesn't follow redirects.
Every login requires an ID token from the token endpoint whose issuer,
audience, authorized party and expiry are valid, and whose subject matches the
UserInfo response. The provider must mark the email address verified
(`email_verified` true). Accounts are identified by a hash of issuer and
subject, so a different provider never signs in to an existing account. The
client config sends the OpenID login button settings without a license
(`server/config/client.go`), and the System Console shows the OpenID Connect
page instead of its upgrade page, offering only "OpenID Connect (Other)"
(`admin_definition.tsx`). Written from the OpenID Connect specifications and
Mattermost's open-source OAuth code, without consulting Mattermost's
enterprise code.

### remove-upsell-pages.patch

2026-11-04. Remove the System Console pages that only advertise paid
Mattermost features: every feature discovery page and the About > Edition and
License page (`remove_upsell_pages.ts`, applied in
`selectors/admin_console.tsx` before plugins change the console). Sections
for unlicensed paid features inside other pages, such as Burn-on-Read
messages, show nothing instead of an upgrade prompt
(`licensed_section_container.tsx`). Mattermax has no license to show, and
these features are not in its build.

### fix-mfa-switch-title.patch

2026-11-04. Fix the title of the MFA step when switching an email/password
account to SSO, which showed a literal "{uiType}" instead of the sign-in
method (`email_to_oauth.tsx`). Upstream formatted the message without its
value.

### no-enterprise-imports.patch

2026-11-04. Remove every import of `server/enterprise/` that isn't behind the
`enterprise` build tag, so Mattermax builds without that tree. The server no
longer imports the enterprise package (`server/cmd/mattermost/main.go`).
mmctl drops its `compliance-export` command, its tests and its docs: the
command used enterprise job settings, and Team Edition has no compliance
export jobs. The enterprise metrics test (`server/channels/app/metrics_test.go`)
is removed.

### id-loaded-push-notifications.patch

2026-11-04. Allow "Full message content fetched from the server on receipt"
(`EmailSettings.PushNotificationContents` = `id_loaded`) without a license.
Push notifications then carry only IDs, and the mobile app fetches the message
from the server through `/api/v4/notifications/ack`, so the push proxy, Apple
and Google never see message contents. A new implementation of upstream's
`NotificationInterface` (`server/channels/app/notification_id_loaded.go`)
registers itself through `RegisterNotificationInterface` and builds the
fetched message with the same code as the "full" setting. The System Console
offers the option without a license (`admin_definition.tsx`). Written from
Mattermost's open-source notification code, without consulting Mattermost's
enterprise code.

### unlock-scheduled-posts.patch

2026-11-12. Allow scheduled messages (including recurring ones), message
acknowledgements and persistent notifications without a license. Upstream
implements all three in its open-source code and disables them on servers
without a Professional license. The patch removes those checks: the client
config sends `ScheduledPosts` and `PostAcknowledgements` (`server/config/client.go`),
the scheduled post API and job run (`api4/scheduled_post.go`,
`app/scheduled_post_job.go`), the acknowledge endpoints and post priority
checks accept the requests (`api4/post.go`, `app/post_permission_utils.go`),
and the persistent notification job runs (`jobs/post_persistent_notifications`).
The web app shows scheduling and its System Console setting without a license
(`selectors/entities/scheduled_posts.ts`, `admin_definition.tsx`). Tests that
asserted the license errors now assert the feature works.

### unlock-permission-schemes.patch

2026-11-12. Allow custom permission schemes (team override and channel
schemes) and channel moderation without a license, so admins can make
read-only channels and limit `@channel` per channel. Upstream implements both
in its open-source code and rejects the requests on servers without a
license. The patch removes those checks from the scheme, team scheme, channel
scheme and channel moderation endpoints (`api4/scheme.go`, `api4/team.go`,
`api4/channel.go`). The System Console shows the team override schemes panel
(`permission_schemes_settings.tsx`) and the channel moderation settings
(`team_channel_settings/channel/details`), and only loads a channel's LDAP
groups when group sync is licensed. Access control policies, assigning
delegated admin roles and editing guest role permissions stay gated.

### unlock-announcement-banner.patch

2026-11-12. Allow the system announcement banner without a license. Upstream
sends the banner settings (`AnnouncementSettings`) to clients only with an
Announcement license, so the banner never showed. The client config now sends
the configured values (`server/config/client.go`), and the System Console page
is gated only by its permission (`admin_definition.tsx`). Its feature
discovery twin stays in the definition and is removed at runtime by
`remove-upsell-pages.patch`.

### unlock-custom-groups.patch

2026-11-12. Allow custom user groups without a license: creating and managing
groups, `@group` mentions with autocomplete, adding groups to channels, and
the `ServiceSettings.EnableCustomGroups` System Console setting. Upstream
implements custom groups in its open-source code and rejects them on servers
without a license. The patch removes those checks from the client config
(`server/config/client.go`), the custom group endpoints (`api4/group.go`), the
member counts used by the mention confirmation (`api4/channel.go`) and group
mentions (`app/notification.go`). The web app loads, offers and highlights
custom groups without a license (`team_controller/actions`,
`status_profile_polling.ts`, `textbox`, `wysiwyg_suggestion_list.tsx`,
`permissions_tree.tsx`, `admin_definition.tsx`). LDAP and plugin groups stay
gated: without a license their endpoints return 501, and group listings,
lookups by name and mentions see only custom groups, for which
`GroupStore.GetByNames` now honours the requested source.

### unlock-guest-accounts.patch

2026-11-12. Allow guest accounts and guest magic links without a license:
inviting guests to channels by email or magic link, guest sign-up with an
invitation token, guest login, demoting a member to guest, and passwordless
guest sign-in. Upstream implements guests in its open-source code and rejects
them on servers without a license. Its login type endpoint even dereferenced
the missing license and crashed. The patch removes those checks
(`api4/user.go`, `api4/team.go`); the `GuestAccountsSettings` switches still
apply. The web app shows the Guest Access page, the guest option when
inviting (hidden before because Mattermax builds are not "enterprise ready"),
inviting guests to a channel, and "Demote to guest" without a license
(`admin_definition.tsx`, `invitation_modal`, `channel_invite_modal`,
`system_users_list_actions`). Custom guest role permissions stay gated.

### unlock-shared-channels.patch

2026-11-12. Allow shared channels and connected workspaces without a license,
so two independent servers can connect and sync a shared channel. Upstream's
sync services are open source and only start, and accept requests from the
other server, with a license. The patch removes those checks: the services
start when `ConnectedWorkspacesSettings.EnableRemoteClusterService` or
`EnableSharedChannels` is on (`app/server.go`), remote cluster token auth
requires the remote cluster service instead of a license (`web/context.go`,
`web/handlers.go`), the client config sends both settings
(`server/config/client.go`), and the System Console shows the Connected
Workspaces pages (`admin_definition.tsx`). The test helpers no longer add a
license when these settings are on, so the shared channel tests run without
one. DMs with remote users stay behind upstream's `EnableSharedChannelsDMs`
feature flag.

### unlock-theme-management.patch

2026-11-12. Allow theme management without a license: admins can set the
default theme, turn theme selection and custom themes on or off, and limit
the themes users can pick. Upstream sent fixed values for `ThemeSettings` to
clients without a ThemeManagement license and hid the settings in the System
Console. The client config now sends the configured values
(`server/config/client.go`), and the four settings on Site Configuration >
Customization are shown (`admin_definition.tsx`). The user settings theme
picker already reads these values.

### unlock-guest-permissions.patch

2026-11-12. Allow editing guest role permissions without a license, so admins
can change what guests may do (post and upload, react, mention, edit and
delete posts, create private channels) in the System Scheme and in team
override schemes. Upstream rejected patches to the guest roles without the
GuestAccountsPermissions license feature (`api4/role.go`) and showed the
Guests panels read-only (`permission_system_scheme_settings.tsx`,
`permission_team_scheme_settings.tsx`). The guest Group Mentions permission is
offered when custom groups are enabled (`guest_permissions_tree`), as it is for
members. Role permission checks are unchanged.

### command-palette.patch

2026-11-13. Turn the Ctrl/Cmd+K channel switcher into a command palette when
the query starts with ">": set your status (online, away, do not disturb for a
chosen time, offline), set or clear a custom status, open Settings, Profile,
Threads, Drafts or the System Console (for users with console access), and run
any slash command available in the current channel through the existing
autocomplete. Without ">", the switcher works as before and shows a hint row.
The commands live in new files under
`components/quick_switch_modal/command_palette/`; `quick_switch_modal.tsx`
gains the provider, the hint and Enter handling. No server change.

### quote-reply.patch

2026-11-13. Add "Quote reply" (shortcut Q) to the post menu. It inserts a
Markdown quote of the post (first 5 lines, "[attachment]" when files are
attached), credited to the author's display name, with a link to the original,
into the channel's composer, or the thread's composer in a thread, and focuses
it without opening a thread. New files under `components/quote_reply/`;
`advanced_text_editor.tsx` registers its composer with one hook call, and
`dot_menu` adds the item and shortcut. No server change. The author name is
Markdown-escaped and its newlines become spaces before it goes into the
attribution line.

### voice-messages.patch

2026-11-13. Record voice messages from the web composer. A microphone button
records up to 5 minutes (MP4/AAC where the browser supports it so recordings
play on iOS, WebM/Opus otherwise) and uploads the recording through the normal
file upload path, so the post is an ordinary post with an audio file. The
duration and a 64-bar waveform are stored in `Post.Props.voice_messages`,
keyed by file id, and those files get an inline player with a seekable
waveform and 1x/1.5x/2x speed. The button follows `EnableFileAttachments` and
the `upload_file` permission. New files under `components/voice_message/`;
small edits in `advanced_text_editor` and `file_attachment_list`. No server,
schema or config change; mobile apps show a normal audio attachment. The
inline player renders only when the attachment's `mime_type` starts with
`audio/`; any other file listed in `voice_messages` keeps its normal
attachment card. The WebM fallback saves recordings as `.weba`, so the server
stores `audio/webm`.

### read-receipts.patch

2026-11-13. Opt-in read receipts for direct and group messages. An admin
switch, `TeamSettings.EnableReadReceipts` (off by default), and a personal
Settings > Display toggle (on by default) stored as the
`display_settings`/`read_receipts` preference. Turning receipts off is
reciprocal: that user neither sends nor sees receipts. The client sends only
"false" or "true"; `App.UpdatePreferences` stores the server's own time when
receipts are turned back on (keeping the existing time if they were already
on), and deleting the preference does the same instead of resetting it, so
reads made while off stay private. Any stored value other than "false", no
row, or a past server time counts as off. A receipt is the other member's
existing `ChannelMembers.LastViewedAt`, so there is no migration. One rule,
`model.ReadReceiptVisible`, gates both the new
`GET /api/v4/channels/{id}/read_receipts` endpoint and the new
`read_receipt` websocket event. The web app shows "Seen" or "Seen by N" under
your newest message. Other members' last-viewed times stay hidden everywhere
else. Mobile apps ignore the event.

### slowmode.patch

2026-11-13. Per-channel slowmode (Off, 5s, 10s, 30s, 1m, 5m, 15m, 1h), set by
channel, team or system admins in a new Moderation tab of channel settings.
Stored as a Systems row `channel_posting_rules_<channelId>`, served by
`GET/PUT /api/v4/channels/{id}/posting_rules`, and cached in memory with the
cache entry dropped on save. Enforced in `App.CreatePost`
(`app/channel_posting_rules.go`), so the API, built-in slash commands (`/me`,
`/shrug`, `/echo`) and scheduled posts all follow it, with HTTP 429 and the
seconds left; slash commands show that message instead of a generic failure.
A scheduled post that would break slowmode at send time fails with "Unable to
Send" and its author is notified. Concurrent posts are serialized per channel
and user with an in-process lock while slowmode is on, which assumes a single
node (Mattermax does not unlock clustering). Deleted posts still count, so
deleting your last post does not reset the wait. Exempt: channel, team and
system admins, bots, incoming webhooks and webhook-style command responses,
plugin posts, system messages, and DMs/GMs. The web app shows an indicator and
a countdown notice at the composer. Mobile apps get the server's error text.

### thread-auto-archive.patch

2026-11-13. Per-channel thread auto-archive (Off, 1, 3, 7, 30 days without
replies), in the same Moderation tab and the same Systems row as slowmode.
Checked in `App.CreatePost` at reply time from max(root `CreateAt`,
`Threads.LastReplyAt`), with no background job, so the same paths and
exemptions as slowmode apply and a scheduled reply to an archived thread
fails with "Unable to Send". Late replies are rejected with HTTP 403. Channel
admins and above can still reply, which reopens the thread. A reply to a
deleted root is left to the post layer, but a database error while looking up
the root rejects the reply. Root posts and reactions are unaffected. The
thread view shows an archived notice instead of the reply box
(`create_comment.tsx`, +6).

### unlock-content-flagging.patch

2026-11-13. Content flagging (Data Spillage Handling) works without a license:
users flag posts with a reason, configured reviewers get a review post from
the content review bot and can keep or remove the post. Gates removed: the
Enterprise Advanced check in `api4/content_flagging.go`
(`requireContentFlaggingAvailable`), the `ContentFlaggingEnabled` client
config in `config/client.go`, and the license tier check on the System Console
page in `admin_definition.tsx`. The `ContentFlagging` feature flag already
defaults on upstream; admins still enable the feature in
`ContentFlaggingSettings.EnableContentFlagging`. Picking LDAP groups as
reviewers stays behind the LDAP groups license.

### unlock-custom-profile-attributes.patch

2026-11-13. Admin-defined custom profile attributes work without a license:
admins create, edit and delete fields under System Console > System Attributes
> Attribute Management, users fill them in Profile settings, and values show
in the profile popover and System Console user detail. Server gates removed:
the properties `LicenseCheckHook` registration in `app/server.go` and the
inline Enterprise check in api4 `getCPAGroup`. Webapp gates removed in
logged_in, the websocket reconnect, profile_popover, user_settings/general,
system_user_detail, and the Attribute Management pages; the unlicensed User
Attributes discovery page and its string are gone. Still gated: Board
Attributes, Classification Markings, and LDAP attribute sync.

### unlock-mobile-security.patch

2026-11-13. Mobile biometric authentication, screen capture prevention,
jailbreak/root protection and the mobile watermark work without a license.
`config/client.go` sends `MobileEnableBiometrics`,
`MobilePreventScreenCapture`, `MobileJailbreakProtection` and
`ExperimentalEnableWatermark` in both client configs, and the System Console
shows the Mobile Security page and the Enable Mobile Watermark setting without
a license. The stock Mattermost mobile app reads these four from the client
config without checking the license. `MobileEnableSecureFilePreview` and
`MobileAllowPdfLinkNavigation` stay gated at Enterprise Advanced, because the
stock app also checks that license tier itself
(`app/queries/servers/security.ts`), so unlocking them on the server would
show settings that do nothing. Intune MAM stays gated.

### unlock-enforce-mfa.patch

2026-11-13. Admins can require multi-factor authentication for all users
(`ServiceSettings.EnforceMultifactorAuthentication`) without a license. As
upstream, the guest setting (`GuestAccountsSettings.EnforceMultifactorAuthentication`)
only applies while global enforcement is on: it decides whether guests are
included, and does not enforce MFA on its own. Gates removed: `CheckUserMfa` in `app/authentication.go`,
the licensed-only client config prop in `config/client.go`, the System Console
setting, and the webapp MFA-required redirect checks (`utils/route.tsx`,
logged_in, team_controller, mfa_controller, the MFA settings section). TOTP
lives in AGPL `server/platform/shared/mfa`. A licensed server whose license
lacks the MFA feature now also enforces MFA when the config asks for it.

### unlock-lock-profile-fields.patch

2026-11-13. `TeamSettings.LockProfileFieldsForEmailUsers` works without a
license: email/password users cannot change locked name, username, nickname,
position or profile image, and invites can preset member profiles. Gates
removed: `CheckLockedProfileFields` and `IsProfileImageLockedForUser` in
`app/user.go`, the invite profile check in `app/team.go`, the Enterprise-only
client config prop in `config/client.go` (which empties and removes that
license block), and the hidden System Console setting.

### unlock-custom-terms-of-service.patch

2026-11-13. Admins can enable Custom Terms of Service without a license, and
users must accept them on login and again after the re-acceptance period.
Gates removed in `api4/terms_of_service.go` (create), `config/client.go`
(`EnableCustomTermsOfService` and `CustomTermsOfServiceReAcceptancePeriod` in
the limited client config), the mattermost-redux `shouldShowTermsOfService`
selector, the System Console page and its enable toggle.

### unlock-audit-logging.patch

2026-11-13. Audit logging works without a license: the System Console Audit
Logging page is visible, and `ExperimentalAuditSettings.AdvancedLoggingJSON`
targets load alongside basic file auditing. The same `AdvancedLogging` license
feature also gated the main server log, so `LogSettings` advanced targets are
no longer stripped when unlicensed (`RemoveUnlicensedLogTargets` deleted).
Release note: on upgrade, a server whose config already lists advanced log or
audit targets (TCP, syslog, extra files) starts writing to them. Gates
removed in `app/audit.go`, `app/server.go`, `app/delivery_tracking_config.go`,
`app/platform/log.go`, `config/logger.go`, `config/client.go`
(`AuditLoggingActive`) and `admin_definition.tsx`. The audit certificate
upload stays Cloud-only.

### prometheus-metrics.patch

2026-11-13. Prometheus metrics without a license, from a clean-room
implementation of `einterfaces.MetricsInterface` in package `platform`
(`metrics_prometheus.go`, `metrics_prometheus_client.go`,
`metrics_prometheus_noop.go`), registered through the existing
`RegisterMetricsInterface` hook. When `MetricsSettings.Enable` is true,
`/metrics` is served on the existing metrics port
(`MetricsSettings.ListenAddress`) beside the upstream pprof and plugin-metrics
routes. 68 interface methods record; 50 are no-ops: 23 for features that stay
enterprise-only (HA cluster, Elasticsearch, Redis cache, replica lag, access
control, auto-translation) and 27 deferred until their client-supplied labels
have a bounded mapping. Nothing records while `Enable` is false, except four
up/down gauges that must stay balanced. `config/client.go` sends
`EnableMetrics`, `EnableClientMetrics` and `EnableNotificationMetrics` without
a license. `PerformanceReport.IsValid` rejects null samples and reports with
more than 500 entries; client samples outside fixed per-metric limits are
dropped. No user, channel or team ID becomes a label, and
`MetricsSettings.ClientSideUserIds` has no effect. The report cap and value
limits are estimates. Keep the whole metrics port private (loopback or a
private address, firewalled): it also serves pprof and unauthenticated plugin
metrics. The server logs a warning when it binds all interfaces. Keep
`FeatureFlags.AggregatePluginMetrics` off, or use plugins that do not export
Go runtime collectors.

### data-retention.patch

2026-11-13. Data retention works without a license: global message and file
retention, custom team and channel message policies, the System Console pages
and the deletion job. Upstream ships the API, store and console in AGPL code
but leaves the policy service and the deletion job to enterprise code; this
patch adds clean-room versions in `app/data_retention_policies.go`,
`app/data_retention_job.go` and `jobs/data_retention/`, plus store methods in
new sqlstore files. As upstream, the global message policy also deletes direct
and group messages; custom policies cannot include them. When the job deletes
a post it also removes the post's attachments, thumbnails and previews from
file storage, with or without file retention (bytes before rows, retried on
the next run if storage fails; a path still used by a `CopyFileInfos` copy
keeps its bytes); file retention still removes old files of kept posts.
Nothing is deleted by default, and scheduled runs stay paused until an admin's
manual run completes: only a job created through the API by an authenticated
admin carries `trigger=manual`, and only that arms the schedule (Systems row
`MattermaxDataRetentionArmedBy`, which records the settings that run used).
The schedule pauses again until the next manual run whenever retention gets
stricter than that: message or file deletion turned on or shortened, Preserve
Pinned Posts turned off, or a custom policy change that makes a team or
channel keep posts for less time (a shorter policy period, a team or channel
added to a policy shorter than what applied to it, or removed from or deleted
with a policy longer than the team policy or global period it falls back to).
Changes that only keep data longer never pause it, and a scheduled run stops
if retention gets stricter mid-run. `CopyFileInfos` now copies through
`FileInfoStore.SaveCopy`, which locks the live source row, so a copy can never
lose its bytes to a concurrent retention run. Small upstream edits:
`app/job.go`, `app/file.go`, `thread_store.go` (`DeleteOrphanedRows` deletes
only the selected rows), `store.go` and the generated layers. License gates
removed in `app/data_retention.go`, `config/client.go` and
`admin_definition.tsx`. Not covered in v1: recaps, abandoned unattached
uploads, audits, legal hold.

### unlock-user-export.patch

2026-11-13. The System Console user list CSV export works without a license.
Removes the Professional check in `app/report.go` (`StartUsersBatchExport`)
and the upgrade gate in the webapp `system_users_export` component, and drops
its two now-unused tooltip strings from `en.json`. The export job, CSV worker
and system-bot delivery are AGPL. System-admin authorization stays. Cells
starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'`
at the CSV writer (`saveCSVChunk`) to prevent formula injection.

### unlock-lock-teammate-name-display.patch

2026-11-13. `TeamSettings.LockTeammateNameDisplay` works without a license:
the admin's teammate name style overrides saved user preferences, and Settings
> Display shows it as managed by the System Administrator. Gates removed in
`admin_definition.tsx`, the teammate-name preference selector and the Display
settings connector. The server already sent the setting without a license.

### unlock-channel-banners.patch

2026-11-13. Channel admins (and anyone granted
`manage_public/private_channel_banner`) can set a channel banner, and members
see it, without a license. Gates removed: `canEditChannelBanner` in
`api4/channel.go`, the Enterprise Advanced checks in webapp
`channel_banner.tsx` and `channel_settings_modal.tsx`, and the banner
permissions in the System Console permissions tree. Classification banners and
channel attributes stay gated.

### unlock-managed-channel-categories.patch

2026-11-13. Admin-managed sidebar categories (set when creating or editing a
channel, then shown in members' sidebars) work without a license. Gates
removed: `getManagedCategories` and the two managed-category checks in
`patchChannel` in `api4/channel.go`, and `CreateChannel` in `app/channel.go`.
Still behind upstream's `ManagedChannelCategories` feature flag (default off,
route registered at startup); enable it with
`MM_FEATUREFLAGS_MANAGEDCHANNELCATEGORIES=true`.

### unlock-email-notification-contents.patch

2026-11-13. `EmailSettings.EmailNotificationContentsType` ("full" or
"generic") applies without a license; "generic" emails omit the message text.
Gates removed: `App.emailNotificationContentsType` in
`app/notification_email.go` (immediate emails), the same check in
`app/email/email_batching.go` (batched emails), and the System Console
control's license check. Generic emails still name the channel, as upstream
does.

### unlock-anonymous-urls.patch

2026-11-13. `PrivacySettings.UseAnonymousURLs` gives new channels (not DMs or
GMs) and new teams server-generated ID names without a license; existing teams
and channels keep their names. Gates removed: `createChannel` in
`api4/channel.go`, `createTeam` in `api4/team.go`, `PluginAPI.CreateTeam` and
`PluginAPI.CreateChannel` in `app/plugin_api.go`, the webapp selector
`isAnonymousURLEnabled` that hides the URL editors, and the System Console
toggle's Enterprise Advanced check.

### thread-activity-lookup.patch

2026-11-14. Reads only root creation and thread last-reply timestamps for
auto-archive in one query over existing primary keys. Avoids full post and
participant decoding and the unrelated reply-count aggregate. Missing/deleted
roots, missing metadata and error handling retain their existing policy. Adds
store/app regressions and a reproducible SQL-store benchmark. This complements
Karan Sharma's thread auto-archive work; existing patches and authorship remain
unchanged. [Measured results](docs/benchmarks/thread-activity/README.md).
