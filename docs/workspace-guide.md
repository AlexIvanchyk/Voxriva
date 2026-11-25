# Workspace and template guide

Start with the [local quickstart](quickstart.md#start-locally). Commands in this
guide run from the repository root. Production operations use [PRODUCTION.md](../PRODUCTION.md).

## Projects and navigation

**Projects** is the workspace directory. Navigation has no global current-project
selector and does not inherit a remembered project. **Members**, **Environments**,
**API keys**, **Templates**, **Deployments**, and provider routing use their own local
filters. Members, environments and keys open across all permitted projects by default.
Direct links may include an explicit project filter, preserved across sign-in and reload.
An inaccessible project produces an error instead of silently selecting another project.

**Templates** remains one shared library and can connect to several projects. Providers
remain assigned to a project/channel or an environment/channel, never to templates.
The installation administrator also sees **System Health**. There is no organization
model or separate account-creation screen.

## Members: one account with independent project roles

Open **Members → Add member** and enter full name, email and an initial password.
Choose one or several projects, with a role for each. **Add another project** appends
another grant; **Add all managed projects** lists the projects you can administer,
initially as Viewer, for review before saving. This is a snapshot of explicitly listed
projects, with no wildcard or automatic access to future projects.

The account and every selected membership are committed in one transaction. All target
permissions are checked first; an inaccessible project or conflicting membership saves
none of the requested changes. For an existing account, leave the password empty:
the same action adds new project access without changing their profile or password.
An existing selected membership is a conflict; change its role in the directory instead.
New accounts require at least twelve password characters. No invitation email is sent.

The directory shows each account once, with its visible projects and roles. Search by
name/email, filter by project and role, change an individual project role, or remove that
project's access. Other memberships are preserved and inaccessible project names/roles
are never exposed. Installation administrators have inherited installation-wide access,
which cannot be changed as a project membership. Account creation dates are displayed;
imported records without historical timestamps use the migration date.

**Edit member** changes the display name and the full set of project grants you manage
in one transaction, including removal of the final grant. Email and password are not
editable here. Users can rename themselves but cannot modify their own permissions.
A project administrator can rename another shared profile only if they administer all
of its projects; inaccessible project grants are preserved. Installation administrators
can rename profiles, while inherited installation permissions remain protected. Stale
names or managed-project grants cause a conflict instead of overwriting newer changes.

Management endpoints: `GET/POST /api/v1/members` and `PATCH /api/v1/members/{account_id}` for the directory and atomic multi-project
grants, and `GET /api/v1/environments` for the scoped environment inventory. Existing
project membership and environment endpoints continue to support scoped changes.

| Role | Access |
| --- | --- |
| Installation admin | All projects and library templates, project creation, and system health. |
| Project admin | Manage their project's members, environments and keys; edit connected templates. |
| Template editor | Create/edit templates connected to projects where they hold this role. |
| Operator / Viewer | Read project resources, the member directory, and preview connected saved templates. |

Project members cannot change their own membership. Passwords are hashed with scrypt.
Dashboard sessions use HTTP-only cookies and CSRF tokens. Delivery keys cannot access
management endpoints. HTTPS cookies are the default; local Compose explicitly permits
HTTP cookies for its loopback-only dashboard.

## Environments and delivery keys

Choose a project, open **Environments → Create environment**, and enter a name such as
`development` or `production`. Open its **API keys** link or choose **API keys** from the
sidebar. Select **Create API key → Purpose → Delivery**. Create a named key for an
environment, copy its value once, and revoke it when needed. Keys default to ninety days; expiration and revocation take effect on the next
request. Use a key with `GET /api/v1/delivery/scope` to verify project and environment.
**Template / MCP**
issues a separate project-scoped authoring credential; see [MCP](../MCP.md).
See [delivery and providers](delivery-guide.md) for submissions and status.

## Shared template library and blank drafts

Open **Templates → Create template**. Set the name, channel and connected projects.
The key is generated from the name unless supplied explicitly. Every new template starts
with empty content, an empty variable schema, empty fixture and no scenarios. No welcome
message or synthetic example is inserted automatically.

Use **Manage projects** in the editor to connect the same template to multiple projects.
Connecting a template makes it available to authorized project members; it does not send
or deploy anything. Read access requires membership in at least one connected project.
Editing requires editor access in every connected project; changing connections or
deleting the template requires administrator access in every connected project. This
prevents one project's editor from changing another project's shared content. A template
with no connections is visible only to installation administrators. Deleting a project
removes its connection but preserves the library template.

Email HTML supports local image upload, static images and typed Image variables with inline SMTP/SES delivery. See [Image v1 authoring, API/SDK and storage contract](email-images.md).

Email editing includes subject, HTML and plain text. Push editing includes title, body
and string-valued data. Monaco and its workers are bundled locally. Preview refreshes
after 700 ms and never creates notification, outbox, audit or provider-send records.
Use **Variables** to define typed fields; **Schema JSON** supports nested objects, arrays,
formats and constraints. In **Test data**, enter fictional fixture values manually,
or explicitly choose **Generate example**. Generated values are checked by the preview;
complex constraints may require manual input. Save named scenarios to test variations.

For a repeatable demo, create a blank email template. Enter `Hello {{ name }}` as subject,
add a required string variable `name`, and set its synthetic value to `Taylor Example`.
The preview shows `Hello Taylor Example`. Give `name` a number in **Fixture JSON** to see
a type error without losing edits. Save and reload; repeat with a blank push template.

Schema `default` values are annotations. Only explicit top-level **Runtime defaults**
fill missing runtime variables, before validation; client values override them. Synthetic
fixtures never fill delivery context. Save uses optimistic draft revisions: a competing
save returns a conflict and keeps unsaved work. Invalid schema/Jinja drafts can be saved
as work in progress. Publication freezes content, schema, fixtures and runtime defaults. Published versions and deployment events are immutable in the database. Templates with published history cannot be deleted.

The library API is `/api/v1/templates`. Create/list there; get/delete `/{template_id}`,
`PUT /{template_id}/projects` with `project_ids`, and `PUT /{template_id}/draft` with
`draft` and `expected_revision`. `POST /{template_id}/preview` accepts an optional
unsaved `draft`, `context`, or saved `scenario`; scenarios take precedence over context.
Preview returns `rendered` or structured `errors` with path, code and message.

Contract version 1 uses JSON Schema Draft 2020-12 with known-format checking. References
must be inlined. Nonimage draft JSON has a 100 KB UTF-8 limit, with a separate bounded image budget; schemas have a 20-level nesting limit, and rendered text/HTML has
a 200 KB output limit. Strict undefined variables, restricted Jinja filters, no globals
or method access, and HTML autoescaping apply. Each render runs in a child process with
a 3-second wall limit; Linux adds a 256 MiB address-space and 2 CPU-second limit. Each
API process allows two concurrent previews and sixty attempts per account per minute.
HTML previews use DOMPurify, a sandboxed iframe, and restrictive CSP. External image
addresses and navigation links are removed. No remote images or scripts are loaded.
Email clients can render differently from the browser preview.

## Language, variables and editor controls

Templates have a named **Primary language** at creation and a separate **Editing language**
picker. **Add language** can start empty or copy a saved draft before any publication.
Copies use the source draft revision as a concurrency guard. The primary language controls
which draft opens by default; **Set as primary** changes editor preference only. The explicit
delivery fallback remains independent, with exact locale matching and no implicit regional
fallback. New templates initialize fallback to their chosen primary language; existing
API/SDK requests still default to `en` unless a locale is supplied. Existing templates are
backfilled with primary `en`, preserving their English main branches, saved content,
published revisions and deployment pointers. Advanced branches remain available within
languages. The library lists available languages and the primary one.

**Variables** uses named types, a format select (plain text, email, phone, URL, date, date/time,
UUID, IPv4, IPv6, hostname, duration), descriptions, required flags, numeric/length limits, allowed values, patterns,
object fields and list item fields. Advanced schema JSON remains available. Type changes
that clear existing constraints require confirmation. Supported advanced formats already
present in schemas are retained. Unknown formats are flagged during authoring/publication;
existing published runtime schemas retain their previous behavior. Raw schema JSON is
never silently discarded or rewritten by opening the visual forms. See [Variable formats](variable-formats.md) for E.164 phone rules, the explicit compatibility opt-in, and validated example generation.

Email subject and push title/body use compact text controls. HTML/plain text are separate
content tabs; source editors provide variable insertion, schema-derived completion,
formatting and full-screen editing. Insertion uses the focused field's current selection.
Preview diagnostics locate syntax errors, undeclared references and unused variables;
warnings remain nonblocking. **Rename** first previews reference replacements, then applies
them to the current in-memory draft, updating its root variable definition, required list,
explicit defaults, preview data and scenarios. It does not write until **Save draft**.
Literal text, quoted strings, attribute names, filters and tests retain their meaning.
Ambiguous local bindings and advanced schema dependencies require manual source editing.
Rename analysis and preview diagnostics execute in bounded child processes; previews
remain sandboxed and external resources blocked.

Live preview has adjustable editor/preview widths, desktop/phone/tablet widths, separate
HTML/plain text output and field-linked errors. Push preview shows rendered byte size;
the complete FCM request must fit 4096 bytes, including the device token and envelope.
**Test data** supports typed controls, dates, nested values and saved scenarios. Generating
an example is an explicit action; new templates and empty translations have no sample
content or data. **Runtime defaults** is a separate form: delivery context overrides each
top-level default, including replacing entire nested objects. Unset, false, zero and
empty string values are distinct. Advanced JSON is available for both data sets.

The header distinguishes saved draft, unpublished changes, published version and versions
resolved by environments (including fallback). Version history filters by language/branch.
Publication checks the saved revision and shows changed sections and validation issues.
Deploy/Roll back still require explicit actions and show before/after versions with
variable-contract review. Publishing a new version never changes the active pointer.
Saving is manual, with **Ctrl/Cmd S**, failure feedback, optimistic revision protection
and unsaved-navigation warnings. After a timeout the editor reconciles the server revision
before offering a retry; a response timeout alone does not prove a save failed.
Autosave and a visual email block builder remain deferred.

## Versions, branches, locales and deployments

The main **Deployments** page lists all visible email and push templates across projects,
environments and locales, including active inherited versions and unconfigured targets.
Search by template, target or version and filter by channel, project, environment, locale,
status or target scope. **Open matrix** goes directly to that template's deployment tab
in the selected locale. Project access is enforced on the server.

The template editor has **Draft editor**, **Version history** and **Deployments** tabs.
The branch selector shows both branch and locale. Historical drafts were migrated to `main · en`
without creating any version or deployment. A draft save revision, a published version
number and a deployment generation are separate values.

1. Save a valid email/push draft with a valid synthetic fixture. Choose **Publish version**
   and enter a publication note. Publication validates the fixture through the shared
   renderer, also checking explicit runtime defaults without fixture overrides. It freezes
   a snapshot and records its author and parent. It does **not** change any deployment.
2. In **Version history**, preview immutable snapshots with editable preview variables or
   saved scenarios. The Monaco comparison shows content/runtime defaults and variable
   schemas. **Create branch** or **Branch from version** copies a published snapshot into
   an independent draft, recording lineage. A locale can be chosen explicitly for a
   translation branch. Version numbers are local to a branch: `main · v2 · en` and
   `candidate · v1 · en` are distinct, unambiguous published snapshots.
3. In **Deployments**, choose a locale and use **Deploy** on the concrete environment or
   default row. The dialog names the target, locale, current effective version and exact
   destination. Only installation admins can set the explicit global default. Project
   admins can deploy versions to their connected projects without editing shared content.
4. To deploy a version tested in `dev` to `prod`, use **Deploy** on `prod` and select
   the same published branch/version. Each environment keeps its own explicit selection.
5. **Roll back** selects a version previously used by that exact target and locale.
   **Activity** shows the twenty most recent changes; all events remain stored with
   actor, from/to versions and generation. The matrix exposes only Deploy, Roll back
   and Activity; promotion and clearing overrides are not dashboard actions.

For a demo: publish `main · v1 · en`, deploy it to `prod`, edit/save/publish
`main · v2 · en`, and verify `prod` still has v1. Deploy v2 to `dev`, deploy that same version to
`prod`, then roll `prod` back to v1. Separately fork v1 into `candidate` and verify that
editing/publishing it leaves both `main` and the deployment matrix unchanged.

Resolution tries the **exact requested locale** through **environment → project default →
explicit global default**. Only if none exists does it repeat that chain for the template's
configured fallback locale. The initial explicit fallback locale is the primary language chosen at creation; there is no
implicit region/language truncation. Thus a requested `uk-UA` can fall back to configured
`en` even if a `uk` version exists. No pointer means no resolution; the server never picks
an arbitrary published version or another project's deployment. The template must be
connected to the target project, and the environment must belong to that project.
**Change fallback** requires administration of every connected project and acknowledgement
when active deployments exist. Publish a locale before selecting it as fallback.

Each deployment mutation locks the template row and checks `expected_generation`.
The UI additionally supplies the expected effective version, protecting a review from
concurrent parent/fallback changes. Promotion checks both source and target generations.
Conflicts return 409 instead of overwriting another user's change. Clearing a pointer
retains its generation, preventing stale requests from reusing an old slot state.

Variable-contract checks compare the destination with the currently effective version.
New required fields without explicit runtime defaults, removed properties, type narrowing,
stricter constraints and removed required runtime defaults are flagged. Unknown changed
constraints are treated conservatively. Metadata-only changes do not require acknowledgement.
This is a conservative compatibility check, not a proof of every possible JSON Schema
relationship. Breaking deploys, promotions and rollbacks require explicit acknowledgement;
the same checks run on the server even if the UI is bypassed.

API routes under `/api/v1/templates/{id}` include `/branches`, `/publish`, `/versions`,
`/versions/diff?before=...&after=...`, immutable version `/preview`, `/fallback`, and
`/deployments`. Explicit mutations are `/deployments/deploy`, `/promote`, `/rollback`,
and `/clear`. Branch draft requests include `branch_id` and `expected_revision`.
The side-effect-free management resolver is
`GET /api/v1/projects/{project}/environments/{environment}/templates/{template}/resolve?locale=en`.
Delivery uses the same resolution helper and pins the returned immutable version.

