# Set up projects, people and keys

Use this route when you are preparing a team or a new application environment.
If you want a running integration first, follow [the local email tutorial](../quickstart.md).

## Choose the delivery scope

Create a project for your application and an environment such as `dev`. Add
`prod` separately when needed: each environment has independent delivery keys and
can select a different template/provider revision. Page filters are local; there
is no global current-project selector carried between unrelated screens.

A shared template can connect to several projects. Providers bind to a
project/channel or environment/channel, never directly to a template.

## Grant only the roles the team needs

An installation administrator bootstraps the installation. Project administrators
manage their project's environments, members, delivery keys and provider bindings.
Template editors work on connected content; operators inspect delivery and can
replay eligible failures; viewers have read access.

In **Members → Add member**, create the fictional account with an initial
password and explicit project roles. No invitation email is sent. Existing
accounts can receive new project grants without changing their password.
An action with several grants is atomic: a conflict or inaccessible project
saves none of the requested changes.

!!! note "Shared content has shared permission checks"
    Editing a template requires editor access in every connected project.
    Changing connections or deleting it requires administration in every
    connected project. Reading needs access through at least one connection.

See the [complete permission and membership reference](../workspace-guide.md)
for role edits, self-permission restrictions and optimistic conflicts.

## Issue the right key

| Purpose in API keys | Use it for | Scope |
| --- | --- | --- |
| Delivery | Validate/send and read notification status from application code | One project environment |
| Template / MCP | Read or explicitly save template drafts through MCP | Named projects, account's live roles and read/write scopes |

Copy a new secret once and keep it in your application's secret store. The
inventory cannot recover it. Revoke keys when they are no longer needed;
expiry/revocation affects subsequent requests. Never place a real key in a
published code sample or captured image.

**Examples** on a Delivery row opens integration snippets and downloads. **Connect**
on a Template / MCP row opens connection instructions. All snippets use placeholders;
the dashboard does not send a notification from that examples screen.

Continue with [API/SDK integration](integrate.md), [MCP authoring](../../MCP.md),
or [authenticator MFA](../mfa.md).

