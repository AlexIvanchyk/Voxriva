# Languages and shared templates

A template can connect to multiple projects and contain multiple locale/branch
drafts. Each target selects explicit published versions independently. The
application can retain one template key while projects route through different
providers and environments activate different content revisions.

## Language and branch identity

A new template selects a primary editing language and initializes its fallback
locale. Additional languages may start blank or copy a saved draft at an expected
revision before any publication. Copying does not publish or deploy. Changing
the primary language is an editor preference; changing delivery fallback is a
separate guarded operation.

Preserve the input contract across translations when callers use the same
payload. Intentional schema differences still require the appropriate request
context and compatibility review. Preview scenarios are useful test vectors,
not locale-specific runtime defaults supplied implicitly.

## Runtime selection

Pass `locale` explicitly in `Client.send` / `AsyncClient.send` or the JSON request.
The server lowercases the tag and resolves exact locale pointers through
environment/project/global scope, then the configured fallback. It never strips
a region suffix. The API default is `en` even if the primary editor language is
different. [Version resolution](lifecycle.md#locale-resolution-at-acceptance)
defines the full algorithm and 404 boundary.

## Shared-project permissions

Connecting a template makes it available to the connected project's authorized
members, without deploying content or configuring provider routing. Read requires
access through at least one connection. Editing requires editor/admin access in
every connected project; changing connections/deleting requires administration
in every connected project. Project deletion removes its connection while
preserving the library template.

For the second application/project, connect the template, deploy a version for
its environment, bind the provider there and issue a key for that environment.
A key from the first project does not acquire access to the second. MCP further
intersects these rules with explicit credential project coverage.
