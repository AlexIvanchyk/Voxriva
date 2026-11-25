import { expect, it } from "vitest";
import { saveOutcome } from "./saveOutcome";
import type { Draft, Template } from "./types";
const draft: Draft = { contract_version: 1, subject: "Hello", text: "", html: "", title: "", body: "", data: {}, variable_schema: { type: "object", properties: { name: { type: "string" } } }, runtime_defaults: {}, preview_context: {}, scenarios: {} };
const attempt = { draft, revision: 4, branch: "main" };
const server = { draft, draft_revision: 5, branch_id: "main" } as Template;
it("matches JSON objects regardless of property insertion order", () => {
  expect(saveOutcome(attempt, { ...server, draft: { ...draft, variable_schema: { properties: { name: { type: "string" } }, type: "object" } } })).toBe("saved");
});
it("does not promise a commit from an unchanged revision or another branch", () => {
  expect(saveOutcome(attempt, { ...server, draft_revision: 4 })).toBe("unconfirmed");
  expect(saveOutcome(attempt, { ...server, branch_id: "translation" })).toBe("unconfirmed");
});
it("requires an explicit conflict when a newer revision contains other work", () => {
  expect(saveOutcome(attempt, { ...server, draft: { ...draft, subject: "Someone else's work" } })).toBe("conflict");
});
