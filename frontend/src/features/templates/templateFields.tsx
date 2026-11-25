import { Button, Collapse, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Tag, Typography } from "antd";
import { useState } from "react";
import { ImageUpload, imageSchema } from "./imageFields";
import type { Draft } from "./types";
import { variableFormats } from "./variableFormats";

export type Value = null | boolean | number | string | Value[] | { [key: string]: Value };
export type Schema = { [key: string]: Value };
export const asSchema = (value: Value | undefined): Schema => value && typeof value === "object" && !Array.isArray(value) ? value : {};
export const propertiesOf = (schema: Schema) => Object.fromEntries(Object.entries(asSchema(schema.properties)).map(([key, field]) => [key, asSchema(field)]));
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const names: Record<string, string> = { en: "English", uk: "Українська", de: "Deutsch", fr: "Français", es: "Español", pl: "Polski", it: "Italiano", pt: "Português", ja: "日本語", ko: "한국어", zh: "中文", ar: "العربية", tr: "Türkçe", nl: "Nederlands", cs: "Čeština", sv: "Svenska" };
export function languageLabel(code: string) { let name = names[code]; if (!name) { try { name = new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; } catch { name = code; } } return `${name} · ${code}`; }
export function LanguageSelect({ value, onChange, existing = [], disabled, label = "Language", excluded = [], ...rest }: { id?: string; onBlur?: () => void; value?: string; onChange?: (value: string) => void; existing?: string[]; disabled?: boolean; label?: string; excluded?: string[] }) {
  const [search, setSearch] = useState("");
  const custom = search.trim().toLowerCase();
  const values = [...new Set([...Object.keys(names), ...existing, ...(value ? [value] : []), ...(/^[a-z]{2,3}(-[a-z0-9]{2,8})*$/.test(custom) && custom.length <= 35 ? [custom] : [])])];
  return <Select {...rest} aria-label={label} virtual={false} showSearch optionFilterProp="label" placeholder="Choose a language or enter its code" disabled={disabled} value={value} onChange={onChange} onSearch={setSearch} options={values.map((code) => ({ value: code, label: languageLabel(code), disabled: excluded.includes(code) }))} />;
}

const typeNames: Record<string, string> = { image: "Image", string: "Text", number: "Number", integer: "Integer", boolean: "Yes / no", object: "Object", array: "List" };
const formats = variableFormats;
const reserved = new Set(["true", "false", "none", "True", "False", "None", "loop", "self", "super"]);
const empty = (schema: Schema): Value => schema.type === "object" ? {} : schema.type === "array" ? [] : schema.type === "boolean" ? false : ["number", "integer"].includes(String(schema.type)) ? 0 : "";

export function VariablesEditor({ schema, disabled, onChange, rename, depth = 0, prefix = "" }: { schema: Schema; disabled: boolean; onChange: (value: Schema) => void; rename?: (name: string) => void; depth?: number; prefix?: string }) {
  const [name, setName] = useState("");
  const [ruleErrors, setRuleErrors] = useState<Record<string, string>>({});
  const fields = propertiesOf(schema);
  const required = Array.isArray(schema.required) ? schema.required.filter((value): value is string => typeof value === "string") : [];
  const change = (key: string, value: Schema) => onChange({ ...schema, properties: { ...fields, [key]: value } });
  const validName = /^[A-Za-z][A-Za-z0-9_]*$/.test(name) && !reserved.has(name) && !(name in fields);
  return <div className="variable-builder">
    {!depth && <p className="muted-text">Define the values your application sends. Formats validate text values; test data is managed separately.</p>}
    {!Object.keys(fields).length && <p className="muted-text">No variables defined.</p>}
    {Object.entries(fields).map(([key, field]) => { const path = prefix+key; const type = field["x-voxriva-image"] === 1 ? "image" : String(field.type ?? "string"); return <section className="variable-card" key={key}>
      <header><div><Typography.Text strong code>{path}</Typography.Text><Tag>{typeNames[type] ?? type}</Tag></div><Space>
        {rename && <Button size="small" aria-label={`Rename ${key}`} disabled={disabled} onClick={() => rename(key)}>Rename</Button>}
        <Popconfirm title={`Remove ${path}?`} description="Review its content references before publishing." disabled={disabled} onConfirm={() => { const next = { ...fields }; delete next[key]; onChange({ ...schema, properties: next, required: required.filter((value) => value !== key) }); }}><Button size="small" aria-label={`Remove ${key}`} danger disabled={disabled}>Remove</Button></Popconfirm></Space></header>
      <div className="variable-properties"><label>Type<Select aria-label={`Type ${path}`} disabled={disabled} value={type} options={Object.entries(typeNames).map(([value, label]) => ({ value, label }))} onChange={(value) => {
        const replace = () => { if (value === "image") { change(key, { ...imageSchema, ...(field.description ? { description: field.description } : {}) }); return; } const next: Schema = { ...field, type: value }; for (const key of ["x-voxriva-image", "additionalProperties", "format", "x-voxriva-phone-version", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern", "enum", "const", "default", "examples", "items", "properties", "required", "minItems", "maxItems"]) delete next[key]; if (value === "object") next.properties = {}; if (value === "array") next.items = { type: "string" }; change(key, next); };
        if (Object.keys(field).some((key) => !["type", "description", "title"].includes(key))) Modal.confirm({ title: `Change type of ${path}?`, content: "Constraints and examples for the previous type will be cleared in this draft.", onOk: replace }); else replace();
      }} /></label>
      <label className="variable-required">Required<Switch aria-label={`Required ${path}`} disabled={disabled} checked={required.includes(key)} onChange={(checked) => onChange({ ...schema, required: checked ? [...required, key] : required.filter((value) => value !== key) })} /></label>
      {type === "string" && <label>Value format<Select virtual={false} aria-label={`Format ${path}`} disabled={disabled} value={String(field.format ?? "")} options={[...formats, ...(field.format && !formats.some((option) => option.value === field.format) ? [{ value: String(field.format), label: `Advanced: ${field.format}` }] : [])]} onChange={(value) => { const next = { ...field }; if (value) next.format = value; else delete next.format; if (value === "phone") next["x-voxriva-phone-version"] = 1; else delete next["x-voxriva-phone-version"]; change(key, next); }} /></label>}
      {type === "string" && field.format && <small className="muted-text">{formats.find((item) => item.value === field.format)?.description} Example: {formats.find((item) => item.value === field.format)?.example}</small>}
      <label className="variable-description">Description<Input aria-label={`Description ${path}`} disabled={disabled} placeholder="What should the application supply?" value={String(field.description ?? "")} onChange={(event) => change(key, { ...field, description: event.target.value })} /></label></div>
      <Collapse ghost items={[{ key: "constraints", label: "Validation rules", children: <div className="variable-properties">
        {(["string", "array"].includes(type) ? [[type === "string" ? "minLength" : "minItems", "Minimum length"], [type === "string" ? "maxLength" : "maxItems", "Maximum length"]] : ["number", "integer"].includes(type) ? [["minimum", "Minimum value"], ["maximum", "Maximum value"]] : []).map(([property, label]) => <label key={property}>{label}<InputNumber aria-label={`${label} ${path}`} disabled={disabled} min={property.includes("Length") || property.includes("Items") ? 0 : undefined} precision={type === "integer" || property.includes("Length") || property.includes("Items") ? 0 : undefined} value={typeof field[property] === "number" ? field[property] : null} onChange={(value) => { const next = { ...field }; if (value === null) delete next[property]; else next[property] = value; change(key, next); }} /></label>)}
        {["string", "number", "integer"].includes(type) && <label className="variable-description">Allowed values<Select aria-label={`Allowed values ${path}`} mode="tags" disabled={disabled} value={Array.isArray(field.enum) ? field.enum.map(String) : []} placeholder="Enter values, pressing Enter after each" onChange={(values) => { const parsed: Value[] = type === "string" ? values : values.map(Number); if (parsed.some((value) => typeof value === "number" && (!Number.isFinite(value) || type === "integer" && !Number.isInteger(value))) || type !== "string" && values.some((value) => !value.trim())) { setRuleErrors((errors) => ({ ...errors, [path]: type === "integer" ? "Enter whole numbers only." : "Enter valid finite numbers only." })); return; } setRuleErrors((errors) => { const next = { ...errors }; delete next[path]; return next; }); const next = { ...field }; if (values.length) next.enum = parsed; else delete next.enum; change(key, next); }} />{ruleErrors[path] && <small className="field-error">{ruleErrors[path]}</small>}</label>}
        {type === "string" && <label className="variable-description">Pattern (regular expression)<Input aria-label={`Pattern ${path}`} disabled={disabled} value={String(field.pattern ?? "")} onChange={(event) => { const next = { ...field }; if (event.target.value) next.pattern = event.target.value; else delete next.pattern; change(key, next); }} /></label>}
        {!(["string", "array", "number", "integer"].includes(type)) && <p className="muted-text">Required and nested fields define this value's rules. Advanced JSON supports additional constraints.</p>}
      </div> }]} />
      {type === "object" && depth < 8 && <Collapse ghost items={[{ key: "nested", label: `Fields inside ${path}`, children: <VariablesEditor schema={field} disabled={disabled} depth={depth+1} prefix={path+"."} onChange={(value) => change(key, value)} /> }]} />}
      {type === "array" && <label>List item type<Select aria-label={`Item type ${path}`} disabled={disabled} value={asSchema(field.items)["x-voxriva-image"] === 1 ? "image" : String(asSchema(field.items).type ?? "string")} options={Object.entries(typeNames).map(([value, label]) => ({ value, label }))} onChange={(value) => change(key, { ...field, items: value === "image" ? imageSchema : { type: value, ...(value === "object" ? { properties: {} } : {}) } })} /></label>}
      {type === "array" && asSchema(field.items).type === "string" && <label>List item format<Select virtual={false} aria-label={`Format ${path}[]`} disabled={disabled} value={String(asSchema(field.items).format ?? "")} options={formats} onChange={(value) => { const next = { ...asSchema(field.items) }; if (value) next.format = value; else delete next.format; if (value === "phone") next["x-voxriva-phone-version"] = 1; else delete next["x-voxriva-phone-version"]; change(key, { ...field, items: next }); }} /><small>{formats.find((item) => item.value === asSchema(field.items).format)?.description}</small></label>}
      {type === "array" && asSchema(field.items).type === "object" && !asSchema(field.items)["x-voxriva-image"] && depth < 8 && <Collapse ghost items={[{ key: "items", label: "List item fields", children: <VariablesEditor schema={asSchema(field.items)} disabled={disabled} depth={depth+1} prefix={path+"[]."} onChange={(value) => change(key, { ...field, items: value })} /> }]} />}
    </section>; })}
    <div className="add-variable"><Input aria-label={prefix ? `New variable ${prefix}` : "New variable"} value={name} disabled={disabled} placeholder="Variable name, e.g. first_name" maxLength={100} onChange={(event) => setName(event.target.value)} onPressEnter={() => { if (validName) { change(name, { type: "string" }); setName(""); } }} /><Button disabled={disabled || !validName} onClick={() => { change(name, { type: "string" }); setName(""); }}>Add variable</Button></div>
    {!!name && !validName && <small className="field-error">Use a unique, non-reserved name starting with a letter; letters, numbers and underscores are supported.</small>}
  </div>;
}

function localTime(value: string) { const date = new Date(value); if (Number.isNaN(date.valueOf())) return ""; const pad = (value: number) => String(value).padStart(2, "0"); return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`; }
function ValueInput({ schema, value, change, disabled, label, depth = 0 }: { schema: Schema; value: Value | undefined; change: (value: Value | undefined) => void; disabled: boolean; label: string; depth?: number }) {
  if (schema["x-voxriva-image"] === 1) return <ImageUpload value={value} onChange={change} disabled={disabled} label={`Upload ${label}`} />;
  const choices = Array.isArray(schema.enum) ? schema.enum : schema.const !== undefined ? [schema.const] : null;
  if (choices) return <Select aria-label={label} disabled={disabled} allowClear value={value === undefined ? undefined : JSON.stringify(value)} options={choices.map((item) => ({ value: JSON.stringify(item), label: typeof item === "string" ? item : JSON.stringify(item) }))} onChange={(value) => change(value === undefined ? undefined : JSON.parse(value))} />;
  if (schema.type === "boolean") return <Select aria-label={label} disabled={disabled} allowClear placeholder="Not supplied" value={value === undefined ? undefined : String(value)} options={[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]} onChange={(value) => change(value === undefined ? undefined : value === "true")} />;
  if (["number", "integer"].includes(String(schema.type))) return <InputNumber aria-label={label} disabled={disabled} min={typeof schema.minimum === "number" ? schema.minimum : undefined} max={typeof schema.maximum === "number" ? schema.maximum : undefined} precision={schema.type === "integer" ? 0 : undefined} value={typeof value === "number" ? value : null} onChange={(value) => change(value ?? undefined)} />;
  if (schema.type === "object" && depth < 8) return <DataFields schema={schema} value={asSchema(value)} onChange={change} disabled={disabled} label={label} depth={depth+1} />;
  if (schema.type === "array" && depth < 8) { const items = Array.isArray(value) ? value : []; const itemSchema = asSchema(schema.items); return <div className="array-values">{items.map((item, index) => <div key={index}><ValueInput schema={itemSchema} value={item} change={(value) => change(items.map((item, key) => key === index ? value ?? null : item))} disabled={disabled} label={`${label} ${index+1}`} depth={depth+1} /><Button disabled={disabled} onClick={() => change(items.filter((_, key) => key !== index))}>Remove item {index+1}</Button></div>)}<Space><Button disabled={disabled} onClick={() => change([...items, empty(itemSchema)])}>Add item</Button><Button disabled={disabled || value === undefined} onClick={() => change(undefined)}>Unset list</Button></Space></div>; }
  return <Input aria-label={label} disabled={disabled} placeholder={formats.find((item) => item.value === schema.format)?.example} title={formats.find((item) => item.value === schema.format)?.description} value={schema.format === "date-time" && typeof value === "string" ? localTime(value) : typeof value === "string" ? value : value === undefined ? "" : String(value)} type={schema.format === "date" ? "date" : schema.format === "date-time" ? "datetime-local" : schema.format === "email" ? "email" : schema.format === "uri" ? "url" : schema.format === "phone" ? "tel" : "text"} onChange={(event) => { const text = event.target.value; change(schema.format === "date-time" && text ? new Date(text).toISOString() : text); }} />;
}
export function DataFields({ schema, value, onChange, disabled, label = "Test data", depth = 0, errors = {} }: { schema: Schema; value: Record<string, Value>; onChange: (value: Record<string, Value>) => void; disabled: boolean; label?: string; depth?: number; errors?: Record<string, string> }) {
  return <div className="data-fields">{Object.entries(propertiesOf(schema)).map(([key, field]) => {
    const supplied = Object.hasOwn(value, key);
    const entry = supplied ? value[key] : undefined;
    const unset = () => { const next = { ...value }; delete next[key]; onChange(next); };
    return <div className="data-field" key={key}><label>{key}{Array.isArray(schema.required) && schema.required.includes(key) ? " *" : ""}<small>{String(field.description ?? (Object.hasOwn(typeNames, String(field.type)) ? typeNames[String(field.type)] : "Value"))}</small></label><ValueInput schema={field} value={entry} disabled={disabled} label={`${label} ${key}`} depth={depth} change={(entry) => { if (entry === undefined) unset(); else onChange({ ...value, [key]: entry }); }} />{supplied && <Button size="small" type="text" disabled={disabled} onClick={unset}>Unset {key}</Button>}{Object.hasOwn(errors, key) && errors[key] && <small className="field-error">{errors[key]}</small>}</div>;
  })}</div>;
}

export function contentChanges(before: Draft, after: Draft): string[] {
  const result: string[] = [];
  for (const key of ["images", "subject", "html", "text", "title", "body", "data", "variable_schema", "runtime_defaults", "preview_context", "scenarios"] as const) if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) result.push(({ images: "Saved images", subject: "Email subject", html: "HTML content", text: "Plain text", title: "Push title", body: "Push message", data: "Push data", variable_schema: "Variable contract", runtime_defaults: "Runtime defaults", preview_context: "Preview test data", scenarios: "Preview scenarios" })[key]);
  return result;
}

